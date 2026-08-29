"""Natural-language capture orchestration and deterministic temporal resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from personal_os.capture_types import (
    ClockExpression, ClockExpressionKind, DateExpression, DateExpressionKind,
    DeadlineKind, InterpretationOutcome, InterpretationResponse,
    ProjectReferenceKind, TaskScheduleKind,
)
from personal_os.errors import DomainValidationError, PersistenceError
from personal_os.models import Capture, CaptureFailureKind, ProjectStatus, TaskScheduleMode, TaskStatus, normalize_instant, require_text
from personal_os.state import SQLiteStateStore


class InterpretationError(Exception):
    """A classified failure at the external interpretation boundary."""

    def __init__(self, kind: CaptureFailureKind, reason: str, *, provider: str | None = None, model: str | None = None, response_id: str | None = None) -> None:
        super().__init__(reason)
        self.kind, self.provider, self.model, self.response_id = kind, provider, model, response_id


class CaptureInterpreter(Protocol):
    def interpret(self, raw_text: str, *, projects: list[dict[str, object]]) -> InterpretationResponse: ...


@dataclass(frozen=True, slots=True)
class CaptureResult:
    capture: Capture
    project_id: int | None = None
    task_ids: tuple[int, ...] = ()
    commitment_ids: tuple[int, ...] = ()
    inbox_item_id: int | None = None


@dataclass(frozen=True, slots=True)
class _Unresolved:
    reason: str


def _date_from_ir(value: DateExpression, local_reference: datetime) -> date | _Unresolved:
    today = local_reference.date()
    if value.kind is DateExpressionKind.TODAY:
        return today
    if value.kind is DateExpressionKind.TOMORROW:
        return today + timedelta(days=1)
    if value.kind in {DateExpressionKind.WEEKDAY, DateExpressionKind.NEXT_WEEKDAY}:
        weekday = int(value.value)
        if value.kind is DateExpressionKind.WEEKDAY:
            return today + timedelta(days=(weekday - today.isoweekday()) % 7)
        next_monday = today + timedelta(days=7 - today.weekday())
        return next_monday + timedelta(days=weekday - 1)
    if value.kind is DateExpressionKind.EXPLICIT_DATE:
        try:
            parsed = date.fromisoformat(str(value.value))
        except ValueError as exc:
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "explicit date is invalid") from exc
        if parsed.isoformat() != value.value:
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "explicit date is not canonical")
        return parsed
    return _Unresolved("explicit date is missing a year")


def _clock_from_ir(value: ClockExpression) -> time | _Unresolved:
    if value.kind is ClockExpressionKind.BARE_HOUR:
        return _Unresolved("time is missing AM/PM or unambiguous 24-hour notation")
    hour = value.hour
    if value.kind is ClockExpressionKind.CLOCK_12:
        hour = (hour % 12) + (12 if value.period == "PM" else 0)
    return time(hour, value.minute)


def _localize(day: date, clock: time, zone: ZoneInfo) -> datetime | _Unresolved:
    naive = datetime.combine(day, clock)
    candidates = []
    for fold in (0, 1):
        local = naive.replace(tzinfo=zone, fold=fold)
        if local.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == naive:
            candidates.append(local)
    instants = {item.astimezone(UTC) for item in candidates}
    if not instants:
        return _Unresolved("local time does not exist because of a daylight-saving transition")
    if len(instants) > 1:
        return _Unresolved("local time is ambiguous because of a daylight-saving transition")
    return instants.pop()


def _instant_from_ir(value, local_reference: datetime, zone: ZoneInfo) -> datetime | _Unresolved:
    day = _date_from_ir(value.date, local_reference)
    if isinstance(day, _Unresolved):
        return day
    clock = _clock_from_ir(value.clock)
    if isinstance(clock, _Unresolved):
        return clock
    return _localize(day, clock, zone)


def _weekend(local_reference: datetime) -> tuple[datetime, datetime]:
    today = local_reference.date()
    saturday = today - timedelta(days=today.weekday() - 5) if today.weekday() >= 5 else today + timedelta(days=5 - today.weekday())
    zone = local_reference.tzinfo
    assert isinstance(zone, ZoneInfo)
    return (datetime.combine(saturday, time(), zone).astimezone(UTC), datetime.combine(saturday + timedelta(days=2), time(), zone).astimezone(UTC))


class CaptureService:
    """Persist first, interpret semantics, then resolve and apply atomically."""

    def __init__(self, store: SQLiteStateStore, interpreter: CaptureInterpreter, *, project_candidate_limit: int = 50) -> None:
        if type(project_candidate_limit) is not int or project_candidate_limit <= 0:
            raise DomainValidationError("project_candidate_limit must be a positive integer")
        self.store, self.interpreter, self.project_candidate_limit = store, interpreter, project_candidate_limit

    def capture_text(self, raw_text: str, *, reference_time: datetime, timezone_name: str) -> CaptureResult:
        raw = require_text(raw_text, "raw_text", preserve=True)
        reference = normalize_instant(reference_time, "reference_time")
        try:
            zone = ZoneInfo(require_text(timezone_name, "timezone_name"))
        except ZoneInfoNotFoundError as exc:
            raise DomainValidationError("timezone_name must identify an IANA timezone") from exc
        capture = self.store.create_capture(raw, reference, timezone_name)
        all_projects = self.store.list_projects()
        active = sorted((item for item in all_projects if item.status is ProjectStatus.ACTIVE), key=lambda item: (item.updated_at, item.id), reverse=True)
        candidates = [{"id": item.id, "name": item.name} for item in active[:self.project_candidate_limit]]
        try:
            response = self.interpreter.interpret(raw, projects=candidates)
        except PersistenceError:
            raise
        except InterpretationError as exc:
            failed = self.store.mark_capture_failed(
                capture.id, exc.kind, str(exc), model_provider=exc.provider,
                model_name=exc.model, model_response_id=exc.response_id,
            )
            return CaptureResult(failed)
        except Exception as exc:
            failed = self.store.mark_capture_failed(capture.id, CaptureFailureKind.PROVIDER_ERROR, str(exc) or type(exc).__name__)
            return CaptureResult(failed)

        try:
            return self._apply(capture, response, zone, candidates, all_projects)
        except PersistenceError:
            raise
        except InterpretationError as exc:
            failed = self.store.mark_capture_failed(
                capture.id, CaptureFailureKind.INVALID_OUTPUT, str(exc),
                model_provider=response.provider, model_name=response.model,
                model_response_id=response.response_id,
            )
            return CaptureResult(failed)
        except (DomainValidationError, ValueError, TypeError, KeyError) as exc:
            failed = self.store.mark_capture_failed(
                capture.id, CaptureFailureKind.INVALID_OUTPUT,
                str(exc) or type(exc).__name__, model_provider=response.provider,
                model_name=response.model, model_response_id=response.response_id,
            )
            return CaptureResult(failed)

    def _apply(self, capture: Capture, response: InterpretationResponse, zone: ZoneInfo, candidates: list[dict[str, object]], all_projects: list) -> CaptureResult:
        interpretation = response.interpretation
        payload = interpretation.to_dict()
        if interpretation.outcome is InterpretationOutcome.UNRESOLVED:
            finalized, inbox = self.store.apply_unresolved_capture(capture.id, interpretation.unresolved_reason, interpretation=payload, model_provider=response.provider, model_name=response.model, model_response_id=response.response_id)
            return CaptureResult(finalized, inbox_item_id=inbox.id)
        new_project = interpretation.new_project
        if new_project is not None:
            if any(item.name.casefold() == new_project.name.casefold() for item in all_projects):
                return self._unresolved(capture, response, payload, "new project name collides with an existing project")
            if not any(item.project.kind is ProjectReferenceKind.NEW for item in interpretation.tasks):
                raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "new project is not referenced by a captured task")
        candidate_ids = {item["id"] for item in candidates}
        local_reference = capture.reference_time.astimezone(zone)
        tasks = []
        for intent in interpretation.tasks:
            if intent.project.kind is ProjectReferenceKind.EXISTING and intent.project.project_id not in candidate_ids:
                raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "task references an unavailable project")
            if intent.project.kind is ProjectReferenceKind.NEW and new_project is None:
                raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "task references an absent new project")
            project_id = "NEW" if intent.project.kind is ProjectReferenceKind.NEW else intent.project.project_id
            deadline_date = deadline_at = None
            if intent.deadline.kind is DeadlineKind.DATE:
                resolved = _date_from_ir(intent.deadline.date, local_reference)
                if isinstance(resolved, _Unresolved): return self._unresolved(capture, response, payload, resolved.reason)
                deadline_date = resolved
            elif intent.deadline.kind is DeadlineKind.INSTANT:
                resolved = _instant_from_ir(intent.deadline.instant, local_reference, zone)
                if isinstance(resolved, _Unresolved): return self._unresolved(capture, response, payload, resolved.reason)
                deadline_at = resolved
            base = {"title": intent.title, "project_id": project_id, "status": TaskStatus.OPEN, "importance": intent.importance,
                    "deadline_date": deadline_date, "deadline_at": deadline_at, "estimated_minutes": intent.estimated_minutes}
            if intent.schedule.kind is TaskScheduleKind.DAY:
                resolved_dates = []
                for expression in intent.schedule.dates:
                    resolved = _date_from_ir(expression, local_reference)
                    if isinstance(resolved, _Unresolved): return self._unresolved(capture, response, payload, resolved.reason)
                    if resolved not in resolved_dates: resolved_dates.append(resolved)
                tasks.extend({**base, "schedule_mode": TaskScheduleMode.DAY, "day_date": day, "window_start": None, "window_end": None} for day in resolved_dates)
            elif intent.schedule.kind is TaskScheduleKind.THIS_WEEKEND:
                start, end = _weekend(local_reference)
                tasks.append({**base, "schedule_mode": TaskScheduleMode.WINDOW, "day_date": None, "window_start": start, "window_end": end})
            else:
                tasks.append({**base, "schedule_mode": TaskScheduleMode.FLEXIBLE, "day_date": None, "window_start": None, "window_end": None})
        commitments = []
        for intent in interpretation.commitments:
            start = _instant_from_ir(intent.start, local_reference, zone)
            if isinstance(start, _Unresolved): return self._unresolved(capture, response, payload, start.reason)
            if start < capture.reference_time: return self._unresolved(capture, response, payload, "fixed commitment resolves into the past")
            commitments.append({"title": intent.title, "start_at": start, "end_at": None, "hardness": intent.hardness})
        finalized, project, made_tasks, made_commitments = self.store.apply_resolved_capture(
            capture.id, interpretation=payload, model_provider=response.provider, model_name=response.model,
            model_response_id=response.response_id, project=None if new_project is None else {"name": new_project.name, "description": new_project.description}, tasks=tasks, commitments=commitments)
        return CaptureResult(finalized, None if project is None else project.id, tuple(item.id for item in made_tasks), tuple(item.id for item in made_commitments))

    def _unresolved(self, capture: Capture, response: InterpretationResponse, payload: dict, reason: str) -> CaptureResult:
        finalized, inbox = self.store.apply_unresolved_capture(capture.id, reason, interpretation=payload, model_provider=response.provider, model_name=response.model, model_response_id=response.response_id)
        return CaptureResult(finalized, inbox_item_id=inbox.id)

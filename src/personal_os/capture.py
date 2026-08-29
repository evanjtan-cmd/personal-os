"""Natural-language capture orchestration and deterministic temporal resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from personal_os.errors import DomainValidationError
from personal_os.models import (
    Capture,
    CaptureFailureKind,
    CommitmentHardness,
    ProjectStatus,
    TaskImportance,
    TaskScheduleMode,
    TaskStatus,
    normalize_instant,
    require_text,
)
from personal_os.state import SQLiteStateStore


class InterpretationError(Exception):
    """A classified failure at the external interpretation boundary."""

    def __init__(
        self, kind: CaptureFailureKind, reason: str, *, provider: str | None = None,
        model: str | None = None, response_id: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.kind = kind
        self.provider = provider
        self.model = model
        self.response_id = response_id


@dataclass(frozen=True, slots=True)
class InterpretationResponse:
    payload: dict[str, Any]
    provider: str
    model: str
    response_id: str | None = None


class CaptureInterpreter(Protocol):
    def interpret(
        self, raw_text: str, *, projects: list[dict[str, object]],
        reference_time: datetime, timezone_name: str,
    ) -> InterpretationResponse: ...


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


def _exact_keys(value: object, required: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != required:
        raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, f"{label} has an invalid shape")
    return value


def _date_from_ir(value: object, local_reference: datetime) -> date | _Unresolved:
    data = _exact_keys(value, {"kind", "value"}, "date expression")
    kind, raw = data["kind"], data["value"]
    today = local_reference.date()
    if kind == "TODAY" and raw is None:
        return today
    if kind == "TOMORROW" and raw is None:
        return today + timedelta(days=1)
    if kind in {"WEEKDAY", "NEXT_WEEKDAY"} and isinstance(raw, int) and not isinstance(raw, bool) and 1 <= raw <= 7:
        if kind == "WEEKDAY":
            return today + timedelta(days=(raw - today.isoweekday()) % 7)
        next_monday = today + timedelta(days=7 - today.weekday())
        return next_monday + timedelta(days=raw - 1)
    if kind == "EXPLICIT_DATE" and isinstance(raw, str):
        try:
            parsed = date.fromisoformat(raw)
        except ValueError as exc:
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "explicit date is invalid") from exc
        if parsed.isoformat() != raw:
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "explicit date is not canonical")
        return parsed
    if kind == "MISSING_YEAR":
        return _Unresolved("explicit date is missing a year")
    raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "unsupported date expression")


def _clock_from_ir(value: object) -> time | _Unresolved:
    if not isinstance(value, dict) or "kind" not in value:
        raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "clock expression has an invalid shape")
    kind = value["kind"]
    if kind == "CLOCK_12":
        data = _exact_keys(value, {"kind", "hour", "minute", "period"}, "12-hour clock")
        hour, minute, period = data["hour"], data["minute"], data["period"]
        if type(hour) is not int or type(minute) is not int or hour not in range(1, 13) or minute not in range(60) or period not in {"AM", "PM"}:
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "12-hour clock is invalid")
        return time((hour % 12) + (12 if period == "PM" else 0), minute)
    if kind in {"CLOCK_24", "BARE_HOUR"}:
        data = _exact_keys(value, {"kind", "hour", "minute"}, "clock")
        hour, minute = data["hour"], data["minute"]
        if type(hour) is not int or type(minute) is not int or hour not in range(24) or minute not in range(60):
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "clock is invalid")
        if kind == "BARE_HOUR":
            return _Unresolved("time is missing AM/PM or unambiguous 24-hour notation")
        return time(hour, minute)
    raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "unsupported clock expression")


def _localize(day: date, clock: time, zone: ZoneInfo) -> datetime | _Unresolved:
    naive = datetime.combine(day, clock)
    candidates: list[datetime] = []
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


def _instant_from_ir(value: object, local_reference: datetime, zone: ZoneInfo) -> datetime | _Unresolved:
    data = _exact_keys(value, {"date", "clock"}, "date-time expression")
    day = _date_from_ir(data["date"], local_reference)
    if isinstance(day, _Unresolved):
        return day
    clock = _clock_from_ir(data["clock"])
    if isinstance(clock, _Unresolved):
        return clock
    return _localize(day, clock, zone)


def _weekend(local_reference: datetime) -> tuple[datetime, datetime]:
    today = local_reference.date()
    saturday = today - timedelta(days=today.weekday() - 5) if today.weekday() >= 5 else today + timedelta(days=5 - today.weekday())
    zone = local_reference.tzinfo
    assert isinstance(zone, ZoneInfo)
    start = datetime.combine(saturday, time(), zone).astimezone(UTC)
    end = datetime.combine(saturday + timedelta(days=2), time(), zone).astimezone(UTC)
    return start, end


class CaptureService:
    """Persist first, interpret externally, then finalize state atomically."""

    def __init__(self, store: SQLiteStateStore, interpreter: CaptureInterpreter) -> None:
        self.store = store
        self.interpreter = interpreter

    def capture_text(self, raw_text: str, *, reference_time: datetime, timezone_name: str) -> CaptureResult:
        raw = require_text(raw_text, "raw_text", preserve=True)
        reference = normalize_instant(reference_time, "reference_time")
        try:
            zone = ZoneInfo(require_text(timezone_name, "timezone_name"))
        except ZoneInfoNotFoundError as exc:
            raise DomainValidationError("timezone_name must identify an IANA timezone") from exc
        capture = self.store.create_capture(raw, reference, timezone_name)
        projects = [
            {"id": project.id, "name": project.name}
            for project in self.store.list_projects() if project.status is ProjectStatus.ACTIVE
        ]
        response: InterpretationResponse | None = None
        try:
            response = self.interpreter.interpret(
                raw, projects=projects, reference_time=reference, timezone_name=timezone_name
            )
            return self._apply(capture, response, zone, projects)
        except InterpretationError as exc:
            failed = self.store.mark_capture_failed(
                capture.id, exc.kind, str(exc),
                model_provider=exc.provider or (None if response is None else response.provider),
                model_name=exc.model or (None if response is None else response.model),
                model_response_id=exc.response_id or (None if response is None else response.response_id),
            )
            return CaptureResult(failed)
        except (DomainValidationError, ValueError, TypeError, KeyError) as exc:
            failed = self.store.mark_capture_failed(
                capture.id, CaptureFailureKind.INVALID_OUTPUT, str(exc) or type(exc).__name__,
                model_provider=None if response is None else response.provider,
                model_name=None if response is None else response.model,
                model_response_id=None if response is None else response.response_id,
            )
            return CaptureResult(failed)
        except Exception as exc:
            failed = self.store.mark_capture_failed(
                capture.id, CaptureFailureKind.PROVIDER_ERROR, str(exc) or type(exc).__name__,
                model_provider=None if response is None else response.provider,
                model_name=None if response is None else response.model,
                model_response_id=None if response is None else response.response_id,
            )
            return CaptureResult(failed)

    def _apply(
        self, capture: Capture, response: InterpretationResponse, zone: ZoneInfo,
        candidates: list[dict[str, object]],
    ) -> CaptureResult:
        payload = _exact_keys(
            response.payload, {"kind", "new_project", "tasks", "commitments", "unresolved_reason"},
            "interpretation",
        )
        if payload["kind"] == "UNRESOLVED":
            reason = require_text(payload["unresolved_reason"], "unresolved_reason")
            finalized, inbox = self.store.apply_unresolved_capture(
                capture.id, reason, interpretation=payload, model_provider=response.provider,
                model_name=response.model, model_response_id=response.response_id,
            )
            return CaptureResult(finalized, inbox_item_id=inbox.id)
        if payload["kind"] != "APPLY" or payload["unresolved_reason"] is not None:
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "interpretation outcome is contradictory")
        if not isinstance(payload["tasks"], list) or not isinstance(payload["commitments"], list):
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "outputs must be arrays")
        new_project = payload["new_project"]
        if new_project is not None:
            new_project = _exact_keys(new_project, {"name", "description"}, "new project")
            name = require_text(new_project["name"], "project name")
            if any(item.name.casefold() == name.casefold() for item in self.store.list_projects()):
                finalized, inbox = self.store.apply_unresolved_capture(
                    capture.id, "new project name collides with an existing project",
                    interpretation=payload, model_provider=response.provider,
                    model_name=response.model, model_response_id=response.response_id,
                )
                return CaptureResult(finalized, inbox_item_id=inbox.id)
            new_project = {"name": name, "description": new_project["description"]}
            if not any(isinstance(item, dict) and item.get("project_id") == "NEW" for item in payload["tasks"]):
                raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "new project is not referenced by a captured task")
        local_reference = capture.reference_time.astimezone(zone)
        tasks: list[dict[str, Any]] = []
        for raw_task in payload["tasks"]:
            task = _exact_keys(raw_task, {"title", "project_id", "importance", "estimated_minutes", "schedule", "deadline"}, "task")
            project_id = task["project_id"]
            valid_ids = {item["id"] for item in candidates}
            if project_id == "NEW" and new_project is None or project_id not in valid_ids and project_id not in (None, "NEW"):
                raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "task references an unavailable project")
            schedule_mode, day_date, window_start, window_end = TaskScheduleMode.FLEXIBLE, None, None, None
            schedule = task["schedule"]
            if schedule is not None:
                schedule = _exact_keys(schedule, {"kind", "value"}, "schedule")
                if schedule["kind"] == "DAY":
                    resolved = _date_from_ir(schedule["value"], local_reference)
                    if isinstance(resolved, _Unresolved): return self._unresolved(capture, response, payload, resolved.reason)
                    schedule_mode, day_date = TaskScheduleMode.DAY, resolved
                elif schedule["kind"] == "THIS_WEEKEND":
                    if schedule["value"] is not None: raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "weekend value must be null")
                    schedule_mode = TaskScheduleMode.WINDOW
                    window_start, window_end = _weekend(local_reference)
                else:
                    raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "unsupported task schedule")
            deadline_date, deadline_at = None, None
            if task["deadline"] is not None:
                deadline = _exact_keys(task["deadline"], {"kind", "value"}, "deadline")
                if deadline["kind"] == "DATE":
                    resolved = _date_from_ir(deadline["value"], local_reference)
                    if isinstance(resolved, _Unresolved): return self._unresolved(capture, response, payload, resolved.reason)
                    deadline_date = resolved
                elif deadline["kind"] == "INSTANT":
                    resolved = _instant_from_ir(deadline["value"], local_reference, zone)
                    if isinstance(resolved, _Unresolved): return self._unresolved(capture, response, payload, resolved.reason)
                    deadline_at = resolved
                else: raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "unsupported deadline")
            try:
                importance = TaskImportance(task["importance"])
            except ValueError as exc:
                raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "invalid task importance") from exc
            tasks.append({"title": task["title"], "project_id": project_id, "status": TaskStatus.OPEN,
                "importance": importance, "schedule_mode": schedule_mode, "day_date": day_date,
                "window_start": window_start, "window_end": window_end, "deadline_date": deadline_date,
                "deadline_at": deadline_at, "estimated_minutes": task["estimated_minutes"]})
        commitments: list[dict[str, Any]] = []
        for raw_item in payload["commitments"]:
            item = _exact_keys(raw_item, {"title", "start", "end", "hardness"}, "commitment")
            start = _instant_from_ir(item["start"], local_reference, zone)
            if isinstance(start, _Unresolved): return self._unresolved(capture, response, payload, start.reason)
            if start < capture.reference_time:
                return self._unresolved(capture, response, payload, "fixed commitment resolves into the past")
            end = None if item["end"] is None else _instant_from_ir(item["end"], local_reference, zone)
            if isinstance(end, _Unresolved): return self._unresolved(capture, response, payload, end.reason)
            if end is not None and start >= end:
                raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "commitment end must be after start")
            try: hardness = CommitmentHardness(item["hardness"])
            except ValueError as exc: raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "invalid commitment hardness") from exc
            commitments.append({"title": item["title"], "start_at": start, "end_at": end, "hardness": hardness})
        if not tasks and not commitments and new_project is None:
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "resolved capture has no output")
        finalized, project, made_tasks, made_commitments = self.store.apply_resolved_capture(
            capture.id, interpretation=payload, model_provider=response.provider, model_name=response.model,
            model_response_id=response.response_id, project=new_project, tasks=tasks, commitments=commitments,
        )
        return CaptureResult(finalized, None if project is None else project.id,
            tuple(item.id for item in made_tasks), tuple(item.id for item in made_commitments))

    def _unresolved(self, capture: Capture, response: InterpretationResponse, payload: dict[str, Any], reason: str) -> CaptureResult:
        finalized, inbox = self.store.apply_unresolved_capture(
            capture.id, reason, interpretation=payload, model_provider=response.provider,
            model_name=response.model, model_response_id=response.response_id,
        )
        return CaptureResult(finalized, inbox_item_id=inbox.id)

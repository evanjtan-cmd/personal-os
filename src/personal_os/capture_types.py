"""Typed, versioned semantic boundary for natural-language capture."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from personal_os.models import CommitmentHardness, TaskImportance


class InterpretationValidationError(ValueError):
    """External interpretation JSON does not satisfy the semantic contract."""


class InterpretationOutcome(StrEnum):
    APPLY = "APPLY"
    UNRESOLVED = "UNRESOLVED"


class ProjectReferenceKind(StrEnum):
    NONE = "NONE"
    EXISTING = "EXISTING"
    NEW = "NEW"


class DateExpressionKind(StrEnum):
    TODAY = "TODAY"
    TOMORROW = "TOMORROW"
    WEEKDAY = "WEEKDAY"
    NEXT_WEEKDAY = "NEXT_WEEKDAY"
    EXPLICIT_DATE = "EXPLICIT_DATE"
    MISSING_YEAR = "MISSING_YEAR"


class ClockExpressionKind(StrEnum):
    CLOCK_12 = "CLOCK_12"
    CLOCK_24 = "CLOCK_24"
    BARE_HOUR = "BARE_HOUR"


class TaskScheduleKind(StrEnum):
    FLEXIBLE = "FLEXIBLE"
    DAY = "DAY"
    THIS_WEEKEND = "THIS_WEEKEND"


class DeadlineKind(StrEnum):
    NONE = "NONE"
    DATE = "DATE"
    INSTANT = "INSTANT"


@dataclass(frozen=True, slots=True)
class DateExpression:
    kind: DateExpressionKind
    value: str | int | None = None


@dataclass(frozen=True, slots=True)
class ClockExpression:
    kind: ClockExpressionKind
    hour: int
    minute: int
    period: str | None = None


@dataclass(frozen=True, slots=True)
class DateTimeExpression:
    date: DateExpression
    clock: ClockExpression


@dataclass(frozen=True, slots=True)
class ProjectReference:
    kind: ProjectReferenceKind
    project_id: int | None = None


@dataclass(frozen=True, slots=True)
class NewProjectIntent:
    name: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class TaskScheduleIntent:
    kind: TaskScheduleKind
    dates: tuple[DateExpression, ...] = ()


@dataclass(frozen=True, slots=True)
class DeadlineIntent:
    kind: DeadlineKind
    date: DateExpression | None = None
    instant: DateTimeExpression | None = None


@dataclass(frozen=True, slots=True)
class TaskIntent:
    title: str
    project: ProjectReference
    importance: TaskImportance
    estimated_minutes: int | None
    schedule: TaskScheduleIntent
    deadline: DeadlineIntent


@dataclass(frozen=True, slots=True)
class FixedCommitmentIntent:
    title: str
    start: DateTimeExpression
    hardness: CommitmentHardness


@dataclass(frozen=True, slots=True)
class CaptureInterpretation:
    outcome: InterpretationOutcome
    new_project: NewProjectIntent | None
    tasks: tuple[TaskIntent, ...]
    commitments: tuple[FixedCommitmentIntent, ...]
    unresolved_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.outcome.value,
            "new_project": None if self.new_project is None else {
                "name": self.new_project.name, "description": self.new_project.description,
            },
            "tasks": [_task_to_dict(item) for item in self.tasks],
            "commitments": [{"title": item.title, "start": _instant_to_dict(item.start), "hardness": item.hardness.value} for item in self.commitments],
            "unresolved_reason": self.unresolved_reason,
        }


@dataclass(frozen=True, slots=True)
class InterpretationResponse:
    interpretation: CaptureInterpretation
    provider: str
    model: str
    response_id: str | None = None


def _object(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise InterpretationValidationError(f"{label} has an invalid shape")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InterpretationValidationError(f"{label} must be non-empty text")
    return value.strip()


def _date(value: object) -> DateExpression:
    data = _object(value, {"kind", "value"}, "date expression")
    try:
        kind = DateExpressionKind(data["kind"])
    except (ValueError, TypeError) as exc:
        raise InterpretationValidationError("unsupported date expression") from exc
    raw = data["value"]
    if kind in {DateExpressionKind.TODAY, DateExpressionKind.TOMORROW} and raw is not None:
        raise InterpretationValidationError("relative date value must be null")
    if kind in {DateExpressionKind.WEEKDAY, DateExpressionKind.NEXT_WEEKDAY} and (type(raw) is not int or raw not in range(1, 8)):
        raise InterpretationValidationError("weekday value must be an ISO weekday")
    if kind in {DateExpressionKind.EXPLICIT_DATE, DateExpressionKind.MISSING_YEAR} and not isinstance(raw, str):
        raise InterpretationValidationError("explicit date value must be text")
    return DateExpression(kind, raw)


def _clock(value: object) -> ClockExpression:
    if not isinstance(value, dict):
        raise InterpretationValidationError("clock expression has an invalid shape")
    try:
        kind = ClockExpressionKind(value.get("kind"))
    except (ValueError, TypeError) as exc:
        raise InterpretationValidationError("unsupported clock expression") from exc
    keys = {"kind", "hour", "minute", "period"} if kind is ClockExpressionKind.CLOCK_12 else {"kind", "hour", "minute"}
    data = _object(value, keys, "clock expression")
    hour, minute = data["hour"], data["minute"]
    if type(hour) is not int or type(minute) is not int or minute not in range(60):
        raise InterpretationValidationError("clock components are invalid")
    period = data.get("period")
    if kind is ClockExpressionKind.CLOCK_12:
        if hour not in range(1, 13) or period not in {"AM", "PM"}:
            raise InterpretationValidationError("12-hour clock is invalid")
    elif hour not in range(24):
        raise InterpretationValidationError("24-hour clock is invalid")
    return ClockExpression(kind, hour, minute, period)


def _instant(value: object) -> DateTimeExpression:
    data = _object(value, {"date", "clock"}, "date-time expression")
    return DateTimeExpression(_date(data["date"]), _clock(data["clock"]))


def _project_reference(value: object) -> ProjectReference:
    if value is None:
        return ProjectReference(ProjectReferenceKind.NONE)
    if value == "NEW":
        return ProjectReference(ProjectReferenceKind.NEW)
    if type(value) is int and value > 0:
        return ProjectReference(ProjectReferenceKind.EXISTING, value)
    raise InterpretationValidationError("project reference is invalid")


def _schedule(value: object) -> TaskScheduleIntent:
    if value is None:
        return TaskScheduleIntent(TaskScheduleKind.FLEXIBLE)
    data = _object(value, {"kind", "dates"}, "task schedule")
    try:
        kind = TaskScheduleKind(data["kind"])
    except (ValueError, TypeError) as exc:
        raise InterpretationValidationError("unsupported task schedule") from exc
    if not isinstance(data["dates"], list):
        raise InterpretationValidationError("schedule dates must be an array")
    dates = tuple(_date(item) for item in data["dates"])
    if kind is TaskScheduleKind.DAY and not dates:
        raise InterpretationValidationError("DAY schedule requires at least one date")
    if kind is not TaskScheduleKind.DAY and dates:
        raise InterpretationValidationError("only DAY schedules may contain dates")
    return TaskScheduleIntent(kind, dates)


def _deadline(value: object) -> DeadlineIntent:
    if value is None:
        return DeadlineIntent(DeadlineKind.NONE)
    data = _object(value, {"kind", "value"}, "deadline")
    try:
        kind = DeadlineKind(data["kind"])
    except (ValueError, TypeError) as exc:
        raise InterpretationValidationError("unsupported deadline") from exc
    if kind is DeadlineKind.DATE:
        return DeadlineIntent(kind, date=_date(data["value"]))
    if kind is DeadlineKind.INSTANT:
        return DeadlineIntent(kind, instant=_instant(data["value"]))
    raise InterpretationValidationError("NONE deadline must be represented by null")


def _task(value: object) -> TaskIntent:
    data = _object(value, {"title", "project_id", "importance", "estimated_minutes", "schedule", "deadline"}, "task")
    try:
        importance = TaskImportance(data["importance"])
    except (ValueError, TypeError) as exc:
        raise InterpretationValidationError("task importance is invalid") from exc
    minutes = data["estimated_minutes"]
    if minutes is not None and (type(minutes) is not int or minutes <= 0):
        raise InterpretationValidationError("estimated minutes must be a positive integer")
    return TaskIntent(_text(data["title"], "task title"), _project_reference(data["project_id"]), importance, minutes, _schedule(data["schedule"]), _deadline(data["deadline"]))


def _commitment(value: object) -> FixedCommitmentIntent:
    data = _object(value, {"title", "start", "hardness"}, "commitment")
    try:
        hardness = CommitmentHardness(data["hardness"])
    except (ValueError, TypeError) as exc:
        raise InterpretationValidationError("commitment hardness is invalid") from exc
    return FixedCommitmentIntent(_text(data["title"], "commitment title"), _instant(data["start"]), hardness)


def parse_interpretation(value: object) -> CaptureInterpretation:
    data = _object(value, {"kind", "new_project", "tasks", "commitments", "unresolved_reason"}, "interpretation")
    try:
        outcome = InterpretationOutcome(data["kind"])
    except (ValueError, TypeError) as exc:
        raise InterpretationValidationError("interpretation outcome is invalid") from exc
    if not isinstance(data["tasks"], list) or not isinstance(data["commitments"], list):
        raise InterpretationValidationError("interpretation outputs must be arrays")
    project = None
    if data["new_project"] is not None:
        raw = _object(data["new_project"], {"name", "description"}, "new project")
        if raw["description"] is not None and not isinstance(raw["description"], str):
            raise InterpretationValidationError("project description must be text or null")
        project = NewProjectIntent(_text(raw["name"], "project name"), raw["description"])
    tasks = tuple(_task(item) for item in data["tasks"])
    commitments = tuple(_commitment(item) for item in data["commitments"])
    reason = data["unresolved_reason"]
    if outcome is InterpretationOutcome.UNRESOLVED:
        reason = _text(reason, "unresolved reason")
        if project is not None or tasks or commitments:
            raise InterpretationValidationError("unresolved interpretation cannot contain outputs")
    elif reason is not None:
        raise InterpretationValidationError("applied interpretation cannot contain an unresolved reason")
    if outcome is InterpretationOutcome.APPLY and not (project or tasks or commitments):
        raise InterpretationValidationError("applied interpretation has no output")
    return CaptureInterpretation(outcome, project, tasks, commitments, reason)


def _date_to_dict(value: DateExpression) -> dict[str, Any]:
    return {"kind": value.kind.value, "value": value.value}


def _clock_to_dict(value: ClockExpression) -> dict[str, Any]:
    result = {"kind": value.kind.value, "hour": value.hour, "minute": value.minute}
    if value.kind is ClockExpressionKind.CLOCK_12:
        result["period"] = value.period
    return result


def _instant_to_dict(value: DateTimeExpression) -> dict[str, Any]:
    return {"date": _date_to_dict(value.date), "clock": _clock_to_dict(value.clock)}


def _task_to_dict(value: TaskIntent) -> dict[str, Any]:
    project_id: int | str | None = None
    if value.project.kind is ProjectReferenceKind.EXISTING:
        project_id = value.project.project_id
    elif value.project.kind is ProjectReferenceKind.NEW:
        project_id = "NEW"
    schedule = None if value.schedule.kind is TaskScheduleKind.FLEXIBLE else {"kind": value.schedule.kind.value, "dates": [_date_to_dict(item) for item in value.schedule.dates]}
    deadline = None
    if value.deadline.kind is DeadlineKind.DATE:
        deadline = {"kind": "DATE", "value": _date_to_dict(value.deadline.date)}
    elif value.deadline.kind is DeadlineKind.INSTANT:
        deadline = {"kind": "INSTANT", "value": _instant_to_dict(value.deadline.instant)}
    return {"title": value.title, "project_id": project_id, "importance": value.importance.value,
            "estimated_minutes": value.estimated_minutes, "schedule": schedule, "deadline": deadline}

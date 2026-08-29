"""Typed canonical structured-state models and deterministic validation."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from personal_os.errors import DomainValidationError

UTC_INSTANT_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


class ProjectStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class TaskStatus(StrEnum):
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"


class TaskImportance(StrEnum):
    UNSPECIFIED = "UNSPECIFIED"
    MUST = "MUST"
    SHOULD = "SHOULD"
    COULD = "COULD"


class TaskScheduleMode(StrEnum):
    FLEXIBLE = "FLEXIBLE"
    DAY = "DAY"
    WINDOW = "WINDOW"


class CommitmentHardness(StrEnum):
    UNKNOWN = "UNKNOWN"
    HARD = "HARD"
    SOFT = "SOFT"


class CaptureStatus(StrEnum):
    RECEIVED = "RECEIVED"
    APPLIED = "APPLIED"
    UNRESOLVED = "UNRESOLVED"
    FAILED = "FAILED"


class CaptureFailureKind(StrEnum):
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    REFUSAL = "REFUSAL"
    INVALID_OUTPUT = "INVALID_OUTPUT"


def require_identifier(value: object, field: str = "id") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DomainValidationError(f"{field} must be a positive integer")
    return value


def require_text(value: object, field: str, *, preserve: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{field} must be a non-empty string")
    return value if preserve else value.strip()


def optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DomainValidationError(f"{field} must be a string or None")
    return value


def require_enum(value: object, enum_type: type[StrEnum], field: str) -> StrEnum:
    if not isinstance(value, enum_type):
        allowed = ", ".join(item.value for item in enum_type)
        raise DomainValidationError(f"{field} must be one of: {allowed}")
    return value


def normalize_instant(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise DomainValidationError(f"{field} must be a timezone-aware datetime")
    if value.utcoffset() is None:
        raise DomainValidationError(f"{field} must have a defined UTC offset")
    return value.astimezone(UTC)


def serialize_instant(value: datetime) -> str:
    return normalize_instant(value, "instant").strftime(UTC_INSTANT_FORMAT)


def parse_instant(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise DomainValidationError(f"stored {field} must be text")
    try:
        parsed = datetime.strptime(value, UTC_INSTANT_FORMAT).replace(tzinfo=UTC)
    except ValueError as exc:
        raise DomainValidationError(f"stored {field} is not canonical UTC") from exc
    if serialize_instant(parsed) != value:
        raise DomainValidationError(f"stored {field} is not canonical UTC")
    return parsed


def normalize_date(value: object, field: str) -> date:
    if type(value) is not date:
        raise DomainValidationError(f"{field} must be a calendar date")
    return value


def serialize_date(value: date) -> str:
    return normalize_date(value, "date").isoformat()


def parse_date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise DomainValidationError(f"stored {field} must be text")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise DomainValidationError(f"stored {field} is not a canonical date") from exc
    if parsed.isoformat() != value:
        raise DomainValidationError(f"stored {field} is not a canonical date")
    return parsed


def optional_instant(value: object, field: str) -> datetime | None:
    return None if value is None else normalize_instant(value, field)


def optional_date(value: object, field: str) -> date | None:
    return None if value is None else normalize_date(value, field)


def validate_estimated_minutes(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DomainValidationError("estimated_minutes must be a positive integer")
    return value


def _validate_json_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DomainValidationError("rule parameters must contain finite numbers")
        return value
    if isinstance(value, list):
        return [_validate_json_value(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise DomainValidationError("rule parameter keys must be strings")
        return {key: _validate_json_value(item) for key, item in value.items()}
    raise DomainValidationError("rule parameters must contain valid JSON values")


def canonicalize_parameters(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DomainValidationError("rule parameters must be a JSON object")
    validated = _validate_json_value(value)
    serialized = json.dumps(
        validated, allow_nan=False, separators=(",", ":"), sort_keys=True
    )
    parsed = json.loads(serialized)
    if not isinstance(parsed, dict):
        raise DomainValidationError("rule parameters must be a JSON object")
    return parsed


def serialize_parameters(value: object) -> str:
    return json.dumps(
        canonicalize_parameters(value),
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def parse_parameters(value: object) -> dict[str, Any]:
    if not isinstance(value, str):
        raise DomainValidationError("stored rule parameters must be text")
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise DomainValidationError("stored rule parameters are malformed JSON") from exc
    if not isinstance(parsed, dict):
        raise DomainValidationError("stored rule parameters must be a JSON object")
    return canonicalize_parameters(parsed)


def validate_task_fields(
    *, title: object, project_id: object, status: object, importance: object,
    schedule_mode: object, day_date: object, window_start: object,
    window_end: object, deadline_date: object, deadline_at: object,
    estimated_minutes: object,
) -> dict[str, object]:
    normalized_project_id = None if project_id is None else require_identifier(project_id, "project_id")
    normalized_mode = require_enum(schedule_mode, TaskScheduleMode, "schedule_mode")
    normalized_day = optional_date(day_date, "day_date")
    normalized_start = optional_instant(window_start, "window_start")
    normalized_end = optional_instant(window_end, "window_end")
    normalized_deadline_date = optional_date(deadline_date, "deadline_date")
    normalized_deadline_at = optional_instant(deadline_at, "deadline_at")
    if normalized_mode is TaskScheduleMode.FLEXIBLE:
        if any(value is not None for value in (normalized_day, normalized_start, normalized_end)):
            raise DomainValidationError("FLEXIBLE tasks cannot have day or window fields")
    elif normalized_mode is TaskScheduleMode.DAY:
        if normalized_day is None or normalized_start is not None or normalized_end is not None:
            raise DomainValidationError("DAY tasks require only day_date")
    elif normalized_mode is TaskScheduleMode.WINDOW:
        if normalized_day is not None or normalized_start is None or normalized_end is None:
            raise DomainValidationError("WINDOW tasks require only window_start and window_end")
        if normalized_start >= normalized_end:
            raise DomainValidationError("window_start must be before window_end")
    if normalized_deadline_date is not None and normalized_deadline_at is not None:
        raise DomainValidationError("deadline_date and deadline_at are mutually exclusive")
    return {
        "title": require_text(title, "title"),
        "project_id": normalized_project_id,
        "status": require_enum(status, TaskStatus, "status"),
        "importance": require_enum(importance, TaskImportance, "importance"),
        "schedule_mode": normalized_mode,
        "day_date": normalized_day,
        "window_start": normalized_start,
        "window_end": normalized_end,
        "deadline_date": normalized_deadline_date,
        "deadline_at": normalized_deadline_at,
        "estimated_minutes": validate_estimated_minutes(estimated_minutes),
    }


def _validate_timestamps(created_at: object, updated_at: object) -> tuple[datetime, datetime]:
    created = normalize_instant(created_at, "created_at")
    updated = normalize_instant(updated_at, "updated_at")
    if updated < created:
        raise DomainValidationError("updated_at must not be before created_at")
    return created, updated


@dataclass(frozen=True, slots=True)
class Project:
    id: int
    name: str
    description: str | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    source_capture_id: int | None = None

    def __post_init__(self) -> None:
        created, updated = _validate_timestamps(self.created_at, self.updated_at)
        object.__setattr__(self, "id", require_identifier(self.id))
        object.__setattr__(self, "name", require_text(self.name, "name"))
        object.__setattr__(self, "description", optional_text(self.description, "description"))
        object.__setattr__(self, "status", require_enum(self.status, ProjectStatus, "status"))
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)
        object.__setattr__(self, "source_capture_id", None if self.source_capture_id is None else require_identifier(self.source_capture_id, "source_capture_id"))


@dataclass(frozen=True, slots=True)
class Task:
    id: int
    title: str
    project_id: int | None
    status: TaskStatus
    importance: TaskImportance
    schedule_mode: TaskScheduleMode
    day_date: date | None
    window_start: datetime | None
    window_end: datetime | None
    deadline_date: date | None
    deadline_at: datetime | None
    estimated_minutes: int | None
    created_at: datetime
    updated_at: datetime
    source_capture_id: int | None = None

    def __post_init__(self) -> None:
        values = validate_task_fields(
            title=self.title, project_id=self.project_id, status=self.status,
            importance=self.importance, schedule_mode=self.schedule_mode,
            day_date=self.day_date, window_start=self.window_start,
            window_end=self.window_end, deadline_date=self.deadline_date,
            deadline_at=self.deadline_at, estimated_minutes=self.estimated_minutes,
        )
        created, updated = _validate_timestamps(self.created_at, self.updated_at)
        object.__setattr__(self, "id", require_identifier(self.id))
        for field, value in values.items():
            object.__setattr__(self, field, value)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)
        object.__setattr__(self, "source_capture_id", None if self.source_capture_id is None else require_identifier(self.source_capture_id, "source_capture_id"))


@dataclass(frozen=True, slots=True)
class FixedCommitment:
    id: int
    title: str
    start_at: datetime
    end_at: datetime | None
    hardness: CommitmentHardness
    created_at: datetime
    updated_at: datetime
    source_capture_id: int | None = None

    def __post_init__(self) -> None:
        start = normalize_instant(self.start_at, "start_at")
        end = optional_instant(self.end_at, "end_at")
        if end is not None and start >= end:
            raise DomainValidationError("start_at must be before end_at")
        created, updated = _validate_timestamps(self.created_at, self.updated_at)
        object.__setattr__(self, "id", require_identifier(self.id))
        object.__setattr__(self, "title", require_text(self.title, "title"))
        object.__setattr__(self, "start_at", start)
        object.__setattr__(self, "end_at", end)
        object.__setattr__(self, "hardness", require_enum(self.hardness, CommitmentHardness, "hardness"))
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)
        object.__setattr__(self, "source_capture_id", None if self.source_capture_id is None else require_identifier(self.source_capture_id, "source_capture_id"))


@dataclass(frozen=True, slots=True)
class Rule:
    id: int
    kind: str
    parameters: dict[str, Any]
    enabled: bool
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise DomainValidationError("enabled must be a boolean")
        created, updated = _validate_timestamps(self.created_at, self.updated_at)
        object.__setattr__(self, "id", require_identifier(self.id))
        object.__setattr__(self, "kind", require_text(self.kind, "kind"))
        object.__setattr__(self, "parameters", canonicalize_parameters(self.parameters))
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)


@dataclass(frozen=True, slots=True)
class InboxItem:
    id: int
    raw_text: str
    unresolved_reason: str
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    source_capture_id: int | None = None

    def __post_init__(self) -> None:
        created, updated = _validate_timestamps(self.created_at, self.updated_at)
        object.__setattr__(self, "id", require_identifier(self.id))
        object.__setattr__(self, "raw_text", require_text(self.raw_text, "raw_text", preserve=True))
        object.__setattr__(self, "unresolved_reason", require_text(self.unresolved_reason, "unresolved_reason"))
        object.__setattr__(self, "resolved_at", optional_instant(self.resolved_at, "resolved_at"))
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)
        object.__setattr__(self, "source_capture_id", None if self.source_capture_id is None else require_identifier(self.source_capture_id, "source_capture_id"))

    @property
    def is_resolved(self) -> bool:
        return self.resolved_at is not None


@dataclass(frozen=True, slots=True)
class Capture:
    id: int
    raw_text: str
    status: CaptureStatus
    reference_time: datetime
    timezone_name: str
    interpretation: dict[str, Any] | None
    interpretation_version: int | None
    model_provider: str | None
    model_name: str | None
    model_response_id: str | None
    unresolved_reason: str | None
    failure_kind: CaptureFailureKind | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        created, updated = _validate_timestamps(self.created_at, self.updated_at)
        object.__setattr__(self, "id", require_identifier(self.id))
        object.__setattr__(self, "raw_text", require_text(self.raw_text, "raw_text", preserve=True))
        object.__setattr__(self, "status", require_enum(self.status, CaptureStatus, "status"))
        object.__setattr__(self, "reference_time", normalize_instant(self.reference_time, "reference_time"))
        object.__setattr__(self, "timezone_name", require_text(self.timezone_name, "timezone_name"))
        if self.interpretation is not None and not isinstance(self.interpretation, dict):
            raise DomainValidationError("interpretation must be a JSON object or None")
        if (self.interpretation is None) != (self.interpretation_version is None):
            raise DomainValidationError("interpretation and version must both be present or absent")
        if self.interpretation_version not in (None, 1):
            raise DomainValidationError("interpretation_version must be 1")
        for field in ("model_provider", "model_name", "model_response_id", "unresolved_reason", "failure_reason"):
            object.__setattr__(self, field, optional_text(getattr(self, field), field))
        if self.failure_kind is not None:
            object.__setattr__(self, "failure_kind", require_enum(self.failure_kind, CaptureFailureKind, "failure_kind"))
        if self.status is CaptureStatus.RECEIVED:
            if any(value is not None for value in (self.interpretation, self.unresolved_reason, self.failure_kind, self.failure_reason)):
                raise DomainValidationError("RECEIVED capture cannot contain finalization fields")
        elif self.status is CaptureStatus.APPLIED:
            if self.interpretation is None or any(value is not None for value in (self.unresolved_reason, self.failure_kind, self.failure_reason)):
                raise DomainValidationError("APPLIED capture has inconsistent finalization fields")
        elif self.status is CaptureStatus.UNRESOLVED:
            if self.interpretation is None or self.unresolved_reason is None or self.failure_kind is not None or self.failure_reason is not None:
                raise DomainValidationError("UNRESOLVED capture has inconsistent finalization fields")
        elif self.status is CaptureStatus.FAILED:
            if self.failure_kind is None or self.failure_reason is None or self.unresolved_reason is not None:
                raise DomainValidationError("FAILED capture has inconsistent finalization fields")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)

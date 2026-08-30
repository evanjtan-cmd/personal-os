"""Typed work-session records and lifecycle errors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from personal_os.errors import DomainValidationError, PersonalOSError
from personal_os.models import normalize_instant, require_enum, require_identifier


class SessionOutcome(StrEnum):
    FINISHED = "FINISHED"
    PROGRESS = "PROGRESS"
    BLOCKED = "BLOCKED"


class SessionStartFailureKind(StrEnum):
    TASK_NOT_OPEN = "TASK_NOT_OPEN"
    PROJECT_COMPLETED = "PROJECT_COMPLETED"
    SCHEDULE_INELIGIBLE = "SCHEDULE_INELIGIBLE"
    HARD_COMMITMENT_ACTIVE = "HARD_COMMITMENT_ACTIVE"
    DURATION_NOT_ALLOWED = "DURATION_NOT_ALLOWED"
    FEASIBLE_MUST_REQUIRED = "FEASIBLE_MUST_REQUIRED"


class SessionConflictKind(StrEnum):
    ACTIVE_SESSION_EXISTS = "ACTIVE_SESSION_EXISTS"
    SESSION_ALREADY_CLOSED = "SESSION_ALREADY_CLOSED"
    TASK_STATE_CONFLICT = "TASK_STATE_CONFLICT"


class SessionStartError(PersonalOSError):
    def __init__(self, kind: SessionStartFailureKind, reason: str) -> None:
        super().__init__(reason)
        self.kind = kind


class SessionConflictError(PersonalOSError):
    def __init__(self, kind: SessionConflictKind, reason: str) -> None:
        super().__init__(reason)
        self.kind = kind


def optional_session_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{field} must be non-empty text or None")
    return value


@dataclass(frozen=True, slots=True)
class WorkSession:
    id: int
    task_id: int
    planned_minutes: int
    started_at: datetime
    ended_at: datetime | None
    outcome: SessionOutcome | None
    start_reason: str | None
    result_note: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_identifier(self.id))
        object.__setattr__(self, "task_id", require_identifier(self.task_id, "task_id"))
        if type(self.planned_minutes) is not int or self.planned_minutes <= 0:
            raise DomainValidationError("planned_minutes must be a positive integer")
        started = normalize_instant(self.started_at, "started_at")
        ended = (
            None
            if self.ended_at is None
            else normalize_instant(self.ended_at, "ended_at")
        )
        outcome = (
            None
            if self.outcome is None
            else require_enum(self.outcome, SessionOutcome, "outcome")
        )
        start_reason = optional_session_text(self.start_reason, "start_reason")
        result_note = optional_session_text(self.result_note, "result_note")
        if ended is None:
            if outcome is not None or result_note is not None:
                raise DomainValidationError(
                    "active session cannot contain outcome or result_note"
                )
        else:
            if outcome is None:
                raise DomainValidationError("closed session requires an outcome")
            if ended < started:
                raise DomainValidationError("ended_at must not be before started_at")
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "ended_at", ended)
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "start_reason", start_reason)
        object.__setattr__(self, "result_note", result_note)

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    @property
    def actual_duration(self) -> timedelta | None:
        if self.ended_at is None:
            return None
        return self.ended_at - self.started_at

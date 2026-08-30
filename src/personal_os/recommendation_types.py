"""Typed boundary structures for deterministic recommendation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from personal_os.errors import DomainValidationError, PersonalOSError
from personal_os.models import Task, TaskImportance, normalize_instant, require_identifier, require_text


class EligibilityReason(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    STATUS_BLOCKED = "STATUS_BLOCKED"
    STATUS_COMPLETED = "STATUS_COMPLETED"
    PROJECT_COMPLETED = "PROJECT_COMPLETED"
    DAY_FUTURE = "DAY_FUTURE"
    WINDOW_NOT_STARTED = "WINDOW_NOT_STARTED"
    WINDOW_EXPIRED = "WINDOW_EXPIRED"


class ScheduleState(StrEnum):
    FLEXIBLE = "FLEXIBLE"
    DAY_FUTURE = "DAY_FUTURE"
    DAY_TODAY = "DAY_TODAY"
    DAY_MISSED = "DAY_MISSED"
    WINDOW_FUTURE = "WINDOW_FUTURE"
    WINDOW_ACTIVE = "WINDOW_ACTIVE"
    WINDOW_EXPIRED = "WINDOW_EXPIRED"


class DeadlineState(StrEnum):
    NONE = "NONE"
    FUTURE = "FUTURE"
    DUE_TODAY = "DUE_TODAY"
    OVERDUE = "OVERDUE"


class AvailabilityKind(StrEnum):
    NO_KNOWN_HARD_BOUND = "NO_KNOWN_HARD_BOUND"
    FINITE = "FINITE"
    BLOCKED_ACTIVE_HARD = "BLOCKED_ACTIVE_HARD"
    BLOCKED_ACTIVE_OPEN_ENDED_HARD = "BLOCKED_ACTIVE_OPEN_ENDED_HARD"


class DeterministicNoWorkReason(StrEnum):
    ACTIVE_HARD_COMMITMENT = "ACTIVE_HARD_COMMITMENT"
    ACTIVE_OPEN_ENDED_HARD_COMMITMENT = "ACTIVE_OPEN_ENDED_HARD_COMMITMENT"
    NO_FEASIBLE_TASKS = "NO_FEASIBLE_TASKS"


class RecommendationChoiceKind(StrEnum):
    RECOMMEND = "RECOMMEND"
    NO_WORK = "NO_WORK"


class RecommendationResultKind(StrEnum):
    RECOMMEND = "RECOMMEND"
    NO_WORK = "NO_WORK"


class RecommendationFailureKind(StrEnum):
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    REFUSAL = "REFUSAL"
    INVALID_OUTPUT = "INVALID_OUTPUT"


class RecommendationError(PersonalOSError):
    def __init__(self, kind: RecommendationFailureKind, reason: str) -> None:
        super().__init__(reason)
        self.kind = kind


@dataclass(frozen=True, slots=True)
class RecommendationContext:
    reference_time: datetime
    timezone_name: str
    available_minutes: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reference_time", normalize_instant(self.reference_time, "reference_time"))
        object.__setattr__(self, "timezone_name", require_text(self.timezone_name, "timezone_name"))
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise DomainValidationError(
                "timezone_name must identify an IANA timezone"
            ) from exc
        if self.available_minutes is not None and (
            type(self.available_minutes) is not int or self.available_minutes < 0
        ):
            raise DomainValidationError("available_minutes must be a nonnegative integer or None")


@dataclass(frozen=True, slots=True)
class AvailabilityDecision:
    kind: AvailabilityKind
    available_minutes: int | None
    limiting_commitment_id: int | None = None


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    task: Task
    eligible: bool
    reasons: tuple[EligibilityReason, ...]
    schedule_state: ScheduleState
    days_late: int | None
    deadline_state: DeadlineState


@dataclass(frozen=True, slots=True)
class EligibleTaskCandidate:
    task_id: int
    title: str
    project_name: str | None
    importance: TaskImportance
    schedule_state: ScheduleState
    days_late: int | None
    deadline_state: DeadlineState
    deadline_date: str | None
    deadline_at: str | None
    estimated_minutes: int | None
    allowed_durations: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RecommendationRankingContext:
    availability_kind: AvailabilityKind
    available_minutes: int | None
    must_gated: bool


@dataclass(frozen=True, slots=True)
class RecommendationChoice:
    kind: RecommendationChoiceKind
    task_id: int | None
    duration_minutes: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class RecommendationResult:
    kind: RecommendationResultKind
    availability: AvailabilityDecision
    explanation: str
    task: Task | None = None
    project_name: str | None = None
    duration_minutes: int | None = None
    deterministic_reason: DeterministicNoWorkReason | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "explanation", require_text(self.explanation, "explanation"))
        if self.kind is RecommendationResultKind.RECOMMEND:
            if self.task is None or self.duration_minutes is None:
                raise DomainValidationError("recommendation result requires task and duration")
            require_identifier(self.task.id, "task_id")
        elif any(value is not None for value in (self.task, self.project_name, self.duration_minutes)):
            raise DomainValidationError("no-work result cannot contain recommendation fields")

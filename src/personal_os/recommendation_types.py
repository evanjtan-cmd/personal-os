"""Typed boundary structures for deterministic recommendation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from personal_os.errors import DomainValidationError, PersonalOSError
from personal_os.models import (
    Task, TaskExecutionMode, TaskImportance, normalize_instant,
    require_identifier, require_text,
)

MAX_EXCLUDED_TASK_IDS = 100


class EligibilityReason(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    STATUS_BLOCKED = "STATUS_BLOCKED"
    STATUS_COMPLETED = "STATUS_COMPLETED"
    STATUS_CANCELLED = "STATUS_CANCELLED"
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
    ALL_FEASIBLE_MUST_TASKS_EXCLUDED = "ALL_FEASIBLE_MUST_TASKS_EXCLUDED"
    ALL_PERMISSIBLE_TASKS_EXCLUDED = "ALL_PERMISSIBLE_TASKS_EXCLUDED"


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
    execution_mode: TaskExecutionMode
    allowed_durations: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RecommendationRankingContext:
    availability_kind: AvailabilityKind
    available_minutes: int | None
    must_gated: bool
    alternative_required: bool = False


@dataclass(frozen=True, slots=True)
class RecommendationChoice:
    kind: RecommendationChoiceKind
    task_id: int | None
    duration_minutes: int | None
    action: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class LowerPriorityAuthorization:
    task_id: int
    duration_minutes: int
    timezone_name: str
    available_minutes: int | None
    feasible_high_task_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", require_identifier(self.task_id, "task_id"))
        if type(self.duration_minutes) is not int or self.duration_minutes <= 0:
            raise DomainValidationError(
                "duration_minutes must be a positive integer"
            )
        timezone_name = require_text(self.timezone_name, "timezone_name")
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise DomainValidationError(
                "timezone_name must identify an IANA timezone"
            ) from exc
        object.__setattr__(self, "timezone_name", timezone_name)
        if self.available_minutes is not None and (
            type(self.available_minutes) is not int or self.available_minutes < 0
        ):
            raise DomainValidationError(
                "available_minutes must be a nonnegative integer or None"
            )
        if (
            not isinstance(self.feasible_high_task_ids, tuple)
            or not self.feasible_high_task_ids
            or any(
                type(task_id) is not int or task_id <= 0
                for task_id in self.feasible_high_task_ids
            )
        ):
            raise DomainValidationError(
                "feasible_high_task_ids must be a non-empty tuple of positive integers"
            )
        if len(set(self.feasible_high_task_ids)) != len(
            self.feasible_high_task_ids
        ):
            raise DomainValidationError(
                "feasible_high_task_ids must contain distinct IDs"
            )
        if len(self.feasible_high_task_ids) > MAX_EXCLUDED_TASK_IDS:
            raise DomainValidationError(
                f"feasible_high_task_ids may contain at most "
                f"{MAX_EXCLUDED_TASK_IDS} IDs"
            )
        if tuple(sorted(self.feasible_high_task_ids)) != self.feasible_high_task_ids:
            raise DomainValidationError(
                "feasible_high_task_ids must be sorted"
            )


@dataclass(frozen=True, slots=True)
class RecommendationResult:
    kind: RecommendationResultKind
    availability: AvailabilityDecision
    explanation: str
    task: Task | None = None
    project_name: str | None = None
    duration_minutes: int | None = None
    action: str | None = None
    deterministic_reason: DeterministicNoWorkReason | None = None
    lower_priority_authorization: LowerPriorityAuthorization | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "explanation", require_text(self.explanation, "explanation"))
        if self.kind is RecommendationResultKind.RECOMMEND:
            if self.task is None or self.duration_minutes is None or self.action is None:
                raise DomainValidationError(
                    "recommendation result requires task, duration, and action"
                )
            require_identifier(self.task.id, "task_id")
            object.__setattr__(self, "action", require_text(self.action, "action"))
            if self.lower_priority_authorization is not None:
                if not isinstance(
                    self.lower_priority_authorization,
                    LowerPriorityAuthorization,
                ):
                    raise DomainValidationError(
                        "lower_priority_authorization must be a LowerPriorityAuthorization"
                    )
                if (
                    self.lower_priority_authorization.task_id != self.task.id
                    or self.lower_priority_authorization.duration_minutes
                    != self.duration_minutes
                ):
                    raise DomainValidationError(
                        "lower-priority authorization must match the recommendation"
                    )
        elif any(value is not None for value in (
            self.task, self.project_name, self.duration_minutes, self.action,
            self.lower_priority_authorization,
        )):
            raise DomainValidationError("no-work result cannot contain recommendation fields")

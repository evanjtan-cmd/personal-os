"""Typed application boundary for work activation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from personal_os.errors import DomainValidationError
from personal_os.models import Task, normalize_instant, require_text
from personal_os.recommendation_types import (
    RecommendationContext,
    RecommendationResult,
    RecommendationResultKind,
)
from personal_os.session_types import WorkSession


class WorkActivationResultKind(StrEnum):
    ACTIVE_SESSION = "ACTIVE_SESSION"
    RECOMMEND = "RECOMMEND"
    NO_WORK = "NO_WORK"


@dataclass(frozen=True, slots=True)
class WorkActivationContext:
    reference_time: datetime
    timezone_name: str | None = None
    time_cap_minutes: int | None = None

    def __post_init__(self) -> None:
        if self.time_cap_minutes is not None and (
            type(self.time_cap_minutes) is not int or self.time_cap_minutes < 0
        ):
            raise DomainValidationError(
                "time_cap_minutes must be a nonnegative integer or None"
            )
        object.__setattr__(
            self,
            "reference_time",
            normalize_instant(self.reference_time, "reference_time"),
        )
        if self.timezone_name is not None:
            timezone_name = require_text(self.timezone_name, "timezone_name")
            try:
                ZoneInfo(timezone_name)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise DomainValidationError(
                    "timezone_name must identify an IANA timezone"
                ) from exc
            object.__setattr__(self, "timezone_name", timezone_name)

    def as_recommendation_context(
        self, timezone_name: str | None = None
    ) -> RecommendationContext:
        return RecommendationContext(
            reference_time=self.reference_time,
            timezone_name=(
                self.timezone_name if timezone_name is None else timezone_name
            ),
            available_minutes=self.time_cap_minutes,
        )


@dataclass(frozen=True, slots=True)
class WorkActivationResult:
    kind: WorkActivationResultKind
    active_session: WorkSession | None = None
    active_task: Task | None = None
    recommendation: RecommendationResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, WorkActivationResultKind):
            raise DomainValidationError(
                "kind must be a WorkActivationResultKind"
            )
        if self.kind is WorkActivationResultKind.ACTIVE_SESSION:
            if (
                self.active_session is None
                or self.active_task is None
                or self.recommendation is not None
            ):
                raise DomainValidationError(
                    "active-session activation requires session and task only"
                )
            if not self.active_session.is_active:
                raise DomainValidationError(
                    "active-session activation requires an active session"
                )
            if self.active_session.task_id != self.active_task.id:
                raise DomainValidationError(
                    "active-session activation task does not match session"
                )
            return
        if (
            self.active_session is not None
            or self.active_task is not None
            or self.recommendation is None
        ):
            raise DomainValidationError(
                "recommendation activation requires recommendation only"
            )
        expected = (
            WorkActivationResultKind.RECOMMEND
            if self.recommendation.kind is RecommendationResultKind.RECOMMEND
            else WorkActivationResultKind.NO_WORK
        )
        if self.kind is not expected:
            raise DomainValidationError(
                "activation kind does not match recommendation result"
            )

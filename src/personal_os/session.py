"""Deterministic work-session lifecycle application service."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from personal_os.eligibility import calculate_availability, evaluate_task
from personal_os.errors import DomainValidationError
from personal_os.models import (
    FixedCommitment, Project, ProjectStatus, Task, TaskImportance, TaskStatus,
    normalize_instant, require_enum, require_identifier,
)
from personal_os.recommendation import allowed_durations
from personal_os.recommendation_types import AvailabilityKind, RecommendationContext
from personal_os.session_types import (
    SessionOutcome, SessionStartError, SessionStartFailureKind, WorkSession,
    optional_session_text,
)
from personal_os.state import SQLiteStateStore


def validate_session_start(
    *, selected: Task, planned_minutes: int, context: RecommendationContext,
    projects: list[Project], tasks: list[Task],
    commitments: list[FixedCommitment],
) -> None:
    """Apply start rejection policy in its explicit deterministic order."""

    project_map = {item.id: item for item in projects}
    if selected.status is not TaskStatus.OPEN:
        raise SessionStartError(
            SessionStartFailureKind.TASK_NOT_OPEN,
            f"task {selected.id} is not OPEN",
        )
    if (selected.project_id is not None and
            project_map[selected.project_id].status is ProjectStatus.COMPLETED):
        raise SessionStartError(
            SessionStartFailureKind.PROJECT_COMPLETED,
            f"task {selected.id} belongs to a completed project",
        )
    local_date = context.reference_time.astimezone(
        ZoneInfo(context.timezone_name)
    ).date()
    decision = evaluate_task(
        selected, projects=project_map, now=context.reference_time,
        local_date=local_date,
    )
    if not decision.eligible:
        raise SessionStartError(
            SessionStartFailureKind.SCHEDULE_INELIGIBLE,
            f"task {selected.id} is not schedule-eligible",
        )
    availability = calculate_availability(context, commitments)
    if availability.kind in {
        AvailabilityKind.BLOCKED_ACTIVE_HARD,
        AvailabilityKind.BLOCKED_ACTIVE_OPEN_ENDED_HARD,
    }:
        raise SessionStartError(
            SessionStartFailureKind.HARD_COMMITMENT_ACTIVE,
            "a HARD commitment is active",
        )
    if planned_minutes not in allowed_durations(
        selected.estimated_minutes, availability.available_minutes
    ):
        raise SessionStartError(
            SessionStartFailureKind.DURATION_NOT_ALLOWED,
            f"planned duration {planned_minutes} is not currently allowed",
        )
    feasible_must = any(
        item.importance is TaskImportance.MUST
        and evaluate_task(
            item, projects=project_map, now=context.reference_time,
            local_date=local_date,
        ).eligible
        and bool(allowed_durations(
            item.estimated_minutes, availability.available_minutes
        ))
        for item in tasks
    )
    if feasible_must and selected.importance is not TaskImportance.MUST:
        raise SessionStartError(
            SessionStartFailureKind.FEASIBLE_MUST_REQUIRED,
            "a feasible MUST task currently requires selection",
        )


class SessionService:
    def __init__(self, store: SQLiteStateStore) -> None:
        self.store = store

    def start_session(
        self, *, task_id: int, planned_minutes: int,
        context: RecommendationContext, start_reason: str | None = None,
    ) -> WorkSession:
        task_id = require_identifier(task_id, "task_id")
        if type(planned_minutes) is not int or planned_minutes <= 0:
            raise DomainValidationError("planned_minutes must be a positive integer")
        if not isinstance(context, RecommendationContext):
            raise DomainValidationError("context must be a RecommendationContext")
        reason = optional_session_text(start_reason, "start_reason")
        return self.store.start_session_atomically(
            task_id=task_id, planned_minutes=planned_minutes,
            context=context, start_reason=reason,
        )

    def close_session(
        self, *, session_id: int, outcome: SessionOutcome,
        ended_at: datetime, result_note: str | None = None,
    ) -> WorkSession:
        session_id = require_identifier(session_id, "session_id")
        outcome = require_enum(outcome, SessionOutcome, "outcome")  # type: ignore[assignment]
        ended = normalize_instant(ended_at, "ended_at")
        note = optional_session_text(result_note, "result_note")
        return self.store.close_session_atomically(
            session_id=session_id, outcome=outcome,
            ended_at=ended, result_note=note,
        )

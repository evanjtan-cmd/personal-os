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
from personal_os.recommendation_types import (
    AvailabilityKind, LowerPriorityAuthorization, RecommendationContext,
)
from personal_os.session_types import (
    SessionOutcome, SessionStartError, SessionStartFailureKind, WorkSession,
    optional_session_text,
)
from personal_os.state import SQLiteStateStore


def validate_session_start(
    *, selected: Task, planned_minutes: int, context: RecommendationContext,
    projects: list[Project], tasks: list[Task],
    commitments: list[FixedCommitment],
    lower_priority_authorization: LowerPriorityAuthorization | None = None,
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
        selected.execution_mode, selected.estimated_minutes, availability.kind,
        availability.available_minutes,
    ):
        raise SessionStartError(
            SessionStartFailureKind.DURATION_NOT_ALLOWED,
            f"planned duration {planned_minutes} is not currently allowed",
        )
    feasible_high_task_ids = tuple(sorted(
        item.id
        for item in tasks
        if item.importance is TaskImportance.MUST
        and evaluate_task(
            item, projects=project_map, now=context.reference_time,
            local_date=local_date,
        ).eligible
        and bool(allowed_durations(
            item.execution_mode, item.estimated_minutes, availability.kind,
            availability.available_minutes,
        ))
    ))
    if lower_priority_authorization is not None:
        if (
            lower_priority_authorization.task_id != selected.id
            or lower_priority_authorization.duration_minutes != planned_minutes
            or lower_priority_authorization.timezone_name != context.timezone_name
            or lower_priority_authorization.available_minutes
            != context.available_minutes
            or selected.importance is TaskImportance.MUST
        ):
            raise SessionStartError(
                SessionStartFailureKind.PRIORITY_AUTHORIZATION_MISMATCH,
                "the lower-priority authorization does not match this Start request",
            )
        if (
            lower_priority_authorization.feasible_high_task_ids
            != feasible_high_task_ids
        ):
            raise SessionStartError(
                SessionStartFailureKind.PRIORITY_AUTHORIZATION_STALE,
                "High-priority availability changed; request a fresh recommendation",
            )
    if (
        feasible_high_task_ids
        and selected.importance is not TaskImportance.MUST
        and lower_priority_authorization is None
    ):
        raise SessionStartError(
            SessionStartFailureKind.FEASIBLE_MUST_REQUIRED,
            "a feasible High-priority Task currently requires selection",
        )


class SessionService:
    def __init__(self, store: SQLiteStateStore) -> None:
        self.store = store

    def start_session(
        self, *, task_id: int, planned_minutes: int,
        context: RecommendationContext, selected_action: str | None = None,
        start_reason: str | None = None,
        lower_priority_authorization: LowerPriorityAuthorization | None = None,
    ) -> WorkSession:
        task_id = require_identifier(task_id, "task_id")
        if type(planned_minutes) is not int or planned_minutes <= 0:
            raise DomainValidationError("planned_minutes must be a positive integer")
        if not isinstance(context, RecommendationContext):
            raise DomainValidationError("context must be a RecommendationContext")
        if (
            lower_priority_authorization is not None
            and not isinstance(
                lower_priority_authorization, LowerPriorityAuthorization
            )
        ):
            raise DomainValidationError(
                "lower_priority_authorization must be a LowerPriorityAuthorization or None"
            )
        action = optional_session_text(selected_action, "selected_action")
        reason = optional_session_text(start_reason, "start_reason")
        return self.store.start_session_atomically(
            task_id=task_id, planned_minutes=planned_minutes,
            context=context, selected_action=action, start_reason=reason,
            lower_priority_authorization=lower_priority_authorization,
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

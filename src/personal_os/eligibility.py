"""Pure deterministic eligibility, deadline, and availability evaluation."""

from __future__ import annotations

from datetime import datetime

from personal_os.models import (
    CommitmentHardness, FixedCommitment, Project, ProjectStatus, Task,
    TaskScheduleMode, TaskStatus,
)
from personal_os.recommendation_types import (
    AvailabilityDecision, AvailabilityKind, DeadlineState, EligibilityDecision,
    EligibilityReason, RecommendationContext, ScheduleState,
)


def deadline_state(task: Task, *, now: datetime, local_date) -> DeadlineState:
    if task.deadline_date is not None:
        if local_date < task.deadline_date:
            return DeadlineState.FUTURE
        if local_date == task.deadline_date:
            return DeadlineState.DUE_TODAY
        return DeadlineState.OVERDUE
    if task.deadline_at is not None:
        return DeadlineState.FUTURE if now < task.deadline_at else DeadlineState.OVERDUE
    return DeadlineState.NONE


def evaluate_task(
    task: Task, *, projects: dict[int, Project], now: datetime, local_date,
) -> EligibilityDecision:
    reasons: list[EligibilityReason] = []
    if task.status is TaskStatus.BLOCKED:
        reasons.append(EligibilityReason.STATUS_BLOCKED)
    elif task.status is TaskStatus.COMPLETED:
        reasons.append(EligibilityReason.STATUS_COMPLETED)
    if task.project_id is not None and projects[task.project_id].status is ProjectStatus.COMPLETED:
        reasons.append(EligibilityReason.PROJECT_COMPLETED)

    days_late = None
    if task.schedule_mode is TaskScheduleMode.FLEXIBLE:
        schedule = ScheduleState.FLEXIBLE
    elif task.schedule_mode is TaskScheduleMode.DAY:
        if task.day_date > local_date:
            schedule = ScheduleState.DAY_FUTURE
            reasons.append(EligibilityReason.DAY_FUTURE)
        elif task.day_date == local_date:
            schedule = ScheduleState.DAY_TODAY
        else:
            schedule = ScheduleState.DAY_MISSED
            days_late = (local_date - task.day_date).days
    elif now < task.window_start:
        schedule = ScheduleState.WINDOW_FUTURE
        reasons.append(EligibilityReason.WINDOW_NOT_STARTED)
    elif now < task.window_end:
        schedule = ScheduleState.WINDOW_ACTIVE
    else:
        schedule = ScheduleState.WINDOW_EXPIRED
        reasons.append(EligibilityReason.WINDOW_EXPIRED)

    eligible = not reasons
    return EligibilityDecision(
        task, eligible,
        (EligibilityReason.ELIGIBLE,) if eligible else tuple(reasons),
        schedule, days_late, deadline_state(task, now=now, local_date=local_date),
    )


def calculate_availability(
    context: RecommendationContext, commitments: list[FixedCommitment],
) -> AvailabilityDecision:
    now = context.reference_time
    future: list[FixedCommitment] = []
    for item in commitments:
        if item.hardness is not CommitmentHardness.HARD:
            continue
        if item.end_at is not None and item.end_at <= now:
            continue
        if item.start_at <= now:
            kind = (
                AvailabilityKind.BLOCKED_ACTIVE_OPEN_ENDED_HARD
                if item.end_at is None
                else AvailabilityKind.BLOCKED_ACTIVE_HARD
            )
            return AvailabilityDecision(kind, 0, item.id)
        future.append(item)

    hard_minutes = None
    limiting_id = None
    if future:
        earliest = min(future, key=lambda item: (item.start_at, item.id))
        hard_minutes = max(0, int((earliest.start_at - now).total_seconds() // 60))
        limiting_id = earliest.id
    limits = [value for value in (hard_minutes, context.available_minutes) if value is not None]
    if not limits:
        return AvailabilityDecision(AvailabilityKind.NO_KNOWN_HARD_BOUND, None)
    finite = min(limits)
    if context.available_minutes is not None and context.available_minutes <= (hard_minutes if hard_minutes is not None else context.available_minutes):
        limiting_id = None
    return AvailabilityDecision(AvailabilityKind.FINITE, finite, limiting_id)

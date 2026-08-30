from datetime import UTC, date, datetime, timedelta

import pytest

from personal_os.eligibility import calculate_availability, evaluate_task
from personal_os.models import (
    CommitmentHardness, FixedCommitment, Project, ProjectStatus, Task,
    TaskImportance, TaskScheduleMode, TaskStatus,
)
from personal_os.recommendation_types import (
    AvailabilityKind, DeadlineState, EligibilityReason, RecommendationContext,
    ScheduleState,
)

NOW = datetime(2026, 9, 2, 16, tzinfo=UTC)
CREATED = datetime(2026, 1, 1, tzinfo=UTC)


def project(*, status=ProjectStatus.ACTIVE) -> Project:
    return Project(1, "Project", None, status, CREATED, CREATED)


def task(**changes) -> Task:
    values = dict(
        id=1, title="Task", project_id=None, status=TaskStatus.OPEN,
        importance=TaskImportance.UNSPECIFIED,
        schedule_mode=TaskScheduleMode.FLEXIBLE, day_date=None,
        window_start=None, window_end=None, deadline_date=None,
        deadline_at=None, estimated_minutes=None, created_at=CREATED,
        updated_at=CREATED,
    )
    values.update(changes)
    return Task(**values)


def commitment(identifier, start, end, hardness) -> FixedCommitment:
    return FixedCommitment(identifier, "Meeting", start, end, hardness, CREATED, CREATED)


@pytest.mark.parametrize(
    ("status", "eligible", "reason"),
    [
        (TaskStatus.OPEN, True, EligibilityReason.ELIGIBLE),
        (TaskStatus.BLOCKED, False, EligibilityReason.STATUS_BLOCKED),
        (TaskStatus.COMPLETED, False, EligibilityReason.STATUS_COMPLETED),
    ],
)
def test_status_eligibility(status, eligible, reason) -> None:
    result = evaluate_task(task(status=status), projects={}, now=NOW, local_date=NOW.date())
    assert result.eligible is eligible
    assert reason in result.reasons


def test_project_status_and_standalone_eligibility() -> None:
    assert evaluate_task(task(), projects={}, now=NOW, local_date=NOW.date()).eligible
    assert evaluate_task(task(project_id=1), projects={1: project()}, now=NOW, local_date=NOW.date()).eligible
    result = evaluate_task(task(project_id=1), projects={1: project(status=ProjectStatus.COMPLETED)}, now=NOW, local_date=NOW.date())
    assert not result.eligible
    assert EligibilityReason.PROJECT_COMPLETED in result.reasons


@pytest.mark.parametrize(
    ("day", "eligible", "state", "late"),
    [
        (date(2026, 9, 3), False, ScheduleState.DAY_FUTURE, None),
        (date(2026, 9, 2), True, ScheduleState.DAY_TODAY, None),
        (date(2026, 8, 30), True, ScheduleState.DAY_MISSED, 3),
    ],
)
def test_day_schedule(day, eligible, state, late) -> None:
    result = evaluate_task(task(schedule_mode=TaskScheduleMode.DAY, day_date=day), projects={}, now=NOW, local_date=NOW.date())
    assert (result.eligible, result.schedule_state, result.days_late) == (eligible, state, late)


@pytest.mark.parametrize(
    ("now", "eligible", "state"),
    [
        (NOW - timedelta(seconds=1), False, ScheduleState.WINDOW_FUTURE),
        (NOW, True, ScheduleState.WINDOW_ACTIVE),
        (NOW + timedelta(minutes=30), True, ScheduleState.WINDOW_ACTIVE),
        (NOW + timedelta(hours=1), False, ScheduleState.WINDOW_EXPIRED),
        (NOW + timedelta(hours=2), False, ScheduleState.WINDOW_EXPIRED),
    ],
)
def test_window_half_open_boundaries(now, eligible, state) -> None:
    item = task(schedule_mode=TaskScheduleMode.WINDOW, window_start=NOW, window_end=NOW + timedelta(hours=1))
    result = evaluate_task(item, projects={}, now=now, local_date=now.date())
    assert (result.eligible, result.schedule_state) == (eligible, state)


def test_deadlines_are_metadata_and_use_local_calendar_date() -> None:
    local_date = date(2026, 9, 2)
    for deadline, expected in [
        (date(2026, 9, 3), DeadlineState.FUTURE),
        (local_date, DeadlineState.DUE_TODAY),
        (date(2026, 9, 1), DeadlineState.OVERDUE),
    ]:
        result = evaluate_task(task(deadline_date=deadline), projects={}, now=NOW, local_date=local_date)
        assert result.eligible and result.deadline_state is expected
    assert evaluate_task(task(deadline_at=NOW + timedelta(seconds=1)), projects={}, now=NOW, local_date=local_date).deadline_state is DeadlineState.FUTURE
    assert evaluate_task(task(deadline_at=NOW), projects={}, now=NOW, local_date=local_date).deadline_state is DeadlineState.OVERDUE


def test_context_validation_and_timezone_normalization() -> None:
    context = RecommendationContext(datetime(2026, 9, 2, 12, tzinfo=UTC), "America/New_York", 0)
    assert context.reference_time == NOW - timedelta(hours=4)
    with pytest.raises(Exception, match="IANA"):
        RecommendationContext(NOW, "Not/A_Zone")
    for value in (-1, True, 1.5):
        with pytest.raises(Exception, match="nonnegative"):
            RecommendationContext(NOW, "UTC", value)  # type: ignore[arg-type]


def test_availability_hard_only_and_earliest_bound() -> None:
    context = RecommendationContext(NOW, "UTC")
    items = [
        commitment(1, NOW - timedelta(hours=2), NOW - timedelta(hours=1), CommitmentHardness.HARD),
        commitment(2, NOW + timedelta(minutes=40), NOW + timedelta(hours=1), CommitmentHardness.HARD),
        commitment(3, NOW + timedelta(minutes=20), None, CommitmentHardness.HARD),
        commitment(4, NOW + timedelta(minutes=2), None, CommitmentHardness.SOFT),
        commitment(5, NOW + timedelta(minutes=1), None, CommitmentHardness.UNKNOWN),
    ]
    result = calculate_availability(context, items)
    assert result.kind is AvailabilityKind.FINITE
    assert result.available_minutes == 20
    assert result.limiting_commitment_id == 3
    assert calculate_availability(context, items[:1]).kind is AvailabilityKind.NO_KNOWN_HARD_BOUND
    assert calculate_availability(context, items[3:]).kind is AvailabilityKind.NO_KNOWN_HARD_BOUND
    assert calculate_availability(RecommendationContext(NOW, "UTC", 10), items).available_minutes == 10
    assert calculate_availability(RecommendationContext(NOW, "UTC", 0), []).available_minutes == 0


@pytest.mark.parametrize("end, kind", [(NOW + timedelta(minutes=1), AvailabilityKind.BLOCKED_ACTIVE_HARD), (None, AvailabilityKind.BLOCKED_ACTIVE_OPEN_ENDED_HARD)])
def test_active_hard_blocks_including_exact_start(end, kind) -> None:
    result = calculate_availability(RecommendationContext(NOW, "UTC"), [commitment(1, NOW, end, CommitmentHardness.HARD)])
    assert result.kind is kind and result.available_minutes == 0


def test_exact_end_is_ended_and_overlapping_active_hard_blocks() -> None:
    ended = commitment(1, NOW - timedelta(hours=1), NOW, CommitmentHardness.HARD)
    active = commitment(2, NOW - timedelta(minutes=1), NOW + timedelta(minutes=1), CommitmentHardness.HARD)
    assert calculate_availability(RecommendationContext(NOW, "UTC"), [ended]).kind is AvailabilityKind.NO_KNOWN_HARD_BOUND
    assert calculate_availability(RecommendationContext(NOW, "UTC"), [ended, active]).kind is AvailabilityKind.BLOCKED_ACTIVE_HARD

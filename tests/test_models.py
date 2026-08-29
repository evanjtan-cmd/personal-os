from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from personal_os.errors import DomainValidationError
from personal_os.models import (
    TaskImportance,
    TaskScheduleMode,
    TaskStatus,
    canonicalize_parameters,
    normalize_instant,
    parse_instant,
    serialize_instant,
    validate_task_fields,
)


BASE_TASK = {
    "title": "Write draft",
    "project_id": None,
    "status": TaskStatus.OPEN,
    "importance": TaskImportance.UNSPECIFIED,
    "schedule_mode": TaskScheduleMode.FLEXIBLE,
    "day_date": None,
    "window_start": None,
    "window_end": None,
    "deadline_date": None,
    "deadline_at": None,
    "estimated_minutes": None,
}


def task_values(**changes: object) -> dict[str, object]:
    return validate_task_fields(**(BASE_TASK | changes))


def test_aware_instants_normalize_to_canonical_utc() -> None:
    eastern = timezone(timedelta(hours=-4))
    value = datetime(2026, 9, 1, 9, 30, tzinfo=eastern)

    normalized = normalize_instant(value, "value")
    serialized = serialize_instant(value)

    assert normalized == datetime(2026, 9, 1, 13, 30, tzinfo=UTC)
    assert serialized == "2026-09-01T13:30:00.000000Z"
    assert parse_instant(serialized, "value") == normalized


def test_naive_instant_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match="timezone-aware"):
        normalize_instant(datetime(2026, 9, 1, 9, 30), "value")


@pytest.mark.parametrize("minutes", [0, -1, True, 1.5])
def test_nonpositive_or_noninteger_duration_is_rejected(minutes: object) -> None:
    with pytest.raises(DomainValidationError, match="positive integer"):
        task_values(estimated_minutes=minutes)


def test_day_and_window_schedule_invariants() -> None:
    assert task_values(
        schedule_mode=TaskScheduleMode.DAY, day_date=date(2026, 9, 1)
    )["day_date"] == date(2026, 9, 1)
    with pytest.raises(DomainValidationError, match="DAY tasks"):
        task_values(schedule_mode=TaskScheduleMode.DAY)
    with pytest.raises(DomainValidationError, match="before"):
        task_values(
            schedule_mode=TaskScheduleMode.WINDOW,
            window_start=datetime(2026, 9, 1, 10, tzinfo=UTC),
            window_end=datetime(2026, 9, 1, 10, tzinfo=UTC),
        )


def test_flexible_rejects_schedule_fields_and_day_rejects_window_fields() -> None:
    with pytest.raises(DomainValidationError, match="FLEXIBLE"):
        task_values(day_date=date(2026, 9, 1))
    with pytest.raises(DomainValidationError, match="DAY tasks"):
        task_values(
            schedule_mode=TaskScheduleMode.DAY,
            day_date=date(2026, 9, 1),
            window_start=datetime(2026, 9, 1, 9, tzinfo=UTC),
        )


def test_window_requires_both_instants_and_rejects_day_date() -> None:
    with pytest.raises(DomainValidationError, match="WINDOW tasks"):
        task_values(
            schedule_mode=TaskScheduleMode.WINDOW,
            window_start=datetime(2026, 9, 1, 9, tzinfo=UTC),
        )
    with pytest.raises(DomainValidationError, match="WINDOW tasks"):
        task_values(
            schedule_mode=TaskScheduleMode.WINDOW,
            day_date=date(2026, 9, 1),
            window_start=datetime(2026, 9, 1, 9, tzinfo=UTC),
            window_end=datetime(2026, 9, 1, 10, tzinfo=UTC),
        )


def test_day_date_must_not_be_a_datetime() -> None:
    with pytest.raises(DomainValidationError, match="calendar date"):
        task_values(
            schedule_mode=TaskScheduleMode.DAY,
            day_date=datetime(2026, 9, 1, tzinfo=UTC),
        )


def test_deadline_forms_are_mutually_exclusive() -> None:
    with pytest.raises(DomainValidationError, match="mutually exclusive"):
        task_values(
            deadline_date=date(2026, 9, 1),
            deadline_at=datetime(2026, 9, 1, 17, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "value",
    [
        [],
        "text",
        None,
        {1: "value"},
        {"nested": {1: "value"}},
        {"x": float("nan")},
        {"x": float("inf")},
        {"x": (1, 2)},
    ],
)
def test_rule_parameters_require_valid_json_object(value: object) -> None:
    with pytest.raises(DomainValidationError):
        canonicalize_parameters(value)


def test_rule_parameters_are_copied_and_canonicalizable() -> None:
    original = {"nested": {"enabled": True}, "values": [1, 2]}
    result = canonicalize_parameters(original)

    assert result == original
    assert result is not original

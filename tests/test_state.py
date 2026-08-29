from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest

from personal_os.database import initialize_database
from personal_os.errors import DomainValidationError, EntityNotFoundError, PersistenceError
from personal_os.models import (
    CommitmentHardness,
    ProjectStatus,
    TaskImportance,
    TaskScheduleMode,
    TaskStatus,
)
from personal_os.state import SQLiteStateStore


def ticking_clock() -> Iterator[datetime]:
    current = datetime(2026, 9, 1, 12, tzinfo=UTC)
    while True:
        yield current
        current += timedelta(seconds=1)


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStateStore:
    path = tmp_path / "state.db"
    initialize_database(path)
    ticks = ticking_clock()
    return SQLiteStateStore(path, clock=lambda: next(ticks))


def test_constructing_store_has_no_filesystem_side_effects(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "state.db"

    state = SQLiteStateStore(path)

    assert state.database_path == path
    assert not path.exists()
    assert not path.parent.exists()


def test_state_operation_does_not_bootstrap_missing_database(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "state.db"
    state = SQLiteStateStore(path)

    with pytest.raises(PersistenceError, match="cannot open initialized"):
        state.list_projects()

    assert not path.exists()
    assert not path.parent.exists()


def test_state_operation_rejects_outdated_database(tmp_path: Path) -> None:
    path = tmp_path / "version1.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 1")

    with pytest.raises(PersistenceError, match="not current"):
        SQLiteStateStore(path).list_projects()

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1


def test_project_create_get_list_update_round_trip(store: SQLiteStateStore) -> None:
    first = store.create_project(" College ", "Applications")
    second = store.create_project("Home")
    updated = store.update_project(
        first.id, name="College applications", description=None,
        status=ProjectStatus.COMPLETED,
    )

    assert first.name == "College"
    assert store.get_project(first.id) == updated
    assert [item.id for item in store.list_projects()] == [first.id, second.id]
    assert updated.description is None
    assert updated.status is ProjectStatus.COMPLETED
    assert updated.updated_at > first.updated_at


@pytest.mark.parametrize("name", ["", "   "])
def test_project_empty_name_is_rejected(store: SQLiteStateStore, name: str) -> None:
    with pytest.raises(DomainValidationError, match="name"):
        store.create_project(name)


def test_project_invalid_status_and_missing_id_are_rejected(store: SQLiteStateStore) -> None:
    with pytest.raises(DomainValidationError, match="status"):
        store.create_project("Project", status="PAUSED")  # type: ignore[arg-type]
    with pytest.raises(EntityNotFoundError):
        store.get_project(999)


def test_standalone_and_project_linked_tasks_round_trip(store: SQLiteStateStore) -> None:
    project = store.create_project("College")
    standalone = store.create_task("Call dentist")
    linked = store.create_task(
        "Draft essay", project_id=project.id, importance=TaskImportance.MUST,
        estimated_minutes=45,
    )
    updated = store.update_task(linked.id, status=TaskStatus.BLOCKED)
    completed = store.update_task(updated.id, status=TaskStatus.COMPLETED)

    assert standalone.project_id is None
    assert standalone.importance is TaskImportance.UNSPECIFIED
    assert linked.importance is TaskImportance.MUST
    assert completed.status is TaskStatus.COMPLETED
    assert completed.updated_at > linked.updated_at
    assert store.list_tasks() == [standalone, completed]


def test_task_nonexistent_project_is_rejected(store: SQLiteStateStore) -> None:
    with pytest.raises(EntityNotFoundError, match="project 999"):
        store.create_task("Impossible", project_id=999)


@pytest.mark.parametrize("importance", list(TaskImportance))
def test_all_importance_values_round_trip(
    store: SQLiteStateStore, importance: TaskImportance
) -> None:
    assert store.create_task("Task", importance=importance).importance is importance


def test_invalid_task_enums_are_rejected(store: SQLiteStateStore) -> None:
    with pytest.raises(DomainValidationError, match="importance"):
        store.create_task("Task", importance="URGENT")  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError, match="status"):
        store.create_task("Task", status="STARTED")  # type: ignore[arg-type]


def test_day_task_and_date_deadline_are_independent(store: SQLiteStateStore) -> None:
    task = store.create_task(
        "Submit essay", schedule_mode=TaskScheduleMode.DAY,
        day_date=date(2026, 9, 1), deadline_date=date(2026, 9, 5),
    )

    assert task.day_date == date(2026, 9, 1)
    assert task.deadline_date == date(2026, 9, 5)
    assert task.deadline_at is None


@pytest.mark.parametrize("mode", list(TaskScheduleMode))
def test_date_deadline_works_with_every_schedule_mode(
    store: SQLiteStateStore, mode: TaskScheduleMode
) -> None:
    schedule = {}
    if mode is TaskScheduleMode.DAY:
        schedule = {"day_date": date(2026, 9, 2)}
    elif mode is TaskScheduleMode.WINDOW:
        schedule = {
            "window_start": datetime(2026, 9, 2, 9, tzinfo=UTC),
            "window_end": datetime(2026, 9, 2, 10, tzinfo=UTC),
        }
    task = store.create_task(
        f"{mode.value} date deadline", schedule_mode=mode,
        deadline_date=date(2026, 9, 3), **schedule,
    )

    assert task.deadline_date == date(2026, 9, 3)
    assert task.deadline_at is None
    assert task.schedule_mode is mode


@pytest.mark.parametrize("mode", list(TaskScheduleMode))
def test_exact_deadline_works_with_every_schedule_mode(
    store: SQLiteStateStore, mode: TaskScheduleMode
) -> None:
    schedule = {}
    if mode is TaskScheduleMode.DAY:
        schedule = {"day_date": date(2026, 9, 2)}
    elif mode is TaskScheduleMode.WINDOW:
        schedule = {
            "window_start": datetime(2026, 9, 2, 9, tzinfo=UTC),
            "window_end": datetime(2026, 9, 2, 10, tzinfo=UTC),
        }
    eastern = timezone(timedelta(hours=-4))
    task = store.create_task(
        f"{mode.value} exact deadline", schedule_mode=mode,
        deadline_at=datetime(2026, 9, 3, 17, tzinfo=eastern), **schedule,
    )

    assert task.deadline_at == datetime(2026, 9, 3, 21, tzinfo=UTC)
    assert task.deadline_date is None
    assert task.schedule_mode is mode


def test_invalid_task_deadlines_are_rejected(store: SQLiteStateStore) -> None:
    with pytest.raises(DomainValidationError, match="mutually exclusive"):
        store.create_task(
            "Task", deadline_date=date(2026, 9, 1),
            deadline_at=datetime(2026, 9, 1, 17, tzinfo=UTC),
        )
    with pytest.raises(DomainValidationError, match="timezone-aware"):
        store.create_task("Task", deadline_at=datetime(2026, 9, 1, 17))


def test_schedule_update_requires_explicit_day_clear(store: SQLiteStateStore) -> None:
    task = store.create_task(
        "Day task", schedule_mode=TaskScheduleMode.DAY, day_date=date(2026, 9, 1)
    )

    with pytest.raises(DomainValidationError, match="FLEXIBLE"):
        store.update_task(task.id, schedule_mode=TaskScheduleMode.FLEXIBLE)

    updated = store.update_task(
        task.id, schedule_mode=TaskScheduleMode.FLEXIBLE, day_date=None
    )
    assert updated.schedule_mode is TaskScheduleMode.FLEXIBLE
    assert updated.day_date is None


def test_schedule_update_requires_explicit_window_clears(store: SQLiteStateStore) -> None:
    task = store.create_task(
        "Window task", schedule_mode=TaskScheduleMode.WINDOW,
        window_start=datetime(2026, 9, 1, 9, tzinfo=UTC),
        window_end=datetime(2026, 9, 1, 10, tzinfo=UTC),
    )

    with pytest.raises(DomainValidationError, match="FLEXIBLE"):
        store.update_task(task.id, schedule_mode=TaskScheduleMode.FLEXIBLE)

    updated = store.update_task(
        task.id, schedule_mode=TaskScheduleMode.FLEXIBLE,
        window_start=None, window_end=None,
    )
    assert updated.window_start is updated.window_end is None


def test_fixed_commitments_round_trip_known_and_unknown_ends(store: SQLiteStateStore) -> None:
    start = datetime(2026, 9, 1, 14, tzinfo=UTC)
    unknown_end = store.create_fixed_commitment("Appointment", start)
    hard = store.create_fixed_commitment(
        "Flight", start, end_at=start + timedelta(hours=2),
        hardness=CommitmentHardness.HARD,
    )
    updated = store.update_fixed_commitment(
        unknown_end.id, hardness=CommitmentHardness.SOFT
    )

    assert unknown_end.end_at is None
    assert unknown_end.hardness is CommitmentHardness.UNKNOWN
    assert hard.end_at == start + timedelta(hours=2)
    assert updated.hardness is CommitmentHardness.SOFT
    assert store.list_fixed_commitments() == [updated, hard]


def test_invalid_commitment_times_and_hardness_are_rejected(store: SQLiteStateStore) -> None:
    aware = datetime(2026, 9, 1, 14, tzinfo=UTC)
    with pytest.raises(DomainValidationError, match="timezone-aware"):
        store.create_fixed_commitment("Appointment", datetime(2026, 9, 1, 14))
    with pytest.raises(DomainValidationError, match="before"):
        store.create_fixed_commitment("Appointment", aware, end_at=aware)
    with pytest.raises(DomainValidationError, match="hardness"):
        store.create_fixed_commitment("Appointment", aware, hardness="MAYBE")  # type: ignore[arg-type]


def test_rule_round_trip_and_update(store: SQLiteStateStore) -> None:
    rule = store.create_rule(
        "work-hours", {"days": ["MON", "TUE"], "range": {"start": 9}},
        enabled=False,
    )
    updated = store.update_rule(rule.id, parameters={"limit": 3}, enabled=True)

    assert rule.enabled is False
    assert updated.parameters == {"limit": 3}
    assert updated.enabled is True
    assert updated.updated_at > rule.updated_at
    assert store.get_rule(rule.id) == updated
    assert store.list_rules() == [updated]


def test_rule_invalid_kind_and_nonobject_parameters_are_rejected(store: SQLiteStateStore) -> None:
    with pytest.raises(DomainValidationError, match="kind"):
        store.create_rule(" ")
    with pytest.raises(DomainValidationError, match="JSON object"):
        store.create_rule("kind", [1, 2])  # type: ignore[arg-type]


def test_malformed_persisted_rule_json_raises_persistence_error(store: SQLiteStateStore) -> None:
    rule = store.create_rule("kind", {"valid": True})
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE rules SET parameters_json = ? WHERE id = ?", ("[]", rule.id)
        )

    with pytest.raises(PersistenceError, match="JSON object"):
        store.get_rule(rule.id)


def test_malformed_persisted_rule_enabled_raises_persistence_error(
    store: SQLiteStateStore,
) -> None:
    disabled = store.create_rule("disabled", enabled=False)
    enabled = store.create_rule("enabled", enabled=True)
    assert store.get_rule(disabled.id).enabled is False
    assert store.get_rule(enabled.id).enabled is True

    with sqlite3.connect(store.database_path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        assert connection.execute("PRAGMA ignore_check_constraints").fetchone()[0] == 1
        connection.execute(
            "UPDATE rules SET enabled = ? WHERE id = ?", (2, enabled.id)
        )

    with pytest.raises(PersistenceError, match="integer 0 or 1"):
        store.get_rule(enabled.id)


def test_inbox_round_trip_update_and_one_way_resolution(store: SQLiteStateStore) -> None:
    item = store.create_inbox_item("  Original raw text  ", "Missing date")
    updated = store.update_inbox_item(item.id, unresolved_reason="Missing exact date")
    resolved = store.resolve_inbox_item(item.id)
    resolved_again = store.resolve_inbox_item(item.id)

    assert item.raw_text == "  Original raw text  "
    assert item.is_resolved is False
    assert updated.raw_text == item.raw_text
    assert resolved.is_resolved is True
    assert resolved.resolved_at == resolved.updated_at
    assert resolved_again.resolved_at == resolved.resolved_at
    assert resolved_again.updated_at == resolved.updated_at
    assert store.get_inbox_item(item.id) == resolved
    assert store.list_inbox_items() == [resolved]


@pytest.mark.parametrize("raw, reason", [("", "reason"), ("text", " ")])
def test_inbox_invalid_required_text_is_rejected(
    store: SQLiteStateStore, raw: str, reason: str
) -> None:
    with pytest.raises(DomainValidationError):
        store.create_inbox_item(raw, reason)


def test_state_store_connections_enforce_foreign_keys(store: SQLiteStateStore) -> None:
    with store._connection() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO tasks (
                    title, project_id, status, importance, schedule_mode,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    "Orphan", 999, "OPEN", "UNSPECIFIED", "FLEXIBLE",
                    "2026-09-01T12:00:00.000000Z",
                    "2026-09-01T12:00:00.000000Z",
                ),
            )


def test_missing_entities_raise_explicit_error(store: SQLiteStateStore) -> None:
    operations = (
        lambda: store.get_task(999),
        lambda: store.get_fixed_commitment(999),
        lambda: store.get_rule(999),
        lambda: store.get_inbox_item(999),
    )
    for operation in operations:
        with pytest.raises(EntityNotFoundError):
            operation()

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import sqlite3
import threading

import pytest

from personal_os.database import TABLE_DDL, initialize_database
from personal_os.errors import PersistenceError
from personal_os.models import (
    CommitmentHardness, ProjectStatus, TaskImportance, TaskScheduleMode,
    TaskStatus,
)
from personal_os.recommendation import RecommendationService, allowed_durations
from personal_os.recommendation_types import (
    AvailabilityKind, DeterministicNoWorkReason, RecommendationChoice,
    RecommendationChoiceKind, RecommendationContext, RecommendationError,
    RecommendationFailureKind, RecommendationResultKind,
)
from personal_os.state import SQLiteStateStore

NOW = datetime(2026, 9, 2, 16, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStateStore:
    path = tmp_path / "state.db"
    initialize_database(path)
    return SQLiteStateStore(path, clock=lambda: NOW)


class Ranker:
    def __init__(self, choice=None, error=None):
        self.choice = choice
        self.error = error
        self.calls = []

    def recommend(self, context, candidates):
        self.calls.append((context, candidates))
        if self.error:
            raise self.error
        return self.choice or RecommendationChoice(
            RecommendationChoiceKind.RECOMMEND, candidates[0].task_id,
            candidates[0].allowed_durations[0], "Do the next concrete step.",
            "Best fit",
        )


@pytest.mark.parametrize(
    ("estimate", "available", "expected"),
    [
        (None, None, (5, 10, 15, 20, 25, 30, 35, 45, 60)),
        (None, 240, (5, 10, 15, 20, 25, 30, 35, 45, 60)),
        (28, None, (5, 10, 15, 20, 25, 28)),
        (35, None, (5, 10, 15, 20, 25, 30, 35)),
        (90, None, (5, 10, 15, 20, 25, 30, 35, 45, 60)),
        (3, None, (3,)), (3, 2, ()), (2, 4, (2,)),
        (None, 4, ()), (None, 0, ()),
    ],
)
def test_duration_policy(estimate, available, expected) -> None:
    assert allowed_durations(estimate, available) == expected


def test_success_returns_ephemeral_recommendation_and_does_not_write(store) -> None:
    project = store.create_project("Launch")
    task = store.create_task("Draft", project_id=project.id, estimated_minutes=28)
    before = _database_dump(store.database_path)
    ranker = Ranker(RecommendationChoice(
        RecommendationChoiceKind.RECOMMEND, task.id, 28,
        "Complete the draft's next section.", "Finish the draft",
    ))
    result = RecommendationService(store, ranker).recommend(RecommendationContext(NOW, "America/New_York", 30))
    assert result.kind is RecommendationResultKind.RECOMMEND
    assert result.task == task and result.project_name == "Launch"
    assert result.duration_minutes == 28
    assert result.action == "Complete the draft's next section."
    assert result.explanation == "Finish the draft"
    assert _database_dump(store.database_path) == before


def test_service_uses_trusted_timezone_for_local_day_boundary(store) -> None:
    # 00:30 UTC is still the prior calendar day in New York.
    reference = datetime(2026, 9, 3, 0, 30, tzinfo=UTC)
    task = store.create_task(
        "Local today", schedule_mode=TaskScheduleMode.DAY,
        day_date=date(2026, 9, 2),
    )
    ranker = Ranker()
    result = RecommendationService(store, ranker).recommend(
        RecommendationContext(reference, "America/New_York")
    )
    assert result.task.id == task.id
    assert ranker.calls[0][1][0].schedule_state.value == "DAY_TODAY"


def test_deterministic_no_work_skips_ranker_and_does_not_write(store) -> None:
    store.create_task("Too long")
    before = _database_dump(store.database_path)
    ranker = Ranker()
    result = RecommendationService(store, ranker).recommend(RecommendationContext(NOW, "UTC", 3))
    assert result.kind is RecommendationResultKind.NO_WORK
    assert result.deterministic_reason is DeterministicNoWorkReason.NO_FEASIBLE_TASKS
    assert not ranker.calls
    assert _database_dump(store.database_path) == before


@pytest.mark.parametrize("end,reason", [(NOW + timedelta(hours=1), DeterministicNoWorkReason.ACTIVE_HARD_COMMITMENT), (None, DeterministicNoWorkReason.ACTIVE_OPEN_ENDED_HARD_COMMITMENT)])
def test_active_hard_commitment_skips_ranker(store, end, reason) -> None:
    store.create_task("Task", estimated_minutes=2)
    store.create_fixed_commitment("Meeting", NOW, end_at=end, hardness=CommitmentHardness.HARD)
    ranker = Ranker()
    result = RecommendationService(store, ranker).recommend(RecommendationContext(NOW, "UTC"))
    assert result.deterministic_reason is reason
    assert not ranker.calls


def test_explicit_short_task_can_be_ranked_and_must_gate(store) -> None:
    store.create_task("Could", importance=TaskImportance.COULD, estimated_minutes=2)
    must = store.create_task("Must", importance=TaskImportance.MUST, estimated_minutes=2)
    ranker = Ranker()
    RecommendationService(store, ranker).recommend(RecommendationContext(NOW, "UTC", 2))
    context, candidates = ranker.calls[0]
    assert context.must_gated is True
    assert [(item.task_id, item.allowed_durations) for item in candidates] == [(must.id, (2,))]


@pytest.mark.parametrize("kind", ["blocked", "future", "duration"])
def test_infeasible_must_does_not_gate_lower_importance(store, kind) -> None:
    kwargs = {"importance": TaskImportance.MUST}
    if kind == "blocked":
        kwargs["status"] = TaskStatus.BLOCKED
    elif kind == "future":
        kwargs.update(schedule_mode=TaskScheduleMode.DAY, day_date=date(2026, 9, 3))
    else:
        kwargs["estimated_minutes"] = 5
    store.create_task("Must", **kwargs)
    lower = store.create_task("Should", importance=TaskImportance.SHOULD, estimated_minutes=2)
    ranker = Ranker()
    RecommendationService(store, ranker).recommend(RecommendationContext(NOW, "UTC", 2))
    context, candidates = ranker.calls[0]
    assert not context.must_gated
    assert [item.task_id for item in candidates] == [lower.id]


def test_multiple_must_tasks_are_ranked_and_no_work_is_invalid(store) -> None:
    first = store.create_task("Must one", importance=TaskImportance.MUST)
    second = store.create_task("Must two", importance=TaskImportance.MUST)
    ranker = Ranker(RecommendationChoice(
        RecommendationChoiceKind.RECOMMEND, second.id, 10,
        "Work on Must two.", "Second",
    ))
    assert RecommendationService(store, ranker).recommend(RecommendationContext(NOW, "UTC")).task.id == second.id
    no_work = Ranker(RecommendationChoice(
        RecommendationChoiceKind.NO_WORK, None, None, None, "Nothing useful",
    ))
    with pytest.raises(RecommendationError) as error:
        RecommendationService(store, no_work).recommend(RecommendationContext(NOW, "UTC"))
    assert error.value.kind is RecommendationFailureKind.INVALID_OUTPUT
    assert [item.task_id for item in ranker.calls[0][1]] == [first.id, second.id]


def test_ai_no_work_without_must_is_valid_and_read_only(store) -> None:
    store.create_task("Could", importance=TaskImportance.COULD)
    before = _database_dump(store.database_path)
    ranker = Ranker(RecommendationChoice(
        RecommendationChoiceKind.NO_WORK, None, None, None, "No useful choice",
    ))
    result = RecommendationService(store, ranker).recommend(RecommendationContext(NOW, "UTC"))
    assert result.kind is RecommendationResultKind.NO_WORK
    assert result.deterministic_reason is None
    assert _database_dump(store.database_path) == before


@pytest.mark.parametrize("choice", [
    RecommendationChoice(RecommendationChoiceKind.RECOMMEND, 999, 5, "Act", "x"),
    RecommendationChoice(RecommendationChoiceKind.RECOMMEND, 1, 7, "Act", "x"),
    RecommendationChoice(RecommendationChoiceKind.NO_WORK, 1, None, None, "x"),
    RecommendationChoice(RecommendationChoiceKind.RECOMMEND, 1, 5, "Act", " "),
    RecommendationChoice(RecommendationChoiceKind.RECOMMEND, 1, 5, None, "x"),
    RecommendationChoice(RecommendationChoiceKind.RECOMMEND, 1, 5, "", "x"),
    RecommendationChoice(RecommendationChoiceKind.RECOMMEND, 1, 5, "   ", "x"),
    RecommendationChoice(RecommendationChoiceKind.RECOMMEND, 1, 5, 123, "x"),
    RecommendationChoice(RecommendationChoiceKind.NO_WORK, None, None, "Act", "x"),
])
def test_invalid_ai_choices_are_rejected_without_writes(store, choice) -> None:
    store.create_task("Task")
    before = _database_dump(store.database_path)
    with pytest.raises(RecommendationError) as error:
        RecommendationService(store, Ranker(choice)).recommend(RecommendationContext(NOW, "UTC"))
    assert error.value.kind is RecommendationFailureKind.INVALID_OUTPUT
    assert _database_dump(store.database_path) == before


@pytest.mark.parametrize("task_id", [True, 1.0, "1", 0, -1])
def test_malformed_task_ids_cannot_alias_integer_candidate(store, task_id) -> None:
    task = store.create_task("Task")
    assert task.id == 1
    before = _database_dump(store.database_path)
    choice = RecommendationChoice(
        RecommendationChoiceKind.RECOMMEND, task_id, 5, "Do it.", "Choose it"
    )
    with pytest.raises(RecommendationError) as error:
        RecommendationService(store, Ranker(choice)).recommend(
            RecommendationContext(NOW, "UTC")
        )
    assert error.value.kind is RecommendationFailureKind.INVALID_OUTPUT
    assert _database_dump(store.database_path) == before


def test_provider_failure_is_classified_but_persistence_and_deterministic_bugs_propagate(store, monkeypatch) -> None:
    store.create_task("Task")
    before = _database_dump(store.database_path)
    with pytest.raises(RecommendationError) as error:
        RecommendationService(store, Ranker(error=RuntimeError("network"))).recommend(RecommendationContext(NOW, "UTC"))
    assert error.value.kind is RecommendationFailureKind.PROVIDER_ERROR
    assert _database_dump(store.database_path) == before
    with pytest.raises(PersistenceError):
        RecommendationService(store, Ranker(error=PersistenceError("db"))).recommend(RecommendationContext(NOW, "UTC"))
    monkeypatch.setattr("personal_os.recommendation.evaluate_task", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("bug")))
    with pytest.raises(RuntimeError, match="bug"):
        RecommendationService(store, Ranker()).recommend(RecommendationContext(NOW, "UTC"))


def test_candidate_filtering_sort_and_bound_happen_before_ai(store) -> None:
    completed_project = store.create_project("Done", status=ProjectStatus.COMPLETED)
    store.create_task("Project task", project_id=completed_project.id)
    store.create_task("Blocked", status=TaskStatus.BLOCKED)
    store.create_task("Future", schedule_mode=TaskScheduleMode.DAY, day_date=date(2026, 9, 3))
    ids = []
    ids.append(store.create_task("Flexible could", importance=TaskImportance.COULD).id)
    ids.append(store.create_task("Due should", importance=TaskImportance.SHOULD, deadline_date=date(2026, 9, 2)).id)
    ids.append(store.create_task("Missed could", importance=TaskImportance.COULD, schedule_mode=TaskScheduleMode.DAY, day_date=date(2026, 9, 1)).id)
    ranker = Ranker()
    RecommendationService(store, ranker, candidate_limit=2).recommend(RecommendationContext(NOW, "UTC"))
    supplied = ranker.calls[0][1]
    assert [item.task_id for item in supplied] == [ids[2], ids[1]]
    assert len(supplied) == 2


def test_bounding_preserves_missed_day_severity_over_task_id(store) -> None:
    less_late_ids = [
        store.create_task(
            f"Two days late {index}", schedule_mode=TaskScheduleMode.DAY,
            day_date=date(2026, 8, 31),
        ).id
        for index in range(3)
    ]
    most_late = store.create_task(
        "Twenty days late", schedule_mode=TaskScheduleMode.DAY,
        day_date=date(2026, 8, 13),
    )
    ranker = Ranker()
    RecommendationService(store, ranker, candidate_limit=3).recommend(
        RecommendationContext(NOW, "UTC")
    )
    supplied_ids = [item.task_id for item in ranker.calls[0][1]]
    assert supplied_ids[0] == most_late.id
    assert less_late_ids[-1] not in supplied_ids


def test_bounding_preserves_comparable_deadline_severity_over_task_id(store) -> None:
    newer_ids = [
        store.create_task(
            f"Recently overdue {index}", deadline_date=date(2026, 9, 1)
        ).id
        for index in range(3)
    ]
    oldest = store.create_task("Oldest deadline", deadline_date=date(2026, 8, 1))
    ranker = Ranker()
    RecommendationService(store, ranker, candidate_limit=3).recommend(
        RecommendationContext(NOW, "UTC")
    )
    supplied_ids = [item.task_id for item in ranker.calls[0][1]]
    assert supplied_ids[0] == oldest.id
    assert newer_ids[-1] not in supplied_ids


def test_snapshot_is_coherent_and_schema_remains_version_four(store) -> None:
    project = store.create_project("P")
    task = store.create_task("T", project_id=project.id)
    commitment = store.create_fixed_commitment("C", NOW + timedelta(hours=1))
    projects, tasks, commitments = store.read_recommendation_snapshot()
    assert (projects, tasks, commitments) == ([project], [task], [commitment])
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    assert tables == set(TABLE_DDL)


def test_snapshot_remains_stable_across_concurrent_commit(
    store, monkeypatch: pytest.MonkeyPatch,
) -> None:
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
    store.create_project("Initial project")
    initial = store.create_task("Initial task")
    first_read = threading.Event()
    continue_read = threading.Event()
    original = store._project_from_row

    def pause_after_snapshot_begins(row):
        decoded = original(row)
        first_read.set()
        assert continue_read.wait(timeout=5), "reader was not released"
        return decoded

    monkeypatch.setattr(store, "_project_from_row", pause_after_snapshot_begins)
    results = []
    failures = []

    def read_snapshot() -> None:
        try:
            results.append(store.read_recommendation_snapshot())
        except Exception as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    reader = threading.Thread(target=read_snapshot)
    reader.start()
    assert first_read.wait(timeout=5), "reader did not establish its snapshot"
    committed_later = SQLiteStateStore(store.database_path).create_task("Later task")
    continue_read.set()
    reader.join(timeout=5)
    assert not reader.is_alive()
    assert not failures
    assert [item.id for item in results[0][1]] == [initial.id]
    assert [item.id for item in store.read_recommendation_snapshot()[1]] == [
        initial.id, committed_later.id,
    ]


def _database_dump(path: Path) -> tuple:
    with sqlite3.connect(path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        rows = []
        for table in sorted(TABLE_DDL):
            rows.append((table, tuple(connection.execute(f'SELECT * FROM "{table}" ORDER BY id'))))
        return version, tuple(rows)

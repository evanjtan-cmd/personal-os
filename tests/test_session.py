from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import sqlite3
import threading

import pytest

from personal_os.capture import CaptureService
from personal_os.capture_types import InterpretationResponse, parse_interpretation
from personal_os.database import TABLE_DDL, initialize_database
from personal_os.errors import DomainValidationError, EntityNotFoundError, PersistenceError
from personal_os.models import (
    CaptureStatus, CommitmentHardness, ProjectStatus, TaskImportance,
    TaskScheduleMode, TaskStatus,
)
from personal_os.recommendation import RecommendationService
from personal_os.recommendation_types import (
    RecommendationChoice, RecommendationChoiceKind, RecommendationContext,
    RecommendationResultKind,
)
from personal_os.session import SessionService
from personal_os.session_types import (
    SessionConflictError, SessionConflictKind, SessionOutcome,
    SessionStartError, SessionStartFailureKind, WorkSession,
)
from personal_os.state import SQLiteStateStore

NOW = datetime(2026, 9, 2, 16, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStateStore:
    path = tmp_path / "state.db"
    initialize_database(path)
    return SQLiteStateStore(path, clock=lambda: NOW)


def context(minutes=None, now=NOW) -> RecommendationContext:
    return RecommendationContext(now, "UTC", minutes)


def start(store, task_id, minutes=5, **kwargs):
    return SessionService(store).start_session(
        task_id=task_id, planned_minutes=minutes, context=context(), **kwargs
    )


def test_work_session_model_derives_exact_duration_and_allows_zero() -> None:
    active = WorkSession(1, 2, 5, NOW, None, None, " reason ", None)
    assert active.is_active and active.actual_duration is None
    closed = WorkSession(1, 2, 5, NOW, NOW, SessionOutcome.PROGRESS, " reason ", " note ")
    assert not closed.is_active
    assert closed.actual_duration == timedelta(0)
    assert closed.start_reason == " reason " and closed.result_note == " note "


@pytest.mark.parametrize("minutes", [True, 1.5, "5", 0, -1])
def test_start_rejects_malformed_planned_minutes(store, minutes) -> None:
    task = store.create_task("Task")
    with pytest.raises(DomainValidationError, match="planned_minutes"):
        SessionService(store).start_session(
            task_id=task.id, planned_minutes=minutes, context=context()
        )
    assert store.list_sessions() == []


@pytest.mark.parametrize("field", ["start_reason", "result_note"])
def test_optional_session_text_rejects_nontext_and_whitespace(store, field) -> None:
    task = store.create_task("Task")
    service = SessionService(store)
    if field == "start_reason":
        for value in (1, "   "):
            with pytest.raises(DomainValidationError):
                service.start_session(task_id=task.id, planned_minutes=5, context=context(), start_reason=value)
    else:
        session = start(store, task.id)
        for value in (1, "   "):
            with pytest.raises(DomainValidationError):
                service.close_session(session_id=session.id, outcome=SessionOutcome.PROGRESS, ended_at=NOW, result_note=value)


def test_valid_start_round_trip_and_single_active_session(store) -> None:
    task = store.create_task("Task", estimated_minutes=25)
    session = SessionService(store).start_session(
        task_id=task.id, planned_minutes=25, context=context(),
        start_reason=" Recommended because it matters. ",
    )
    assert session.started_at == NOW and session.planned_minutes == 25
    assert session.start_reason == " Recommended because it matters. "
    assert session.is_active and store.get_active_session() == session
    assert store.get_task(task.id).status is TaskStatus.OPEN
    assert store.get_session(session.id) == session
    assert store.list_sessions() == [session]


@pytest.mark.parametrize("status", [TaskStatus.BLOCKED, TaskStatus.COMPLETED])
def test_start_rejects_nonopen_task(store, status) -> None:
    task = store.create_task("Task", status=status)
    with pytest.raises(SessionStartError) as error:
        start(store, task.id)
    assert error.value.kind is SessionStartFailureKind.TASK_NOT_OPEN


def test_start_rejects_completed_project(store) -> None:
    project = store.create_project("Done", status=ProjectStatus.COMPLETED)
    task = store.create_task("Task", project_id=project.id)
    with pytest.raises(SessionStartError) as error:
        start(store, task.id)
    assert error.value.kind is SessionStartFailureKind.PROJECT_COMPLETED


@pytest.mark.parametrize("mode,fields", [
    (TaskScheduleMode.DAY, {"day_date": date(2026, 9, 3)}),
    (TaskScheduleMode.WINDOW, {"window_start": NOW + timedelta(minutes=1), "window_end": NOW + timedelta(hours=1)}),
    (TaskScheduleMode.WINDOW, {"window_start": NOW - timedelta(hours=1), "window_end": NOW}),
])
def test_start_rejects_schedule_ineligible_task(store, mode, fields) -> None:
    task = store.create_task("Task", schedule_mode=mode, **fields)
    with pytest.raises(SessionStartError) as error:
        start(store, task.id)
    assert error.value.kind is SessionStartFailureKind.SCHEDULE_INELIGIBLE


@pytest.mark.parametrize("mode,fields", [
    (TaskScheduleMode.DAY, {"day_date": date(2026, 9, 2)}),
    (TaskScheduleMode.DAY, {"day_date": date(2026, 9, 1)}),
    (TaskScheduleMode.WINDOW, {"window_start": NOW, "window_end": NOW + timedelta(hours=1)}),
])
def test_start_accepts_today_missed_and_active_window(store, mode, fields) -> None:
    task = store.create_task("Task", schedule_mode=mode, **fields)
    assert start(store, task.id).task_id == task.id


@pytest.mark.parametrize("end", [NOW + timedelta(hours=1), None])
def test_active_hard_commitment_blocks_start(store, end) -> None:
    task = store.create_task("Task")
    store.create_fixed_commitment("Hard", NOW, end_at=end, hardness=CommitmentHardness.HARD)
    with pytest.raises(SessionStartError) as error:
        start(store, task.id)
    assert error.value.kind is SessionStartFailureKind.HARD_COMMITMENT_ACTIVE


def test_soft_unknown_and_ended_hard_do_not_block(store) -> None:
    task = store.create_task("Task")
    store.create_fixed_commitment("Soft", NOW, hardness=CommitmentHardness.SOFT)
    store.create_fixed_commitment("Unknown", NOW, hardness=CommitmentHardness.UNKNOWN)
    store.create_fixed_commitment("Ended", NOW - timedelta(hours=1), end_at=NOW, hardness=CommitmentHardness.HARD)
    assert start(store, task.id).task_id == task.id


def test_current_duration_is_exact_and_not_clamped(store) -> None:
    task = store.create_task("Task", estimated_minutes=25)
    store.create_fixed_commitment("Soon", NOW + timedelta(minutes=10), hardness=CommitmentHardness.HARD)
    service = SessionService(store)
    with pytest.raises(SessionStartError) as error:
        service.start_session(task_id=task.id, planned_minutes=25, context=context())
    assert error.value.kind is SessionStartFailureKind.DURATION_NOT_ALLOWED
    assert service.start_session(task_id=task.id, planned_minutes=10, context=context()).planned_minutes == 10


def test_short_task_exception_and_nonladder_rejection(store) -> None:
    short = store.create_task("Short", estimated_minutes=2)
    assert SessionService(store).start_session(task_id=short.id, planned_minutes=2, context=context(2)).planned_minutes == 2
    SessionService(store).close_session(session_id=1, outcome=SessionOutcome.PROGRESS, ended_at=NOW)
    normal = store.create_task("Normal")
    with pytest.raises(SessionStartError) as error:
        SessionService(store).start_session(task_id=normal.id, planned_minutes=7, context=context())
    assert error.value.kind is SessionStartFailureKind.DURATION_NOT_ALLOWED


def test_feasible_must_gates_without_candidate_bound(store) -> None:
    lower = store.create_task("Lower", importance=TaskImportance.SHOULD)
    for index in range(51):
        store.create_task(f"Must {index}", importance=TaskImportance.MUST)
    with pytest.raises(SessionStartError) as error:
        start(store, lower.id)
    assert error.value.kind is SessionStartFailureKind.FEASIBLE_MUST_REQUIRED


@pytest.mark.parametrize("must_kind", ["blocked", "future", "duration"])
def test_infeasible_must_does_not_gate_start(store, must_kind) -> None:
    kwargs = {"importance": TaskImportance.MUST}
    if must_kind == "blocked": kwargs["status"] = TaskStatus.BLOCKED
    elif must_kind == "future": kwargs.update(schedule_mode=TaskScheduleMode.DAY, day_date=date(2026, 9, 3))
    else: kwargs["estimated_minutes"] = 5
    store.create_task("Must", **kwargs)
    lower = store.create_task("Lower", estimated_minutes=2)
    assert SessionService(store).start_session(task_id=lower.id, planned_minutes=2, context=context(2)).task_id == lower.id


def test_start_rejection_precedence(store) -> None:
    open_task = store.create_task("Open")
    blocked = store.create_task("Blocked", status=TaskStatus.BLOCKED)
    active = start(store, open_task.id)
    with pytest.raises(EntityNotFoundError):
        start(store, 999)
    with pytest.raises(SessionConflictError) as conflict:
        start(store, blocked.id)
    assert conflict.value.kind is SessionConflictKind.ACTIVE_SESSION_EXISTS
    SessionService(store).close_session(session_id=active.id, outcome=SessionOutcome.PROGRESS, ended_at=NOW)

    future = store.create_task("Future", schedule_mode=TaskScheduleMode.DAY, day_date=date(2026, 9, 3))
    store.create_fixed_commitment("Hard", NOW, hardness=CommitmentHardness.HARD)
    with pytest.raises(SessionStartError) as schedule:
        start(store, future.id)
    assert schedule.value.kind is SessionStartFailureKind.SCHEDULE_INELIGIBLE


def test_duration_rejection_precedes_feasible_must(store) -> None:
    lower = store.create_task("Lower", importance=TaskImportance.SHOULD)
    store.create_task("Must", importance=TaskImportance.MUST)
    with pytest.raises(SessionStartError) as error:
        SessionService(store).start_session(task_id=lower.id, planned_minutes=7, context=context())
    assert error.value.kind is SessionStartFailureKind.DURATION_NOT_ALLOWED


def test_concurrent_starts_leave_exactly_one_active_session(store) -> None:
    first = store.create_task("First")
    second = store.create_task("Second")
    barrier = threading.Barrier(2)
    successes, failures = [], []

    def run(task_id):
        local = SessionService(SQLiteStateStore(store.database_path, clock=lambda: NOW))
        barrier.wait()
        try:
            successes.append(local.start_session(task_id=task_id, planned_minutes=5, context=context()))
        except Exception as exc:
            failures.append(exc)

    threads = [threading.Thread(target=run, args=(item.id,)) for item in (first, second)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert len(successes) == len(failures) == 1
    assert isinstance(failures[0], SessionConflictError)
    assert failures[0].kind is SessionConflictKind.ACTIVE_SESSION_EXISTS
    assert len([item for item in store.list_sessions() if item.is_active]) == 1


@pytest.mark.parametrize("outcome,target", [
    (SessionOutcome.FINISHED, TaskStatus.COMPLETED),
    (SessionOutcome.PROGRESS, TaskStatus.OPEN),
    (SessionOutcome.BLOCKED, TaskStatus.BLOCKED),
])
def test_close_outcomes_are_atomic_and_preserve_other_task_fields(store, outcome, target) -> None:
    project = store.create_project("Project")
    task = store.create_task("Task", project_id=project.id, importance=TaskImportance.SHOULD, estimated_minutes=25)
    before_updated = task.updated_at
    session = start(store, task.id, 25)
    closed = SessionService(store).close_session(
        session_id=session.id, outcome=outcome,
        ended_at=NOW + timedelta(minutes=12, seconds=3), result_note=" result ",
    )
    current = store.get_task(task.id)
    assert closed.outcome is outcome and closed.result_note == " result "
    assert closed.actual_duration == timedelta(minutes=12, seconds=3)
    assert current.status is target
    assert (current.title, current.importance, current.estimated_minutes, current.project_id) == (task.title, task.importance, task.estimated_minutes, task.project_id)
    if outcome is SessionOutcome.PROGRESS:
        assert current.updated_at == before_updated
    assert store.get_project(project.id).status is ProjectStatus.ACTIVE
    assert store.get_active_session() is None


def test_matching_task_state_closes_but_conflicting_state_does_not(store) -> None:
    task = store.create_task("Task")
    session = start(store, task.id)
    store.update_task(task.id, status=TaskStatus.COMPLETED)
    assert SessionService(store).close_session(session_id=session.id, outcome=SessionOutcome.FINISHED, ended_at=NOW).outcome is SessionOutcome.FINISHED
    task2 = store.create_task("Task 2")
    session2 = start(store, task2.id)
    store.update_task(task2.id, status=TaskStatus.BLOCKED)
    with pytest.raises(SessionConflictError) as error:
        SessionService(store).close_session(session_id=session2.id, outcome=SessionOutcome.FINISHED, ended_at=NOW)
    assert error.value.kind is SessionConflictKind.TASK_STATE_CONFLICT
    assert store.get_session(session2.id).is_active


def test_close_validation_and_second_close_leave_history_immutable(store) -> None:
    task = store.create_task("Task")
    session = start(store, task.id)
    service = SessionService(store)
    with pytest.raises(DomainValidationError):
        service.close_session(session_id=session.id, outcome=SessionOutcome.PROGRESS, ended_at=NOW - timedelta(seconds=1))
    assert store.get_session(session.id).is_active
    closed = service.close_session(session_id=session.id, outcome=SessionOutcome.PROGRESS, ended_at=NOW)
    with pytest.raises(SessionConflictError) as error:
        service.close_session(session_id=session.id, outcome=SessionOutcome.BLOCKED, ended_at=NOW)
    assert error.value.kind is SessionConflictKind.SESSION_ALREADY_CLOSED
    assert store.get_session(session.id) == closed
    with pytest.raises(EntityNotFoundError):
        service.close_session(session_id=999, outcome=SessionOutcome.PROGRESS, ended_at=NOW)


@pytest.mark.parametrize("outcome", [SessionOutcome.FINISHED, SessionOutcome.BLOCKED])
def test_injected_close_failure_rolls_back_task_and_session(store, monkeypatch, outcome) -> None:
    task = store.create_task("Task")
    session = start(store, task.id)
    original = store._close_session_row

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("after close write")

    monkeypatch.setattr(store, "_close_session_row", fail)
    with pytest.raises(RuntimeError, match="after close write"):
        SessionService(store).close_session(session_id=session.id, outcome=outcome, ended_at=NOW)
    assert store.get_task(task.id).status is TaskStatus.OPEN
    assert store.get_session(session.id).is_active


def test_direct_database_session_integrity(store) -> None:
    task = store.create_task("Task")
    stamp = "2026-09-02T16:00:00.000000Z"
    active = (task.id, 5, stamp, None, None, None, None, 1)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        sql = "INSERT INTO sessions (task_id,planned_minutes,started_at,ended_at,outcome,start_reason,result_note,active_slot) VALUES (?,?,?,?,?,?,?,?)"
        for bad in [(999, 5, stamp, None, None, None, None, 1), (task.id, 0, stamp, None, None, None, None, 1), (task.id, -1, stamp, None, None, None, None, 1), (task.id, 2.5, stamp, None, None, None, None, 1)]:
            with pytest.raises(sqlite3.IntegrityError): connection.execute(sql, bad)
        connection.execute(sql, active)
        for bad in [
            (task.id, 5, stamp, stamp, "BAD", None, None, None),
            (task.id, 5, stamp, stamp, None, None, None, None),
            (task.id, 5, stamp, None, "PROGRESS", None, None, 1),
            (task.id, 5, stamp, stamp, "PROGRESS", None, None, 1),
            (task.id, 5, stamp, "2026-09-02T15:00:00.000000Z", "PROGRESS", None, None, None),
            (task.id, 5, stamp, None, None, None, None, 2),
        ]:
            with pytest.raises(sqlite3.IntegrityError): connection.execute(sql, bad)
        with pytest.raises(sqlite3.IntegrityError): connection.execute(sql, active)
        connection.execute("UPDATE sessions SET ended_at=?,outcome='PROGRESS',active_slot=NULL WHERE id=1", (stamp,))
        connection.execute(sql, active)
        connection.execute("UPDATE sessions SET ended_at=?,outcome='PROGRESS',active_slot=NULL WHERE id=2", (stamp,))
        connection.execute(sql, active)
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 3


def test_malformed_stored_session_fails_typed_read(store) -> None:
    task = store.create_task("Task")
    session = start(store, task.id)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute("UPDATE sessions SET planned_minutes=2.5 WHERE id=?", (session.id,))
    with pytest.raises(PersistenceError, match="stored session is malformed"):
        store.get_session(session.id)


def test_malformed_stored_active_slot_fails_typed_read(store) -> None:
    task = store.create_task("Task")
    session = start(store, task.id)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute(
            "UPDATE sessions SET active_slot=NULL WHERE id=?", (session.id,)
        )
    with pytest.raises(PersistenceError, match="stored session is malformed"):
        store.get_session(session.id)


def test_close_rejects_invalid_outcome_and_naive_end(store) -> None:
    task = store.create_task("Task")
    session = start(store, task.id)
    service = SessionService(store)
    with pytest.raises(DomainValidationError, match="outcome"):
        service.close_session(session_id=session.id, outcome="FINISHED", ended_at=NOW)
    with pytest.raises(DomainValidationError, match="timezone-aware"):
        service.close_session(
            session_id=session.id, outcome=SessionOutcome.PROGRESS,
            ended_at=datetime(2026, 9, 2, 16),
        )
    assert store.get_session(session.id).is_active


class FakeInterpreter:
    def interpret(self, raw_text, *, projects):
        payload = {
            "kind": "APPLY",
            "new_project": {"name": "MVP", "description": None},
            "tasks": [{"title": "Finish loop", "project_id": "NEW", "importance": "MUST", "estimated_minutes": 10, "schedule": None, "deadline": None}],
            "commitments": [], "unresolved_reason": None,
        }
        return InterpretationResponse(parse_interpretation(payload), "fake", "fake", "1")


class FirstRanker:
    def __init__(self): self.calls = 0
    def recommend(self, context, candidates):
        self.calls += 1
        return RecommendationChoice(RecommendationChoiceKind.RECOMMEND, candidates[0].task_id, 10, "Complete the loop")


def test_full_capture_recommend_session_finish_loop(store) -> None:
    captured = CaptureService(store, FakeInterpreter()).capture_text("Finish the loop", reference_time=NOW, timezone_name="UTC")
    assert captured.capture.status is CaptureStatus.APPLIED
    task = store.get_task(captured.task_ids[0])
    ranker = FirstRanker()
    recommendation = RecommendationService(store, ranker).recommend(context())
    session = SessionService(store).start_session(task_id=recommendation.task.id, planned_minutes=recommendation.duration_minutes, context=context(), start_reason=recommendation.explanation)
    assert store.get_task(task.id).status is TaskStatus.OPEN
    closed = SessionService(store).close_session(session_id=session.id, outcome=SessionOutcome.FINISHED, ended_at=NOW + timedelta(minutes=8), result_note="Finished")
    assert closed.actual_duration == timedelta(minutes=8)
    assert store.get_task(task.id).status is TaskStatus.COMPLETED
    assert store.get_project(captured.project_id).status is ProjectStatus.ACTIVE
    assert store.list_sessions() == [closed]
    again = RecommendationService(store, ranker).recommend(context())
    assert again.kind is RecommendationResultKind.NO_WORK
    assert ranker.calls == 1


@pytest.mark.parametrize("outcome,expected,recommendable", [
    (SessionOutcome.PROGRESS, TaskStatus.OPEN, True),
    (SessionOutcome.BLOCKED, TaskStatus.BLOCKED, False),
])
def test_feedback_controls_subsequent_recommendation(store, outcome, expected, recommendable) -> None:
    task = store.create_task("Task")
    session = start(store, task.id)
    SessionService(store).close_session(session_id=session.id, outcome=outcome, ended_at=NOW)
    ranker = FirstRanker()
    result = RecommendationService(store, ranker).recommend(context())
    assert store.get_task(task.id).status is expected
    assert (result.kind is RecommendationResultKind.RECOMMEND) is recommendable

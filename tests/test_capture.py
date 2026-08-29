from datetime import UTC, datetime
from pathlib import Path

import pytest

from personal_os.capture import CaptureResult, CaptureService, InterpretationError, InterpretationResponse
from personal_os.database import initialize_database
from personal_os.errors import DomainValidationError, PersistenceError
from personal_os.models import CaptureFailureKind, CaptureStatus
from personal_os.state import SQLiteStateStore
from personal_os.openai_capture import OpenAIResponsesCaptureInterpreter


REFERENCE = datetime(2026, 8, 28, 16, tzinfo=UTC)


class FakeInterpreter:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.observed_received = False
        self.store = None

    def interpret(self, raw_text, *, projects, reference_time, timezone_name):
        if self.store is not None:
            self.observed_received = self.store.list_captures()[0].status is CaptureStatus.RECEIVED
        if self.error:
            raise self.error
        return InterpretationResponse(self.payload, "fake", "fake-model", "response-1")


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStateStore:
    path = tmp_path / "state.db"
    initialize_database(path)
    return SQLiteStateStore(path, clock=lambda: REFERENCE)


def apply_payload(*, tasks=None, commitments=None, new_project=None):
    return {"kind": "APPLY", "new_project": new_project, "tasks": tasks or [],
            "commitments": commitments or [], "unresolved_reason": None}


def task(title, *, project_id=None, schedule=None, deadline=None, minutes=None):
    return {"title": title, "project_id": project_id, "importance": "UNSPECIFIED",
            "estimated_minutes": minutes, "schedule": schedule, "deadline": deadline}


def date_ir(kind, value=None):
    return {"kind": kind, "value": value}


def instant(day, clock):
    return {"date": day, "clock": clock}


def test_capture_is_durable_before_interpretation(store: SQLiteStateStore) -> None:
    fake = FakeInterpreter(apply_payload(tasks=[task("Buy milk")]))
    fake.store = store
    result = CaptureService(store, fake).capture_text("Buy milk", reference_time=REFERENCE, timezone_name="America/New_York")
    assert fake.observed_received
    assert result.capture.status is CaptureStatus.APPLIED
    assert store.get_task(result.task_ids[0]).source_capture_id == result.capture.id


def test_multi_task_and_new_project_are_atomic_and_traceable(store: SQLiteStateStore) -> None:
    payload = apply_payload(new_project={"name": "College", "description": "Applications"},
        tasks=[task("Draft essay", project_id="NEW"), task("Request transcript", project_id="NEW")])
    result = CaptureService(store, FakeInterpreter(payload)).capture_text("College tasks", reference_time=REFERENCE, timezone_name="America/New_York")
    assert result.project_id is not None
    assert len(result.task_ids) == 2
    assert all(item.source_capture_id == result.capture.id for item in store.list_tasks())
    assert store.get_project(result.project_id).source_capture_id == result.capture.id


def test_bare_hour_becomes_unresolved_inbox_item(store: SQLiteStateStore) -> None:
    payload = apply_payload(commitments=[{"title": "Call Mike", "start": instant(date_ir("TOMORROW"), {"kind": "BARE_HOUR", "hour": 4, "minute": 0}), "end": None, "hardness": "UNKNOWN"}])
    result = CaptureService(store, FakeInterpreter(payload)).capture_text("Call Mike tomorrow at 4", reference_time=REFERENCE, timezone_name="America/New_York")
    assert result.capture.status is CaptureStatus.UNRESOLVED
    assert result.inbox_item_id is not None
    assert store.get_inbox_item(result.inbox_item_id).source_capture_id == result.capture.id
    assert store.list_fixed_commitments() == []


def test_explicit_pm_commitment_resolves_to_utc(store: SQLiteStateStore) -> None:
    payload = apply_payload(commitments=[{"title": "Call Mike", "start": instant(date_ir("TOMORROW"), {"kind": "CLOCK_12", "hour": 4, "minute": 0, "period": "PM"}), "end": None, "hardness": "UNKNOWN"}])
    result = CaptureService(store, FakeInterpreter(payload)).capture_text("Call Mike tomorrow at 4 PM", reference_time=REFERENCE, timezone_name="America/New_York")
    assert result.capture.status is CaptureStatus.APPLIED
    assert store.get_fixed_commitment(result.commitment_ids[0]).start_at == datetime(2026, 8, 29, 20, tzinfo=UTC)


def test_two_dates_create_independently_completable_tasks(store: SQLiteStateStore) -> None:
    payload = apply_payload(tasks=[
        task("Water John's plants", schedule={"kind": "DAY", "value": date_ir("WEEKDAY", 1)}),
        task("Water John's plants", schedule={"kind": "DAY", "value": date_ir("WEEKDAY", 3)}),
    ])
    result = CaptureService(store, FakeInterpreter(payload)).capture_text("Water John's plants Monday and Wednesday", reference_time=REFERENCE, timezone_name="America/New_York")
    assert len(result.task_ids) == 2
    assert [item.day_date.isoformat() for item in store.list_tasks()] == ["2026-08-31", "2026-09-02"]


def test_weekend_is_deterministic_half_open_local_window(store: SQLiteStateStore) -> None:
    payload = apply_payload(tasks=[task("Work on college list", schedule={"kind": "THIS_WEEKEND", "value": None})])
    result = CaptureService(store, FakeInterpreter(payload)).capture_text("college list this weekend", reference_time=REFERENCE, timezone_name="America/New_York")
    captured = store.get_task(result.task_ids[0])
    assert captured.window_start == datetime(2026, 8, 29, 4, tzinfo=UTC)
    assert captured.window_end == datetime(2026, 8, 31, 4, tzinfo=UTC)


@pytest.mark.parametrize(
    ("day", "clock"),
    [
        (date_ir("EXPLICIT_DATE", "2026-03-08"), {"kind": "CLOCK_24", "hour": 2, "minute": 30}),
        (date_ir("EXPLICIT_DATE", "2026-11-01"), {"kind": "CLOCK_24", "hour": 1, "minute": 30}),
    ],
)
def test_dst_nonexistent_and_ambiguous_times_are_unresolved(store: SQLiteStateStore, day, clock) -> None:
    payload = apply_payload(commitments=[{"title": "DST", "start": instant(day, clock), "end": None, "hardness": "UNKNOWN"}])
    result = CaptureService(store, FakeInterpreter(payload)).capture_text("DST time", reference_time=REFERENCE, timezone_name="America/New_York")
    assert result.capture.status is CaptureStatus.UNRESOLVED
    assert store.list_fixed_commitments() == []


def test_past_deadline_is_allowed_but_past_commitment_is_unresolved(store: SQLiteStateStore) -> None:
    deadline = apply_payload(tasks=[task("Late task", deadline={"kind": "DATE", "value": date_ir("EXPLICIT_DATE", "2026-01-01")})])
    applied = CaptureService(store, FakeInterpreter(deadline)).capture_text("late", reference_time=REFERENCE, timezone_name="UTC")
    commitment = apply_payload(commitments=[{"title": "Past", "start": instant(date_ir("TODAY"), {"kind": "CLOCK_24", "hour": 1, "minute": 0}), "end": None, "hardness": "UNKNOWN"}])
    unresolved = CaptureService(store, FakeInterpreter(commitment)).capture_text("past", reference_time=REFERENCE, timezone_name="UTC")
    assert applied.capture.status is CaptureStatus.APPLIED
    assert unresolved.capture.status is CaptureStatus.UNRESOLVED


def test_missing_year_and_recurrence_are_unresolved(store: SQLiteStateStore) -> None:
    missing_year = apply_payload(tasks=[task("Submit", deadline={"kind": "DATE", "value": date_ir("MISSING_YEAR", "September 15")})])
    first = CaptureService(store, FakeInterpreter(missing_year)).capture_text("Submit by September 15", reference_time=REFERENCE, timezone_name="UTC")
    unresolved = {"kind": "UNRESOLVED", "new_project": None, "tasks": [], "commitments": [], "unresolved_reason": "recurrence is unsupported"}
    second = CaptureService(store, FakeInterpreter(unresolved)).capture_text("Every Tuesday", reference_time=REFERENCE, timezone_name="UTC")
    assert first.capture.status is second.capture.status is CaptureStatus.UNRESOLVED


@pytest.mark.parametrize("kind", list(CaptureFailureKind))
def test_classified_interpreter_failures_preserve_raw_without_inbox(store: SQLiteStateStore, kind: CaptureFailureKind) -> None:
    result = CaptureService(store, FakeInterpreter(error=InterpretationError(kind, "failure"))).capture_text("raw input", reference_time=REFERENCE, timezone_name="UTC")
    assert result.capture.status is CaptureStatus.FAILED
    assert result.capture.failure_kind is kind
    assert result.capture.raw_text == "raw input"
    assert store.list_inbox_items() == []


def test_invalid_input_is_rejected_before_persistence(store: SQLiteStateStore) -> None:
    service = CaptureService(store, FakeInterpreter({}))
    with pytest.raises(DomainValidationError): service.capture_text("  ", reference_time=REFERENCE, timezone_name="UTC")
    with pytest.raises(DomainValidationError): service.capture_text("text", reference_time=REFERENCE, timezone_name="Not/AZone")
    assert store.list_captures() == []


def test_duplicate_project_name_is_unresolved_across_completed_projects(store: SQLiteStateStore) -> None:
    store.create_project("College")
    payload = apply_payload(new_project={"name": "college", "description": None}, tasks=[task("Essay", project_id="NEW")])
    result = CaptureService(store, FakeInterpreter(payload)).capture_text("college essay", reference_time=REFERENCE, timezone_name="UTC")
    assert result.capture.status is CaptureStatus.UNRESOLVED
    assert len(store.list_projects()) == 1


def test_missing_model_configuration_fails_only_after_raw_is_persisted(store: SQLiteStateStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PERSONAL_OS_CAPTURE_MODEL", raising=False)
    result = CaptureService(store, OpenAIResponsesCaptureInterpreter()).capture_text("keep me", reference_time=REFERENCE, timezone_name="UTC")
    assert result.capture.status is CaptureStatus.FAILED
    assert result.capture.failure_kind is CaptureFailureKind.CONFIGURATION_ERROR
    assert store.get_capture(result.capture.id).raw_text == "keep me"


def test_invalid_output_rolls_back_all_derived_state(store: SQLiteStateStore) -> None:
    payload = apply_payload(new_project={"name": "New", "description": None}, tasks=[task("Bad", project_id="NEW", minutes=True)])
    result = CaptureService(store, FakeInterpreter(payload)).capture_text("bad", reference_time=REFERENCE, timezone_name="UTC")
    assert result.capture.status is CaptureStatus.FAILED
    assert result.capture.failure_kind is CaptureFailureKind.INVALID_OUTPUT
    assert store.list_projects() == []
    assert store.list_tasks() == []


def test_double_finalization_and_invalid_source_foreign_key_are_rejected(store: SQLiteStateStore) -> None:
    capture = store.create_capture("raw", REFERENCE, "UTC")
    store.mark_capture_failed(capture.id, CaptureFailureKind.PROVIDER_ERROR, "failure")
    with pytest.raises(PersistenceError, match="already been finalized"):
        store.mark_capture_failed(capture.id, CaptureFailureKind.PROVIDER_ERROR, "again")
    with store._connection() as connection, pytest.raises(Exception):
        connection.execute("INSERT INTO projects (name, status, created_at, updated_at, source_capture_id) VALUES ('X','ACTIVE','2026-09-01T00:00:00.000000Z','2026-09-01T00:00:00.000000Z',999)")

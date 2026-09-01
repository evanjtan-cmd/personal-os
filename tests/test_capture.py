from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from personal_os.capture import CaptureService, InterpretationError
from personal_os.capture_types import InterpretationResponse, InterpretationValidationError, parse_interpretation
from personal_os.database import initialize_database
from personal_os.errors import DomainValidationError, PersistenceError
from personal_os.models import (
    CaptureFailureKind,
    CaptureStatus,
    ProjectStatus,
    TaskImportance,
    TaskScheduleMode,
)
from personal_os.state import SQLiteStateStore
from personal_os.openai_capture import OpenAIResponsesCaptureInterpreter


REFERENCE = datetime(2026, 8, 28, 16, tzinfo=UTC)


class FakeInterpreter:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.observed_received = False
        self.store = None
        self.projects = None

    def interpret(self, raw_text, *, projects):
        self.projects = projects
        if self.store is not None:
            self.observed_received = self.store.list_captures()[0].status is CaptureStatus.RECEIVED
        if self.error:
            raise self.error
        try:
            interpretation = parse_interpretation(self.payload)
        except InterpretationValidationError as exc:
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, str(exc)) from exc
        return InterpretationResponse(interpretation, "fake", "fake-model", "response-1")


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


def test_scheduleless_action_applies_as_standalone_flexible_task(
    store: SQLiteStateStore,
) -> None:
    payload = apply_payload(tasks=[task("Study for ACT")])

    result = CaptureService(store, FakeInterpreter(payload)).capture_text(
        "Study for ACT", reference_time=REFERENCE, timezone_name="America/New_York"
    )

    assert result.capture.status is CaptureStatus.APPLIED
    assert len(result.task_ids) == 1
    captured = store.get_task(result.task_ids[0])
    assert captured.title == "Study for ACT"
    assert captured.project_id is None
    assert captured.importance is TaskImportance.UNSPECIFIED
    assert captured.estimated_minutes is None
    assert captured.schedule_mode is TaskScheduleMode.FLEXIBLE
    assert captured.day_date is None
    assert captured.window_start is None
    assert captured.window_end is None
    assert captured.deadline_date is None
    assert captured.deadline_at is None
    assert result.inbox_item_id is None
    assert store.list_inbox_items() == []


def test_groq_adapter_metadata_is_persisted_as_groq(store: SQLiteStateStore) -> None:
    payload = {
        "kind": "UNRESOLVED", "new_project": None, "tasks": [],
        "commitments": [], "unresolved_reason": "uncertain",
    }
    response = SimpleNamespace(
        id="groq-response", model="openai/gpt-oss-20b", status="completed",
        output=[], output_text=json.dumps(payload),
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(create=lambda **_kwargs: response)
    )
    adapter = OpenAIResponsesCaptureInterpreter(
        client=client, model="openai/gpt-oss-20b", provider="groq"
    )

    result = CaptureService(store, adapter).capture_text(
        "uncertain item", reference_time=REFERENCE, timezone_name="UTC"
    )

    persisted = store.get_capture(result.capture.id)
    assert persisted.model_provider == "groq"
    assert persisted.model_name == "openai/gpt-oss-20b"
    assert persisted.model_response_id == "groq-response"


def test_multi_task_and_new_project_are_atomic_and_traceable(store: SQLiteStateStore) -> None:
    payload = apply_payload(new_project={"name": "College", "description": "Applications"},
        tasks=[task("Draft essay", project_id="NEW"), task("Request transcript", project_id="NEW")])
    result = CaptureService(store, FakeInterpreter(payload)).capture_text("College tasks", reference_time=REFERENCE, timezone_name="America/New_York")
    assert result.project_id is not None
    assert len(result.task_ids) == 2
    assert all(item.source_capture_id == result.capture.id for item in store.list_tasks())
    assert store.get_project(result.project_id).source_capture_id == result.capture.id


def test_bare_hour_becomes_unresolved_inbox_item(store: SQLiteStateStore) -> None:
    payload = apply_payload(commitments=[{"title": "Call Mike", "start": instant(date_ir("TOMORROW"), {"kind": "BARE_HOUR", "hour": 4, "minute": 0}), "hardness": "UNKNOWN"}])
    result = CaptureService(store, FakeInterpreter(payload)).capture_text("Call Mike tomorrow at 4", reference_time=REFERENCE, timezone_name="America/New_York")
    assert result.capture.status is CaptureStatus.UNRESOLVED
    assert result.inbox_item_id is not None
    assert store.get_inbox_item(result.inbox_item_id).source_capture_id == result.capture.id
    assert store.list_fixed_commitments() == []


def test_explicit_pm_commitment_resolves_to_utc(store: SQLiteStateStore) -> None:
    payload = apply_payload(commitments=[{"title": "Call Mike", "start": instant(date_ir("TOMORROW"), {"kind": "CLOCK_12", "hour": 4, "minute": 0, "period": "PM"}), "hardness": "UNKNOWN"}])
    result = CaptureService(store, FakeInterpreter(payload)).capture_text("Call Mike tomorrow at 4 PM", reference_time=REFERENCE, timezone_name="America/New_York")
    assert result.capture.status is CaptureStatus.APPLIED
    commitment = store.get_fixed_commitment(result.commitment_ids[0])
    assert commitment.start_at == datetime(2026, 8, 29, 20, tzinfo=UTC)
    assert commitment.end_at is None


def test_two_dates_create_independently_completable_tasks(store: SQLiteStateStore) -> None:
    payload = apply_payload(tasks=[task("Water John's plants", schedule={"kind": "DAY", "dates": [date_ir("WEEKDAY", 1), date_ir("WEEKDAY", 3)]})])
    result = CaptureService(store, FakeInterpreter(payload)).capture_text("Water John's plants Monday and Wednesday", reference_time=REFERENCE, timezone_name="America/New_York")
    assert len(result.task_ids) == 2
    assert [item.day_date.isoformat() for item in store.list_tasks()] == ["2026-08-31", "2026-09-02"]


def test_multi_date_resolution_deduplicates_equal_dates(store: SQLiteStateStore) -> None:
    payload = apply_payload(tasks=[task("Water", schedule={"kind": "DAY", "dates": [date_ir("WEEKDAY", 1), date_ir("EXPLICIT_DATE", "2026-08-31")]})])
    result = CaptureService(store, FakeInterpreter(payload)).capture_text("Water Monday", reference_time=REFERENCE, timezone_name="America/New_York")
    assert len(result.task_ids) == 1


def test_weekend_is_deterministic_half_open_local_window(store: SQLiteStateStore) -> None:
    payload = apply_payload(tasks=[task("Work on college list", schedule={"kind": "THIS_WEEKEND", "dates": []})])
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
    payload = apply_payload(commitments=[{"title": "DST", "start": instant(day, clock), "hardness": "UNKNOWN"}])
    result = CaptureService(store, FakeInterpreter(payload)).capture_text("DST time", reference_time=REFERENCE, timezone_name="America/New_York")
    assert result.capture.status is CaptureStatus.UNRESOLVED
    assert store.list_fixed_commitments() == []


def test_past_deadline_is_allowed_but_past_commitment_is_unresolved(store: SQLiteStateStore) -> None:
    deadline = apply_payload(tasks=[task("Late task", deadline={"kind": "DATE", "value": date_ir("EXPLICIT_DATE", "2026-01-01")})])
    applied = CaptureService(store, FakeInterpreter(deadline)).capture_text("late", reference_time=REFERENCE, timezone_name="UTC")
    commitment = apply_payload(commitments=[{"title": "Past", "start": instant(date_ir("TODAY"), {"kind": "CLOCK_24", "hour": 1, "minute": 0}), "hardness": "UNKNOWN"}])
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


def test_new_project_reference_without_new_project_fails_closed(
    store: SQLiteStateStore,
) -> None:
    payload = apply_payload(tasks=[task("Buy milk", project_id="NEW")])
    result = CaptureService(store, FakeInterpreter(payload)).capture_text(
        "Buy milk", reference_time=REFERENCE, timezone_name="UTC"
    )
    assert result.capture.status is CaptureStatus.FAILED
    assert result.capture.failure_kind is CaptureFailureKind.INVALID_OUTPUT
    assert result.capture.failure_reason == "task references an absent new project"
    assert store.list_tasks() == []


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


def test_candidate_context_is_bounded_active_and_deterministic(store: SQLiteStateStore) -> None:
    first = store.create_project("First")
    completed = store.create_project("Completed")
    latest = store.create_project("Latest")
    store.update_project(completed.id, status=ProjectStatus.COMPLETED)
    fake = FakeInterpreter(apply_payload(tasks=[task("Task")]))
    CaptureService(store, fake, project_candidate_limit=1).capture_text("task", reference_time=REFERENCE, timezone_name="UTC")
    assert fake.projects == [{"id": latest.id, "name": "Latest"}]
    assert first.id != latest.id


def test_unavailable_project_candidate_id_is_invalid_output(store: SQLiteStateStore) -> None:
    project = store.create_project("Hidden")
    payload = apply_payload(tasks=[task("Task", project_id=project.id)])
    result = CaptureService(store, FakeInterpreter(payload), project_candidate_limit=1).capture_text("task", reference_time=REFERENCE, timezone_name="UTC")
    assert result.capture.status is CaptureStatus.APPLIED
    store.update_project(project.id, status=ProjectStatus.COMPLETED)
    second = CaptureService(store, FakeInterpreter(payload)).capture_text("task", reference_time=REFERENCE, timezone_name="UTC")
    assert second.capture.status is CaptureStatus.FAILED
    assert second.capture.failure_kind is CaptureFailureKind.INVALID_OUTPUT


def test_second_multi_date_insert_failure_rolls_back_and_propagates(store: SQLiteStateStore, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = apply_payload(tasks=[task("Water", schedule={"kind": "DAY", "dates": [date_ir("WEEKDAY", 1), date_ir("WEEKDAY", 3)]})])
    original = store._insert_task
    calls = 0
    def failing_insert(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PersistenceError("injected task failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(store, "_insert_task", failing_insert)
    with pytest.raises(PersistenceError, match="injected"):
        CaptureService(store, FakeInterpreter(payload)).capture_text("water", reference_time=REFERENCE, timezone_name="UTC")
    assert calls == 2
    assert store.list_tasks() == []
    assert store.list_captures()[0].status is CaptureStatus.RECEIVED


def test_task_failure_after_new_project_rolls_back_and_propagates(store: SQLiteStateStore, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = apply_payload(new_project={"name": "New", "description": None}, tasks=[task("Task", project_id="NEW")])
    def failing_insert(*args, **kwargs):
        raise PersistenceError("injected task failure")
    monkeypatch.setattr(store, "_insert_task", failing_insert)
    with pytest.raises(PersistenceError, match="injected"):
        CaptureService(store, FakeInterpreter(payload)).capture_text("new task", reference_time=REFERENCE, timezone_name="UTC")
    assert store.list_projects() == []
    assert store.list_tasks() == []
    assert store.list_captures()[0].status is CaptureStatus.RECEIVED


def test_unexpected_deterministic_application_error_propagates_without_provider_classification(
    store: SQLiteStateStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = CaptureService(store, FakeInterpreter(apply_payload(tasks=[task("Task")])))

    def fail_application(*args, **kwargs):
        raise RuntimeError("internal application defect")

    monkeypatch.setattr(service, "_apply", fail_application)
    with pytest.raises(RuntimeError, match="internal application defect"):
        service.capture_text("task", reference_time=REFERENCE, timezone_name="UTC")

    captures = store.list_captures()
    assert len(captures) == 1
    assert captures[0].status is CaptureStatus.RECEIVED
    assert captures[0].failure_kind is None


@pytest.mark.parametrize("importance", ["MUST", "SHOULD", "COULD", "UNSPECIFIED"])
def test_typed_task_importance_round_trips(store: SQLiteStateStore, importance: str) -> None:
    payload = apply_payload(tasks=[{**task("Essay"), "importance": importance}])
    result = CaptureService(store, FakeInterpreter(payload)).capture_text("essay", reference_time=REFERENCE, timezone_name="UTC")
    assert store.get_task(result.task_ids[0]).importance.value == importance


def test_task_schedule_deadline_and_estimate_semantics(store: SQLiteStateStore) -> None:
    cases = [
        ("Finish essay by Friday.", task("Finish essay", deadline={"kind": "DATE", "value": date_ir("WEEKDAY", 5)})),
        ("Finish essay by Friday at 5 PM.", task("Finish essay", deadline={"kind": "INSTANT", "value": instant(date_ir("WEEKDAY", 5), {"kind": "CLOCK_12", "hour": 5, "minute": 0, "period": "PM"})})),
        ("Work on essay Friday.", task("Work on essay", schedule={"kind": "DAY", "dates": [date_ir("WEEKDAY", 5)]})),
        ("Work on essay for 30 minutes.", task("Work on essay", minutes=30)),
        ("Work on essay sometime.", task("Work on essay")),
    ]
    made = []
    for raw, intent in cases:
        result = CaptureService(store, FakeInterpreter(apply_payload(tasks=[intent]))).capture_text(raw, reference_time=REFERENCE, timezone_name="America/New_York")
        made.append(store.get_task(result.task_ids[0]))
    assert made[0].schedule_mode.value == "FLEXIBLE" and made[0].deadline_date is not None
    assert made[1].deadline_at is not None and made[1].deadline_date is None
    assert made[2].schedule_mode.value == "DAY"
    assert made[3].estimated_minutes == 30
    assert made[4].schedule_mode.value == "FLEXIBLE" and made[4].estimated_minutes is None


def test_double_finalization_and_invalid_source_foreign_key_are_rejected(store: SQLiteStateStore) -> None:
    capture = store.create_capture("raw", REFERENCE, "UTC")
    store.mark_capture_failed(capture.id, CaptureFailureKind.PROVIDER_ERROR, "failure")
    with pytest.raises(PersistenceError, match="already been finalized"):
        store.mark_capture_failed(capture.id, CaptureFailureKind.PROVIDER_ERROR, "again")
    with store._connection() as connection, pytest.raises(Exception):
        connection.execute("INSERT INTO projects (name, status, created_at, updated_at, source_capture_id) VALUES ('X','ACTIVE','2026-09-01T00:00:00.000000Z','2026-09-01T00:00:00.000000Z',999)")

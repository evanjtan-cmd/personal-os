import io
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import personal_os.bridge as bridge
from personal_os.config import DEFAULT_DATABASE_FILENAME, TIMEZONE_ENV_VAR
from personal_os.database import initialize_database
from personal_os.models import TaskImportance, TaskStatus
from personal_os.recommendation import RecommendationService
from personal_os.recommendation_types import (
    DeterministicNoWorkReason,
    RecommendationChoice,
    RecommendationChoiceKind,
    RecommendationResultKind,
)
from personal_os.runtime import PersonalOSRuntime
from personal_os.session import SessionService
from personal_os.session_types import (
    SessionConflictError,
    SessionConflictKind,
    SessionOutcome,
    SessionStartError,
    SessionStartFailureKind,
)
from personal_os.state import SQLiteStateStore

NOW = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)


def fake_runtime() -> SimpleNamespace:
    return SimpleNamespace(
        store=Mock(),
        capture_service=Mock(),
        recommendation_service=Mock(),
        session_service=Mock(),
    )


def invoke(
    payload: str | object,
    runtime: object,
    *,
    now: datetime = NOW,
    environ: dict[str, str] | None = None,
) -> tuple[int, dict[str, object], str]:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    output = io.StringIO()
    status = bridge.run(
        io.StringIO(raw),
        output,
        runtime_factory=lambda: runtime,
        clock=lambda: now,
        environ={} if environ is None else environ,
    )
    text = output.getvalue()
    return status, json.loads(text), text


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "stdin"),
        ("   ", "stdin"),
        ("{", "valid JSON"),
        ("{}{}", "valid JSON"),
        ("[]", "JSON object"),
        ('"text"', "JSON object"),
        ("1", "JSON object"),
        ("null", "JSON object"),
    ],
)
def test_invalid_json_inputs_are_structured_exit_two(raw: str, message: str) -> None:
    status, response, text = invoke(raw, fake_runtime())
    assert status == 2
    assert response["version"] == 1
    assert response["ok"] is False
    assert response["error"]["code"] == "INVALID_REQUEST"
    assert message in response["error"]["message"]
    assert text.endswith("\n") and text.count("\n") == 1


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"operation": "active"}, "version"),
        ({"version": True, "operation": "active"}, "version"),
        ({"version": "1", "operation": "active"}, "version"),
        ({"version": 2, "operation": "active"}, "unsupported version"),
        ({"version": 1}, "operation"),
        ({"version": 1, "operation": None}, "operation"),
        ({"version": 1, "operation": "capture"}, "unknown operation"),
    ],
)
def test_invalid_protocol_envelope_is_rejected(
    payload: dict[str, object], message: str
) -> None:
    status, response, _ = invoke(payload, fake_runtime())
    assert status == 2
    assert response["error"]["code"] == "INVALID_REQUEST"
    assert message in response["error"]["message"]


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 1, "operation": "recommend", "extra": 1},
        {
            "version": 1,
            "operation": "start",
            "task_id": 1,
            "planned_minutes": 5,
            "extra": 1,
        },
        {"version": 1, "operation": "feedback", "outcome": "PROGRESS", "extra": 1},
        {"version": 1, "operation": "active", "timezone": "UTC"},
    ],
)
def test_unknown_fields_are_rejected_for_every_operation(
    payload: dict[str, object]
) -> None:
    status, response, _ = invoke(payload, fake_runtime(), environ={TIMEZONE_ENV_VAR: "UTC"})
    assert status == 2
    assert response["error"]["code"] == "INVALID_REQUEST"
    assert "unknown field" in response["error"]["message"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_id", True),
        ("task_id", 0),
        ("task_id", "1"),
        ("planned_minutes", False),
        ("planned_minutes", 0),
        ("planned_minutes", 5.0),
        ("available_minutes", True),
        ("available_minutes", -1),
        ("available_minutes", "5"),
    ],
)
def test_start_integer_fields_are_strict(field: str, value: object) -> None:
    request = {
        "version": 1,
        "operation": "start",
        "task_id": 1,
        "planned_minutes": 5,
        field: value,
    }
    status, response, _ = invoke(request, fake_runtime(), environ={TIMEZONE_ENV_VAR: "UTC"})
    assert status == 2
    assert field in response["error"]["message"]


def test_recommend_bool_available_minutes_is_rejected() -> None:
    status, response, _ = invoke(
        {"version": 1, "operation": "recommend", "available_minutes": True},
        fake_runtime(),
        environ={TIMEZONE_ENV_VAR: "UTC"},
    )
    assert status == 2
    assert "available_minutes" in response["error"]["message"]


@pytest.mark.parametrize("timezone", [None, 4, "Not/A_Zone"])
def test_invalid_timezone_is_request_error(timezone: object) -> None:
    status, response, _ = invoke(
        {"version": 1, "operation": "recommend", "timezone": timezone},
        fake_runtime(),
    )
    assert status == 2
    assert "timezone" in response["error"]["message"].lower()


@pytest.mark.parametrize("outcome", [None, 1, "DONE", "progress"])
def test_invalid_feedback_outcome_is_rejected(outcome: object) -> None:
    status, response, _ = invoke(
        {"version": 1, "operation": "feedback", "outcome": outcome},
        fake_runtime(),
    )
    assert status == 2
    assert "outcome" in response["error"]["message"]


@pytest.mark.parametrize(
    ("operation", "required"),
    [
        ("start", "task_id"),
        ("feedback", "outcome"),
    ],
)
def test_missing_operation_fields_are_rejected(operation: str, required: str) -> None:
    request: dict[str, object] = {"version": 1, "operation": operation}
    if operation == "start":
        request["planned_minutes"] = 5
    status, response, _ = invoke(request, fake_runtime())
    assert status == 2
    assert required in response["error"]["message"]


@pytest.mark.parametrize(
    ("operation", "field", "value"),
    [
        ("start", "selected_action", ""),
        ("start", "selected_action", "   "),
        ("start", "selected_action", 3),
        ("start", "start_reason", ""),
        ("feedback", "result_note", "\t"),
        ("feedback", "result_note", False),
    ],
)
def test_invalid_optional_text_is_rejected(
    operation: str, field: str, value: object
) -> None:
    request: dict[str, object] = {"version": 1, "operation": operation, field: value}
    if operation == "start":
        request.update(task_id=1, planned_minutes=5, timezone="UTC")
    else:
        request["outcome"] = "PROGRESS"
    status, response, _ = invoke(request, fake_runtime())
    assert status == 2
    assert field in response["error"]["message"]


def test_recommend_response_preserves_action_and_has_no_shell_hint() -> None:
    runtime = fake_runtime()
    runtime.recommendation_service.recommend.return_value = SimpleNamespace(
        kind=RecommendationResultKind.RECOMMEND,
        task=SimpleNamespace(id=4, title="Write outline"),
        project_name="Essay",
        duration_minutes=25,
        action="Draft three section headings.",
        explanation="It fits now.",
    )
    request = {
        "version": 1,
        "operation": "recommend",
        "available_minutes": 30,
        "timezone": "America/New_York",
    }
    status, response, text = invoke(request, runtime)
    assert status == 0
    assert response == {
        "version": 1,
        "ok": True,
        "operation": "recommend",
        "result": {
            "kind": "RECOMMEND",
            "task_id": 4,
            "task_title": "Write outline",
            "project_name": "Essay",
            "duration_minutes": 25,
            "action": "Draft three section headings.",
            "explanation": "It fits now.",
        },
    }
    context = runtime.recommendation_service.recommend.call_args.args[0]
    assert context.reference_time == NOW
    assert context.timezone_name == "America/New_York"
    assert context.available_minutes == 30
    assert "Next:" not in text and "personal-os start" not in text


def test_recommend_uses_environment_timezone_fallback() -> None:
    runtime = fake_runtime()
    runtime.recommendation_service.recommend.return_value = SimpleNamespace(
        kind=RecommendationResultKind.NO_WORK,
        explanation="Nothing fits.",
        deterministic_reason=DeterministicNoWorkReason.NO_FEASIBLE_TASKS,
    )
    status, response, _ = invoke(
        {"version": 1, "operation": "recommend"},
        runtime,
        environ={TIMEZONE_ENV_VAR: "Europe/London"},
    )
    assert status == 0
    context = runtime.recommendation_service.recommend.call_args.args[0]
    assert context.timezone_name == "Europe/London"
    assert response["result"] == {
        "kind": "NO_WORK",
        "explanation": "Nothing fits.",
        "reason": "NO_FEASIBLE_TASKS",
    }


def test_missing_timezone_configuration_is_expected_error() -> None:
    status, response, _ = invoke(
        {"version": 1, "operation": "recommend"}, fake_runtime(), environ={}
    )
    assert status == 1
    assert response["error"]["code"] == "CONFIGURATION"
    assert response["error"]["kind"] is None


def test_no_work_without_deterministic_reason_uses_null() -> None:
    runtime = fake_runtime()
    runtime.recommendation_service.recommend.return_value = SimpleNamespace(
        kind=RecommendationResultKind.NO_WORK,
        explanation="Not useful now.",
        deterministic_reason=None,
    )
    status, response, _ = invoke(
        {"version": 1, "operation": "recommend", "timezone": "UTC"}, runtime
    )
    assert status == 0
    assert response["result"]["reason"] is None


def test_reference_time_cannot_be_supplied() -> None:
    status, response, _ = invoke(
        {
            "version": 1,
            "operation": "recommend",
            "timezone": "UTC",
            "reference_time": "2020-01-01T00:00:00Z",
        },
        fake_runtime(),
    )
    assert status == 2
    assert "unknown field: reference_time" in response["error"]["message"]


@pytest.mark.parametrize("selected_action", [None, "  Exact accepted action.  "])
def test_start_delegates_and_preserves_optional_action(selected_action: str | None) -> None:
    runtime = fake_runtime()
    runtime.session_service.start_session.return_value = SimpleNamespace(
        id=9,
        task_id=4,
        planned_minutes=25,
        selected_action=selected_action,
        started_at=NOW,
    )
    runtime.store.get_task.return_value = SimpleNamespace(title="Write outline")
    request = {
        "version": 1,
        "operation": "start",
        "task_id": 4,
        "planned_minutes": 25,
        "available_minutes": 30,
        "timezone": "UTC",
        "selected_action": selected_action,
        "start_reason": "  Ready now.  ",
    }
    status, response, _ = invoke(request, runtime)
    assert status == 0
    call = runtime.session_service.start_session.call_args.kwargs
    assert call["task_id"] == 4
    assert call["planned_minutes"] == 25
    assert call["selected_action"] == selected_action
    assert call["start_reason"] == "  Ready now.  "
    assert call["context"].reference_time == NOW
    assert response["result"]["selected_action"] == selected_action
    runtime.store.get_active_session.assert_not_called()


def test_start_allows_omitted_selected_action() -> None:
    runtime = fake_runtime()
    runtime.session_service.start_session.return_value = SimpleNamespace(
        id=9,
        task_id=4,
        planned_minutes=5,
        selected_action=None,
        started_at=NOW,
    )
    runtime.store.get_task.return_value = SimpleNamespace(title="Manual task")
    status, response, _ = invoke(
        {
            "version": 1,
            "operation": "start",
            "task_id": 4,
            "planned_minutes": 5,
            "timezone": "UTC",
        },
        runtime,
    )
    assert status == 0
    assert runtime.session_service.start_session.call_args.kwargs["selected_action"] is None
    assert response["result"]["selected_action"] is None


def test_start_error_preserves_semantic_kind_and_does_not_precheck() -> None:
    runtime = fake_runtime()
    runtime.session_service.start_session.side_effect = SessionStartError(
        SessionStartFailureKind.DURATION_NOT_ALLOWED,
        "duration is not currently allowed",
    )
    status, response, _ = invoke(
        {
            "version": 1,
            "operation": "start",
            "task_id": 4,
            "planned_minutes": 25,
            "timezone": "UTC",
        },
        runtime,
    )
    assert status == 1
    assert response["error"] == {
        "code": "SESSION_START",
        "message": "duration is not currently allowed",
        "kind": "DURATION_NOT_ALLOWED",
    }
    runtime.store.get_task.assert_not_called()
    runtime.store.get_active_session.assert_not_called()


def test_failed_real_start_leaves_no_session(tmp_path: Path) -> None:
    database_path = tmp_path / DEFAULT_DATABASE_FILENAME
    initialize_database(database_path)
    store = SQLiteStateStore(database_path, clock=lambda: NOW)
    task = store.create_task("Short task", estimated_minutes=5)
    runtime = PersonalOSRuntime(
        store=store,
        capture_service=Mock(),
        recommendation_service=Mock(),
        session_service=SessionService(store),
    )
    status, response, _ = invoke(
        {
            "version": 1,
            "operation": "start",
            "task_id": task.id,
            "planned_minutes": 10,
            "timezone": "UTC",
        },
        runtime,
    )
    assert status == 1
    assert response["error"]["kind"] == "DURATION_NOT_ALLOWED"
    assert store.list_sessions() == []


def test_active_no_session_is_explicit_success() -> None:
    runtime = fake_runtime()
    runtime.store.get_active_session.return_value = None
    status, response, _ = invoke({"version": 1, "operation": "active"}, runtime)
    assert status == 0
    assert response["result"] == {"active": False}


def test_active_session_returns_selected_action() -> None:
    runtime = fake_runtime()
    runtime.store.get_active_session.return_value = SimpleNamespace(
        id=9,
        task_id=4,
        planned_minutes=25,
        selected_action="Draft three headings.",
        started_at=NOW,
    )
    runtime.store.get_task.return_value = SimpleNamespace(title="Write outline")
    status, response, _ = invoke({"version": 1, "operation": "active"}, runtime)
    assert status == 0
    assert response["result"] == {
        "active": True,
        "session_id": 9,
        "task_id": 4,
        "task_title": "Write outline",
        "planned_minutes": 25,
        "selected_action": "Draft three headings.",
        "started_at": "2026-09-01T14:00:00.000000Z",
    }


def test_feedback_without_active_session_is_expected_error() -> None:
    runtime = fake_runtime()
    runtime.store.get_active_session.return_value = None
    status, response, _ = invoke(
        {"version": 1, "operation": "feedback", "outcome": "PROGRESS"}, runtime
    )
    assert status == 1
    assert response["error"]["code"] == "NO_ACTIVE_SESSION"
    assert response["error"]["kind"] is None
    runtime.session_service.close_session.assert_not_called()


def test_feedback_delegates_and_returns_exact_elapsed_and_resulting_status() -> None:
    runtime = fake_runtime()
    runtime.store.get_active_session.return_value = SimpleNamespace(id=9)
    runtime.session_service.close_session.return_value = SimpleNamespace(
        id=9,
        task_id=4,
        outcome=SessionOutcome.PROGRESS,
        selected_action="Draft three headings.",
        result_note="  Two drafted.  ",
        started_at=NOW,
        ended_at=NOW + timedelta(minutes=7, microseconds=12),
        actual_duration=timedelta(minutes=7, microseconds=12),
    )
    runtime.store.get_task.return_value = SimpleNamespace(
        title="Write outline", status=TaskStatus.OPEN
    )
    status, response, _ = invoke(
        {
            "version": 1,
            "operation": "feedback",
            "outcome": "PROGRESS",
            "result_note": "  Two drafted.  ",
        },
        runtime,
        now=NOW + timedelta(minutes=7, microseconds=12),
    )
    assert status == 0
    runtime.session_service.close_session.assert_called_once_with(
        session_id=9,
        outcome=SessionOutcome.PROGRESS,
        ended_at=NOW + timedelta(minutes=7, microseconds=12),
        result_note="  Two drafted.  ",
    )
    assert response["result"]["elapsed_microseconds"] == 420_000_012
    assert response["result"]["task_status"] == "OPEN"
    assert response["result"]["result_note"] == "  Two drafted.  "


def test_feedback_conflict_preserves_kind() -> None:
    runtime = fake_runtime()
    runtime.store.get_active_session.return_value = SimpleNamespace(id=9)
    runtime.session_service.close_session.side_effect = SessionConflictError(
        SessionConflictKind.SESSION_ALREADY_CLOSED, "session already closed"
    )
    status, response, _ = invoke(
        {"version": 1, "operation": "feedback", "outcome": "FINISHED"}, runtime
    )
    assert status == 1
    assert response["error"]["code"] == "SESSION_CONFLICT"
    assert response["error"]["kind"] == "SESSION_ALREADY_CLOSED"


def test_unexpected_programming_error_is_not_converted_to_protocol_error() -> None:
    runtime = fake_runtime()
    runtime.store.get_active_session.side_effect = RuntimeError("bug")
    with pytest.raises(RuntimeError, match="bug"):
        invoke({"version": 1, "operation": "active"}, runtime)


def test_product_request_does_not_initialize_missing_database(tmp_path: Path) -> None:
    path = tmp_path / DEFAULT_DATABASE_FILENAME
    store = SQLiteStateStore(path)
    runtime = SimpleNamespace(store=store)
    status, response, _ = invoke({"version": 1, "operation": "active"}, runtime)
    assert status == 1
    assert response["error"]["code"] == "PERSISTENCE"
    assert not path.exists()


def test_bridge_module_import_is_filesystem_safe(tmp_path: Path) -> None:
    code = "import personal_os.bridge"
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        env={"HOME": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / ".personal-os").exists()


class FirstCandidateRanker:
    def recommend(self, context: object, candidates: tuple[object, ...]) -> RecommendationChoice:
        candidate = candidates[0]
        return RecommendationChoice(
            RecommendationChoiceKind.RECOMMEND,
            candidate.task_id,
            10,
            "Complete the first concrete step.",
            "This feasible MUST task is ready.",
        )


def test_complete_bridge_loop_uses_persistence_without_hidden_bridge_state(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / DEFAULT_DATABASE_FILENAME
    initialize_database(database_path)
    store = SQLiteStateStore(database_path, clock=lambda: NOW)
    task = store.create_task(
        "Complete bridge loop",
        importance=TaskImportance.MUST,
        estimated_minutes=10,
    )
    runtime = PersonalOSRuntime(
        store=store,
        capture_service=Mock(),
        recommendation_service=RecommendationService(store, FirstCandidateRanker()),
        session_service=SessionService(store),
    )
    initial_snapshot = store.read_state_snapshot()

    status, recommended, _ = invoke(
        {
            "version": 1,
            "operation": "recommend",
            "available_minutes": 10,
            "timezone": "UTC",
        },
        runtime,
    )
    assert status == 0
    choice = recommended["result"]
    assert store.read_state_snapshot() == initial_snapshot

    status, started, _ = invoke(
        {
            "version": 1,
            "operation": "start",
            "task_id": choice["task_id"],
            "planned_minutes": choice["duration_minutes"],
            "available_minutes": 10,
            "timezone": "UTC",
            "selected_action": choice["action"],
        },
        runtime,
        now=NOW + timedelta(seconds=1),
    )
    assert status == 0
    session_id = started["result"]["session_id"]
    assert store.get_session(session_id).selected_action == choice["action"]

    status, active, _ = invoke({"version": 1, "operation": "active"}, runtime)
    assert status == 0
    assert active["result"]["active"] is True
    assert active["result"]["selected_action"] == choice["action"]

    status, closed, _ = invoke(
        {
            "version": 1,
            "operation": "feedback",
            "outcome": "PROGRESS",
            "result_note": "Made measurable progress.",
        },
        runtime,
        now=NOW + timedelta(minutes=8, seconds=1),
    )
    assert status == 0
    assert closed["result"]["elapsed_microseconds"] == 480_000_000
    assert closed["result"]["task_status"] == "OPEN"
    assert store.get_task(task.id).status is TaskStatus.OPEN
    assert store.get_session(session_id).selected_action == choice["action"]

    status, inactive, _ = invoke({"version": 1, "operation": "active"}, runtime)
    assert status == 0
    assert inactive["result"] == {"active": False}


@pytest.mark.parametrize(
    ("outcome", "expected_status"),
    [("FINISHED", TaskStatus.COMPLETED), ("BLOCKED", TaskStatus.BLOCKED)],
)
def test_feedback_outcomes_use_real_session_service(
    tmp_path: Path, outcome: str, expected_status: TaskStatus
) -> None:
    database_path = tmp_path / DEFAULT_DATABASE_FILENAME
    initialize_database(database_path)
    store = SQLiteStateStore(database_path, clock=lambda: NOW)
    task = store.create_task("Outcome task", estimated_minutes=5)
    runtime = PersonalOSRuntime(
        store=store,
        capture_service=Mock(),
        recommendation_service=Mock(),
        session_service=SessionService(store),
    )
    SessionService(store).start_session(
        task_id=task.id,
        planned_minutes=5,
        context=bridge.RecommendationContext(NOW, "UTC", 5),
        selected_action="Take the exact action.",
    )
    status, response, _ = invoke(
        {"version": 1, "operation": "feedback", "outcome": outcome},
        runtime,
        now=NOW + timedelta(minutes=3),
    )
    assert status == 0
    assert response["result"]["task_status"] == expected_status.value
    assert response["result"]["selected_action"] == "Take the exact action."
    assert store.get_task(task.id).status is expected_status

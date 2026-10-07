import http.client
import json
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from personal_os.activation import WorkActivationService
from personal_os.capture import CaptureService
from personal_os.capture_types import InterpretationResponse, parse_interpretation
from personal_os.database import initialize_database
from personal_os.http_api import create_server
from personal_os.recommendation import RecommendationService
from personal_os.recommendation_types import (
    RecommendationChoice,
    RecommendationChoiceKind,
    RecommendationContext,
)
from personal_os.session import SessionService
from personal_os.models import TaskExecutionMode, TaskStatus
from personal_os.state import SQLiteStateStore

NOW = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)


class FakeRanker:
    def __init__(self) -> None:
        self.calls = 0

    def recommend(self, context, candidates) -> RecommendationChoice:
        self.calls += 1
        return RecommendationChoice(
            RecommendationChoiceKind.RECOMMEND,
            candidates[0].task_id,
            candidates[0].allowed_durations[0],
            "Do the next step.",
            "This fits now.",
        )


@pytest.fixture
def api(tmp_path: Path):
    path = tmp_path / "http.db"
    initialize_database(path)
    store = SQLiteStateStore(path, clock=lambda: NOW)
    ranker = FakeRanker()
    activation = WorkActivationService(store, RecommendationService(store, ranker))
    runtime_factory = Mock(return_value=SimpleNamespace(
        store=store,
        capture_service=Mock(),
        session_service=SessionService(store),
        activation_service=activation,
    ))
    server = create_server(
        0, runtime_factory=runtime_factory, clock=lambda: NOW, environ={}
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, store, ranker, runtime_factory
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def request(
    api, body: object, *, method: str = "POST",
    path: str = "/v1/activate", content_type: str = "application/json",
    raw: str | None = None, extra_headers: dict[str, str] | None = None,
):
    server = api[0]
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        payload = (
            raw
            if raw is not None
            else json.dumps(body) if method == "POST" else None
        )
        headers = {"Content-Type": content_type} if payload is not None else {}
        headers.update(extra_headers or {})
        connection.request(
            method, path, body=payload,
            headers=headers,
        )
        response = connection.getresponse()
        return (
            response.status,
            json.loads(response.read()),
            response.getheader("Content-Type"),
        )
    finally:
        connection.close()


def test_recommend_uses_application_service_and_machine_shape(api) -> None:
    _, store, ranker, runtime_factory = api
    store.create_task("Write draft", estimated_minutes=25)
    before = store.read_state_snapshot()

    status, body, content_type = request(
        api, {"timezone": "UTC", "time_cap_minutes": 20}
    )

    assert status == 200
    assert content_type == "application/json; charset=utf-8"
    assert body == {
        "version": 1,
        "ok": True,
        "operation": "activate",
        "result": {
            "kind": "RECOMMEND",
            "task_id": 1,
            "task_title": "Write draft",
            "project_name": None,
            "duration_minutes": 5,
            "action": "Do the next step.",
            "explanation": "This fits now.",
        },
    }
    assert ranker.calls == 1
    runtime_factory.assert_called_once_with()
    assert store.read_state_snapshot() == before


def test_active_session_wins_without_timezone_or_ai(api) -> None:
    _, store, ranker, _ = api
    task = store.create_task("Continue draft")
    session = SessionService(store).start_session(
        task_id=task.id,
        planned_minutes=25,
        context=RecommendationContext(NOW, "UTC", 25),
        selected_action="Keep writing.",
    )
    before = store.read_state_snapshot()

    status, body, _ = request(api, {})

    assert status == 200
    assert body["result"] == {
        "kind": "ACTIVE_SESSION",
        "session_id": session.id,
        "task_id": task.id,
        "task_title": task.title,
        "planned_minutes": 25,
        "selected_action": "Keep writing.",
        "started_at": "2026-09-21T14:00:00.000000Z",
    }
    assert ranker.calls == 0
    assert store.read_state_snapshot() == before


def test_no_work_preserves_deterministic_reason_and_skips_ai(api) -> None:
    _, store, ranker, _ = api
    store.create_task("Write draft")

    status, body, _ = request(api, {"timezone": "UTC", "time_cap_minutes": 0})

    assert status == 200
    assert body["result"]["kind"] == "NO_WORK"
    assert body["result"]["reason"] == "NO_FEASIBLE_TASKS"
    assert ranker.calls == 0


@pytest.mark.parametrize(
    "body",
    [
        {"time_cap_minutes": True},
        {"time_cap_minutes": -1},
        {"timezone": "Not/A_Zone"},
        {"reference_time": "2020-01-01T00:00:00Z"},
        {"operation": "recommend"},
        [],
    ],
)
def test_invalid_requests_are_structured_and_skip_runtime(api, body) -> None:
    runtime_factory = api[3]

    status, response, _ = request(api, body)

    assert status == 400
    assert response["version"] == 1
    assert response["ok"] is False
    assert response["error"]["code"] == "INVALID_REQUEST"
    runtime_factory.assert_not_called()


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"version": 1}, "version"),
        ({"operation": "activate"}, "operation"),
        ({"version": 1, "operation": "activate"}, "operation"),
    ],
)
def test_http_body_rejects_transport_owned_fields(api, body, field) -> None:
    status, response, _ = request(api, body)

    assert status == 400
    assert response["version"] == 1
    assert response["operation"] == "activate"
    assert response["ok"] is False
    assert response["error"]["code"] == "INVALID_REQUEST"
    assert response["error"]["message"] == f"unknown field: {field}"
    api[3].assert_not_called()


def test_missing_timezone_is_structured_operational_error(api) -> None:
    status, body, _ = request(api, {})

    assert status == 500
    assert body["error"]["code"] == "CONFIGURATION"


def test_malformed_json_is_structured_and_skips_runtime(api) -> None:
    status, body, _ = request(api, {}, raw="{")

    assert status == 400
    assert body["error"]["code"] == "INVALID_REQUEST"
    api[3].assert_not_called()


def test_route_method_and_media_errors_are_json(api) -> None:
    assert request(api, {}, path="/v1/other")[0:2] == (
        404,
        {
            "version": 1,
            "ok": False,
            "operation": None,
            "error": {
                "code": "NOT_FOUND",
                "message": "unknown endpoint",
                "kind": None,
            },
        },
    )
    assert request(api, {}, method="GET")[0] == 405
    assert request(api, {}, method="PUT")[0] == 405
    assert request(api, {}, content_type="text/plain")[0] == 415


def test_server_binds_only_to_ipv4_loopback(api) -> None:
    assert api[0].server_address[0] == "127.0.0.1"


def test_get_overview_returns_machine_envelope_without_configuration(api) -> None:
    _, store, ranker, runtime_factory = api
    project = store.create_project("College", "Applications")
    task = store.create_task("Draft essay", project_id=project.id)
    store.create_inbox_item("Call Mike at 4", "time is missing AM/PM")

    status, response, content_type = request(
        api, {}, method="GET", path="/v1/overview"
    )

    assert status == 200
    assert content_type == "application/json; charset=utf-8"
    assert response["version"] == 1
    assert response["ok"] is True
    assert response["operation"] == "overview"
    assert response["result"]["projects"] == [{
        "id": project.id,
        "name": "College",
        "description": "Applications",
    }]
    assert response["result"]["tasks"][0]["id"] == task.id
    assert response["result"]["tasks"][0]["execution_mode"] == "SPLITTABLE"
    assert response["result"]["inbox"][0]["raw_text"] == "Call Mike at 4"
    assert response["result"]["active_session"] is None
    assert ranker.calls == 0
    runtime_factory.assert_called_once_with()


def test_task_planning_endpoint_updates_only_planning_fields(api) -> None:
    _, store, _, runtime_factory = api
    task = store.create_task("Take diagnostic PSAT", estimated_minutes=30)

    status, response, _ = request(api, {
        "task_id": task.id,
        "execution_mode": "ONE_SITTING",
        "estimated_minutes": 180,
    }, path="/v1/task-planning")

    assert status == 200
    assert response["operation"] == "update_task_planning"
    assert response["result"] == {
        "task_id": task.id,
        "title": "Take diagnostic PSAT",
        "execution_mode": "ONE_SITTING",
        "estimated_minutes": 180,
    }
    updated = store.get_task(task.id)
    assert updated.title == task.title
    assert updated.execution_mode is TaskExecutionMode.ONE_SITTING
    assert updated.estimated_minutes == 180
    runtime_factory.assert_called_once_with()


def test_task_status_endpoint_updates_allowed_lifecycle(api) -> None:
    _, store, _, runtime_factory = api
    task = store.create_task("Remove this")

    status, response, _ = request(
        api,
        {"task_id": task.id, "status": "CANCELLED"},
        path="/v1/task-status",
    )

    assert status == 200
    assert response["operation"] == "correct_task_status"
    assert response["result"] == {
        "task_id": task.id,
        "title": "Remove this",
        "status": "CANCELLED",
    }
    assert store.get_task(task.id).status is TaskStatus.CANCELLED
    runtime_factory.assert_called_once_with()


def test_overview_enforces_host_and_get_only(api) -> None:
    status, response, _ = request(
        api,
        {},
        method="GET",
        path="/v1/overview",
        extra_headers={"Host": "evil.test"},
    )
    assert status == 400
    assert response["error"]["message"] == "invalid Host header"
    assert api[3].call_count == 0

    status, response, _ = request(api, {}, path="/v1/overview")
    assert status == 405
    assert response["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert api[3].call_count == 0

    status, response, _ = request(
        api, {}, method="GET", path="/v1/overview", raw="{}"
    )
    assert status == 400
    assert "does not accept a request body" in response["error"]["message"]
    assert api[3].call_count == 0


def test_capture_uses_configured_timezone_when_http_omits_it(
    tmp_path: Path,
) -> None:
    class FakeInterpreter:
        def interpret(self, raw_text, *, projects):
            assert raw_text == "Finish biology worksheet tomorrow"
            assert projects == []
            return InterpretationResponse(
                parse_interpretation({
                    "kind": "APPLY",
                    "new_project": None,
                    "tasks": [{
                        "title": "Finish biology worksheet",
                        "project_id": None,
                        "importance": "UNSPECIFIED",
                        "estimated_minutes": None,
                        "execution_mode": "SPLITTABLE",
                        "schedule": {
                            "kind": "DAY",
                            "dates": [{"kind": "TOMORROW", "value": None}],
                        },
                        "deadline": None,
                    }],
                    "commitments": [],
                    "unresolved_reason": None,
                }),
                "fake",
                "fake-model",
                "fake-response",
            )

    path = tmp_path / "capture-http.db"
    initialize_database(path)
    store = SQLiteStateStore(path, clock=lambda: NOW)
    capture_service = CaptureService(store, FakeInterpreter())
    runtime_factory = Mock(return_value=SimpleNamespace(
        store=store,
        capture_service=capture_service,
    ))
    server = create_server(
        0,
        runtime_factory=runtime_factory,
        clock=lambda: NOW,
        environ={"PERSONAL_OS_TIMEZONE": "America/New_York"},
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        capture_api = (server, store, None, runtime_factory)
        status, response, _ = request(
            capture_api,
            {"raw_text": "Finish biology worksheet tomorrow"},
            path="/v1/capture",
        )

        assert status == 200
        assert response["result"] == {
            "capture_id": 1,
            "status": "APPLIED",
            "project": None,
            "tasks": [{
                "id": 1,
                "title": "Finish biology worksheet",
                "execution_mode": "SPLITTABLE",
                "estimated_minutes": None,
                "planning_note": None,
            }],
            "commitments": [],
        }
        capture = store.get_capture(1)
        assert capture.reference_time == NOW
        assert capture.timezone_name == "America/New_York"
        assert store.get_task(1).day_date.isoformat() == "2026-09-22"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_resolve_and_dismiss_inbox_endpoints_use_narrow_operations(
    tmp_path: Path,
) -> None:
    class FakeInterpreter:
        def interpret(self, raw_text, *, projects):
            assert raw_text == "Call Mike tomorrow at 4 PM"
            return InterpretationResponse(
                parse_interpretation({
                    "kind": "APPLY",
                    "new_project": None,
                    "tasks": [{
                        "title": "Call Mike tomorrow at 4 PM",
                        "project_id": None,
                        "importance": "UNSPECIFIED",
                        "estimated_minutes": None,
                        "execution_mode": "SPLITTABLE",
                        "schedule": None,
                        "deadline": None,
                    }],
                    "commitments": [],
                    "unresolved_reason": None,
                }),
                "fake",
                "fake-model",
                "fake-response",
            )

    path = tmp_path / "resolve-http.db"
    initialize_database(path)
    store = SQLiteStateStore(path, clock=lambda: NOW)
    first = store.create_inbox_item("Call Mike tomorrow at 4", "time is missing AM/PM")
    second = store.create_inbox_item("Ignore this", "not actionable")
    runtime_factory = Mock(return_value=SimpleNamespace(
        store=store,
        capture_service=CaptureService(store, FakeInterpreter()),
    ))
    server = create_server(
        0,
        runtime_factory=runtime_factory,
        clock=lambda: NOW,
        environ={"PERSONAL_OS_TIMEZONE": "UTC"},
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        local_api = (server, store, None, runtime_factory)
        status, resolved, _ = request(
            local_api,
            {
                "inbox_item_id": first.id,
                "raw_text": "Call Mike tomorrow at 4 PM",
            },
            path="/v1/resolve-inbox",
        )
        assert status == 200
        assert resolved["operation"] == "resolve_inbox"
        assert resolved["result"]["status"] == "APPLIED"
        assert resolved["result"]["resolved_inbox_item_id"] == first.id
        assert store.get_inbox_item(first.id).is_resolved

        status, dismissed, _ = request(
            local_api,
            {"inbox_item_id": second.id},
            path="/v1/dismiss-inbox",
        )
        assert status == 200
        assert dismissed["operation"] == "dismiss_inbox"
        assert dismissed["result"]["resolved"] is True
        assert store.get_inbox_item(second.id).is_resolved
        assert len(store.list_captures()) == 1
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize(
    ("outcome", "expected_status"),
    [
        ("FINISHED", TaskStatus.COMPLETED),
        ("PROGRESS", TaskStatus.OPEN),
        ("BLOCKED", TaskStatus.BLOCKED),
    ],
)
def test_http_work_loop_preserves_action_and_closes_session(
    api, outcome, expected_status
) -> None:
    _, store, ranker, _ = api
    task = store.create_task("Write draft", estimated_minutes=25)
    status, activation, _ = request(api, {"timezone": "UTC", "time_cap_minutes": 20})
    assert status == 200
    choice = activation["result"]
    assert choice["kind"] == "RECOMMEND"

    status, started, _ = request(api, {
        "task_id": choice["task_id"],
        "planned_minutes": choice["duration_minutes"],
        "selected_action": choice["action"],
        "timezone": "UTC",
        "available_minutes": 20,
    }, path="/v1/start")
    assert status == 200
    session = store.get_active_session()
    assert session is not None
    assert session.planned_minutes == choice["duration_minutes"]
    assert session.selected_action == choice["action"]
    assert started["result"]["selected_action"] == choice["action"]

    status, active, _ = request(api, {})
    assert status == 200
    assert active["result"]["kind"] == "ACTIVE_SESSION"
    assert active["result"]["selected_action"] == choice["action"]
    assert ranker.calls == 1

    status, closed, _ = request(api, {
        "outcome": outcome,
        "result_note": "  Worked on the draft.  ",
    }, path="/v1/feedback")
    assert status == 200
    assert closed["result"]["outcome"] == outcome
    assert closed["result"]["task_status"] == expected_status.value
    assert closed["result"]["selected_action"] == choice["action"]
    assert closed["result"]["result_note"] == "  Worked on the draft.  "
    assert store.get_active_session() is None
    assert store.get_task(task.id).status is expected_status


def test_work_loop_uses_configured_timezone_when_browser_omits_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "configured-timezone.db"
    initialize_database(path)
    store = SQLiteStateStore(path, clock=lambda: NOW)
    ranker = FakeRanker()
    runtime_factory = Mock(return_value=SimpleNamespace(
        store=store,
        session_service=SessionService(store),
        activation_service=WorkActivationService(
            store, RecommendationService(store, ranker)
        ),
    ))
    server = create_server(
        0,
        runtime_factory=runtime_factory,
        clock=lambda: NOW,
        environ={"PERSONAL_OS_TIMEZONE": "UTC"},
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        configured_api = (server, store, ranker, runtime_factory)
        store.create_task("Write draft", estimated_minutes=25)

        status, activation, _ = request(configured_api, {"time_cap_minutes": 20})

        assert status == 200
        choice = activation["result"]
        assert choice["kind"] == "RECOMMEND"

        status, started, _ = request(configured_api, {
            "task_id": choice["task_id"],
            "planned_minutes": choice["duration_minutes"],
            "selected_action": choice["action"],
            "available_minutes": 20,
        }, path="/v1/start")

        assert status == 200
        assert started["result"]["task_id"] == choice["task_id"]
        session = store.get_active_session()
        assert session is not None
        assert session.planned_minutes == choice["duration_minutes"]
        assert session.selected_action == choice["action"]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_start_revalidates_stale_recommendation(api) -> None:
    _, store, _, _ = api
    task = store.create_task("Write draft", estimated_minutes=25)
    _, activation, _ = request(api, {"timezone": "UTC"})
    choice = activation["result"]
    store.update_task(task.id, status=TaskStatus.COMPLETED)

    status, response, _ = request(api, {
        "task_id": choice["task_id"],
        "planned_minutes": choice["duration_minutes"],
        "selected_action": choice["action"],
        "timezone": "UTC",
    }, path="/v1/start")

    assert status == 500
    assert response["error"]["code"] == "SESSION_START"
    assert response["error"]["kind"] == "TASK_NOT_OPEN"
    assert store.list_sessions() == []


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/v1/start", {"task_id": 1, "planned_minutes": True}),
        ("/v1/start", {"task_id": 1}),
        ("/v1/start", {"task_id": 1, "planned_minutes": 5, "version": 1}),
        ("/v1/feedback", {"outcome": "DONE"}),
        ("/v1/feedback", {"outcome": "PROGRESS", "operation": "feedback"}),
        ("/v1/capture", {}),
        ("/v1/capture", {"raw_text": "   "}),
        ("/v1/capture", {"raw_text": 42}),
        ("/v1/capture", {"raw_text": "Study", "current_time": "now"}),
        ("/v1/resolve-inbox", {"inbox_item_id": 1}),
        ("/v1/resolve-inbox", {"inbox_item_id": 1, "raw_text": "Corrected", "current_time": "now"}),
        ("/v1/dismiss-inbox", {"inbox_item_id": 0}),
        ("/v1/dismiss-inbox", {"inbox_item_id": 1, "raw_text": "No"}),
        ("/v1/task-planning", {"task_id": 1, "execution_mode": "SPLITTABLE"}),
        ("/v1/task-planning", {"task_id": 1, "execution_mode": "MAYBE", "estimated_minutes": None}),
        ("/v1/task-planning", {"task_id": 1, "execution_mode": "SPLITTABLE", "estimated_minutes": 0}),
        ("/v1/task-planning", {"task_id": 1, "execution_mode": "SPLITTABLE", "estimated_minutes": None, "title": "Rename"}),
        ("/v1/task-status", {"task_id": 1, "status": "BLOCKED"}),
        ("/v1/task-status", {"task_id": 1}),
        ("/v1/task-status", {"task_id": 1, "status": "COMPLETED", "title": "Rename"}),
    ],
)
def test_new_endpoints_reject_invalid_bodies_before_runtime(api, path, body) -> None:
    status, response, _ = request(api, body, path=path)
    assert status == 400
    assert response["error"]["code"] == "INVALID_REQUEST"
    api[3].assert_not_called()


def test_feedback_without_session_is_structured_error(api) -> None:
    status, response, _ = request(api, {"outcome": "PROGRESS"}, path="/v1/feedback")
    assert status == 500
    assert response["error"]["code"] == "NO_ACTIVE_SESSION"


@pytest.mark.parametrize(
    "path", [
        "/v1/activate", "/v1/start", "/v1/feedback", "/v1/capture",
        "/v1/resolve-inbox", "/v1/dismiss-inbox", "/v1/task-planning",
        "/v1/task-status",
    ]
)
def test_host_and_cross_origin_requests_are_rejected(api, path) -> None:
    body = {
        "/v1/activate": {},
        "/v1/start": {"task_id": 1, "planned_minutes": 5},
        "/v1/feedback": {"outcome": "PROGRESS"},
        "/v1/capture": {"raw_text": "Study for ACT"},
        "/v1/resolve-inbox": {"inbox_item_id": 1, "raw_text": "Study for ACT"},
        "/v1/dismiss-inbox": {"inbox_item_id": 1},
        "/v1/task-planning": {"task_id": 1, "execution_mode": "SPLITTABLE", "estimated_minutes": None},
        "/v1/task-status": {"task_id": 1, "status": "COMPLETED"},
    }[path]
    for header in (
        {"Host": "example.com"},
        {"Origin": "http://example.com"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
    ):
        status, response, headers = request(api, body, path=path, extra_headers=header)
        assert status in (400, 403)
        assert response["ok"] is False
        assert headers == "application/json; charset=utf-8"
    api[3].assert_not_called()


def test_same_origin_request_is_allowed(api) -> None:
    _, store, _, _ = api
    store.create_task("Write draft")
    origin = f"http://127.0.0.1:{api[0].server_port}"
    status, response, _ = request(
        api, {"timezone": "UTC"},
        extra_headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"},
    )
    assert status == 200
    assert response["result"]["kind"] == "RECOMMEND"


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/", "text/html; charset=utf-8"),
        ("/state", "text/html; charset=utf-8"),
        ("/state.js", "text/javascript; charset=utf-8"),
        ("/work.css", "text/css; charset=utf-8"),
        ("/work.js", "text/javascript; charset=utf-8"),
    ],
)
def test_browser_assets_are_served_with_restrictive_headers(api, path, content_type) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", api[0].server_port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        assert response.status == 200
        assert response.getheader("Content-Type") == content_type
        assert response.getheader("X-Content-Type-Options") == "nosniff"
        assert "script-src 'self'" in response.getheader("Content-Security-Policy")
        assert response.getheader("Access-Control-Allow-Origin") is None
        assert body
    finally:
        connection.close()


def test_work_page_assets_do_not_collect_or_send_timezone() -> None:
    static = files("personal_os").joinpath("static")
    html = static.joinpath("work.html").read_text(encoding="utf-8")
    script = static.joinpath("work.js").read_text(encoding="utf-8")

    assert 'id="timezone"' not in html
    assert 'name="timezone"' not in html
    assert "Timezone" not in html
    assert 'byId("timezone")' not in script
    assert "body.timezone" not in script
    assert "time_cap_minutes" in script
    assert "available_minutes" in script
    assert "Finish biology worksheet tomorrow" not in html
    assert "No cap" not in html
    assert "How much time do you have?" in html
    assert "optional" in html
    assert "placeholder=\"Not sure\"" in html
    assert "Leave blank if you're not sure" in html


def test_work_page_assets_include_capture_without_client_time_context() -> None:
    static = files("personal_os").joinpath("static")
    html = static.joinpath("work.html").read_text(encoding="utf-8")
    script = static.joinpath("work.js").read_text(encoding="utf-8")

    assert 'id="capture-form"' in html
    assert 'id="capture-text"' in html
    assert 'id="capture-button"' in html
    assert 'request("/v1/capture", { raw_text: rawText })' in script
    assert 'request("/v1/resolve-inbox"' in script
    assert 'request("/v1/dismiss-inbox"' in script
    assert 'request("/v1/task-planning"' in script
    assert "raw_text" in script
    assert "reference_time" not in script
    assert "current_time" not in script
    assert "body.timezone" not in script
    assert "Capture failed while interpreting this item" in script
    assert "failure_reason" not in script


def test_state_page_assets_use_overview_and_safe_dom_rendering() -> None:
    static = files("personal_os").joinpath("static")
    work_html = static.joinpath("work.html").read_text(encoding="utf-8")
    state_html = static.joinpath("state.html").read_text(encoding="utf-8")
    script = static.joinpath("state.js").read_text(encoding="utf-8")

    assert 'href="/state"' in work_html
    assert 'href="/"' in state_html
    assert 'href="/state" aria-current="page"' in state_html
    assert 'fetch("/v1/overview"' in script
    assert 'byId("refresh-button").addEventListener("click", loadOverview)' in script
    assert "textContent" in script
    assert "createElement" in script
    assert "innerHTML" not in script
    assert 'postJson("/v1/task-planning"' in script
    assert 'postJson("/v1/resolve-inbox"' in script
    assert 'postJson("/v1/dismiss-inbox"' in script
    assert 'postJson("/v1/task-status"' in script
    assert "Can this be split across work sessions?" in script
    assert "No, it needs one sitting" in script
    assert "Needs a duration before recommendation." in script
    assert "Nothing needs input." in script
    assert "needsDuration" in script
    assert "formatPlanning(task)" not in script
    for section in ("needs-input", "active-session", "tasks", "projects"):
        assert f'id="{section}"' in state_html


def test_static_paths_are_exact_and_invalid_host_is_rejected(api) -> None:
    assert request(api, {}, method="GET", path="/../pyproject.toml")[0] == 404
    assert request(api, {}, method="GET", path="/", extra_headers={"Host": "evil.test"})[0] == 400

import http.client
import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from personal_os.activation import WorkActivationService
from personal_os.database import initialize_database
from personal_os.http_api import create_server
from personal_os.recommendation import RecommendationService
from personal_os.recommendation_types import (
    RecommendationChoice,
    RecommendationChoiceKind,
    RecommendationContext,
)
from personal_os.session import SessionService
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
    runtime_factory = Mock(return_value=SimpleNamespace(activation_service=activation))
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
    raw: str | None = None,
):
    server = api[0]
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        payload = (raw if raw is not None else json.dumps(body)) if method == "POST" else None
        connection.request(
            method, path, body=payload,
            headers={"Content-Type": content_type} if payload is not None else {},
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

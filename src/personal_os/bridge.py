"""One-shot, versioned JSON bridge over Personal OS application services."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import IO, Any

from personal_os.config import get_timezone_name
from personal_os.errors import PersonalOSError
from personal_os.models import serialize_instant
from personal_os.recommendation_types import (
    RecommendationContext,
    RecommendationResultKind,
)
from personal_os.runtime import PersonalOSRuntime, build_runtime
from personal_os.session_types import SessionOutcome

PROTOCOL_VERSION = 1


class InvalidRequestError(Exception):
    """Raised when input does not satisfy the bridge protocol contract."""


class NoActiveSessionError(PersonalOSError):
    """Raised when feedback is requested without an active session."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_fields(
    request: dict[str, object], *, required: set[str], optional: set[str]
) -> None:
    missing = required - request.keys()
    if missing:
        raise InvalidRequestError(f"missing required field: {sorted(missing)[0]}")
    unknown = request.keys() - required - optional
    if unknown:
        raise InvalidRequestError(f"unknown field: {sorted(unknown)[0]}")


def _integer(
    request: dict[str, object], field: str, *, positive: bool = False
) -> int | None:
    if field not in request:
        return None
    value = request[field]
    minimum = 1 if positive else 0
    description = "positive" if positive else "nonnegative"
    if type(value) is not int or value < minimum:
        raise InvalidRequestError(f"{field} must be a {description} integer")
    return value


def _optional_text(request: dict[str, object], field: str) -> str | None:
    if field not in request or request[field] is None:
        return None
    value = request[field]
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{field} must be non-empty text or null")
    return value


def _optional_timezone(
    request: dict[str, object], environ: Mapping[str, str] | None
) -> str:
    if "timezone" in request and request["timezone"] is None:
        raise InvalidRequestError("timezone must be text")
    explicit = request.get("timezone")
    if explicit is not None and not isinstance(explicit, str):
        raise InvalidRequestError("timezone must be text")
    if explicit is None:
        return get_timezone_name(None, environ)
    try:
        return get_timezone_name(explicit, environ)
    except PersonalOSError as exc:
        raise InvalidRequestError(str(exc)) from exc


def _context(
    request: dict[str, object], *, now: datetime, environ: Mapping[str, str] | None
) -> RecommendationContext:
    return RecommendationContext(
        reference_time=now,
        timezone_name=_optional_timezone(request, environ),
        available_minutes=_integer(request, "available_minutes"),
    )


def _elapsed_microseconds(value: timedelta) -> int:
    return (
        value.days * 86_400_000_000
        + value.seconds * 1_000_000
        + value.microseconds
    )


def _recommend(
    request: dict[str, object], runtime: PersonalOSRuntime, *, now: datetime,
    environ: Mapping[str, str] | None,
) -> dict[str, object]:
    _require_fields(
        request,
        required={"version", "operation"},
        optional={"available_minutes", "timezone"},
    )
    result = runtime.recommendation_service.recommend(
        _context(request, now=now, environ=environ)
    )
    if result.kind is RecommendationResultKind.NO_WORK:
        return {
            "kind": "NO_WORK",
            "explanation": result.explanation,
            "reason": (
                None
                if result.deterministic_reason is None
                else result.deterministic_reason.value
            ),
        }
    assert result.task is not None
    assert result.duration_minutes is not None
    assert result.action is not None
    return {
        "kind": "RECOMMEND",
        "task_id": result.task.id,
        "task_title": result.task.title,
        "project_name": result.project_name,
        "duration_minutes": result.duration_minutes,
        "action": result.action,
        "explanation": result.explanation,
    }


def _start(
    request: dict[str, object], runtime: PersonalOSRuntime, *, now: datetime,
    environ: Mapping[str, str] | None,
) -> dict[str, object]:
    _require_fields(
        request,
        required={"version", "operation", "task_id", "planned_minutes"},
        optional={
            "available_minutes", "timezone", "selected_action", "start_reason"
        },
    )
    task_id = _integer(request, "task_id", positive=True)
    planned_minutes = _integer(request, "planned_minutes", positive=True)
    assert task_id is not None and planned_minutes is not None
    session = runtime.session_service.start_session(
        task_id=task_id,
        planned_minutes=planned_minutes,
        context=_context(request, now=now, environ=environ),
        selected_action=_optional_text(request, "selected_action"),
        start_reason=_optional_text(request, "start_reason"),
    )
    task = runtime.store.get_task(session.task_id)
    return {
        "session_id": session.id,
        "task_id": session.task_id,
        "task_title": task.title,
        "planned_minutes": session.planned_minutes,
        "selected_action": session.selected_action,
        "started_at": serialize_instant(session.started_at),
    }


def _feedback(
    request: dict[str, object], runtime: PersonalOSRuntime, *, now: datetime,
) -> dict[str, object]:
    _require_fields(
        request,
        required={"version", "operation", "outcome"},
        optional={"result_note"},
    )
    raw_outcome = request["outcome"]
    if not isinstance(raw_outcome, str):
        raise InvalidRequestError(
            "outcome must be FINISHED, PROGRESS, or BLOCKED"
        )
    try:
        outcome = SessionOutcome(raw_outcome)
    except ValueError as exc:
        raise InvalidRequestError(
            "outcome must be FINISHED, PROGRESS, or BLOCKED"
        ) from exc
    note = _optional_text(request, "result_note")
    active = runtime.store.get_active_session()
    if active is None:
        raise NoActiveSessionError("no active session")
    session = runtime.session_service.close_session(
        session_id=active.id,
        outcome=outcome,
        ended_at=now,
        result_note=note,
    )
    task = runtime.store.get_task(session.task_id)
    assert session.actual_duration is not None
    return {
        "session_id": session.id,
        "task_id": session.task_id,
        "task_title": task.title,
        "outcome": session.outcome.value,
        "selected_action": session.selected_action,
        "result_note": session.result_note,
        "started_at": serialize_instant(session.started_at),
        "ended_at": serialize_instant(session.ended_at),
        "elapsed_microseconds": _elapsed_microseconds(session.actual_duration),
        "task_status": task.status.value,
    }


def _active(
    request: dict[str, object], runtime: PersonalOSRuntime
) -> dict[str, object]:
    _require_fields(request, required={"version", "operation"}, optional=set())
    session = runtime.store.get_active_session()
    if session is None:
        return {"active": False}
    task = runtime.store.get_task(session.task_id)
    return {
        "active": True,
        "session_id": session.id,
        "task_id": session.task_id,
        "task_title": task.title,
        "planned_minutes": session.planned_minutes,
        "selected_action": session.selected_action,
        "started_at": serialize_instant(session.started_at),
    }


def handle_request(
    request: object,
    runtime: PersonalOSRuntime,
    *,
    clock: Callable[[], datetime] = _utc_now,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, dict[str, object]]:
    """Validate one decoded request and return its operation and result."""

    if not isinstance(request, dict):
        raise InvalidRequestError("request must be a JSON object")
    version = request.get("version")
    if type(version) is not int:
        raise InvalidRequestError("version must be integer 1")
    if version != PROTOCOL_VERSION:
        raise InvalidRequestError(f"unsupported version: {version}")
    operation = request.get("operation")
    if not isinstance(operation, str) or not operation:
        raise InvalidRequestError("operation must be supplied as text")
    if operation not in {"recommend", "start", "feedback", "active"}:
        raise InvalidRequestError(f"unknown operation: {operation}")

    if operation == "active":
        return operation, _active(request, runtime)
    now = clock()
    if operation == "recommend":
        return operation, _recommend(request, runtime, now=now, environ=environ)
    if operation == "start":
        return operation, _start(request, runtime, now=now, environ=environ)
    return operation, _feedback(request, runtime, now=now)


def _error_kind(exc: BaseException) -> str | None:
    kind = getattr(exc, "kind", None)
    if isinstance(kind, Enum):
        return str(kind.value)
    return None


def _error_code(exc: BaseException) -> str:
    name = type(exc).__name__.removesuffix("Error")
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()


def _response(
    *, operation: str | None, result: dict[str, object] | None = None,
    code: str | None = None, message: str | None = None,
    kind: str | None = None,
) -> dict[str, object]:
    if result is not None:
        return {
            "version": PROTOCOL_VERSION,
            "ok": True,
            "operation": operation,
            "result": result,
        }
    return {
        "version": PROTOCOL_VERSION,
        "ok": False,
        "operation": operation,
        "error": {"code": code, "message": message, "kind": kind},
    }


def run(
    stdin: IO[str], stdout: IO[str], *,
    runtime_factory: Callable[[], PersonalOSRuntime] = build_runtime,
    clock: Callable[[], datetime] = _utc_now,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Process exactly one stdin request and write exactly one JSON response."""

    operation: str | None = None
    try:
        raw = stdin.read()
        if not raw.strip():
            raise InvalidRequestError("stdin must contain one JSON object")
        try:
            request: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InvalidRequestError("stdin must contain one valid JSON value") from exc
        if isinstance(request, dict) and isinstance(request.get("operation"), str):
            operation = request["operation"]
        operation, result = handle_request(
            request, runtime_factory(), clock=clock, environ=environ
        )
        response = _response(operation=operation, result=result)
        status = 0
    except InvalidRequestError as exc:
        response = _response(
            operation=operation, code="INVALID_REQUEST", message=str(exc)
        )
        status = 2
    except NoActiveSessionError as exc:
        response = _response(
            operation=operation, code="NO_ACTIVE_SESSION", message=str(exc)
        )
        status = 1
    except (PersonalOSError, OSError) as exc:
        response = _response(
            operation=operation,
            code=_error_code(exc),
            message=str(exc),
            kind=_error_kind(exc),
        )
        status = 1
    json.dump(response, stdout, ensure_ascii=False, separators=(",", ":"))
    stdout.write("\n")
    return status


def main() -> int:
    """Run the one-shot machine bridge."""

    return run(sys.stdin, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())

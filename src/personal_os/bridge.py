"""One-shot, versioned JSON bridge over Personal OS application services."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import IO, Any

from personal_os.activation_types import (
    WorkActivationContext,
    WorkActivationResultKind,
)
from personal_os.config import get_timezone_name
from personal_os.errors import PersonalOSError
from personal_os.models import (
    CaptureStatus,
    ProjectStatus,
    TaskExecutionMode,
    TaskStatus,
    serialize_instant,
)
from personal_os.recommendation_types import (
    RecommendationContext,
    RecommendationResult,
    RecommendationResultKind,
)
from personal_os.runtime import PersonalOSRuntime, build_runtime
from personal_os.session_types import SessionOutcome

PROTOCOL_VERSION = 1


class InvalidRequestError(Exception):
    """Raised when input does not satisfy the bridge protocol contract."""


class NoActiveSessionError(PersonalOSError):
    """Raised when feedback is requested without an active session."""


@dataclass(frozen=True, slots=True)
class _ValidatedRequest:
    operation: str
    raw_text: str | None = None
    available_minutes: int | None = None
    timezone: str | None = None
    inbox_item_id: int | None = None
    task_id: int | None = None
    task_status: TaskStatus | None = None
    planned_minutes: int | None = None
    execution_mode: TaskExecutionMode | None = None
    estimated_minutes: int | None = None
    selected_action: str | None = None
    start_reason: str | None = None
    outcome: SessionOutcome | None = None
    result_note: str | None = None
    time_cap_minutes: int | None = None


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


def _nullable_positive_integer(request: dict[str, object], field: str) -> int | None:
    if field not in request:
        return None
    value = request[field]
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise InvalidRequestError(f"{field} must be a positive integer or null")
    return value


def _execution_mode(request: dict[str, object]) -> TaskExecutionMode:
    value = request["execution_mode"]
    if not isinstance(value, str):
        raise InvalidRequestError("execution_mode must be SPLITTABLE or ONE_SITTING")
    try:
        return TaskExecutionMode(value)
    except ValueError as exc:
        raise InvalidRequestError(
            "execution_mode must be SPLITTABLE or ONE_SITTING"
        ) from exc


def _optional_text(request: dict[str, object], field: str) -> str | None:
    if field not in request or request[field] is None:
        return None
    value = request[field]
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{field} must be non-empty text or null")
    return value


def _required_text(request: dict[str, object], field: str) -> str:
    value = request[field]
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{field} must be non-empty text")
    return value


def _explicit_timezone(request: dict[str, object]) -> str | None:
    if "timezone" not in request:
        return None
    explicit = request["timezone"]
    if explicit is None:
        raise InvalidRequestError("timezone must be text")
    if not isinstance(explicit, str):
        raise InvalidRequestError("timezone must be text")
    try:
        return get_timezone_name(explicit, {})
    except PersonalOSError as exc:
        raise InvalidRequestError(str(exc)) from exc


def _context(
    request: _ValidatedRequest, *, now: datetime,
    environ: Mapping[str, str] | None,
) -> RecommendationContext:
    return RecommendationContext(
        reference_time=now,
        timezone_name=get_timezone_name(request.timezone, environ),
        available_minutes=request.available_minutes,
    )


def _elapsed_microseconds(value: timedelta) -> int:
    return (
        value.days * 86_400_000_000
        + value.seconds * 1_000_000
        + value.microseconds
    )


def _serialize_recommendation(
    result: RecommendationResult,
) -> dict[str, object]:
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


def _capture(
    request: _ValidatedRequest, runtime: PersonalOSRuntime, *, now: datetime,
    environ: Mapping[str, str] | None,
) -> dict[str, object]:
    assert request.raw_text is not None
    result = runtime.capture_service.capture_text(
        request.raw_text,
        reference_time=now,
        timezone_name=get_timezone_name(request.timezone, environ),
    )
    return _serialize_capture_result(result, runtime)


def _serialize_capture_result(
    result, runtime: PersonalOSRuntime, *,
    resolved_inbox_item_id: int | None = None,
) -> dict[str, object]:
    capture = result.capture
    response: dict[str, object] = {
        "capture_id": capture.id,
        "status": capture.status.value,
    }
    if (
        resolved_inbox_item_id is not None
        and capture.status in {CaptureStatus.APPLIED, CaptureStatus.UNRESOLVED}
    ):
        response["resolved_inbox_item_id"] = resolved_inbox_item_id
    if capture.status is CaptureStatus.APPLIED:
        tasks = [runtime.store.get_task(task_id) for task_id in result.task_ids]
        response.update(
            project=(
                None
                if result.project_id is None
                else {
                    "id": result.project_id,
                    "name": runtime.store.get_project(result.project_id).name,
                }
            ),
            tasks=[
                {
                    "id": task.id,
                    "title": task.title,
                    "execution_mode": task.execution_mode.value,
                    "estimated_minutes": task.estimated_minutes,
                    "planning_note": (
                        "Needs a duration before it can be recommended."
                        if task.execution_mode is TaskExecutionMode.ONE_SITTING
                        and task.estimated_minutes is None
                        else None
                    ),
                }
                for task in tasks
            ],
            commitments=[
                {
                    "id": commitment_id,
                    "title": runtime.store.get_fixed_commitment(commitment_id).title,
                }
                for commitment_id in result.commitment_ids
            ],
        )
    elif capture.status is CaptureStatus.UNRESOLVED:
        response.update(
            unresolved_reason=capture.unresolved_reason,
            inbox_item_id=result.inbox_item_id,
        )
    elif capture.status is CaptureStatus.FAILED:
        assert capture.failure_kind is not None
        response.update(
            failure_kind=capture.failure_kind.value,
            failure_reason=capture.failure_reason,
        )
    else:
        raise RuntimeError("capture service returned a non-final capture")
    return response


def _resolve_inbox(
    request: _ValidatedRequest, runtime: PersonalOSRuntime, *, now: datetime,
    environ: Mapping[str, str] | None,
) -> dict[str, object]:
    assert request.inbox_item_id is not None and request.raw_text is not None
    result = runtime.capture_service.resolve_inbox_text(
        request.inbox_item_id,
        request.raw_text,
        reference_time=now,
        timezone_name=get_timezone_name(request.timezone, environ),
    )
    return _serialize_capture_result(
        result, runtime, resolved_inbox_item_id=request.inbox_item_id
    )


def _dismiss_inbox(
    request: _ValidatedRequest, runtime: PersonalOSRuntime,
) -> dict[str, object]:
    assert request.inbox_item_id is not None
    item = runtime.store.resolve_inbox_item(request.inbox_item_id)
    return {
        "inbox_item_id": item.id,
        "resolved": True,
        "resolved_at": None if item.resolved_at is None else serialize_instant(item.resolved_at),
    }


def _recommend(
    request: _ValidatedRequest, runtime: PersonalOSRuntime, *, now: datetime,
    environ: Mapping[str, str] | None,
) -> dict[str, object]:
    result = runtime.recommendation_service.recommend(
        _context(request, now=now, environ=environ)
    )
    return _serialize_recommendation(result)


def _activate(
    request: _ValidatedRequest, runtime: PersonalOSRuntime, *, now: datetime,
    environ: Mapping[str, str] | None,
) -> dict[str, object]:
    result = runtime.activation_service.activate(
        WorkActivationContext(
            reference_time=now,
            timezone_name=request.timezone,
            time_cap_minutes=request.time_cap_minutes,
        ),
        timezone_resolver=lambda explicit: get_timezone_name(explicit, environ),
    )
    if result.kind is WorkActivationResultKind.ACTIVE_SESSION:
        session = result.active_session
        task = result.active_task
        assert session is not None and task is not None
        return {
            "kind": "ACTIVE_SESSION",
            "session_id": session.id,
            "task_id": session.task_id,
            "task_title": task.title,
            "planned_minutes": session.planned_minutes,
            "selected_action": session.selected_action,
            "started_at": serialize_instant(session.started_at),
        }
    assert result.recommendation is not None
    return _serialize_recommendation(result.recommendation)


def _start(
    request: _ValidatedRequest, runtime: PersonalOSRuntime, *, now: datetime,
    environ: Mapping[str, str] | None,
) -> dict[str, object]:
    assert request.task_id is not None and request.planned_minutes is not None
    session = runtime.session_service.start_session(
        task_id=request.task_id,
        planned_minutes=request.planned_minutes,
        context=_context(request, now=now, environ=environ),
        selected_action=request.selected_action,
        start_reason=request.start_reason,
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
    request: _ValidatedRequest, runtime: PersonalOSRuntime, *, now: datetime,
) -> dict[str, object]:
    assert request.outcome is not None
    active = runtime.store.get_active_session()
    if active is None:
        raise NoActiveSessionError("no active session")
    session = runtime.session_service.close_session(
        session_id=active.id,
        outcome=request.outcome,
        ended_at=now,
        result_note=request.result_note,
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


def _update_task_planning(
    request: _ValidatedRequest, runtime: PersonalOSRuntime,
) -> dict[str, object]:
    assert request.task_id is not None and request.execution_mode is not None
    task = runtime.store.update_task_planning(
        request.task_id,
        execution_mode=request.execution_mode,
        estimated_minutes=request.estimated_minutes,
    )
    return {
        "task_id": task.id,
        "title": task.title,
        "execution_mode": task.execution_mode.value,
        "estimated_minutes": task.estimated_minutes,
    }


def _correct_task_status(
    request: _ValidatedRequest, runtime: PersonalOSRuntime,
) -> dict[str, object]:
    assert request.task_id is not None and request.task_status is not None
    task = runtime.store.correct_task_status(
        request.task_id, status=request.task_status
    )
    return {
        "task_id": task.id,
        "title": task.title,
        "status": task.status.value,
    }


def _active(
    runtime: PersonalOSRuntime,
) -> dict[str, object]:
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


def _overview(runtime: PersonalOSRuntime) -> dict[str, object]:
    snapshot = runtime.store.read_state_snapshot()
    project_names = {project.id: project.name for project in snapshot.projects}
    task_titles = {task.id: task.title for task in snapshot.tasks}

    tasks = []
    for task in snapshot.tasks:
        if task.status not in {TaskStatus.OPEN, TaskStatus.BLOCKED}:
            continue
        if task.deadline_date is not None:
            deadline: dict[str, object] | None = {
                "kind": "DATE",
                "date": task.deadline_date.isoformat(),
            }
        elif task.deadline_at is not None:
            deadline = {
                "kind": "INSTANT",
                "at": serialize_instant(task.deadline_at),
            }
        else:
            deadline = None
        tasks.append({
            "id": task.id,
            "title": task.title,
            "status": task.status.value,
            "importance": task.importance.value,
            "project_id": task.project_id,
            "project_name": project_names.get(task.project_id),
            "schedule": {
                "mode": task.schedule_mode.value,
                "day_date": (
                    None if task.day_date is None else task.day_date.isoformat()
                ),
                "window_start": (
                    None
                    if task.window_start is None
                    else serialize_instant(task.window_start)
                ),
                "window_end": (
                    None
                    if task.window_end is None
                    else serialize_instant(task.window_end)
                ),
            },
            "deadline": deadline,
            "execution_mode": task.execution_mode.value,
            "estimated_minutes": task.estimated_minutes,
        })

    active_session = next(
        (session for session in snapshot.sessions if session.is_active), None
    )
    return {
        "projects": [
            {
                "id": project.id,
                "name": project.name,
                "description": project.description,
            }
            for project in snapshot.projects
            if project.status is ProjectStatus.ACTIVE
        ],
        "tasks": tasks,
        "inbox": [
            {
                "id": item.id,
                "raw_text": item.raw_text,
                "unresolved_reason": item.unresolved_reason,
                "source_capture_id": item.source_capture_id,
            }
            for item in snapshot.inbox_items
            if not item.is_resolved
        ],
        "active_session": (
            None
            if active_session is None
            else {
                "session_id": active_session.id,
                "task_id": active_session.task_id,
                "task_title": task_titles[active_session.task_id],
                "planned_minutes": active_session.planned_minutes,
                "selected_action": active_session.selected_action,
                "started_at": serialize_instant(active_session.started_at),
            }
        ),
    }


def _validate_request(request: object) -> _ValidatedRequest:
    """Validate the complete protocol contract without constructing runtime."""
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
    if operation not in {
        "capture", "recommend", "start", "feedback", "active", "activate",
        "overview", "update_task_planning", "resolve_inbox", "dismiss_inbox",
        "correct_task_status",
    }:
        raise InvalidRequestError(f"unknown operation: {operation}")

    if operation == "capture":
        _require_fields(
            request,
            required={"version", "operation", "raw_text"},
            optional={"timezone"},
        )
        return _ValidatedRequest(
            operation=operation,
            raw_text=_required_text(request, "raw_text"),
            timezone=_explicit_timezone(request),
        )
    if operation == "resolve_inbox":
        _require_fields(
            request,
            required={"version", "operation", "inbox_item_id", "raw_text"},
            optional={"timezone"},
        )
        inbox_item_id = _integer(request, "inbox_item_id", positive=True)
        assert inbox_item_id is not None
        return _ValidatedRequest(
            operation=operation,
            inbox_item_id=inbox_item_id,
            raw_text=_required_text(request, "raw_text"),
            timezone=_explicit_timezone(request),
        )
    if operation == "dismiss_inbox":
        _require_fields(
            request,
            required={"version", "operation", "inbox_item_id"},
            optional=set(),
        )
        inbox_item_id = _integer(request, "inbox_item_id", positive=True)
        assert inbox_item_id is not None
        return _ValidatedRequest(operation=operation, inbox_item_id=inbox_item_id)
    if operation == "activate":
        _require_fields(
            request,
            required={"version", "operation"},
            optional={"time_cap_minutes", "timezone"},
        )
        return _ValidatedRequest(
            operation=operation,
            time_cap_minutes=_integer(request, "time_cap_minutes"),
            timezone=_explicit_timezone(request),
        )
    if operation == "recommend":
        _require_fields(
            request,
            required={"version", "operation"},
            optional={"available_minutes", "timezone"},
        )
        return _ValidatedRequest(
            operation=operation,
            available_minutes=_integer(request, "available_minutes"),
            timezone=_explicit_timezone(request),
        )
    if operation == "start":
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
        return _ValidatedRequest(
            operation=operation,
            available_minutes=_integer(request, "available_minutes"),
            timezone=_explicit_timezone(request),
            task_id=task_id,
            planned_minutes=planned_minutes,
            selected_action=_optional_text(request, "selected_action"),
            start_reason=_optional_text(request, "start_reason"),
        )
    if operation == "feedback":
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
        return _ValidatedRequest(
            operation=operation,
            outcome=outcome,
            result_note=_optional_text(request, "result_note"),
        )
    if operation == "update_task_planning":
        _require_fields(
            request,
            required={
                "version", "operation", "task_id", "execution_mode",
                "estimated_minutes",
            },
            optional=set(),
        )
        task_id = _integer(request, "task_id", positive=True)
        assert task_id is not None
        return _ValidatedRequest(
            operation=operation,
            task_id=task_id,
            execution_mode=_execution_mode(request),
            estimated_minutes=_nullable_positive_integer(
                request, "estimated_minutes"
            ),
        )
    if operation == "correct_task_status":
        _require_fields(
            request,
            required={"version", "operation", "task_id", "status"},
            optional=set(),
        )
        task_id = _integer(request, "task_id", positive=True)
        assert task_id is not None
        raw_status = request["status"]
        if not isinstance(raw_status, str):
            raise InvalidRequestError("status must be OPEN, COMPLETED, or CANCELLED")
        try:
            task_status = TaskStatus(raw_status)
        except ValueError as exc:
            raise InvalidRequestError(
                "status must be OPEN, COMPLETED, or CANCELLED"
            ) from exc
        if task_status not in {
            TaskStatus.OPEN, TaskStatus.COMPLETED, TaskStatus.CANCELLED,
        }:
            raise InvalidRequestError("status must be OPEN, COMPLETED, or CANCELLED")
        return _ValidatedRequest(
            operation=operation, task_id=task_id, task_status=task_status
        )
    _require_fields(request, required={"version", "operation"}, optional=set())
    return _ValidatedRequest(operation=operation)


def handle_request(
    request: _ValidatedRequest,
    runtime: PersonalOSRuntime,
    *,
    clock: Callable[[], datetime] = _utc_now,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, dict[str, object]]:
    """Dispatch one fully validated request to application services."""

    operation = request.operation
    if operation == "overview":
        return operation, _overview(runtime)
    if operation == "active":
        return operation, _active(runtime)
    if operation == "update_task_planning":
        return operation, _update_task_planning(request, runtime)
    if operation == "dismiss_inbox":
        return operation, _dismiss_inbox(request, runtime)
    if operation == "correct_task_status":
        return operation, _correct_task_status(request, runtime)
    now = clock()
    if operation == "capture":
        return operation, _capture(request, runtime, now=now, environ=environ)
    if operation == "resolve_inbox":
        return operation, _resolve_inbox(request, runtime, now=now, environ=environ)
    if operation == "recommend":
        return operation, _recommend(request, runtime, now=now, environ=environ)
    if operation == "activate":
        return operation, _activate(request, runtime, now=now, environ=environ)
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


def process_request(
    request: object, *,
    runtime_factory: Callable[[], PersonalOSRuntime] = build_runtime,
    clock: Callable[[], datetime] = _utc_now,
    environ: Mapping[str, str] | None = None,
    expected_operation: str | None = None,
) -> tuple[int, dict[str, object]]:
    """Validate and dispatch a parsed machine request for local adapters."""

    operation: str | None = None
    if isinstance(request, dict) and isinstance(request.get("operation"), str):
        operation = request["operation"]
    try:
        validated = _validate_request(request)
        operation = validated.operation
        if expected_operation is not None and operation != expected_operation:
            raise InvalidRequestError(f"operation must be {expected_operation}")
        operation, result = handle_request(
            validated, runtime_factory(), clock=clock, environ=environ
        )
        return 0, _response(operation=operation, result=result)
    except InvalidRequestError as exc:
        return 2, _response(
            operation=operation, code="INVALID_REQUEST", message=str(exc)
        )
    except NoActiveSessionError as exc:
        return 1, _response(
            operation=operation, code="NO_ACTIVE_SESSION", message=str(exc)
        )
    except (PersonalOSError, OSError) as exc:
        return 1, _response(
            operation=operation,
            code=_error_code(exc),
            message=str(exc),
            kind=_error_kind(exc),
        )


def run(
    stdin: IO[str], stdout: IO[str], *,
    runtime_factory: Callable[[], PersonalOSRuntime] = build_runtime,
    clock: Callable[[], datetime] = _utc_now,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Process exactly one stdin request and write exactly one JSON response."""

    try:
        raw = stdin.read()
        if not raw.strip():
            raise InvalidRequestError("stdin must contain one JSON object")
        try:
            request: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InvalidRequestError("stdin must contain one valid JSON value") from exc
        status, response = process_request(
            request, runtime_factory=runtime_factory, clock=clock, environ=environ
        )
    except InvalidRequestError as exc:
        response = _response(
            operation=None, code="INVALID_REQUEST", message=str(exc)
        )
        status = 2
    json.dump(response, stdout, ensure_ascii=False, separators=(",", ":"))
    stdout.write("\n")
    return status


def main() -> int:
    """Run the one-shot machine bridge."""

    return run(sys.stdin, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())

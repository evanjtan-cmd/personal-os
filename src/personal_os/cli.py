"""Thin human-facing command-line adapter over Personal OS services."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from personal_os.capture import CaptureService
from personal_os.config import get_database_path, get_timezone_name
from personal_os.database import initialize_database
from personal_os.errors import PersonalOSError
from personal_os.models import CaptureStatus, serialize_instant
from personal_os.openai_capture import OpenAIResponsesCaptureInterpreter
from personal_os.openai_recommendation import OpenAIResponsesRecommendationRanker
from personal_os.recommendation import RecommendationService
from personal_os.recommendation_types import (
    RecommendationContext,
    RecommendationResultKind,
)
from personal_os.session import SessionService
from personal_os.session_types import SessionOutcome
from personal_os.state import SQLiteStateStore


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _nonnegative_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return parsed


def _add_timezone(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--timezone", help="IANA timezone (or use PERSONAL_OS_TIMEZONE)")


def _add_available_minutes(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--available-minutes", type=_nonnegative_integer)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="personal-os")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="initialize the configured SQLite database")

    capture = subparsers.add_parser("capture", help="capture natural-language work")
    capture.add_argument("text")
    _add_timezone(capture)

    recommend = subparsers.add_parser("recommend", help="recommend one eligible task")
    _add_available_minutes(recommend)
    _add_timezone(recommend)

    start = subparsers.add_parser("start", help="start a work session")
    start.add_argument("task_id", type=_positive_integer)
    start.add_argument("minutes", type=_positive_integer)
    _add_available_minutes(start)
    start.add_argument("--reason")
    _add_timezone(start)

    for command, help_text in (
        ("finish", "finish the active session and its task"),
        ("progress", "close the active session with progress"),
        ("block", "close and block the active session's task"),
    ):
        feedback = subparsers.add_parser(command, help=help_text)
        feedback.add_argument("--note")
    subparsers.add_parser("active", help="show the active work session")
    return parser


@dataclass(frozen=True, slots=True)
class _CLIRuntime:
    store: SQLiteStateStore
    capture_service: CaptureService
    recommendation_service: RecommendationService
    session_service: SessionService


def _build_runtime() -> _CLIRuntime:
    store = SQLiteStateStore(get_database_path())
    return _CLIRuntime(
        store=store,
        capture_service=CaptureService(store, OpenAIResponsesCaptureInterpreter()),
        recommendation_service=RecommendationService(
            store, OpenAIResponsesRecommendationRanker()
        ),
        session_service=SessionService(store),
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _context(args: argparse.Namespace) -> RecommendationContext:
    return RecommendationContext(
        reference_time=_utc_now(),
        timezone_name=get_timezone_name(args.timezone),
        available_minutes=args.available_minutes,
    )


def _print_task(runtime: _CLIRuntime, task_id: int) -> None:
    task = runtime.store.get_task(task_id)
    print(f"Task #{task.id}: {task.title}")


def _handle_capture(args: argparse.Namespace, runtime: _CLIRuntime) -> int:
    result = runtime.capture_service.capture_text(
        args.text,
        reference_time=_utc_now(),
        timezone_name=get_timezone_name(args.timezone),
    )
    capture = result.capture
    if capture.status is CaptureStatus.FAILED:
        print(
            f"error: Capture #{capture.id} FAILED "
            f"[{capture.failure_kind.value}]: {capture.failure_reason}",
            file=sys.stderr,
        )
        return 1
    print(f"Captured #{capture.id}: {capture.status.value}")
    if result.project_id is not None:
        project = runtime.store.get_project(result.project_id)
        print(f"Project #{project.id}: {project.name}")
    for task_id in result.task_ids:
        _print_task(runtime, task_id)
    for commitment_id in result.commitment_ids:
        commitment = runtime.store.get_fixed_commitment(commitment_id)
        print(f"Commitment #{commitment.id}: {commitment.title}")
    if capture.status is CaptureStatus.UNRESOLVED:
        print(f"Reason: {capture.unresolved_reason}")
        assert result.inbox_item_id is not None
        print(f"Inbox #{result.inbox_item_id}")
    return 0


def _handle_recommend(args: argparse.Namespace, runtime: _CLIRuntime) -> int:
    result = runtime.recommendation_service.recommend(_context(args))
    if result.kind is RecommendationResultKind.NO_WORK:
        print(f"No work recommended: {result.explanation}")
        return 0
    assert result.task is not None and result.duration_minutes is not None
    print(f"Task #{result.task.id}: {result.task.title}")
    if result.project_name is not None:
        print(f"Project: {result.project_name}")
    print(f"Duration: {result.duration_minutes} minutes")
    print(f"Why: {result.explanation}")
    hint = f"Next: personal-os start {result.task.id} {result.duration_minutes}"
    if args.available_minutes is not None:
        hint += f" --available-minutes {args.available_minutes}"
    if args.timezone is not None:
        hint += f" --timezone {args.timezone}"
    print(hint)
    return 0


def _handle_start(args: argparse.Namespace, runtime: _CLIRuntime) -> int:
    session = runtime.session_service.start_session(
        task_id=args.task_id,
        planned_minutes=args.minutes,
        context=_context(args),
        start_reason=args.reason,
    )
    print(f"Started session #{session.id}")
    _print_task(runtime, session.task_id)
    print(f"Planned: {session.planned_minutes} minutes")
    print(f"Started: {serialize_instant(session.started_at)}")
    return 0


def _format_elapsed(value: timedelta) -> str:
    total_microseconds = (
        value.days * 86_400_000_000
        + value.seconds * 1_000_000
        + value.microseconds
    )
    hours, remainder = divmod(total_microseconds, 3_600_000_000)
    minutes, remainder = divmod(remainder, 60_000_000)
    seconds, microseconds = divmod(remainder, 1_000_000)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}m")
    second_text = str(seconds)
    if microseconds:
        second_text += f".{microseconds:06d}"
    parts.append(f"{second_text}s")
    return " ".join(parts)


def _handle_feedback(
    args: argparse.Namespace, runtime: _CLIRuntime, outcome: SessionOutcome
) -> int:
    active = runtime.store.get_active_session()
    if active is None:
        print("error: No active session.", file=sys.stderr)
        return 1
    session = runtime.session_service.close_session(
        session_id=active.id,
        outcome=outcome,
        ended_at=_utc_now(),
        result_note=args.note,
    )
    task = runtime.store.get_task(session.task_id)
    assert session.actual_duration is not None
    print(f"Closed session #{session.id}: {session.outcome.value}")
    print(f"Task #{task.id}: {task.title}")
    print(f"Elapsed: {_format_elapsed(session.actual_duration)}")
    return 0


def _handle_active(runtime: _CLIRuntime) -> int:
    session = runtime.store.get_active_session()
    if session is None:
        print("No active session.")
        return 0
    print(f"Active session #{session.id}")
    _print_task(runtime, session.task_id)
    print(f"Planned: {session.planned_minutes} minutes")
    print(f"Started: {serialize_instant(session.started_at)}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit status."""

    args = build_parser().parse_args(argv)

    try:
        if args.command == "init-db":
            database_path = get_database_path()
            version = initialize_database(database_path)
            print(f"Initialized database at {database_path} (schema version {version})")
            return 0
        runtime = _build_runtime()
        if args.command == "capture":
            return _handle_capture(args, runtime)
        if args.command == "recommend":
            return _handle_recommend(args, runtime)
        if args.command == "start":
            return _handle_start(args, runtime)
        if args.command == "finish":
            return _handle_feedback(args, runtime, SessionOutcome.FINISHED)
        if args.command == "progress":
            return _handle_feedback(args, runtime, SessionOutcome.PROGRESS)
        if args.command == "block":
            return _handle_feedback(args, runtime, SessionOutcome.BLOCKED)
        if args.command == "active":
            return _handle_active(runtime)
    except (PersonalOSError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    raise AssertionError(f"unhandled command: {args.command}")

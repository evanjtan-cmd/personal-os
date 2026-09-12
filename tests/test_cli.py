import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import sqlite3
import shlex
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import personal_os.cli as cli
from personal_os.cli import build_parser, main
from personal_os.config import (
    DATA_DIR_ENV_VAR,
    DEFAULT_DATABASE_FILENAME,
    TIMEZONE_ENV_VAR,
)
from personal_os.database import CURRENT_SCHEMA_VERSION
from personal_os.database import initialize_database
from personal_os.capture import CaptureService
from personal_os.capture_types import InterpretationResponse, parse_interpretation
from personal_os.errors import PersistenceError
from personal_os.models import (
    CaptureFailureKind,
    CaptureStatus,
    CommitmentHardness,
    TaskImportance,
    TaskScheduleMode,
)
from personal_os.recommendation import RecommendationService
from personal_os.recommendation_types import (
    RecommendationChoice,
    RecommendationChoiceKind,
    RecommendationResultKind,
)
from personal_os.session import SessionService
from personal_os.session_types import SessionConflictError, SessionConflictKind, SessionOutcome
from personal_os.state import SQLiteStateStore, StateSnapshot


NOW = datetime(2026, 8, 30, 16, 0, tzinfo=UTC)


def runtime(*, store: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        store=store or Mock(),
        capture_service=Mock(),
        recommendation_service=Mock(),
        session_service=Mock(),
    )


def install_runtime(monkeypatch: pytest.MonkeyPatch, value: object) -> None:
    monkeypatch.setattr(cli, "_build_runtime", lambda: value)
    monkeypatch.setattr(cli, "_utc_now", lambda: NOW)


def test_runtime_wires_provider_capable_capture_and_recommendation_adapters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))
    value = cli._build_runtime()
    assert value.capture_service.interpreter.__class__.__name__ == (
        "OpenAIResponsesCaptureInterpreter"
    )
    assert value.recommendation_service.ranker.__class__.__name__ == (
        "OpenAIResponsesRecommendationRanker"
    )
    assert (
        value.activation_service.recommendation_service
        is value.recommendation_service
    )


def test_module_help_succeeds() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "personal_os", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "usage: personal-os" in result.stdout
    assert "init-db" in result.stdout
    for command in ("capture", "recommend", "start", "finish", "progress", "block", "active", "state"):
        assert command in result.stdout


@pytest.mark.parametrize("command", ["init-db", "capture", "recommend", "start", "finish", "progress", "block", "active", "state"])
def test_each_command_help_succeeds(command: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "personal_os", command, "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_capture_parser_preserves_shell_parsed_text() -> None:
    args = build_parser().parse_args(["capture", "  Finish my essay Friday.  ", "--timezone", "UTC"])
    assert args.text == "  Finish my essay Friday.  "


@pytest.mark.parametrize(
    "argv",
    [
        ["start", "0", "5", "--timezone", "UTC"],
        ["start", "1", "0", "--timezone", "UTC"],
        ["recommend", "--available-minutes", "-1", "--timezone", "UTC"],
    ],
)
def test_simple_numeric_argument_validation_uses_argparse(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(argv)
    assert exc_info.value.code == 2


def test_init_db_command_uses_configured_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))

    status = main(["init-db"])

    database_path = tmp_path / DEFAULT_DATABASE_FILENAME
    assert status == 0
    assert database_path.exists()
    assert f"schema version {CURRENT_SCHEMA_VERSION}" in capsys.readouterr().out


def test_init_db_command_reports_incompatible_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = tmp_path / DEFAULT_DATABASE_FILENAME
    with sqlite3.connect(database_path) as connection:
        connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 1}")
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))

    status = main(["init-db"])

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    assert "newer than supported" in captured.err


@pytest.mark.parametrize("command", ["active", "state"])
def test_product_command_does_not_initialize_missing_database(
    command: str,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "not-created"
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(data_dir))

    assert main([command]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err
    assert not data_dir.exists()


@pytest.mark.parametrize("command", ["active", "state"])
def test_product_command_does_not_migrate_stale_database(
    command: str,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = tmp_path / DEFAULT_DATABASE_FILENAME
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 3")
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))

    assert main([command]) == 1

    assert "not current version 5" in capsys.readouterr().err
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3


def test_state_command_prints_all_empty_sections_without_services(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = runtime()
    value.store.read_state_snapshot.return_value = StateSnapshot(
        projects=(), tasks=(), fixed_commitments=(), rules=(), inbox_items=(),
        captures=(), sessions=(),
    )
    install_runtime(monkeypatch, value)

    assert main(["state"]) == 0

    assert capsys.readouterr().out == (
        "Projects (0)\n  (none)\n\nTasks (0)\n  (none)\n\n"
        "Commitments (0)\n  (none)\n\nRules (0)\n  (none)\n\n"
        "Inbox (0)\n  (none)\n\nCaptures (0)\n  (none)\n\n"
        "Sessions (0)\n  (none)\n"
    )
    value.capture_service.capture_text.assert_not_called()
    value.recommendation_service.recommend.assert_not_called()
    value.session_service.start_session.assert_not_called()
    value.session_service.close_session.assert_not_called()


def test_state_command_formats_complete_persisted_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = tmp_path / DEFAULT_DATABASE_FILENAME
    initialize_database(database_path)
    store = SQLiteStateStore(database_path, clock=lambda: NOW)
    project = store.create_project("College", "Applications")
    task = store.create_task(
        "Submit essay", project_id=project.id, importance=TaskImportance.MUST,
        schedule_mode=TaskScheduleMode.WINDOW,
        window_start=NOW + timedelta(hours=1),
        window_end=NOW + timedelta(hours=2),
        deadline_date=date(2026, 9, 1), estimated_minutes=25,
    )
    store.create_fixed_commitment(
        "Call", NOW + timedelta(hours=3), hardness=CommitmentHardness.HARD
    )
    store.create_rule("duration", {"minutes": [10, 25]}, enabled=False)
    store.create_inbox_item("essay sometime", "date is unclear")
    store.create_capture("Buy milk", NOW, "UTC")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """INSERT INTO sessions
               (task_id, planned_minutes, started_at, ended_at, outcome,
                start_reason, result_note, active_slot)
               VALUES (?, 25, ?, ?, 'PROGRESS', ?, ?, NULL)""",
            (
                task.id, "2026-08-30T12:00:00.000000Z",
                "2026-08-30T13:02:03.000004Z", "Focus now", "Drafted intro",
            ),
        )
        connection.execute(
            """INSERT INTO sessions
               (task_id, planned_minutes, started_at, ended_at, outcome,
                start_reason, result_note, active_slot, selected_action)
               VALUES (?, 10, ?, NULL, NULL, NULL, NULL, 1, ?)""",
            (task.id, "2026-08-30T14:00:00.000000Z", "Review questions"),
        )
    value = runtime(store=store)
    install_runtime(monkeypatch, value)

    assert main(["state"]) == 0

    output = capsys.readouterr().out
    assert "Projects (1)\n  #1 [ACTIVE] College" in output
    assert "Tasks (1)\n  #1 [OPEN/MUST] Submit essay" in output
    assert "Schedule: WINDOW 2026-08-30T17:00:00.000000Z to 2026-08-30T18:00:00.000000Z" in output
    assert "Deadline: DATE 2026-09-01" in output
    assert "Commitments (1)\n  #1 [HARD] Call" in output
    assert "Rules (1)\n  #1 [disabled] duration" in output
    assert 'Parameters: {"minutes":[10,25]}' in output
    assert "Inbox (1)\n  #1 [UNRESOLVED] essay sometime" in output
    assert "Captures (1)\n  #1 [RECEIVED] Buy milk" in output
    assert "Sessions (2)\n  #1 [PROGRESS] Task #1" in output
    assert "Elapsed: 1h 2m 3.000004s" in output
    assert "Start reason: Focus now" in output
    assert "Result note: Drafted intro" in output
    assert "Selected action: none" in output
    assert "#2 [ACTIVE] Task #1" in output
    assert "Selected action: Review questions" in output
    assert "Ended: none" in output
    assert "interpretation" not in output.lower()
    assert "model_provider" not in output


def test_capture_applied_prints_only_created_records(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = runtime()
    value.capture_service.capture_text.return_value = SimpleNamespace(
        capture=SimpleNamespace(id=12, status=CaptureStatus.APPLIED),
        project_id=7,
        task_ids=(34, 35),
        commitment_ids=(9,),
        inbox_item_id=None,
    )
    value.store.get_project.return_value = SimpleNamespace(id=7, name="College")
    value.store.get_task.side_effect = [
        SimpleNamespace(id=34, title="Finish essay"),
        SimpleNamespace(id=35, title="Email adviser"),
    ]
    value.store.get_fixed_commitment.return_value = SimpleNamespace(id=9, title="Call Mike")
    install_runtime(monkeypatch, value)

    assert main(["capture", "raw text", "--timezone", "America/New_York"]) == 0

    value.capture_service.capture_text.assert_called_once_with(
        "raw text", reference_time=NOW, timezone_name="America/New_York"
    )
    assert capsys.readouterr().out == (
        "Captured #12: APPLIED\nProject #7: College\nTask #34: Finish essay\n"
        "Task #35: Email adviser\nCommitment #9: Call Mike\n"
    )


def test_capture_unresolved_is_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = runtime()
    value.capture_service.capture_text.return_value = SimpleNamespace(
        capture=SimpleNamespace(
            id=13,
            status=CaptureStatus.UNRESOLVED,
            unresolved_reason="explicit date is missing a year",
        ),
        project_id=None,
        task_ids=(),
        commitment_ids=(),
        inbox_item_id=5,
    )
    install_runtime(monkeypatch, value)

    assert main(["capture", "essay Friday", "--timezone", "UTC"]) == 0
    assert capsys.readouterr().out == (
        "Captured #13: UNRESOLVED\n"
        "Reason: explicit date is missing a year\nInbox #5\n"
    )


def test_capture_failed_is_error_without_provider_objects(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = runtime()
    value.capture_service.capture_text.return_value = SimpleNamespace(
        capture=SimpleNamespace(
            id=14,
            status=CaptureStatus.FAILED,
            failure_kind=CaptureFailureKind.PROVIDER_ERROR,
            failure_reason="request unavailable",
        )
    )
    install_runtime(monkeypatch, value)

    assert main(["capture", "text", "--timezone", "UTC"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: Capture #14 FAILED [PROVIDER_ERROR]: request unavailable\n"
    assert "SimpleNamespace" not in captured.err


def test_capture_uses_environment_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = runtime()
    value.capture_service.capture_text.return_value = SimpleNamespace(
        capture=SimpleNamespace(id=1, status=CaptureStatus.APPLIED),
        project_id=None, task_ids=(), commitment_ids=(), inbox_item_id=None,
    )
    install_runtime(monkeypatch, value)
    monkeypatch.setenv(TIMEZONE_ENV_VAR, "Europe/London")

    assert main(["capture", "text"]) == 0
    assert value.capture_service.capture_text.call_args.kwargs["timezone_name"] == "Europe/London"


def test_recommendation_and_explicit_context_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = runtime()
    value.recommendation_service.recommend.return_value = SimpleNamespace(
        kind=RecommendationResultKind.RECOMMEND,
        task=SimpleNamespace(id=34, title="Finish essay"),
        project_name="College",
        duration_minutes=25,
        action="Draft the essay introduction.",
        explanation="Due today and currently feasible.",
    )
    install_runtime(monkeypatch, value)

    assert main(["recommend", "--available-minutes", "30", "--timezone", "America/New_York"]) == 0

    context = value.recommendation_service.recommend.call_args.args[0]
    assert context.reference_time == NOW
    assert context.timezone_name == "America/New_York"
    assert context.available_minutes == 30
    output = capsys.readouterr().out
    assert output.startswith(
        "Action: Draft the essay introduction.\nTask #34: Finish essay\n"
    )
    assert "Duration: 25 minutes\nWhy: Due today and currently feasible.\n" in output
    assert output.endswith(
        "Next: personal-os start 34 25 --action "
        f"{shlex.quote('Draft the essay introduction.')} "
        "--available-minutes 30 --timezone America/New_York\n"
    )
    value.session_service.start_session.assert_not_called()


def test_environment_timezone_is_omitted_from_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = runtime()
    value.recommendation_service.recommend.return_value = SimpleNamespace(
        kind=RecommendationResultKind.RECOMMEND,
        task=SimpleNamespace(id=2, title="Task"), project_name=None,
        duration_minutes=10, action="Do the task.", explanation="Feasible.",
    )
    install_runtime(monkeypatch, value)
    monkeypatch.setenv(TIMEZONE_ENV_VAR, "UTC")

    assert main(["recommend"]) == 0
    output = capsys.readouterr().out
    assert "Project:" not in output
    assert output.endswith(
        f"Next: personal-os start 2 10 --action {shlex.quote('Do the task.')}\n"
    )
    assert "--timezone" not in output


def test_recommendation_hint_shell_quotes_selected_action(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    action = "Review Sam's $HOME; `stop` and \"quote\""
    value = runtime()
    value.recommendation_service.recommend.return_value = SimpleNamespace(
        kind=RecommendationResultKind.RECOMMEND,
        task=SimpleNamespace(id=9, title="Review"), project_name=None,
        duration_minutes=10, action=action, explanation="Fits now.",
    )
    install_runtime(monkeypatch, value)

    assert main(["recommend", "--timezone", "UTC"]) == 0

    hint = capsys.readouterr().out.splitlines()[-1].removeprefix("Next: ")
    assert f"--action {shlex.quote(action)}" in hint
    assert shlex.split(hint) == [
        "personal-os", "start", "9", "10", "--action", action,
        "--timezone", "UTC",
    ]


def test_no_work_is_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = runtime()
    value.recommendation_service.recommend.return_value = SimpleNamespace(
        kind=RecommendationResultKind.NO_WORK, explanation="No eligible task fits."
    )
    install_runtime(monkeypatch, value)

    assert main(["recommend", "--timezone", "UTC"]) == 0
    assert capsys.readouterr().out == "No work recommended: No eligible task fits.\n"


def test_start_forwards_only_inputs_and_prints_session(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = runtime()
    value.session_service.start_session.return_value = SimpleNamespace(
        id=8, task_id=34, planned_minutes=25, started_at=NOW,
        selected_action=None,
    )
    value.store.get_task.return_value = SimpleNamespace(id=34, title="Finish essay")
    install_runtime(monkeypatch, value)

    assert main(["start", "34", "25", "--available-minutes", "30", "--reason", "Ready", "--timezone", "UTC"]) == 0

    call = value.session_service.start_session.call_args.kwargs
    assert call["task_id"] == 34
    assert call["planned_minutes"] == 25
    assert call["selected_action"] is None
    assert call["start_reason"] == "Ready"
    assert call["context"].reference_time == NOW
    assert capsys.readouterr().out == (
        "Started session #8\nTask #34: Finish essay\nPlanned: 25 minutes\n"
        "Started: 2026-08-30T16:00:00.000000Z\n"
    )


def test_start_action_is_forwarded_and_confirmed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = runtime()
    value.session_service.start_session.return_value = SimpleNamespace(
        id=8, task_id=34, planned_minutes=25, started_at=NOW,
        selected_action="Draft one section.",
    )
    value.store.get_task.return_value = SimpleNamespace(id=34, title="Essay")
    install_runtime(monkeypatch, value)

    assert main([
        "start", "34", "25", "--action", "Draft one section.",
        "--timezone", "UTC",
    ]) == 0

    call = value.session_service.start_session.call_args.kwargs
    assert call["selected_action"] == "Draft one section."
    assert call["start_reason"] is None
    assert "Action: Draft one section.\n" in capsys.readouterr().out


def test_start_service_error_is_not_prechecked_or_reclassified(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = runtime()
    value.session_service.start_session.side_effect = SessionConflictError(
        SessionConflictKind.ACTIVE_SESSION_EXISTS, "an active session already exists"
    )
    install_runtime(monkeypatch, value)

    assert main(["start", "1", "5", "--timezone", "UTC"]) == 1
    assert "an active session already exists" in capsys.readouterr().err
    value.store.get_task.assert_not_called()


@pytest.mark.parametrize(
    "command,outcome",
    [("finish", SessionOutcome.FINISHED), ("progress", SessionOutcome.PROGRESS), ("block", SessionOutcome.BLOCKED)],
)
def test_feedback_forwards_verbatim_note_and_fresh_end(
    command: str,
    outcome: SessionOutcome,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    value = runtime()
    value.store.get_active_session.return_value = SimpleNamespace(id=8)
    value.session_service.close_session.return_value = SimpleNamespace(
        id=8, task_id=34, outcome=outcome,
        actual_duration=timedelta(hours=1, minutes=18, seconds=42, microseconds=123456),
    )
    value.store.get_task.return_value = SimpleNamespace(id=34, title="Finish essay")
    install_runtime(monkeypatch, value)

    assert main([command, "--note", "  Kept verbatim  "]) == 0

    value.session_service.close_session.assert_called_once_with(
        session_id=8, outcome=outcome, ended_at=NOW, result_note="  Kept verbatim  "
    )
    assert "Elapsed: 1h 18m 42.123456s" in capsys.readouterr().out


def test_feedback_without_active_session_is_clean_error_without_timezone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = runtime()
    value.store.get_active_session.return_value = None
    install_runtime(monkeypatch, value)

    assert main(["finish"]) == 1
    assert capsys.readouterr().err == "error: No active session.\n"
    value.session_service.close_session.assert_not_called()


def test_feedback_close_race_surfaces_service_conflict(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = runtime()
    value.store.get_active_session.return_value = SimpleNamespace(id=8)
    value.session_service.close_session.side_effect = SessionConflictError(
        SessionConflictKind.SESSION_ALREADY_CLOSED, "session 8 is already closed"
    )
    install_runtime(monkeypatch, value)

    assert main(["progress"]) == 1
    assert "already closed" in capsys.readouterr().err
    value.store.get_task.assert_not_called()


def test_active_display_needs_no_timezone_and_does_not_mutate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = runtime()
    value.store.get_active_session.return_value = SimpleNamespace(
        id=8, task_id=34, planned_minutes=25, started_at=NOW,
        selected_action="Draft one section.",
    )
    value.store.get_task.return_value = SimpleNamespace(id=34, title="Finish essay")
    install_runtime(monkeypatch, value)

    assert main(["active"]) == 0
    assert capsys.readouterr().out == (
        "Active session #8\nTask #34: Finish essay\nAction: Draft one section.\n"
        "Planned: 25 minutes\n"
        "Started: 2026-08-30T16:00:00.000000Z\n"
    )
    value.session_service.start_session.assert_not_called()
    value.session_service.close_session.assert_not_called()


def test_active_with_none_is_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = runtime()
    value.store.get_active_session.return_value = None
    install_runtime(monkeypatch, value)

    assert main(["active"]) == 0
    assert capsys.readouterr().out == "No active session.\n"


def test_expected_os_and_personal_os_errors_are_stderr_exit_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = runtime()
    value.store.get_active_session.side_effect = PersistenceError("broken state")
    install_runtime(monkeypatch, value)
    assert main(["active"]) == 1
    assert capsys.readouterr().err == "error: broken state\n"


def test_unexpected_programming_error_is_not_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    value = runtime()
    value.store.get_active_session.side_effect = RuntimeError("bug")
    install_runtime(monkeypatch, value)
    with pytest.raises(RuntimeError, match="bug"):
        main(["active"])


def test_complete_dogfood_cli_loop_uses_real_services_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeInterpreter:
        def interpret(self, raw_text: str, *, projects: list[dict[str, object]]) -> InterpretationResponse:
            assert raw_text == "Finish the loop"
            payload = {
                "kind": "APPLY",
                "new_project": {"name": "MVP", "description": None},
                "tasks": [{
                    "title": "Finish loop", "project_id": "NEW",
                    "importance": "MUST", "estimated_minutes": 10,
                    "schedule": None, "deadline": None,
                }],
                "commitments": [],
                "unresolved_reason": None,
            }
            return InterpretationResponse(
                parse_interpretation(payload), "fake", "fake-model", "fake-response"
            )

    class FakeRanker:
        def __init__(self) -> None:
            self.calls = 0

        def recommend(self, context: object, candidates: tuple[object, ...]) -> RecommendationChoice:
            self.calls += 1
            candidate = candidates[0]
            return RecommendationChoice(
                RecommendationChoiceKind.RECOMMEND,
                candidate.task_id,
                10,
                "Complete the loop's next step.",
                "Complete the loop.",
            )

    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))
    monkeypatch.setenv(TIMEZONE_ENV_VAR, "UTC")
    assert main(["init-db"]) == 0
    capsys.readouterr()

    store = SQLiteStateStore(tmp_path / DEFAULT_DATABASE_FILENAME, clock=lambda: NOW)
    ranker = FakeRanker()
    value = SimpleNamespace(
        store=store,
        capture_service=CaptureService(store, FakeInterpreter()),
        recommendation_service=RecommendationService(store, ranker),
        session_service=SessionService(store),
    )
    monkeypatch.setattr(cli, "_build_runtime", lambda: value)
    times = iter((NOW, NOW, NOW, NOW + timedelta(minutes=8), NOW + timedelta(minutes=9)))
    monkeypatch.setattr(cli, "_utc_now", lambda: next(times))

    assert main(["capture", "Finish the loop"]) == 0
    capture_output = capsys.readouterr().out
    assert "Captured #1: APPLIED" in capture_output
    assert "Task #1: Finish loop" in capture_output

    assert main(["recommend", "--available-minutes", "10"]) == 0
    recommendation_output = capsys.readouterr().out
    assert "--action " + shlex.quote("Complete the loop's next step.") in recommendation_output
    assert "--available-minutes 10" in recommendation_output

    assert main([
        "start", "1", "10", "--action", "Complete the loop's next step.",
        "--available-minutes", "10",
    ]) == 0
    start_output = capsys.readouterr().out
    assert "Started session #1" in start_output
    assert "Action: Complete the loop's next step." in start_output

    assert main(["finish", "--note", "Done"]) == 0
    assert "Elapsed: 8m 0s" in capsys.readouterr().out

    assert main(["state"]) == 0
    state_output = capsys.readouterr().out
    assert "Tasks (1)\n  #1 [COMPLETED/MUST] Finish loop" in state_output
    assert "Sessions (1)\n  #1 [FINISHED] Task #1" in state_output
    assert "Result note: Done" in state_output

    assert main(["recommend"]) == 0
    assert "No work recommended:" in capsys.readouterr().out
    assert ranker.calls == 1

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from personal_os.activation import WorkActivationService
from personal_os.activation_types import (
    WorkActivationContext,
    WorkActivationResultKind,
)
from personal_os.database import initialize_database
from personal_os.errors import DomainValidationError
from personal_os.models import CommitmentHardness, TaskImportance
from personal_os.recommendation import RecommendationService
from personal_os.recommendation_types import (
    DeterministicNoWorkReason,
    RecommendationChoice,
    RecommendationChoiceKind,
    RecommendationContext,
)
from personal_os.session import SessionService
from personal_os.state import SQLiteStateStore

NOW = datetime(2026, 9, 12, 14, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStateStore:
    path = tmp_path / "state.db"
    initialize_database(path)
    return SQLiteStateStore(path, clock=lambda: NOW)


class RecordingRanker:
    def __init__(self, *, no_work: bool = False, duration: int | None = None) -> None:
        self.no_work = no_work
        self.duration = duration
        self.calls: list[tuple[object, tuple[object, ...]]] = []

    def recommend(
        self, context: object, candidates: tuple[object, ...]
    ) -> RecommendationChoice:
        self.calls.append((context, candidates))
        if self.no_work:
            return RecommendationChoice(
                RecommendationChoiceKind.NO_WORK,
                None,
                None,
                None,
                "No useful work right now.",
            )
        candidate = candidates[0]
        duration = (
            candidate.allowed_durations[0]
            if self.duration is None
            else self.duration
        )
        return RecommendationChoice(
            RecommendationChoiceKind.RECOMMEND,
            candidate.task_id,
            duration,
            "Do the concrete next step.",
            "This is the best fit.",
        )


def test_active_session_wins_without_recommendation_or_mutation(store) -> None:
    task = store.create_task("Continue current work", estimated_minutes=25)
    session = SessionService(store).start_session(
        task_id=task.id,
        planned_minutes=25,
        context=RecommendationContext(NOW, "UTC", 25),
        selected_action="Draft the opening section.",
    )
    recommendation_service = Mock()
    before = store.read_state_snapshot()

    result = WorkActivationService(store, recommendation_service).activate(
        WorkActivationContext(NOW + timedelta(minutes=2), "UTC")
    )

    assert result.kind is WorkActivationResultKind.ACTIVE_SESSION
    assert result.active_session == session
    assert result.active_task == task
    assert result.recommendation is None
    recommendation_service.recommend.assert_not_called()
    assert store.read_state_snapshot() == before


def test_no_active_session_preserves_recommendation_result(store) -> None:
    task = store.create_task("Write draft", estimated_minutes=25)
    ranker = RecordingRanker(duration=10)
    recommendation_service = RecommendationService(store, ranker)
    before = store.read_state_snapshot()

    result = WorkActivationService(store, recommendation_service).activate(
        WorkActivationContext(NOW, "UTC", 20)
    )

    assert result.kind is WorkActivationResultKind.RECOMMEND
    assert result.recommendation is not None
    assert result.recommendation.task == task
    assert result.recommendation.duration_minutes == 10
    assert result.recommendation.action == "Do the concrete next step."
    assert ranker.calls[0][0].available_minutes == 20
    assert ranker.calls[0][1][0].allowed_durations == (5, 10, 15, 20)
    assert store.read_state_snapshot() == before


def test_deterministic_no_work_is_preserved_and_skips_ranker(store) -> None:
    store.create_task("Task")
    ranker = RecordingRanker()

    result = WorkActivationService(
        store, RecommendationService(store, ranker)
    ).activate(WorkActivationContext(NOW, "UTC", 0))

    assert result.kind is WorkActivationResultKind.NO_WORK
    assert result.recommendation is not None
    assert (
        result.recommendation.deterministic_reason
        is DeterministicNoWorkReason.NO_FEASIBLE_TASKS
    )
    assert not ranker.calls


def test_ranker_no_work_is_preserved_when_valid(store) -> None:
    store.create_task("Optional task", importance=TaskImportance.COULD)
    ranker = RecordingRanker(no_work=True)

    result = WorkActivationService(
        store, RecommendationService(store, ranker)
    ).activate(WorkActivationContext(NOW, "UTC"))

    assert result.kind is WorkActivationResultKind.NO_WORK
    assert result.recommendation is not None
    assert result.recommendation.deterministic_reason is None
    assert result.recommendation.explanation == "No useful work right now."
    assert len(ranker.calls) == 1


def test_omitted_cap_invents_no_default_and_activation_is_read_only(store) -> None:
    store.create_task("Unbounded task")
    ranker = RecordingRanker(duration=35)
    before = store.read_state_snapshot()

    result = WorkActivationService(
        store, RecommendationService(store, ranker)
    ).activate(WorkActivationContext(NOW, "UTC"))

    assert result.recommendation is not None
    assert result.recommendation.duration_minutes == 35
    ranking_context, candidates = ranker.calls[0]
    assert ranking_context.available_minutes is None
    assert candidates[0].allowed_durations == (5, 10, 15, 20, 25, 30, 35, 45, 60)
    assert store.read_state_snapshot() == before


def test_hard_commitment_bound_remains_authoritative(store) -> None:
    store.create_task("Task")
    store.create_fixed_commitment(
        "Meeting",
        NOW + timedelta(minutes=12),
        end_at=NOW + timedelta(minutes=30),
        hardness=CommitmentHardness.HARD,
    )
    ranker = RecordingRanker(duration=10)

    result = WorkActivationService(
        store, RecommendationService(store, ranker)
    ).activate(WorkActivationContext(NOW, "UTC", 30))

    assert result.kind is WorkActivationResultKind.RECOMMEND
    ranking_context, candidates = ranker.calls[0]
    assert ranking_context.available_minutes == 12
    assert candidates[0].allowed_durations == (5, 10)
    assert result.recommendation.duration_minutes == 10


@pytest.mark.parametrize("cap", [True, -1, 1.5, "10"])
def test_activation_context_rejects_malformed_time_cap(cap: object) -> None:
    with pytest.raises(DomainValidationError, match="time_cap_minutes"):
        WorkActivationContext(NOW, "UTC", cap)  # type: ignore[arg-type]


def test_activation_rejects_untyped_context(store) -> None:
    with pytest.raises(DomainValidationError, match="WorkActivationContext"):
        WorkActivationService(store, Mock()).activate(object())  # type: ignore[arg-type]

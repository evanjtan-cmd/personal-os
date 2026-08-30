"""Read-only deterministic recommendation application service."""

from __future__ import annotations

from typing import Protocol
from zoneinfo import ZoneInfo

from personal_os.eligibility import calculate_availability, evaluate_task
from personal_os.errors import DomainValidationError, PersistenceError
from personal_os.models import Project, TaskImportance, serialize_date, serialize_instant
from personal_os.recommendation_types import (
    AvailabilityKind, DeterministicNoWorkReason, EligibleTaskCandidate,
    RecommendationChoice, RecommendationChoiceKind, RecommendationContext,
    RecommendationError, RecommendationFailureKind, RecommendationRankingContext,
    RecommendationResult, RecommendationResultKind, ScheduleState, DeadlineState,
)
from personal_os.state import SQLiteStateStore

NORMAL_DURATION_LADDER = (5, 10, 15, 20, 25, 30, 35, 45, 60)


class RecommendationRanker(Protocol):
    def recommend(
        self, context: RecommendationRankingContext,
        candidates: tuple[EligibleTaskCandidate, ...],
    ) -> RecommendationChoice: ...


def allowed_durations(
    estimated_minutes: int | None, available_minutes: int | None,
) -> tuple[int, ...]:
    if estimated_minutes is not None and estimated_minutes < 5:
        if available_minutes is None or estimated_minutes <= available_minutes:
            return (estimated_minutes,)
        return ()
    maximum = 60
    if available_minutes is not None:
        maximum = min(maximum, available_minutes)
    if estimated_minutes is not None:
        maximum = min(maximum, estimated_minutes)
    values = [item for item in NORMAL_DURATION_LADDER if item <= maximum]
    if (
        estimated_minutes is not None
        and 5 <= estimated_minutes <= maximum
        and estimated_minutes not in values
    ):
        values.append(estimated_minutes)
    return tuple(sorted(values))


def _candidate_sort_key(candidate: EligibleTaskCandidate) -> tuple[int, int, int, int]:
    schedule = {
        ScheduleState.DAY_MISSED: 0,
        ScheduleState.DAY_TODAY: 1,
    }.get(candidate.schedule_state, 2)
    deadline = {
        DeadlineState.OVERDUE: 0,
        DeadlineState.DUE_TODAY: 1,
        DeadlineState.FUTURE: 2,
        DeadlineState.NONE: 3,
    }[candidate.deadline_state]
    importance = {
        TaskImportance.MUST: 0,
        TaskImportance.SHOULD: 1,
        TaskImportance.UNSPECIFIED: 2,
        TaskImportance.COULD: 3,
    }[candidate.importance]
    return schedule, deadline, importance, candidate.task_id


class RecommendationService:
    def __init__(
        self, store: SQLiteStateStore, ranker: RecommendationRanker, *,
        candidate_limit: int = 50,
    ) -> None:
        if type(candidate_limit) is not int or candidate_limit <= 0:
            raise DomainValidationError("candidate_limit must be a positive integer")
        self.store, self.ranker, self.candidate_limit = store, ranker, candidate_limit

    def recommend(self, context: RecommendationContext) -> RecommendationResult:
        if not isinstance(context, RecommendationContext):
            raise DomainValidationError("context must be a RecommendationContext")
        zone = ZoneInfo(context.timezone_name)
        projects, tasks, commitments = self.store.read_recommendation_snapshot()
        availability = calculate_availability(context, commitments)
        if availability.kind is AvailabilityKind.BLOCKED_ACTIVE_HARD:
            return RecommendationResult(
                RecommendationResultKind.NO_WORK, availability,
                "A hard commitment is active now.",
                deterministic_reason=DeterministicNoWorkReason.ACTIVE_HARD_COMMITMENT,
            )
        if availability.kind is AvailabilityKind.BLOCKED_ACTIVE_OPEN_ENDED_HARD:
            return RecommendationResult(
                RecommendationResultKind.NO_WORK, availability,
                "An open-ended hard commitment is active now.",
                deterministic_reason=DeterministicNoWorkReason.ACTIVE_OPEN_ENDED_HARD_COMMITMENT,
            )

        project_map = {item.id: item for item in projects}
        local_date = context.reference_time.astimezone(zone).date()
        candidates = []
        tasks_by_id = {item.id: item for item in tasks}
        for task in tasks:
            decision = evaluate_task(
                task, projects=project_map, now=context.reference_time,
                local_date=local_date,
            )
            if not decision.eligible:
                continue
            durations = allowed_durations(
                task.estimated_minutes, availability.available_minutes,
            )
            if not durations:
                continue
            project: Project | None = (
                None if task.project_id is None else project_map[task.project_id]
            )
            candidates.append(EligibleTaskCandidate(
                task.id, task.title, None if project is None else project.name,
                task.importance, decision.schedule_state, decision.days_late,
                decision.deadline_state,
                None if task.deadline_date is None else serialize_date(task.deadline_date),
                None if task.deadline_at is None else serialize_instant(task.deadline_at),
                task.estimated_minutes, durations,
            ))
        if not candidates:
            return RecommendationResult(
                RecommendationResultKind.NO_WORK, availability,
                "No eligible task fits the available time.",
                deterministic_reason=DeterministicNoWorkReason.NO_FEASIBLE_TASKS,
            )

        must_gated = any(item.importance is TaskImportance.MUST for item in candidates)
        if must_gated:
            candidates = [
                item for item in candidates if item.importance is TaskImportance.MUST
            ]
        bounded = tuple(sorted(candidates, key=_candidate_sort_key)[:self.candidate_limit])
        ranking_context = RecommendationRankingContext(
            availability.kind, availability.available_minutes, must_gated,
        )
        try:
            choice = self.ranker.recommend(ranking_context, bounded)
        except PersistenceError:
            raise
        except RecommendationError:
            raise
        except Exception as exc:
            raise RecommendationError(
                RecommendationFailureKind.PROVIDER_ERROR,
                str(exc) or type(exc).__name__,
            ) from exc
        return self._validate_choice(
            choice, bounded, tasks_by_id, project_map, availability, must_gated,
        )

    @staticmethod
    def _validate_choice(
        choice: RecommendationChoice,
        candidates: tuple[EligibleTaskCandidate, ...], tasks_by_id: dict,
        projects: dict, availability, must_gated: bool,
    ) -> RecommendationResult:
        if not isinstance(choice, RecommendationChoice):
            raise RecommendationError(
                RecommendationFailureKind.INVALID_OUTPUT,
                "ranker returned an invalid choice type",
            )
        if not isinstance(choice.reason, str) or not choice.reason.strip():
            raise RecommendationError(
                RecommendationFailureKind.INVALID_OUTPUT,
                "reason must be non-empty",
            )
        candidate_map = {item.task_id: item for item in candidates}
        if choice.kind is RecommendationChoiceKind.NO_WORK:
            if choice.task_id is not None or choice.duration_minutes is not None:
                raise RecommendationError(RecommendationFailureKind.INVALID_OUTPUT, "NO_WORK cannot contain task or duration")
            if must_gated:
                raise RecommendationError(RecommendationFailureKind.INVALID_OUTPUT, "NO_WORK is invalid while feasible MUST tasks exist")
            return RecommendationResult(
                RecommendationResultKind.NO_WORK, availability, choice.reason,
            )
        if choice.kind is not RecommendationChoiceKind.RECOMMEND:
            raise RecommendationError(RecommendationFailureKind.INVALID_OUTPUT, "unknown recommendation choice")
        candidate = candidate_map.get(choice.task_id)
        if candidate is None:
            raise RecommendationError(RecommendationFailureKind.INVALID_OUTPUT, "selected task was not supplied")
        if type(choice.duration_minutes) is not int or choice.duration_minutes not in candidate.allowed_durations:
            raise RecommendationError(RecommendationFailureKind.INVALID_OUTPUT, "duration was not allowed for selected task")
        task = tasks_by_id[candidate.task_id]
        project_name = None if task.project_id is None else projects[task.project_id].name
        return RecommendationResult(
            RecommendationResultKind.RECOMMEND, availability, choice.reason,
            task=task, project_name=project_name,
            duration_minutes=choice.duration_minutes,
        )

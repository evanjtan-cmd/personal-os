"""Canonical application service for an availability-now activation."""

from __future__ import annotations

from collections.abc import Callable

from personal_os.activation_types import (
    WorkActivationContext,
    WorkActivationResult,
    WorkActivationResultKind,
)
from personal_os.errors import DomainValidationError
from personal_os.recommendation import RecommendationService
from personal_os.recommendation_types import RecommendationResultKind
from personal_os.state import SQLiteStateStore


class WorkActivationService:
    def __init__(
        self,
        store: SQLiteStateStore,
        recommendation_service: RecommendationService,
    ) -> None:
        self.store = store
        self.recommendation_service = recommendation_service

    def activate(
        self,
        context: WorkActivationContext,
        *,
        timezone_resolver: Callable[[str | None], str] | None = None,
    ) -> WorkActivationResult:
        if not isinstance(context, WorkActivationContext):
            raise DomainValidationError(
                "context must be a WorkActivationContext"
            )
        active_session = self.store.get_active_session()
        if active_session is not None:
            return WorkActivationResult(
                WorkActivationResultKind.ACTIVE_SESSION,
                active_session=active_session,
                active_task=self.store.get_task(active_session.task_id),
            )
        timezone_name = (
            context.timezone_name
            if timezone_resolver is None
            else timezone_resolver(context.timezone_name)
        )
        recommendation = self.recommendation_service.recommend(
            context.as_recommendation_context(timezone_name)
        )
        kind = (
            WorkActivationResultKind.RECOMMEND
            if recommendation.kind is RecommendationResultKind.RECOMMEND
            else WorkActivationResultKind.NO_WORK
        )
        return WorkActivationResult(kind, recommendation=recommendation)

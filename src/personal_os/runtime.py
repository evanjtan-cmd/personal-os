"""Shared, side-effect-free runtime construction for thin adapters."""

from __future__ import annotations

from dataclasses import dataclass

from personal_os.capture import CaptureService
from personal_os.config import get_database_path
from personal_os.openai_capture import OpenAIResponsesCaptureInterpreter
from personal_os.openai_recommendation import OpenAIResponsesRecommendationRanker
from personal_os.recommendation import RecommendationService
from personal_os.session import SessionService
from personal_os.state import SQLiteStateStore


@dataclass(frozen=True, slots=True)
class PersonalOSRuntime:
    """Concrete services shared by local process adapters."""

    store: SQLiteStateStore
    capture_service: CaptureService
    recommendation_service: RecommendationService
    session_service: SessionService


def build_runtime() -> PersonalOSRuntime:
    """Construct services without opening storage or provider connections."""

    store = SQLiteStateStore(get_database_path())
    return PersonalOSRuntime(
        store=store,
        capture_service=CaptureService(store, OpenAIResponsesCaptureInterpreter()),
        recommendation_service=RecommendationService(
            store, OpenAIResponsesRecommendationRanker()
        ),
        session_service=SessionService(store),
    )

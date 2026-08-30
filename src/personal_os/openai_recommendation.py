"""OpenAI Responses API adapter for recommendation ranking."""

from __future__ import annotations

import json
import os

from personal_os.recommendation_types import (
    EligibleTaskCandidate,
    RecommendationChoice,
    RecommendationChoiceKind,
    RecommendationError,
    RecommendationFailureKind,
    RecommendationRankingContext,
)


RECOMMENDATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {"type": "string", "enum": ["RECOMMEND", "NO_WORK"]},
        "task_id": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "duration_minutes": {
            "anyOf": [{"type": "integer"}, {"type": "null"}]
        },
        "reason": {"type": "string"},
    },
    "required": ["kind", "task_id", "duration_minutes", "reason"],
}


class OpenAIResponsesRecommendationRanker:
    """Rank eligible tasks through a lazily constructed OpenAI client."""

    def __init__(self, *, client: object | None = None, model: str | None = None) -> None:
        self._client = client
        self._model = model

    def recommend(
        self,
        context: RecommendationRankingContext,
        candidates: tuple[EligibleTaskCandidate, ...],
    ) -> RecommendationChoice:
        model = self._model or os.environ.get("PERSONAL_OS_RECOMMEND_MODEL")
        if not model:
            raise RecommendationError(
                RecommendationFailureKind.CONFIGURATION_ERROR,
                "PERSONAL_OS_RECOMMEND_MODEL is not configured",
            )
        client = self._client
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise RecommendationError(
                    RecommendationFailureKind.CONFIGURATION_ERROR,
                    "OPENAI_API_KEY is not configured",
                )
            try:
                from openai import OpenAI

                client = OpenAI()
            except Exception as exc:
                raise RecommendationError(
                    RecommendationFailureKind.CONFIGURATION_ERROR,
                    f"OpenAI client configuration failed: {exc}",
                ) from exc

        payload = {
            "availability": {
                "kind": context.availability_kind.value,
                "available_minutes": context.available_minutes,
            },
            "must_gated": context.must_gated,
            "candidates": [
                {
                    "task_id": item.task_id,
                    "title": item.title,
                    "project_name": item.project_name,
                    "importance": item.importance.value,
                    "schedule_state": item.schedule_state.value,
                    "days_late": item.days_late,
                    "deadline_state": item.deadline_state.value,
                    "deadline_date": item.deadline_date,
                    "deadline_at": item.deadline_at,
                    "estimated_minutes": item.estimated_minutes,
                    "allowed_durations": list(item.allowed_durations),
                }
                for item in candidates
            ],
        }
        instructions = (
            "Select one supplied eligible task and exactly one of its allowed_durations, "
            "or return NO_WORK only when must_gated is false. Treat importance, schedule "
            "state, missed days, and deadline state as supplied ranking facts. Do not invent "
            "hard conflicts, rule evaluation, business hours, energy constraints, schedule "
            "facts, or availability. Give a concise qualitative reason."
        )
        try:
            response = client.responses.create(
                model=model,
                instructions=instructions,
                input=json.dumps(payload, separators=(",", ":")),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "personal_os_recommendation_v1",
                        "strict": True,
                        "schema": RECOMMENDATION_SCHEMA,
                    }
                },
                store=False,
            )
        except RecommendationError:
            raise
        except Exception as exc:
            raise RecommendationError(
                RecommendationFailureKind.PROVIDER_ERROR,
                f"OpenAI request failed: {exc}",
            ) from exc

        status = getattr(response, "status", None)
        if status in {"failed", "incomplete"}:
            raise RecommendationError(
                RecommendationFailureKind.PROVIDER_ERROR,
                f"OpenAI response status was {status}",
            )
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                refusal = getattr(content, "refusal", None)
                if refusal:
                    raise RecommendationError(
                        RecommendationFailureKind.REFUSAL, str(refusal)
                    )
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text:
            raise RecommendationError(
                RecommendationFailureKind.INVALID_OUTPUT,
                "OpenAI response contained no structured text",
            )
        try:
            decoded = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise RecommendationError(
                RecommendationFailureKind.INVALID_OUTPUT,
                "OpenAI response was malformed JSON",
            ) from exc
        if not isinstance(decoded, dict) or set(decoded) != {
            "kind", "task_id", "duration_minutes", "reason"
        }:
            raise RecommendationError(
                RecommendationFailureKind.INVALID_OUTPUT,
                "OpenAI response did not match the recommendation contract",
            )
        try:
            kind = RecommendationChoiceKind(decoded["kind"])
        except (TypeError, ValueError) as exc:
            raise RecommendationError(
                RecommendationFailureKind.INVALID_OUTPUT,
                "OpenAI response contained an invalid choice kind",
            ) from exc
        return RecommendationChoice(
            kind,
            decoded["task_id"],
            decoded["duration_minutes"],
            decoded["reason"],
        )

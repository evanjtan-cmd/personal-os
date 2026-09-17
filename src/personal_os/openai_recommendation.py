"""Strict Responses API adapter for recommendation ranking."""

from __future__ import annotations

import json

from personal_os.ai_provider import (
    InferenceProvider,
    build_responses_client,
    resolve_recommendation_provider,
)
from personal_os.config import ConfigurationError

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
        "action": {"type": ["string", "null"]},
        "reason": {"type": "string"},
    },
    "required": ["kind", "task_id", "duration_minutes", "action", "reason"],
}


class OpenAIResponsesRecommendationRanker:
    """Rank eligible tasks through a lazily configured Responses client."""

    def __init__(
        self, *, client: object | None = None, model: str | None = None,
        provider: InferenceProvider | str = InferenceProvider.OPENAI,
    ) -> None:
        self._client = client
        self._model = model
        self._provider = provider

    def recommend(
        self,
        context: RecommendationRankingContext,
        candidates: tuple[EligibleTaskCandidate, ...],
    ) -> RecommendationChoice:
        client = self._client
        if client is not None:
            model = self._model
            provider = str(self._provider)
            if not model:
                raise RecommendationError(
                    RecommendationFailureKind.CONFIGURATION_ERROR,
                    "PERSONAL_OS_RECOMMEND_MODEL is not configured",
                )
        else:
            try:
                config = resolve_recommendation_provider()
                client = build_responses_client(config)
            except ConfigurationError as exc:
                raise RecommendationError(
                    RecommendationFailureKind.CONFIGURATION_ERROR, str(exc)
                ) from exc
            except Exception as exc:
                raise RecommendationError(
                    RecommendationFailureKind.CONFIGURATION_ERROR,
                    f"Responses client configuration failed: {exc}",
                ) from exc
            model = config.model
            provider = config.provider.value

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
            "Select only one supplied eligible task and exactly one of its allowed_durations, "
            "or return NO_WORK only when must_gated is false AND none of the supplied eligible "
            "candidates should reasonably be recommended for work now based only on supplied "
            "ranking facts. Explain concisely why no supplied candidate is appropriate now; "
            "the NO_WORK reason must support not working, never describe why work would be "
            "appropriate. Do not choose NO_WORK merely because a task is FLEXIBLE, has "
            "UNSPECIFIED or COULD importance, lacks a deadline, or has no higher-priority "
            "constraint. If supplied facts support an ordinary feasible work session, choose "
            "RECOMMEND. Treat importance, schedule state, missed days, and deadline state as "
            "supplied ranking facts. Do not invent "
            "hard conflicts, rule evaluation, business hours, energy constraints, schedule "
            "facts, dependencies, or availability, and do not claim unknown facts. For RECOMMEND, "
            "produce one concise concrete action that is executable for the selected task within "
            "the selected duration. Ground the action only in the supplied task title and project "
            "facts. You may make a broad task executable with a generic work-session framing, "
            "but do not invent a specific subject, subtopic, resource, person, place, quantity, "
            "or project detail not supplied. For a task titled 'Study for ACT', 'Study for the "
            "ACT for 30 minutes' is grounded, but 'Review algebra practice problems for the "
            "ACT' invents an unsupported subtask. If the task title is already executable, "
            "preserve its action rather than adding invented specificity. The reason is a "
            "short ranking explanation, not a substitute for the action. For NO_WORK, action must be null."
        )
        try:
            response = client.responses.create(
                model=model,
                instructions=instructions,
                input=json.dumps(payload, separators=(",", ":")),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "personal_os_recommendation_v2",
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
                f"{provider} request failed: {exc}",
            ) from exc

        status = getattr(response, "status", None)
        if status in {"failed", "incomplete"}:
            raise RecommendationError(
                RecommendationFailureKind.PROVIDER_ERROR,
                f"{provider} response status was {status}",
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
                f"{provider} response contained no structured text",
            )
        try:
            decoded = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise RecommendationError(
                RecommendationFailureKind.INVALID_OUTPUT,
                f"{provider} response was malformed JSON",
            ) from exc
        if not isinstance(decoded, dict) or set(decoded) != {
            "kind", "task_id", "duration_minutes", "action", "reason"
        }:
            raise RecommendationError(
                RecommendationFailureKind.INVALID_OUTPUT,
                f"{provider} response did not match the recommendation contract",
            )
        try:
            kind = RecommendationChoiceKind(decoded["kind"])
        except (TypeError, ValueError) as exc:
            raise RecommendationError(
                RecommendationFailureKind.INVALID_OUTPUT,
                f"{provider} response contained an invalid choice kind",
            ) from exc
        return RecommendationChoice(
            kind,
            decoded["task_id"],
            decoded["duration_minutes"],
            decoded["action"],
            decoded["reason"],
        )

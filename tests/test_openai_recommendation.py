import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from personal_os.models import TaskImportance
from personal_os.openai_recommendation import OpenAIResponsesRecommendationRanker
from personal_os.recommendation_types import (
    AvailabilityKind, DeadlineState, EligibleTaskCandidate, RecommendationError,
    RecommendationFailureKind, RecommendationRankingContext, ScheduleState,
)


class Responses:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def setup(response):
    responses = Responses(response)
    return SimpleNamespace(responses=responses), responses


def candidate():
    return EligibleTaskCandidate(1, "Write", None, TaskImportance.SHOULD, ScheduleState.FLEXIBLE, None, DeadlineState.NONE, None, None, 20, (5, 10, 15, 20))


def test_adapter_uses_strict_responses_without_raw_temporal_context() -> None:
    response = SimpleNamespace(status="completed", output=[], output_text=json.dumps({
        "kind": "RECOMMEND", "task_id": 1, "duration_minutes": 10,
        "action": "Write the opening paragraph.", "reason": "Important",
    }))
    client, responses = setup(response)
    result = OpenAIResponsesRecommendationRanker(client=client, model="gpt-test").recommend(RecommendationRankingContext(AvailabilityKind.FINITE, 20, False), (candidate(),))
    assert result.task_id == 1
    assert result.action == "Write the opening paragraph."
    assert responses.kwargs["store"] is False
    assert responses.kwargs["text"]["format"]["strict"] is True
    schema = responses.kwargs["text"]["format"]["schema"]
    assert responses.kwargs["text"]["format"]["name"] == (
        "personal_os_recommendation_v2"
    )
    assert schema["properties"]["action"] == {"type": ["string", "null"]}
    assert "action" in schema["required"]
    instructions = responses.kwargs["instructions"].lower()
    assert "only one supplied eligible task" in instructions
    assert "exactly one of its allowed_durations" in instructions
    assert "one concise concrete action" in instructions
    assert "none of the supplied eligible candidates should reasonably be recommended" in instructions
    assert "explain concisely why no supplied candidate is appropriate now" in instructions
    assert "the no_work reason must support not working" in instructions
    assert "do not choose no_work merely because a task is flexible" in instructions
    assert "if supplied facts support an ordinary feasible work session, choose recommend" in instructions
    assert "do not invent a specific subject, subtopic, resource, person, place, quantity" in instructions
    assert "'study for act'" in instructions
    assert "'review algebra practice problems for the act' invents an unsupported subtask" in instructions
    assert "already executable" in instructions
    assert "do not claim unknown facts" in instructions
    assert "not a substitute for the action" in instructions
    payload = json.loads(responses.kwargs["input"])
    serialized = json.dumps(payload).lower()
    assert set(payload) == {"availability", "must_gated", "candidates"}
    assert "reference_time" not in serialized
    assert "timezone" not in serialized
    assert "daypart" not in serialized
    assert "rules" not in serialized
    assert payload["candidates"][0]["allowed_durations"] == [5, 10, 15, 20]


def test_flexible_study_task_can_return_generic_grounded_recommendation() -> None:
    study = replace(candidate(), title="Study for ACT", importance=TaskImportance.UNSPECIFIED)
    response = SimpleNamespace(status="completed", output=[], output_text=json.dumps({
        "kind": "RECOMMEND", "task_id": 1, "duration_minutes": 20,
        "action": "Study for the ACT for 20 minutes.",
        "reason": "This eligible task fits a focused session now.",
    }))
    client, responses = setup(response)

    choice = OpenAIResponsesRecommendationRanker(
        client=client, model="gpt-test"
    ).recommend(RecommendationRankingContext(AvailabilityKind.FINITE, 20, False), (study,))

    assert choice.kind.value == "RECOMMEND"
    assert choice.action == "Study for the ACT for 20 minutes."
    assert json.loads(responses.kwargs["input"])["candidates"][0]["title"] == "Study for ACT"
    assert "algebra" not in responses.kwargs["input"].lower()
    assert "review algebra practice problems" in responses.kwargs["instructions"].lower()


def test_valid_no_work_shape_remains_supported_without_must_gate() -> None:
    response = SimpleNamespace(status="completed", output=[], output_text=json.dumps({
        "kind": "NO_WORK", "task_id": None, "duration_minutes": None,
        "action": None, "reason": "None of these choices is useful now.",
    }))
    client, responses = setup(response)

    choice = OpenAIResponsesRecommendationRanker(
        client=client, model="gpt-test"
    ).recommend(RecommendationRankingContext(AvailabilityKind.FINITE, 20, False), (candidate(),))

    assert choice.kind.value == "NO_WORK"
    assert choice.action is None
    assert "only when must_gated is false and none" in responses.kwargs["instructions"].lower()


def test_adapter_configuration_is_lazy(monkeypatch) -> None:
    monkeypatch.delenv("PERSONAL_OS_RECOMMEND_PROVIDER", raising=False)
    monkeypatch.delenv("PERSONAL_OS_RECOMMEND_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RecommendationError) as error:
        OpenAIResponsesRecommendationRanker().recommend(RecommendationRankingContext(AvailabilityKind.NO_KNOWN_HARD_BOUND, None, False), (candidate(),))
    assert error.value.kind is RecommendationFailureKind.CONFIGURATION_ERROR


def test_openai_environment_builds_client_lazily(monkeypatch) -> None:
    response = SimpleNamespace(
        status="completed", output=[],
        output_text=json.dumps({
            "kind": "RECOMMEND", "task_id": 1,
            "duration_minutes": 10, "action": "Write one paragraph.",
            "reason": "Important",
        }),
    )
    fake, responses = setup(response)
    built = []

    def build(config):
        built.append(config)
        return fake

    monkeypatch.setenv("PERSONAL_OS_RECOMMEND_PROVIDER", "openai")
    monkeypatch.setenv("PERSONAL_OS_RECOMMEND_MODEL", "gpt-test")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "personal_os.openai_recommendation.build_responses_client", build
    )
    ranker = OpenAIResponsesRecommendationRanker()
    assert built == []

    result = ranker.recommend(
        RecommendationRankingContext(AvailabilityKind.FINITE, 20, False),
        (candidate(),),
    )

    assert result.task_id == 1
    assert built[0].provider.value == "openai"
    assert built[0].base_url is None
    assert responses.kwargs["model"] == "gpt-test"


@pytest.mark.parametrize("response,kind", [
    (RuntimeError("network"), RecommendationFailureKind.PROVIDER_ERROR),
    (SimpleNamespace(status="incomplete", output=[], output_text=""), RecommendationFailureKind.PROVIDER_ERROR),
    (SimpleNamespace(status="completed", output=[SimpleNamespace(content=[SimpleNamespace(refusal="no")])], output_text=""), RecommendationFailureKind.REFUSAL),
    (SimpleNamespace(status="completed", output=[], output_text="{"), RecommendationFailureKind.INVALID_OUTPUT),
    (SimpleNamespace(status="completed", output=[], output_text=json.dumps({"kind": "BAD", "task_id": None, "duration_minutes": None, "action": None, "reason": "x"})), RecommendationFailureKind.INVALID_OUTPUT),
])
def test_adapter_classifies_failures(response, kind) -> None:
    client, _ = setup(response)
    with pytest.raises(RecommendationError) as error:
        OpenAIResponsesRecommendationRanker(client=client, model="m").recommend(RecommendationRankingContext(AvailabilityKind.FINITE, 20, False), (candidate(),))
    assert error.value.kind is kind

import json
from types import SimpleNamespace

import pytest

from personal_os.capture import InterpretationError
from personal_os.models import CaptureFailureKind
from personal_os.openai_capture import OpenAIResponsesCaptureInterpreter


PAYLOAD = {"kind": "UNRESOLVED", "new_project": None, "tasks": [], "commitments": [], "unresolved_reason": "uncertain"}


class Responses:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def client(response):
    responses = Responses(response)
    return SimpleNamespace(responses=responses), responses


def interpret(adapter):
    return adapter.interpret("text", projects=[])


def test_adapter_uses_responses_strict_schema_and_disables_storage() -> None:
    fake, responses = client(SimpleNamespace(id="resp_1", model="gpt-test", status="completed", output=[], output_text=json.dumps(PAYLOAD)))
    result = interpret(OpenAIResponsesCaptureInterpreter(client=fake, model="gpt-test"))
    assert result.interpretation.to_dict() == PAYLOAD
    assert result.response_id == "resp_1"
    assert responses.kwargs["model"] == "gpt-test"
    assert responses.kwargs["store"] is False
    assert responses.kwargs["text"]["format"]["type"] == "json_schema"
    assert responses.kwargs["text"]["format"]["strict"] is True
    assert set(json.loads(responses.kwargs["input"])) == {"raw_text", "active_projects"}
    commitment = responses.kwargs["text"]["format"]["schema"]["properties"]["commitments"]["items"]
    assert "end" not in commitment["properties"]


def test_adapter_configuration_is_lazy_and_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PERSONAL_OS_CAPTURE_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    adapter = OpenAIResponsesCaptureInterpreter()
    with pytest.raises(InterpretationError) as error:
        interpret(adapter)
    assert error.value.kind is CaptureFailureKind.CONFIGURATION_ERROR


@pytest.mark.parametrize("response", [RuntimeError("network"), SimpleNamespace(id="x", model="m", status="incomplete", output=[], output_text="")])
def test_adapter_provider_failures_are_classified(response) -> None:
    fake, _ = client(response)
    with pytest.raises(InterpretationError) as error:
        interpret(OpenAIResponsesCaptureInterpreter(client=fake, model="m"))
    assert error.value.kind is CaptureFailureKind.PROVIDER_ERROR


def test_adapter_refusal_and_malformed_output_are_classified() -> None:
    refusal = SimpleNamespace(id="x", model="m", status="completed", output=[SimpleNamespace(content=[SimpleNamespace(refusal="no")])], output_text="")
    fake, _ = client(refusal)
    with pytest.raises(InterpretationError) as error:
        interpret(OpenAIResponsesCaptureInterpreter(client=fake, model="m"))
    assert error.value.kind is CaptureFailureKind.REFUSAL
    malformed, _ = client(SimpleNamespace(id="x", model="m", status="completed", output=[], output_text="{"))
    with pytest.raises(InterpretationError) as error:
        interpret(OpenAIResponsesCaptureInterpreter(client=malformed, model="m"))
    assert error.value.kind is CaptureFailureKind.INVALID_OUTPUT

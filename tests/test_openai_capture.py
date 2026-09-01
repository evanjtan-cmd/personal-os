import json
from types import SimpleNamespace

import pytest

from personal_os.capture import InterpretationError
from personal_os.capture_types import InterpretationValidationError, parse_interpretation
from personal_os.models import CaptureFailureKind
from personal_os.openai_capture import (
    CAPTURE_SCHEMA,
    OpenAIResponsesCaptureInterpreter,
    _normalize_capture_wire_payload,
    _nullable,
)


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
    assert "never infer" in responses.kwargs["instructions"].lower()
    assert "commitment hardness" in responses.kwargs["instructions"].lower()
    assert "use unknown" in responses.kwargs["instructions"].lower()
    assert "if kind is apply" in responses.kwargs["instructions"].lower()
    assert "unresolved_reason as null" in responses.kwargs["instructions"].lower()
    assert "if kind is unresolved" in responses.kwargs["instructions"].lower()
    assert "non-empty explanation" in responses.kwargs["instructions"].lower()
    assert "never use an empty string" in responses.kwargs["instructions"].lower()
    assert "existing integer id only" in responses.kwargs["instructions"].lower()
    assert "use new only when new_project is non-null" in responses.kwargs["instructions"].lower()
    assert "otherwise use project_id null" in responses.kwargs["instructions"].lower()
    assert "must not invent a project" in responses.kwargs["instructions"].lower()
    instructions = responses.kwargs["instructions"].lower()
    assert "ordinary actionable tasks do not require scheduling information" in instructions
    assert "use schedule null; this means flexible, not unresolved" in instructions
    assert "no deadline is explicit, use deadline null" in instructions
    assert "no importance is explicit, use unspecified" in instructions
    assert "no duration is explicit, use estimated_minutes null" in instructions
    assert "no project relationship is explicit, use project_id null" in instructions
    assert "do not return unresolved solely because" in instructions
    assert "preserve explicit temporal facts" in instructions
    assert "retains a day friday schedule without inventing a clock time" in instructions
    assert "genuinely ambiguous, missing, or unsupported fact" in instructions
    assert "meet sam at 4 is unresolved" in instructions
    assert "never invent a date, time, deadline" in instructions
    commitment = responses.kwargs["text"]["format"]["schema"]["properties"]["commitments"]["items"]
    assert "end" not in commitment["properties"]


def _applied_task_payload(reason: object) -> dict:
    return {
        "kind": "APPLY", "new_project": None,
        "tasks": [{
            "title": "Buy milk", "project_id": None,
            "importance": "UNSPECIFIED", "estimated_minutes": None,
            "schedule": None, "deadline": None,
        }],
        "commitments": [], "unresolved_reason": reason,
    }


def _adapter_for_payload(payload: dict, *, provider: str = "openai"):
    fake, _ = client(SimpleNamespace(
        id="response-1", model="model-1", status="completed", output=[],
        output_text=json.dumps(payload),
    ))
    return OpenAIResponsesCaptureInterpreter(
        client=fake, model="model-1", provider=provider
    )


def test_apply_with_null_reason_parses_normally() -> None:
    result = interpret(_adapter_for_payload(_applied_task_payload(None)))
    assert result.interpretation.unresolved_reason is None


def test_apply_empty_reason_is_normalized_only_at_wire_boundary() -> None:
    result = interpret(_adapter_for_payload(_applied_task_payload(""), provider="groq"))
    assert result.interpretation.unresolved_reason is None
    assert result.interpretation.to_dict()["unresolved_reason"] is None


def test_unresolved_nonempty_reason_parses_normally() -> None:
    result = interpret(_adapter_for_payload(PAYLOAD, provider="groq"))
    assert result.interpretation.unresolved_reason == "uncertain"


def test_unresolved_empty_reason_still_fails_closed() -> None:
    payload = {**PAYLOAD, "unresolved_reason": ""}
    with pytest.raises(InterpretationError) as error:
        interpret(_adapter_for_payload(payload, provider="groq"))
    assert error.value.kind is CaptureFailureKind.INVALID_OUTPUT
    assert "non-empty" in str(error.value)


def test_arbitrary_empty_text_is_not_normalized() -> None:
    payload = _applied_task_payload("")
    payload["tasks"][0]["title"] = ""
    with pytest.raises(InterpretationError) as error:
        interpret(_adapter_for_payload(payload, provider="groq"))
    assert error.value.kind is CaptureFailureKind.INVALID_OUTPUT
    assert "task title" in str(error.value)


def test_canonical_parser_semantics_remain_strict_without_wire_normalization() -> None:
    with pytest.raises(
        InterpretationValidationError,
        match="applied interpretation cannot contain an unresolved reason",
    ):
        parse_interpretation(_applied_task_payload(""))
    with pytest.raises(InterpretationValidationError, match="non-empty"):
        parse_interpretation({**PAYLOAD, "unresolved_reason": ""})


def test_wire_normalization_is_exact_and_does_not_trim_or_discard_values() -> None:
    whitespace = _applied_task_payload("   ")
    nonempty = _applied_task_payload("unexpected")
    unresolved = {**PAYLOAD, "unresolved_reason": ""}
    assert _normalize_capture_wire_payload(whitespace) is whitespace
    assert _normalize_capture_wire_payload(nonempty) is nonempty
    assert _normalize_capture_wire_payload(unresolved) is unresolved


def test_capture_schema_contains_no_nested_any_of() -> None:
    nested_paths = []

    def walk(value, path: str = "$", *, inside_any_of: bool = False) -> None:
        if isinstance(value, dict):
            has_any_of = "anyOf" in value
            if has_any_of and inside_any_of:
                nested_paths.append(path)
            for key, child in value.items():
                walk(
                    child,
                    f"{path}/{key}",
                    inside_any_of=inside_any_of or has_any_of,
                )
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}/{index}", inside_any_of=inside_any_of)

    walk(CAPTURE_SCHEMA)
    assert nested_paths == []


def test_nullable_flattens_union_and_uses_type_union_when_possible() -> None:
    assert _nullable({"type": "string"}) == {"type": ["string", "null"]}
    assert _nullable({"anyOf": [{"type": "string"}, {"type": "integer"}]}) == {
        "anyOf": [
            {"type": "string"},
            {"type": "integer"},
            {"type": "null"},
        ]
    }


def test_capture_schema_preserves_date_project_clock_and_deadline_alternatives() -> None:
    task = CAPTURE_SCHEMA["properties"]["tasks"]["items"]
    properties = task["properties"]
    date_value = (
        properties["schedule"]["properties"]["dates"]["items"]
        ["properties"]["value"]
    )
    assert date_value == {
        "type": ["string", "integer", "null"],
        "minimum": 1,
        "maximum": 7,
    }
    assert properties["schedule"]["type"] == ["object", "null"]
    assert properties["deadline"]["type"] == ["object", "null"]
    assert properties["project_id"] == {
        "type": ["integer", "string", "null"]
    }

    deadline_variants = properties["deadline"]["properties"]["value"]["anyOf"]
    assert deadline_variants[0]["properties"]["kind"]["enum"] == [
        "TODAY", "TOMORROW", "WEEKDAY", "NEXT_WEEKDAY",
        "EXPLICIT_DATE", "MISSING_YEAR",
    ]
    assert len(deadline_variants) == 2
    instant = deadline_variants[1]
    assert set(instant["properties"]) == {"date", "clock"}
    clock = instant["properties"]["clock"]
    assert clock["properties"]["kind"]["enum"] == [
        "CLOCK_12", "CLOCK_24", "BARE_HOUR"
    ]
    assert clock["properties"]["hour"] == {
        "type": "integer", "minimum": 0, "maximum": 23
    }
    assert clock["properties"]["period"] == {
        "type": ["string", "null"], "enum": ["AM", "PM", None]
    }
    assert clock["required"] == ["kind", "hour", "minute", "period"]


def test_capture_schema_has_no_ambiguous_object_any_of_variants() -> None:
    ambiguous = []

    def walk(value, path: str = "$") -> None:
        if isinstance(value, dict):
            variants = value.get("anyOf")
            if isinstance(variants, list):
                objects = [
                    variant for variant in variants
                    if isinstance(variant, dict) and variant.get("type") == "object"
                ]
                for index, left in enumerate(objects):
                    for right in objects[index + 1:]:
                        left_keys = set(left.get("properties", {}))
                        right_keys = set(right.get("properties", {}))
                        if left_keys & right_keys:
                            ambiguous.append(path)
            for key, child in value.items():
                walk(child, f"{path}/{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}/{index}")

    walk(CAPTURE_SCHEMA)
    assert ambiguous == []


def test_only_remaining_any_of_is_structurally_distinct_deadline_union() -> None:
    unions = []

    def walk(value, path: str = "$") -> None:
        if isinstance(value, dict):
            if "anyOf" in value:
                unions.append((path, value["anyOf"]))
            for key, child in value.items():
                walk(child, f"{path}/{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}/{index}")

    walk(CAPTURE_SCHEMA)
    assert [path for path, _variants in unions] == [
        "$/properties/tasks/items/properties/deadline/properties/value"
    ]
    variants = unions[0][1]
    assert [set(variant["properties"]) for variant in variants] == [
        {"kind", "value"}, {"date", "clock"}
    ]
    assert all(variant["type"] == "object" for variant in variants)


@pytest.mark.parametrize("project_id", [7, "NEW", None])
def test_canonical_parser_accepts_int_new_and_null_project_references(
    project_id: int | str | None,
) -> None:
    payload = _applied_task_payload(None)
    payload["tasks"][0]["project_id"] = project_id
    if project_id == "NEW":
        payload["new_project"] = {"name": "Errands", "description": None}
    parsed = parse_interpretation(payload)
    assert parsed.to_dict()["tasks"][0]["project_id"] == project_id


def test_canonical_parser_rejects_other_project_reference_strings() -> None:
    payload = _applied_task_payload(None)
    payload["tasks"][0]["project_id"] = "Errands"
    with pytest.raises(InterpretationValidationError, match="project reference"):
        parse_interpretation(payload)


@pytest.mark.parametrize("kind", ["CLOCK_24", "BARE_HOUR"])
def test_typed_parser_accepts_nullable_period_wire_shape_without_changing_canonical_payload(
    kind: str,
) -> None:
    payload = {
        "kind": "APPLY", "new_project": None, "tasks": [],
        "commitments": [{
            "title": "Call", "hardness": "UNKNOWN",
            "start": {
                "date": {"kind": "TOMORROW", "value": None},
                "clock": {"kind": kind, "hour": 16, "minute": 0, "period": None},
            },
        }],
        "unresolved_reason": None,
    }
    parsed = parse_interpretation(payload)
    assert parsed.to_dict()["commitments"][0]["start"]["clock"] == {
        "kind": kind, "hour": 16, "minute": 0
    }


@pytest.mark.parametrize(
    "clock",
    [
        {"kind": "CLOCK_12", "hour": 0, "minute": 0, "period": "AM"},
        {"kind": "CLOCK_12", "hour": 13, "minute": 0, "period": "PM"},
        {"kind": "CLOCK_12", "hour": 4, "minute": 0, "period": None},
        {"kind": "CLOCK_24", "hour": 16, "minute": 0, "period": "PM"},
        {"kind": "BARE_HOUR", "hour": 4, "minute": 0, "period": "AM"},
    ],
)
def test_typed_parser_rejects_illegal_unified_clock_combinations(clock: dict) -> None:
    payload = {
        "kind": "APPLY", "new_project": None, "tasks": [],
        "commitments": [{
            "title": "Call", "hardness": "UNKNOWN",
            "start": {
                "date": {"kind": "TOMORROW", "value": None},
                "clock": clock,
            },
        }],
        "unresolved_reason": None,
    }
    with pytest.raises(InterpretationValidationError, match="clock"):
        parse_interpretation(payload)


def test_groq_provider_metadata_is_not_relabelled_as_openai() -> None:
    fake, _ = client(SimpleNamespace(
        id="groq-response", model="openai/gpt-oss-20b", status="completed",
        output=[], output_text=json.dumps(PAYLOAD),
    ))
    result = interpret(OpenAIResponsesCaptureInterpreter(
        client=fake, model="openai/gpt-oss-20b", provider="groq"
    ))
    assert result.provider == "groq"
    assert result.model == "openai/gpt-oss-20b"
    assert result.response_id == "groq-response"


def test_adapter_configuration_is_lazy_and_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PERSONAL_OS_CAPTURE_PROVIDER", raising=False)
    monkeypatch.delenv("PERSONAL_OS_CAPTURE_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    adapter = OpenAIResponsesCaptureInterpreter()
    with pytest.raises(InterpretationError) as error:
        interpret(adapter)
    assert error.value.kind is CaptureFailureKind.CONFIGURATION_ERROR


def test_groq_environment_builds_client_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, responses = client(SimpleNamespace(
        id="groq-response", model="openai/gpt-oss-120b", status="completed",
        output=[], output_text=json.dumps(PAYLOAD),
    ))
    built = []

    def build(config):
        built.append(config)
        return fake

    monkeypatch.setenv("PERSONAL_OS_CAPTURE_PROVIDER", "groq")
    monkeypatch.setenv("PERSONAL_OS_CAPTURE_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr("personal_os.openai_capture.build_responses_client", build)
    adapter = OpenAIResponsesCaptureInterpreter()
    assert built == []

    result = interpret(adapter)

    assert built[0].provider.value == "groq"
    assert built[0].base_url == "https://api.groq.com/openai/v1"
    assert responses.kwargs["model"] == "openai/gpt-oss-120b"
    assert result.provider == "groq"


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

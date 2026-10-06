import json
from types import SimpleNamespace

import pytest

from personal_os.capture import InterpretationError
from personal_os.capture_types import InterpretationValidationError, parse_interpretation
from personal_os.models import CaptureFailureKind
from personal_os.openai_capture import (
    CAPTURE_SCHEMA,
    OpenAIResponsesCaptureInterpreter,
    _normalize_clock_wire,
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
    assert "classify execution_mode as splittable" in instructions
    assert "classify execution_mode as one_sitting" in instructions
    assert "one_sitting with unknown duration is valid persisted state" in instructions
    assert "do not use world knowledge to guess durations" in instructions
    assert "no project relationship is explicit, use project_id null" in instructions
    assert "do not return unresolved solely because" in instructions
    assert "preserve an explicitly supplied temporal fact" in instructions
    assert "rather than dropping it because other optional fields are absent" in instructions
    assert "do not invent an exact clock time or deadline semantics" in instructions
    assert "do not discard scheduling or deadline semantics" in instructions
    assert "genuinely ambiguous, missing, or unsupported fact" in instructions
    assert "meet sam at 4 is unresolved" in instructions
    assert "never invent a date, time, deadline" in instructions
    assert "copy only the explicit clock wording" in instructions
    assert "do not add am/pm" in instructions
    assert "convert notation" in instructions
    commitment = responses.kwargs["text"]["format"]["schema"]["properties"]["commitments"]["items"]
    assert "end" not in commitment["properties"]


def _applied_task_payload(reason: object) -> dict:
    return {
        "kind": "APPLY", "new_project": None,
        "tasks": [{
            "title": "Buy milk", "project_id": None,
            "importance": "UNSPECIFIED", "estimated_minutes": None,
            "execution_mode": "SPLITTABLE",
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


def wire_date(kind: str, *, weekday: str | None = None, date: str | None = None, text: str | None = None) -> dict:
    return {"kind": kind, "weekday": weekday, "date": date, "text": text}


def wire_clock(text: str) -> dict:
    return {"text": text}


def wire_deadline(kind: str, day: dict, clock: dict | None = None) -> dict:
    return {"kind": kind, "date": day, "clock": clock}


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
    assert _normalize_capture_wire_payload(whitespace)["unresolved_reason"] == "   "
    assert _normalize_capture_wire_payload(nonempty)["unresolved_reason"] == "unexpected"
    assert _normalize_capture_wire_payload(unresolved)["unresolved_reason"] == ""


def test_capture_schema_contains_no_any_of() -> None:
    paths = []

    def walk(value, path: str = "$") -> None:
        if isinstance(value, dict):
            if "anyOf" in value:
                paths.append(path)
            for key, child in value.items():
                walk(child, f"{path}/{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}/{index}")

    walk(CAPTURE_SCHEMA)
    assert paths == []


def test_nullable_flattens_union_and_uses_type_union_when_possible() -> None:
    assert _nullable({"type": "string"}) == {"type": ["string", "null"]}
    assert _nullable({"anyOf": [{"type": "string"}, {"type": "integer"}]}) == {
        "anyOf": [
            {"type": "string"},
            {"type": "integer"},
            {"type": "null"},
        ]
    }


def test_capture_schema_preserves_fixed_date_project_clock_and_deadline_wire_shapes() -> None:
    task = CAPTURE_SCHEMA["properties"]["tasks"]["items"]
    properties = task["properties"]
    assert properties["execution_mode"] == {
        "type": "string",
        "enum": ["SPLITTABLE", "ONE_SITTING"],
    }
    date_wire = (
        properties["schedule"]["properties"]["dates"]["items"]
        ["properties"]
    )
    assert set(date_wire) == {"kind", "weekday", "date", "text"}
    assert date_wire["kind"]["enum"] == [
        "TODAY", "TOMORROW", "WEEKDAY", "NEXT_WEEKDAY",
        "EXPLICIT_DATE", "MISSING_YEAR",
    ]
    assert date_wire["weekday"]["enum"] == [
        "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY",
        "FRIDAY", "SATURDAY", "SUNDAY", None,
    ]
    assert properties["schedule"]["type"] == ["object", "null"]
    assert properties["deadline"]["type"] == ["object", "null"]
    assert properties["project_id"] == {
        "type": ["integer", "string", "null"]
    }

    deadline = properties["deadline"]
    assert set(deadline["properties"]) == {"kind", "date", "clock"}
    assert deadline["properties"]["kind"]["enum"] == ["DATE", "INSTANT"]
    assert set(deadline["properties"]["date"]["properties"]) == {
        "kind", "weekday", "date", "text",
    }
    clock = deadline["properties"]["clock"]
    assert clock["type"] == ["object", "null"]
    assert set(clock["properties"]) == {"text"}
    assert clock["properties"]["text"] == {"type": "string"}
    assert clock["required"] == ["text"]


def test_capture_schema_no_longer_exposes_canonical_clock_choices() -> None:
    schema_text = json.dumps(CAPTURE_SCHEMA)
    assert "CLOCK_12" not in schema_text
    assert "CLOCK_24" not in schema_text
    assert "BARE_HOUR" not in schema_text


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


def test_weekday_name_wire_converts_to_canonical_iso_weekday() -> None:
    payload = _applied_task_payload(None)
    payload["tasks"][0]["schedule"] = {
        "kind": "DAY",
        "dates": [wire_date("WEEKDAY", weekday="WEDNESDAY")],
    }

    result = interpret(_adapter_for_payload(payload, provider="groq"))

    assert result.interpretation.to_dict()["tasks"][0]["schedule"] == {
        "kind": "DAY",
        "dates": [{"kind": "WEEKDAY", "value": 3}],
    }


@pytest.mark.parametrize(
    "raw_text",
    ["bio homework due Wednesday", "Finish chinese by Wednesday"],
)
def test_weekday_deadline_wire_for_ordinary_task_phrasing(raw_text: str) -> None:
    payload = _applied_task_payload(None)
    payload["tasks"][0]["title"] = raw_text.split(" due ")[0].removesuffix(" by Wednesday")
    payload["tasks"][0]["deadline"] = wire_deadline(
        "DATE", wire_date("WEEKDAY", weekday="WEDNESDAY")
    )

    result = _adapter_for_payload(payload, provider="groq").interpret(raw_text, projects=[])

    assert result.interpretation.to_dict()["tasks"][0]["deadline"] == {
        "kind": "DATE",
        "value": {"kind": "WEEKDAY", "value": 3},
    }


def test_tomorrow_deadline_wire_converts_to_canonical_date_expression() -> None:
    payload = _applied_task_payload(None)
    payload["tasks"][0]["title"] = "Finish essay"
    payload["tasks"][0]["deadline"] = wire_deadline(
        "DATE", wire_date("TOMORROW")
    )

    result = interpret(_adapter_for_payload(payload, provider="groq"))

    assert result.interpretation.to_dict()["tasks"][0]["deadline"] == {
        "kind": "DATE",
        "value": {"kind": "TOMORROW", "value": None},
    }


def test_instant_deadline_wire_converts_to_canonical_instant_expression() -> None:
    payload = _applied_task_payload(None)
    payload["tasks"][0]["deadline"] = wire_deadline(
        "INSTANT",
        wire_date("TOMORROW"),
        wire_clock("4 PM"),
    )

    result = interpret(_adapter_for_payload(payload, provider="groq"))

    assert result.interpretation.to_dict()["tasks"][0]["deadline"] == {
        "kind": "INSTANT",
        "value": {
            "date": {"kind": "TOMORROW", "value": None},
            "clock": {"kind": "CLOCK_12", "hour": 4, "minute": 0, "period": "PM"},
        },
    }


@pytest.mark.parametrize(
    "deadline",
    [
        wire_deadline("DATE", wire_date("TOMORROW"), wire_clock("4 PM")),
        wire_deadline("INSTANT", wire_date("TOMORROW"), None),
        wire_deadline("DATE", wire_date("WEEKDAY", weekday="Wednesday"), None),
        wire_deadline("DATE", wire_date("WEEKDAY", weekday="WEDNESDAY", date="2026-09-02"), None),
        wire_deadline("INSTANT", wire_date("TOMORROW"), {"kind": "CLOCK_12", "hour": 4, "minute": 0, "period": None}),
        wire_deadline("INSTANT", wire_date("TOMORROW"), wire_clock("quarter to four")),
    ],
)
def test_malformed_temporal_wire_combinations_fail_closed(deadline: dict) -> None:
    payload = _applied_task_payload(None)
    payload["tasks"][0]["deadline"] = deadline

    with pytest.raises(InterpretationError) as error:
        interpret(_adapter_for_payload(payload, provider="groq"))

    assert error.value.kind is CaptureFailureKind.INVALID_OUTPUT


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3", {"kind": "BARE_HOUR", "hour": 3, "minute": 0}),
        ("3:45", {"kind": "BARE_HOUR", "hour": 3, "minute": 45}),
        ("10:30", {"kind": "BARE_HOUR", "hour": 10, "minute": 30}),
        ("12:45", {"kind": "BARE_HOUR", "hour": 12, "minute": 45}),
        ("3 PM", {"kind": "CLOCK_12", "hour": 3, "minute": 0, "period": "PM"}),
        ("3:45 PM", {"kind": "CLOCK_12", "hour": 3, "minute": 45, "period": "PM"}),
        (" 3 : 45 pm ", {"kind": "CLOCK_12", "hour": 3, "minute": 45, "period": "PM"}),
        ("3am", {"kind": "CLOCK_12", "hour": 3, "minute": 0, "period": "AM"}),
        ("15:45", {"kind": "CLOCK_24", "hour": 15, "minute": 45}),
        ("03:45", {"kind": "CLOCK_24", "hour": 3, "minute": 45}),
        ("09:30", {"kind": "CLOCK_24", "hour": 9, "minute": 30}),
        ("00:30", {"kind": "CLOCK_24", "hour": 0, "minute": 30}),
    ],
)
def test_clock_wire_text_normalizes_to_canonical_clock(text: str, expected: dict) -> None:
    assert _normalize_clock_wire(wire_clock(text)) == expected


def test_ambiguous_clock_wire_text_does_not_infer_am_pm() -> None:
    assert _normalize_clock_wire(wire_clock("3:45")) == {
        "kind": "BARE_HOUR",
        "hour": 3,
        "minute": 45,
    }


@pytest.mark.parametrize(
    "text",
    ["", "   ", "noon", "quarter to four", "3:7", "3:75", "24:00", "13 PM", "0"],
)
def test_unsupported_clock_wire_text_fails_closed(text: str) -> None:
    with pytest.raises(InterpretationValidationError, match="clock"):
        _normalize_clock_wire(wire_clock(text))


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

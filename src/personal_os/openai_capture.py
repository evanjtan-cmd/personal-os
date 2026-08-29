"""Single production OpenAI Responses API adapter for capture interpretation."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from personal_os.capture import InterpretationError, InterpretationResponse
from personal_os.models import CaptureFailureKind, serialize_instant


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


DATE_IR = {
    "type": "object", "additionalProperties": False,
    "properties": {"kind": {"type": "string", "enum": ["TODAY", "TOMORROW", "WEEKDAY", "NEXT_WEEKDAY", "EXPLICIT_DATE", "MISSING_YEAR"]}, "value": _nullable({"anyOf": [{"type": "string"}, {"type": "integer", "minimum": 1, "maximum": 7}]})},
    "required": ["kind", "value"],
}
def _clock_schema(kind: str, *, twelve_hour: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "kind": {"type": "string", "enum": [kind]},
        "hour": {"type": "integer", "minimum": 1 if twelve_hour else 0, "maximum": 12 if twelve_hour else 23},
        "minute": {"type": "integer", "minimum": 0, "maximum": 59},
    }
    if twelve_hour:
        properties["period"] = {"type": "string", "enum": ["AM", "PM"]}
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)}


CLOCK_IR = {"anyOf": [_clock_schema("CLOCK_12", twelve_hour=True), _clock_schema("CLOCK_24", twelve_hour=False), _clock_schema("BARE_HOUR", twelve_hour=False)]}
INSTANT_IR = {"type": "object", "additionalProperties": False, "properties": {"date": DATE_IR, "clock": CLOCK_IR}, "required": ["date", "clock"]}
CAPTURE_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "kind": {"type": "string", "enum": ["APPLY", "UNRESOLVED"]},
        "new_project": _nullable({"type": "object", "additionalProperties": False, "properties": {"name": {"type": "string"}, "description": _nullable({"type": "string"})}, "required": ["name", "description"]}),
        "tasks": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
            "title": {"type": "string"}, "project_id": _nullable({"anyOf": [{"type": "integer"}, {"type": "string", "enum": ["NEW"]}]}),
            "importance": {"type": "string", "enum": ["UNSPECIFIED", "MUST", "SHOULD", "COULD"]},
            "estimated_minutes": _nullable({"type": "integer", "minimum": 1}),
            "schedule": _nullable({"type": "object", "additionalProperties": False, "properties": {"kind": {"type": "string", "enum": ["DAY", "THIS_WEEKEND"]}, "value": _nullable(DATE_IR)}, "required": ["kind", "value"]}),
            "deadline": _nullable({"type": "object", "additionalProperties": False, "properties": {"kind": {"type": "string", "enum": ["DATE", "INSTANT"]}, "value": {"anyOf": [DATE_IR, INSTANT_IR]}}, "required": ["kind", "value"]}),
        }, "required": ["title", "project_id", "importance", "estimated_minutes", "schedule", "deadline"]}},
        "commitments": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"title": {"type": "string"}, "start": INSTANT_IR, "end": _nullable(INSTANT_IR), "hardness": {"type": "string", "enum": ["UNKNOWN", "HARD", "SOFT"]}}, "required": ["title", "start", "end", "hardness"]}},
        "unresolved_reason": _nullable({"type": "string"}),
    },
    "required": ["kind", "new_project", "tasks", "commitments", "unresolved_reason"],
}


class OpenAIResponsesCaptureInterpreter:
    """Interpret capture text through a lazily constructed OpenAI 3.x client."""

    def __init__(self, *, client: object | None = None, model: str | None = None) -> None:
        self._client = client
        self._model = model

    def interpret(self, raw_text: str, *, projects: list[dict[str, object]], reference_time: datetime, timezone_name: str) -> InterpretationResponse:
        model = self._model or os.environ.get("PERSONAL_OS_CAPTURE_MODEL")
        if not model:
            raise InterpretationError(CaptureFailureKind.CONFIGURATION_ERROR, "PERSONAL_OS_CAPTURE_MODEL is not configured")
        client = self._client
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise InterpretationError(CaptureFailureKind.CONFIGURATION_ERROR, "OPENAI_API_KEY is not configured")
            try:
                from openai import OpenAI
                client = OpenAI()
            except Exception as exc:
                raise InterpretationError(CaptureFailureKind.CONFIGURATION_ERROR, f"OpenAI client configuration failed: {exc}") from exc
        prompt = {
            "raw_text": raw_text, "reference_time_utc": serialize_instant(reference_time),
            "timezone_name": timezone_name, "active_projects": projects,
        }
        instructions = (
            "Extract only explicit Personal OS capture semantics. Never infer AM/PM, a missing year, "
            "importance, duration, project identity, or recurrence. Use BARE_HOUR for a bare clock hour, "
            "MISSING_YEAR for a date without a year, and UNRESOLVED for unsupported or uncertain meaning."
        )
        try:
            response = client.responses.create(
                model=model, instructions=instructions, input=json.dumps(prompt, separators=(",", ":")),
                text={"format": {"type": "json_schema", "name": "personal_os_capture_v1", "strict": True, "schema": CAPTURE_SCHEMA}},
                store=False,
            )
        except InterpretationError:
            raise
        except Exception as exc:
            raise InterpretationError(CaptureFailureKind.PROVIDER_ERROR, f"OpenAI request failed: {exc}") from exc
        response_id = getattr(response, "id", None)
        response_model = getattr(response, "model", None) or model
        if getattr(response, "status", None) in {"failed", "incomplete"}:
            raise InterpretationError(CaptureFailureKind.PROVIDER_ERROR, f"OpenAI response status was {response.status}", provider="openai", model=str(response_model), response_id=None if response_id is None else str(response_id))
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                refusal = getattr(content, "refusal", None)
                if refusal:
                    raise InterpretationError(CaptureFailureKind.REFUSAL, str(refusal), provider="openai", model=str(response_model), response_id=None if response_id is None else str(response_id))
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text:
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "OpenAI response contained no structured text", provider="openai", model=str(response_model), response_id=None if response_id is None else str(response_id))
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "OpenAI response was malformed JSON", provider="openai", model=str(response_model), response_id=None if response_id is None else str(response_id)) from exc
        if not isinstance(payload, dict):
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, "OpenAI response was not a JSON object", provider="openai", model=str(response_model), response_id=None if response_id is None else str(response_id))
        return InterpretationResponse(payload, "openai", str(response_model), None if response_id is None else str(response_id))

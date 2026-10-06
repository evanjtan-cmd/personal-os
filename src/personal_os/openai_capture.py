"""Strict Responses API adapter for capture interpretation."""

from __future__ import annotations

import json
from typing import Any

from personal_os.ai_provider import (
    InferenceProvider,
    build_responses_client,
    resolve_capture_provider,
)
from personal_os.capture import InterpretationError
from personal_os.capture_types import InterpretationResponse, InterpretationValidationError, parse_interpretation
from personal_os.config import ConfigurationError
from personal_os.models import CaptureFailureKind


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """Add null without nesting a union inside another union."""

    if set(schema) == {"anyOf"}:
        return {"anyOf": [*schema["anyOf"], {"type": "null"}]}
    if isinstance(schema.get("type"), str):
        return {**schema, "type": [schema["type"], "null"]}
    raise ValueError("nullable schema must have a type or direct anyOf union")


WEEKDAY_TO_ISO = {
    "MONDAY": 1,
    "TUESDAY": 2,
    "WEDNESDAY": 3,
    "THURSDAY": 4,
    "FRIDAY": 5,
    "SATURDAY": 6,
    "SUNDAY": 7,
}
DATE_IR = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {
            "type": "string",
            "enum": [
                "TODAY", "TOMORROW", "WEEKDAY", "NEXT_WEEKDAY",
                "EXPLICIT_DATE", "MISSING_YEAR",
            ],
        },
        "weekday": {
            "type": ["string", "null"],
            "enum": [*WEEKDAY_TO_ISO, None],
        },
        "date": {"type": ["string", "null"]},
        "text": {"type": ["string", "null"]},
    },
    "required": ["kind", "weekday", "date", "text"],
}
CLOCK_IR = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["CLOCK_12", "CLOCK_24", "BARE_HOUR"],
        },
        "hour": {"type": "integer", "minimum": 0, "maximum": 23},
        "minute": {"type": "integer", "minimum": 0, "maximum": 59},
        "period": {"type": ["string", "null"], "enum": ["AM", "PM", None]},
    },
    "required": ["kind", "hour", "minute", "period"],
}
INSTANT_IR = {"type": "object", "additionalProperties": False, "properties": {"date": DATE_IR, "clock": CLOCK_IR}, "required": ["date", "clock"]}
DEADLINE_IR = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {"type": "string", "enum": ["DATE", "INSTANT"]},
        "date": DATE_IR,
        "clock": _nullable(CLOCK_IR),
    },
    "required": ["kind", "date", "clock"],
}
CAPTURE_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "kind": {"type": "string", "enum": ["APPLY", "UNRESOLVED"]},
        "new_project": _nullable({"type": "object", "additionalProperties": False, "properties": {"name": {"type": "string"}, "description": _nullable({"type": "string"})}, "required": ["name", "description"]}),
        "tasks": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
            "title": {"type": "string"}, "project_id": {"type": ["integer", "string", "null"]},
            "importance": {"type": "string", "enum": ["UNSPECIFIED", "MUST", "SHOULD", "COULD"]},
            "estimated_minutes": _nullable({"type": "integer", "minimum": 1}),
            "execution_mode": {"type": "string", "enum": ["SPLITTABLE", "ONE_SITTING"]},
            "schedule": _nullable({"type": "object", "additionalProperties": False, "properties": {"kind": {"type": "string", "enum": ["DAY", "THIS_WEEKEND"]}, "dates": {"type": "array", "items": DATE_IR}}, "required": ["kind", "dates"]}),
            "deadline": _nullable(DEADLINE_IR),
        }, "required": ["title", "project_id", "importance", "estimated_minutes", "execution_mode", "schedule", "deadline"]}},
        "commitments": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"title": {"type": "string"}, "start": INSTANT_IR, "hardness": {"type": "string", "enum": ["UNKNOWN", "HARD", "SOFT"]}}, "required": ["title", "start", "hardness"]}},
        "unresolved_reason": _nullable({"type": "string"}),
    },
    "required": ["kind", "new_project", "tasks", "commitments", "unresolved_reason"],
}


def _wire_object(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise InterpretationValidationError(f"{label} has an invalid wire shape")
    return value


def _normalize_date_wire(value: object) -> dict[str, Any]:
    data = _wire_object(value, {"kind", "weekday", "date", "text"}, "date expression")
    kind = data["kind"]
    weekday, date, text = data["weekday"], data["date"], data["text"]
    if kind in {"TODAY", "TOMORROW"}:
        if weekday is not None or date is not None or text is not None:
            raise InterpretationValidationError("relative date wire fields must be null")
        return {"kind": kind, "value": None}
    if kind in {"WEEKDAY", "NEXT_WEEKDAY"}:
        if weekday not in WEEKDAY_TO_ISO or date is not None or text is not None:
            raise InterpretationValidationError("weekday date wire fields are invalid")
        return {"kind": kind, "value": WEEKDAY_TO_ISO[weekday]}
    if kind == "EXPLICIT_DATE":
        if not isinstance(date, str) or weekday is not None or text is not None:
            raise InterpretationValidationError("explicit date wire fields are invalid")
        return {"kind": kind, "value": date}
    if kind == "MISSING_YEAR":
        if not isinstance(text, str) or weekday is not None or date is not None:
            raise InterpretationValidationError("missing-year date wire fields are invalid")
        return {"kind": kind, "value": text}
    raise InterpretationValidationError("unsupported date expression")


def _normalize_instant_wire(value: object) -> dict[str, Any]:
    data = _wire_object(value, {"date", "clock"}, "date-time expression")
    return {"date": _normalize_date_wire(data["date"]), "clock": data["clock"]}


def _normalize_deadline_wire(value: object) -> dict[str, Any]:
    data = _wire_object(value, {"kind", "date", "clock"}, "deadline")
    kind = data["kind"]
    if kind == "DATE":
        if data["clock"] is not None:
            raise InterpretationValidationError("date deadline wire clock must be null")
        return {"kind": "DATE", "value": _normalize_date_wire(data["date"])}
    if kind == "INSTANT":
        if data["clock"] is None:
            raise InterpretationValidationError("instant deadline wire clock is required")
        return {
            "kind": "INSTANT",
            "value": {
                "date": _normalize_date_wire(data["date"]),
                "clock": data["clock"],
            },
        }
    raise InterpretationValidationError("unsupported deadline")


def _normalize_schedule_wire(value: object) -> dict[str, Any]:
    data = _wire_object(value, {"kind", "dates"}, "task schedule")
    dates = data["dates"]
    if not isinstance(dates, list):
        raise InterpretationValidationError("schedule dates must be an array")
    return {
        "kind": data["kind"],
        "dates": [_normalize_date_wire(item) for item in dates],
    }


def _normalize_task_wire(value: object) -> dict[str, Any]:
    data = _wire_object(
        value,
        {
            "title", "project_id", "importance", "estimated_minutes",
            "execution_mode", "schedule", "deadline",
        },
        "task",
    )
    return {
        **data,
        "schedule": None if data["schedule"] is None else _normalize_schedule_wire(data["schedule"]),
        "deadline": None if data["deadline"] is None else _normalize_deadline_wire(data["deadline"]),
    }


def _normalize_commitment_wire(value: object) -> dict[str, Any]:
    data = _wire_object(value, {"title", "start", "hardness"}, "commitment")
    return {**data, "start": _normalize_instant_wire(data["start"])}


def _normalize_capture_wire_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize strict provider wire output before canonical parsing."""

    data = _wire_object(
        payload,
        {"kind", "new_project", "tasks", "commitments", "unresolved_reason"},
        "capture interpretation",
    )
    if not isinstance(data["tasks"], list):
        raise InterpretationValidationError("tasks must be an array")
    if not isinstance(data["commitments"], list):
        raise InterpretationValidationError("commitments must be an array")
    normalized = {
        **data,
        "tasks": [_normalize_task_wire(item) for item in data["tasks"]],
        "commitments": [
            _normalize_commitment_wire(item)
            for item in data["commitments"]
        ],
    }
    if data["kind"] == "APPLY" and data["unresolved_reason"] == "":
        normalized["unresolved_reason"] = None
    return normalized



class OpenAIResponsesCaptureInterpreter:
    """Interpret capture text through a lazily configured Responses client."""

    def __init__(
        self, *, client: object | None = None, model: str | None = None,
        provider: InferenceProvider | str = InferenceProvider.OPENAI,
    ) -> None:
        self._client = client
        self._model = model
        self._provider = provider

    def interpret(self, raw_text: str, *, projects: list[dict[str, object]]) -> InterpretationResponse:
        client = self._client
        if client is not None:
            model = self._model
            provider = str(self._provider)
            if not model:
                raise InterpretationError(
                    CaptureFailureKind.CONFIGURATION_ERROR,
                    "PERSONAL_OS_CAPTURE_MODEL is not configured",
                )
        else:
            try:
                config = resolve_capture_provider()
                client = build_responses_client(config)
            except ConfigurationError as exc:
                raise InterpretationError(
                    CaptureFailureKind.CONFIGURATION_ERROR, str(exc)
                ) from exc
            except Exception as exc:
                raise InterpretationError(CaptureFailureKind.CONFIGURATION_ERROR, f"Responses client configuration failed: {exc}") from exc
            model = config.model
            provider = config.provider.value
        prompt = {"raw_text": raw_text, "active_projects": projects}
        instructions = (
            "Extract only explicit Personal OS capture semantics. Ordinary actionable tasks do not require "
            "scheduling information. When no date, time, or window is explicit, use schedule null; this means "
            "FLEXIBLE, not UNRESOLVED. When no deadline is explicit, use deadline null. When no importance is "
            "explicit, use UNSPECIFIED. When no duration is explicit, use estimated_minutes null. Classify "
            "execution_mode as SPLITTABLE when the task can usefully be advanced in partial bounded sessions "
            "such as studying, researching, writing, planning, or general project work. Classify execution_mode "
            "as ONE_SITTING only when the requested action must be completed in one continuous sitting, such as "
            "taking a test or exam. Absence of duration does not make ordinary SPLITTABLE work unresolved. "
            "ONE_SITTING with unknown duration is valid persisted state; keep estimated_minutes null unless "
            "the user supplied a duration. Do not use world knowledge to guess durations. When no "
            "project relationship is explicit, use project_id null. Do not return UNRESOLVED solely because "
            "any of these optional facts are absent. Study for ACT and Buy milk are APPLY standalone FLEXIBLE "
            "SPLITTABLE tasks. Preserve an explicitly supplied temporal fact in the appropriate existing task temporal "
            "representation rather than dropping it because other optional fields are absent. Do not invent an "
            "exact clock time or deadline semantics that were not expressed, and do not discard scheduling or "
            "deadline semantics that were expressed. Use UNRESOLVED only when safely representing "
            "explicit user meaning requires a genuinely ambiguous, missing, or unsupported fact. For example, "
            "Meet Sam at 4 is UNRESOLVED because AM/PM cannot be inferred. Never infer hard facts. Never invent a date, time, deadline, "
            "importance, duration, project identity, recurrence, commitment hardness, or other hard fact. Use UNKNOWN "
            "commitment hardness unless the user's language explicitly establishes HARD or SOFT semantics. "
            "Use BARE_HOUR for a bare clock hour, MISSING_YEAR for a date without a year, weekday names "
            "MONDAY through SUNDAY for weekday dates, and UNRESOLVED for unsupported or uncertain meaning. "
            "For every date object, fill only the field matching its kind: weekday for WEEKDAY or NEXT_WEEKDAY, "
            "date for EXPLICIT_DATE, text for MISSING_YEAR, and nulls for TODAY or TOMORROW. For every deadline, "
            "use kind DATE with clock null or kind INSTANT with a non-null clock. "
            "If kind is APPLY, output unresolved_reason as null. If kind is UNRESOLVED, output a concise "
            "non-empty explanation in unresolved_reason. Never use an empty string as a substitute for null. "
            "For task project_id, use an existing integer ID only when the user's text clearly associates "
            "the task with one of the supplied active projects. Use NEW only when new_project is non-null "
            "and the task belongs to that newly created project. Otherwise use project_id null; ordinary "
            "standalone captures such as Buy milk must not invent a project."
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
            raise InterpretationError(
                CaptureFailureKind.PROVIDER_ERROR,
                f"{provider} request failed: {exc}",
                provider=provider,
                model=model,
            ) from exc
        response_id = getattr(response, "id", None)
        response_model = getattr(response, "model", None) or model
        if getattr(response, "status", None) in {"failed", "incomplete"}:
            raise InterpretationError(CaptureFailureKind.PROVIDER_ERROR, f"{provider} response status was {response.status}", provider=provider, model=str(response_model), response_id=None if response_id is None else str(response_id))
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                refusal = getattr(content, "refusal", None)
                if refusal:
                    raise InterpretationError(CaptureFailureKind.REFUSAL, str(refusal), provider=provider, model=str(response_model), response_id=None if response_id is None else str(response_id))
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text:
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, f"{provider} response contained no structured text", provider=provider, model=str(response_model), response_id=None if response_id is None else str(response_id))
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, f"{provider} response was malformed JSON", provider=provider, model=str(response_model), response_id=None if response_id is None else str(response_id)) from exc
        if not isinstance(payload, dict):
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, f"{provider} response was not a JSON object", provider=provider, model=str(response_model), response_id=None if response_id is None else str(response_id))
        try:
            payload = _normalize_capture_wire_payload(payload)
            interpretation = parse_interpretation(payload)
        except InterpretationValidationError as exc:
            raise InterpretationError(CaptureFailureKind.INVALID_OUTPUT, str(exc), provider=provider, model=str(response_model), response_id=None if response_id is None else str(response_id)) from exc
        return InterpretationResponse(interpretation, provider, str(response_model), None if response_id is None else str(response_id))

from __future__ import annotations

from copy import deepcopy
from typing import Any


TIME_KEYS = {"start", "end", "duration"}


def parse_job_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    parsed = deepcopy(payload)
    global_time_range = _normalize_time_range(parsed.get("time_range"), field_name="payload.time_range")
    if global_time_range is not None:
        parsed["time_range"] = global_time_range

    providers = parsed.get("providers")
    if providers is not None and not isinstance(providers, dict):
        raise ValueError("payload.providers must be an object")

    request = parsed.get("request")
    if request is not None and not isinstance(request, str):
        raise ValueError("payload.request must be a string")

    operations = parsed.get("operations")
    if operations is None:
        return parsed
    if not isinstance(operations, list):
        raise ValueError("payload.operations must be a list")
    parsed["operations"] = [
        _normalize_operation(operation, index=index, global_time_range=global_time_range)
        for index, operation in enumerate(operations, start=1)
    ]
    return parsed


def _normalize_operation(
    operation: Any,
    *,
    index: int,
    global_time_range: dict[str, float] | None,
) -> dict[str, Any]:
    if not isinstance(operation, dict):
        raise ValueError(f"payload.operations[{index - 1}] must be an object")

    nested_params = operation.get("params", {})
    if nested_params is None:
        nested_params = {}
    if not isinstance(nested_params, dict):
        raise ValueError(f"payload.operations[{index - 1}].params must be an object")

    normalized: dict[str, Any] = dict(nested_params)
    for key, value in operation.items():
        if key == "params":
            continue
        if key == "type":
            normalized.setdefault("name", value)
            normalized["type"] = value
        elif key == "id":
            normalized["operation_id"] = value
            normalized["id"] = value
        else:
            normalized[key] = value

    op_name = normalized.get("name")
    if op_name is None and normalized.get("type") is not None:
        op_name = normalized["type"]
        normalized["name"] = op_name
    if op_name is not None:
        normalized["name"] = str(op_name).strip().lower()
    elif "request" not in normalized:
        raise ValueError(f"payload.operations[{index - 1}] requires name or type")

    time_range = _normalize_time_range(
        normalized.get("time_range", global_time_range),
        field_name=f"payload.operations[{index - 1}].time_range",
    )
    if time_range is not None:
        normalized["time_range"] = time_range
        _apply_time_range(normalized, time_range)

    return normalized


def _normalize_time_range(value: Any, *, field_name: str) -> dict[str, float] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    normalized: dict[str, float] = {}
    for key in TIME_KEYS:
        if key in value and value[key] is not None:
            normalized[key] = _as_non_negative_float(value[key], f"{field_name}.{key}")
    if not normalized:
        return None
    start = normalized.get("start")
    end = normalized.get("end")
    duration = normalized.get("duration")
    if end is not None and start is not None and end <= start:
        raise ValueError(f"{field_name}.end must be greater than start")
    if duration is not None and duration <= 0:
        raise ValueError(f"{field_name}.duration must be greater than 0")
    if end is None and start is not None and duration is not None:
        normalized["end"] = start + duration
    elif duration is None and start is not None and end is not None:
        normalized["duration"] = end - start
    return normalized


def _apply_time_range(operation: dict[str, Any], time_range: dict[str, float]) -> None:
    for key in TIME_KEYS:
        if key not in operation and key in time_range:
            operation[key] = time_range[key]


def _as_non_negative_float(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if number < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return number

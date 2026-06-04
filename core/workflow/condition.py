from __future__ import annotations

import ast
import operator
import re
from collections.abc import Mapping
from typing import Any


_OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
}

_SIMPLE_PATTERN = re.compile(
    r"^(payload|metadata|context)\[['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\]\s*(==|!=|>=|<=|>|<)\s*(.+)$"
)


def evaluate_condition(condition: str, context_vars: dict[str, Any]) -> bool:
    """Evaluate the supported V1 workflow condition grammar."""
    match = _SIMPLE_PATTERN.match(condition.strip())
    if match:
        namespace, key, op, raw_value = match.groups()
        lhs = _lookup(context_vars.get(namespace), key)
        rhs = _parse_literal(raw_value.strip())
        return bool(_OPS[op](lhs, rhs))

    raise ValueError(
        "unsupported workflow condition; expected payload['key'] == value, metadata['key'] == value, "
        "or context['key'] == value"
    )


def _lookup(container: Any, key: str) -> Any:
    if isinstance(container, Mapping):
        return container.get(key)
    return getattr(container, key, None)


def _parse_literal(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"none", "null"}:
        return None
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value

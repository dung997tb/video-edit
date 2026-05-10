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
    """Evaluate simple workflow conditions safely, with legacy eval fallback."""
    match = _SIMPLE_PATTERN.match(condition.strip())
    if match:
        namespace, key, op, raw_value = match.groups()
        lhs = _lookup(context_vars.get(namespace), key)
        rhs = _parse_literal(raw_value.strip())
        return bool(_OPS[op](lhs, rhs))

    allowed_globals = {"__builtins__": {}}
    return bool(eval(condition, allowed_globals, context_vars))


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

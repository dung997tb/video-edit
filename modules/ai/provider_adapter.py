from __future__ import annotations

from copy import deepcopy
from typing import Any


def get_provider_config(context: Any, services: Any, kind: str) -> dict[str, Any]:
    providers = context.state.get("providers") or {}
    if not isinstance(providers, dict):
        return {}
    raw_config = providers.get(kind) or {}
    if not isinstance(raw_config, dict):
        return {}
    config = deepcopy(raw_config)
    secret_path = f"payload.providers.{kind}.api_key"
    secret_store = getattr(services, "secret_store", None)
    secret_value = secret_store.get(context.job_id, secret_path) if secret_store is not None else None
    if secret_value:
        config["api_key"] = secret_value
    elif _looks_redacted(config.get("api_key")):
        config.pop("api_key", None)
    return config


def provider_name(config: dict[str, Any], default: str) -> str:
    return str(config.get("provider") or config.get("engine") or config.get("service") or default).strip().lower()


def _looks_redacted(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("***")

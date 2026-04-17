from __future__ import annotations

from typing import TypeVar

from modules.base import BaseModule

ModuleType = TypeVar("ModuleType", bound=type[BaseModule])

_REGISTRY: dict[str, type[BaseModule]] = {}


def register(cls: ModuleType) -> ModuleType:
    if not getattr(cls, "NAME", None):
        raise ValueError(f"{cls.__name__} must define NAME")
    _REGISTRY[cls.NAME] = cls
    return cls


def get_registry() -> dict[str, type[BaseModule]]:
    return dict(_REGISTRY)

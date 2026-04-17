from __future__ import annotations

from orchestrators.dubbing_orchestrator import DubbingOrchestrator
from orchestrators.low_level_orchestrator import LowLevelOrchestrator


def build_orchestrators():
    orchestrators = [
        DubbingOrchestrator(),
        LowLevelOrchestrator(),
    ]
    return {item.NAME: item for item in orchestrators}

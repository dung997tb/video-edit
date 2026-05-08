from __future__ import annotations

from orchestrators.audio_extract_orchestrator import AudioExtractOrchestrator
from orchestrators.dubbing_orchestrator import DubbingOrchestrator
from orchestrators.low_level_orchestrator import LowLevelOrchestrator
from orchestrators.ad_orchestrator import AdOrchestrator
from orchestrators.multilang_dubbing_orchestrator import MultilangDubbingOrchestrator
from orchestrators.subtitle_orchestrator import SubtitleOrchestrator


def build_orchestrators():
    orchestrators = [
        DubbingOrchestrator(),
        LowLevelOrchestrator(),
        SubtitleOrchestrator(),
        AudioExtractOrchestrator(),
        MultilangDubbingOrchestrator(),
        AdOrchestrator(),
    ]
    result = {item.NAME: item for item in orchestrators}
    result["subtitle-only"] = result["subtitle"]
    result["audio_extract"] = result["audio-extract"]
    return result

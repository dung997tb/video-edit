from __future__ import annotations

from orchestrators.audio_extract_orchestrator import AudioExtractOrchestrator
from orchestrators.auto_broll_orchestrator import AutoBrollOrchestrator
from orchestrators.dubbing_orchestrator import DubbingOrchestrator
from orchestrators.face_track_orchestrator import FaceTrackOrchestrator
from orchestrators.extract_frames_orchestrator import ExtractFramesOrchestrator
from orchestrators.low_level_orchestrator import LowLevelOrchestrator
from orchestrators.ad_orchestrator import AdOrchestrator
from orchestrators.multilang_dubbing_orchestrator import MultilangDubbingOrchestrator
from orchestrators.semantic_edit_orchestrator import SemanticEditOrchestrator
from orchestrators.silence_cut_orchestrator import SilenceCutOrchestrator
from orchestrators.split_video_orchestrator import SplitVideoOrchestrator
from orchestrators.subtitle_orchestrator import SubtitleOrchestrator
from orchestrators.workflow_orchestrator import WorkflowOrchestrator


def build_orchestrators():
    orchestrators = [
        DubbingOrchestrator(),
        LowLevelOrchestrator(),
        SubtitleOrchestrator(),
        AudioExtractOrchestrator(),
        MultilangDubbingOrchestrator(),
        AdOrchestrator(),
        WorkflowOrchestrator(),
        SemanticEditOrchestrator(),
        SilenceCutOrchestrator(),
        SplitVideoOrchestrator(),
        ExtractFramesOrchestrator(),
        FaceTrackOrchestrator(),
        AutoBrollOrchestrator(),
    ]
    result = {item.NAME: item for item in orchestrators}
    result["subtitle-only"] = result["subtitle"]
    result["audio_extract"] = result["audio-extract"]
    result["multilang_dubbing"] = result["multilang-dubbing"]
    return result

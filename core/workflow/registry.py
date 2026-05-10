from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from core.workflow.spec import NodeSpec


NodeFactory = Callable[[dict[str, Any]], Any]
_log = logging.getLogger(__name__)


class NodeRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, NodeFactory] = {}

    def register(self, node_type: str, factory: NodeFactory | type) -> None:
        def _build(params: dict[str, Any]) -> Any:
            return factory(params=params) if isinstance(factory, type) else factory(params)

        self._factories[node_type] = _build

    def has(self, node_type: str) -> bool:
        return node_type in self._factories

    def build(self, node: NodeSpec) -> Any:
        if node.module is not None:
            return node.module
        factory = self._factories.get(node.type)
        if factory is None:
            supported = ", ".join(sorted(self._factories))
            raise ValueError(f"unsupported workflow node type '{node.type}'. supported: {supported}")
        return factory(node.params)


def build_default_registry() -> NodeRegistry:
    registry = NodeRegistry()

    from modules.ai.audio_mixer import AudioMixerModule
    from modules.ai.broll_injector import BrollInjectorModule
    from modules.ai.face_tracker import FaceTrackerModule
    from modules.ai.karaoke_subtitle import KaraokeSubtitleModule
    from modules.ai.multilang_fanout import MultilangFanOutModule
    from modules.ai.segmenter import SegmenterModule
    from modules.ai.semantic_edit import SemanticEditModule
    from modules.ai.silence_remover import SilenceRemoverModule
    from modules.ai.subtitle_export import SubtitleExportModule
    from modules.ai.subtitle_gen import SubtitleModule
    from modules.ai.transcriber import TranscriberModule
    from modules.ai.translator import TranslatorModule
    from modules.ai.tts import TTSModule
    from modules.ai.voice_sync import VoiceSyncModule
    from modules.ai.voice_sync_retry import VoiceSyncRetryModule
    from modules.audio.audio_export import AudioExportModule
    from modules.video.extract_audio import ExtractAudioModule
    from modules.video.finalize import FinalizeVideoModule
    from modules.video.remux_audio import RemuxAudioModule
    from modules.video.subtitle_burn import SubtitleBurnModule

    defaults: dict[str, type] = {
        "ai.transcribe": TranscriberModule,
        "ai.translate": TranslatorModule,
        "ai.segment": SegmenterModule,
        "ai.semantic_edit": SemanticEditModule,
        "ai.subtitle": SubtitleModule,
        "ai.karaoke_subtitle": KaraokeSubtitleModule,
        "ai.subtitle_export": SubtitleExportModule,
        "ai.tts": TTSModule,
        "ai.voice_sync": VoiceSyncModule,
        "ai.voice_sync_retry": VoiceSyncRetryModule,
        "ai.audio_mixer": AudioMixerModule,
        "ai.multilang_fanout": MultilangFanOutModule,
        "ai.silence_remover": SilenceRemoverModule,
        "ai.face_tracker": FaceTrackerModule,
        "ai.broll_injector": BrollInjectorModule,
        "audio.extract": ExtractAudioModule,
        "audio.export": AudioExportModule,
        "media.extract_audio": ExtractAudioModule,
        "media.subtitle_burn": SubtitleBurnModule,
        "media.remux_audio": RemuxAudioModule,
        "media.finalize": FinalizeVideoModule,
    }
    for node_type, factory in defaults.items():
        registry.register(node_type, factory)

    try:
        from modules.video.low_level import VIDEO_OPERATION_MODULES

        for operation, module_cls in VIDEO_OPERATION_MODULES.items():
            registry.register(f"media.{operation}", module_cls)
            registry.register(f"video.{operation}", module_cls)
    except Exception as exc:
        _log.warning("low_level video modules unavailable: %s", exc)
    try:
        from core.plugins import PluginLoader

        loader = PluginLoader()
        for manifest in loader.discover():
            try:
                loader._load_single(manifest, registry)
                _log.info("plugin loaded: %s v%s", manifest.name, manifest.version)
            except Exception as exc:
                _log.error("plugin '%s' failed to load: %s", manifest.name, exc, exc_info=True)
    except Exception as exc:
        _log.warning("plugin discovery failed: %s", exc)
    return registry

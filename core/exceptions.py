from __future__ import annotations


class VideoEditError(RuntimeError):
    """Base error for application-level video processing failures."""


class WorkflowNodeError(VideoEditError):
    def __init__(self, node_id: str, cause: str, error_code: str | None = None) -> None:
        super().__init__(cause)
        self.node_id = node_id
        self.error_code = error_code


class FFmpegError(VideoEditError):
    pass


class TranscriptionError(VideoEditError):
    pass


class TranslationError(VideoEditError):
    pass


class TTSError(VideoEditError):
    pass


class PluginLoadError(VideoEditError):
    pass


class JobCancelledError(VideoEditError):
    pass


class IllegalStateTransition(VideoEditError):
    """Raised when a job state transition violates the lifecycle contract."""


class ConfigurationError(VideoEditError):
    pass

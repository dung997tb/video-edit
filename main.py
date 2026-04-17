from __future__ import annotations

import json
from pathlib import Path

try:
    import typer
except ImportError:  # pragma: no cover - fallback for minimal local environments
    class _FallbackTyperApp:
        def __init__(self, *args, **kwargs) -> None:
            self.help = kwargs.get("help")

        def command(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def __call__(self, *args, **kwargs) -> None:
            raise RuntimeError("typer is required to use the CLI entrypoints")

    class _FallbackTyperModule:
        Typer = _FallbackTyperApp

        @staticmethod
        def echo(message: str) -> None:
            print(message)

    typer = _FallbackTyperModule()

from core.batch_engine import WorkerService
from config import settings as default_settings
from core.cache import hash_file
from core.pipeline import PipelineRunner
from core.runtime import build_services, get_services

cli = typer.Typer(help="AI video engine entrypoints")


@cli.command()
def api(host: str | None = None, port: int | None = None) -> None:
    from api.main import app as fastapi_app
    import uvicorn

    services = get_services()
    uvicorn.run(
        fastapi_app,
        host=host or services.settings.api_host,
        port=port or services.settings.api_port,
    )


@cli.command()
def worker() -> None:
    services = get_services()
    WorkerService(services).run_forever()


@cli.command()
def run(
    input_path: Path,
    pipeline_type: str = "dubbing",
    target_language: str = "vi",
    source_language: str = "auto",
    tts_voice: str | None = None,
    background_audio: Path | None = None,
    config_file: Path | None = None,
) -> None:
    local_settings = default_settings.with_overrides(
        job_backend="memory",
        artifact_store_backend="local",
    )
    services = build_services(local_settings)
    payload: dict[str, str | float] = {}
    if config_file:
        config_payload = json.loads(config_file.read_text(encoding="utf-8"))
        pipeline_type = config_payload.get("pipeline_type", pipeline_type)
        payload.update(config_payload.get("payload", {}))
    payload.setdefault("target_language", target_language)
    payload.setdefault("source_language", source_language)
    if tts_voice:
        payload["tts_voice"] = tts_voice
    if background_audio:
        payload["background_audio"] = str(background_audio)
    job = services.job_manager.create_job(
        pipeline_type=pipeline_type,
        source_sha256=hash_file(input_path),
        payload=payload,
        input_path=str(input_path),
    )
    context = PipelineRunner(services).run_job(job)
    typer.echo(context.output_video or "")


if __name__ == "__main__":
    cli()

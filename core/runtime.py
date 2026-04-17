from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable

from config import settings as default_settings
from config.settings import Settings
from core.artifact_store import ArtifactStore, LocalArtifactStore, SupabaseArtifactStore
from core.cache import CacheManager
from core.exceptions import ConfigurationError
from core.job_manager import InMemoryJobRepository, JobManager, JobRepository, SupabaseJobRepository
from core.logger import configure_logger
from core.process import ProcessRegistry
from core.models import JobRecord


PipelineBuilder = Callable[[JobRecord, "AppServices"], list[Any]]


@dataclass(slots=True)
class AppServices:
    settings: Settings
    artifact_store: ArtifactStore
    cache_manager: CacheManager
    job_manager: JobManager
    process_registry: ProcessRegistry
    pipeline_builders: dict[str, PipelineBuilder] = field(default_factory=dict)


def create_supabase_client(settings: Settings) -> Any:
    if not settings.supabase_url or not settings.supabase_key:
        raise ConfigurationError("SUPABASE_URL and SUPABASE_KEY are required for Supabase backends")
    from supabase import Client, create_client

    return create_client(settings.supabase_url, settings.supabase_key)


def build_artifact_store(settings: Settings) -> ArtifactStore:
    if settings.artifact_store_backend == "supabase":
        client = create_supabase_client(settings)
        return SupabaseArtifactStore(client, settings.supabase_storage_bucket)
    local_root = settings.cache_dir / "artifacts"
    return LocalArtifactStore(local_root)


def build_job_repository(settings: Settings) -> JobRepository:
    if settings.job_backend == "supabase":
        client = create_supabase_client(settings)
        return SupabaseJobRepository(client, settings.supabase_jobs_table)
    return InMemoryJobRepository()


def build_pipeline_builders() -> dict[str, PipelineBuilder]:
    from orchestrators.factory import build_orchestrators

    orchestrators = build_orchestrators()
    return {name: orchestrator.build for name, orchestrator in orchestrators.items()}


def build_services(settings: Settings | None = None) -> AppServices:
    active_settings = settings or default_settings
    active_settings.logs_dir.mkdir(parents=True, exist_ok=True)
    active_settings.temp_dir.mkdir(parents=True, exist_ok=True)
    active_settings.output_dir.mkdir(parents=True, exist_ok=True)
    active_settings.cache_dir.mkdir(parents=True, exist_ok=True)
    configure_logger(active_settings.logs_dir, level=active_settings.log_level)
    artifact_store = build_artifact_store(active_settings)
    cache_manager = CacheManager(artifact_store=artifact_store, cache_version=active_settings.cache_version)
    job_manager = JobManager(build_job_repository(active_settings))
    process_registry = ProcessRegistry()
    return AppServices(
        settings=active_settings,
        artifact_store=artifact_store,
        cache_manager=cache_manager,
        job_manager=job_manager,
        process_registry=process_registry,
        pipeline_builders=build_pipeline_builders(),
    )


@lru_cache(maxsize=1)
def get_services() -> AppServices:
    return build_services()

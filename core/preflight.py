from __future__ import annotations

from typing import Any


REQUIRED_RPCS = ("claim_jobs", "release_stale_leases", "request_cancel_job")
REQUIRED_TRIGGER = "jobs_set_updated_at"
REQUIRED_COLUMNS = (
    "id",
    "status",
    "pipeline_type",
    "priority",
    "payload",
    "input_path",
    "input_uri",
    "output_path",
    "source_sha256",
    "pid",
    "worker_id",
    "lease_expires_at",
    "cancel_requested",
    "attempt_count",
    "progress",
    "step_index",
    "total_steps",
    "current_step",
    "log",
    "error",
    "error_detail",
    "metadata",
    "terminal_notified",
    "webhook_attempts",
    "last_webhook_error",
    "created_at",
    "started_at",
    "finished_at",
    "updated_at",
)
REQUIRED_INDEXES = (
    "jobs_claim_lookup_idx",
    "jobs_worker_lookup_idx",
    "jobs_status_created_idx",
    "jobs_priority_claim_idx",
)
VERIFY_RPC_NAME = "verify_jobs_schema_requirements"


def verify_supabase_jobs_schema(
    client: Any,
    *,
    table_name: str = "jobs",
    required_trigger: str = REQUIRED_TRIGGER,
    required_rpcs: tuple[str, ...] = REQUIRED_RPCS,
    required_columns: tuple[str, ...] = REQUIRED_COLUMNS,
    required_indexes: tuple[str, ...] = REQUIRED_INDEXES,
) -> dict[str, Any]:
    response = client.rpc(
        VERIFY_RPC_NAME,
        {
            "p_table_name": table_name,
            "p_required_trigger": required_trigger,
            "p_required_rpcs": list(required_rpcs),
            "p_required_columns": list(required_columns),
            "p_required_indexes": list(required_indexes),
        },
    ).execute()
    raw_data = response.data
    if raw_data is None:
        raise RuntimeError(f"{VERIFY_RPC_NAME} returned no payload")
    payload = raw_data[0] if isinstance(raw_data, list) else raw_data
    if not isinstance(payload, dict):
        raise RuntimeError(f"{VERIFY_RPC_NAME} returned unexpected payload: {type(payload).__name__}")
    payload.setdefault("missing_rpcs", [])
    payload.setdefault("missing_columns", [])
    payload.setdefault("missing_indexes", [])
    payload.setdefault("table_exists", False)
    payload.setdefault("secret_table_exists", False)
    payload.setdefault("trigger_exists", False)
    payload.setdefault("ok", False)
    return payload


def verify_services_preflight(services: Any) -> dict[str, Any]:
    if services.settings.job_backend != "supabase":
        raise RuntimeError("preflight check requires JOB_BACKEND=supabase")
    if not services.settings.supabase_url or not services.settings.supabase_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY are required for preflight")
    repository = getattr(services.job_manager, "repository", None)
    client = getattr(repository, "client", None)
    if client is None:
        raise RuntimeError("job repository does not expose a Supabase client for preflight")
    return verify_supabase_jobs_schema(
        client=client,
        table_name=services.settings.supabase_jobs_table,
    )

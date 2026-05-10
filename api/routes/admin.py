from __future__ import annotations

from html import escape

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from api.schemas import JobListResponse, JobResponse
from core.models import JobStatus
from core.runtime import get_services

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("", response_class=HTMLResponse)
def admin_dashboard() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Video Engine Admin</title>
  <style>
    :root { color-scheme: light; font-family: Inter, Segoe UI, Arial, sans-serif; }
    body { margin: 0; background: #f6f7f9; color: #17202a; }
    header { background: #ffffff; border-bottom: 1px solid #d8dee8; padding: 14px 18px; display: flex; gap: 12px; align-items: center; }
    h1 { font-size: 18px; margin: 0; font-weight: 650; }
    main { padding: 18px; }
    .toolbar { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
    select, input, button { height: 34px; border: 1px solid #bcc7d6; border-radius: 6px; background: white; padding: 0 10px; }
    button { cursor: pointer; background: #1f6feb; color: white; border-color: #1f6feb; }
    table { width: 100%; border-collapse: collapse; background: white; border: 1px solid #d8dee8; }
    th, td { text-align: left; padding: 10px; border-bottom: 1px solid #edf0f4; font-size: 13px; vertical-align: top; }
    th { background: #f0f3f7; font-weight: 650; }
    code { font-family: Consolas, monospace; font-size: 12px; }
    .muted { color: #667085; }
  </style>
</head>
<body>
  <header><h1>AI Video Engine Admin</h1></header>
  <main>
    <div class="toolbar">
      <select id="status">
        <option value="">All</option><option>pending</option><option>running</option>
        <option>done</option><option>failed</option><option>cancelled</option>
      </select>
      <input id="search" placeholder="Job ID">
      <button id="refresh">Refresh</button>
    </div>
    <table>
      <thead><tr><th>ID</th><th>Status</th><th>Pipeline</th><th>Progress</th><th>Step</th><th>Output/Error</th><th></th></tr></thead>
      <tbody id="jobs"></tbody>
    </table>
  </main>
  <script>
    const tbody = document.querySelector("#jobs");
    async function loadJobs() {
      const status = document.querySelector("#status").value;
      const search = document.querySelector("#search").value.trim();
      const url = search ? `/jobs/${encodeURIComponent(search)}` : `/jobs?limit=100${status ? `&status=${status}` : ""}`;
      const response = await fetch(url);
      if (!response.ok) { tbody.innerHTML = `<tr><td colspan="7">No job found</td></tr>`; return; }
      const data = await response.json();
      const rows = search ? [data] : data.items;
      tbody.innerHTML = rows.map(job => `
        <tr>
          <td><code>${job.id}</code></td><td>${job.status}</td><td>${job.pipeline_type}</td>
          <td>${job.progress}%</td><td>${job.current_step || ""}</td>
          <td class="muted">${job.output_path || job.error || ""}</td>
          <td>${["pending","running"].includes(job.status) ? `<button data-id="${job.id}">Cancel</button>` : ""}</td>
        </tr>`).join("");
      tbody.querySelectorAll("button[data-id]").forEach(button => button.onclick = async () => {
        await fetch(`/jobs/${button.dataset.id}/cancel`, { method: "POST" });
        await loadJobs();
      });
    }
    document.querySelector("#refresh").onclick = loadJobs;
    document.querySelector("#status").onchange = loadJobs;
    loadJobs();
  </script>
</body>
</html>
"""


@router.get("/jobs", response_model=JobListResponse)
def admin_jobs(status: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500)) -> JobListResponse:
    services = get_services()
    try:
        parsed_status = JobStatus(status) if status else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid status: {escape(str(status))}") from exc
    jobs = services.job_manager.list_jobs(status=parsed_status, limit=limit)
    return JobListResponse(items=[JobResponse(**job.to_dict()) for job in jobs])


@router.get("/jobs/{job_id}/assets")
def admin_job_assets(job_id: str) -> dict:
    services = get_services()
    graph = getattr(services, "asset_graph", None)
    if graph is None:
        return {"items": []}
    return {"items": [record.to_dict() for record in graph.list_for_job(job_id)]}


@router.get("/events")
def admin_events(event_type: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500)) -> dict:
    services = get_services()
    event_bus = getattr(services, "event_bus", None)
    if event_bus is None:
        return {"items": []}
    return {"items": [event.to_dict() for event in event_bus.recent(event_type=event_type, limit=limit)]}


@router.delete("/jobs/{job_id}/cleanup")
def admin_job_cleanup(job_id: str) -> dict:
    services = get_services()
    job = services.job_manager.get_job(job_id)
    
    output_name = None
    if job:
        output_name = job.payload.get("output_name")
        
    import re
    import shutil
    
    safe_output_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', output_name) if output_name else job_id

    temp_dir = services.settings.temp_dir / job_id
    output_dir = services.settings.output_dir / safe_output_name

    deleted_temp = False
    deleted_output = False

    if temp_dir.exists() and temp_dir.is_dir():
        shutil.rmtree(temp_dir, ignore_errors=True)
        deleted_temp = True
        
    if output_dir.exists() and output_dir.is_dir():
        shutil.rmtree(output_dir, ignore_errors=True)
        deleted_output = True
        
    return {
        "job_id": job_id,
        "status": "success",
        "deleted_temp": deleted_temp,
        "deleted_output": deleted_output
    }

from __future__ import annotations

from contextlib import asynccontextmanager
from hmac import compare_digest

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.routes.jobs import router as jobs_router
from core.batch_engine import WorkerService
from core.runtime import get_services


def _should_start_embedded_worker(services) -> bool:
    return bool(getattr(services.settings, "api_embedded_worker", True))


def _extract_api_key(request: Request) -> str | None:
    direct = request.headers.get("x-api-key")
    if direct:
        return direct.strip()
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        return token or None
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    services = get_services()
    app.state.services = services
    embedded_worker = None
    if _should_start_embedded_worker(services):
        embedded_worker = WorkerService(services)
        embedded_worker.start_background(name="api-embedded-worker")
    app.state.embedded_worker = embedded_worker
    try:
        yield
    finally:
        if embedded_worker is not None:
            embedded_worker.stop(timeout=services.settings.cancel_grace_seconds)


def create_app() -> FastAPI:
    app = FastAPI(title="AI Video Engine", lifespan=lifespan)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        services = get_services()
        if request.url.path == "/health":
            return await call_next(request)
        if not services.settings.api_auth_enabled:
            return await call_next(request)
        provided = _extract_api_key(request)
        if not provided or not compare_digest(provided, services.settings.api_secret_key):
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(jobs_router)
    return app


app = create_app()

from __future__ import annotations

from contextlib import asynccontextmanager
from hmac import compare_digest

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from api.middleware.rate_limit import InMemoryRateLimiter
try:
    from api.routes.admin import router as admin_router
except ImportError:  # pragma: no cover - admin route is optional in minimal builds
    admin_router = None
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
    app.state.rate_limiter = None

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        services = get_services()
        if request.url.path in {"/health", "/metrics"}:
            return await call_next(request)
        if not services.settings.api_auth_enabled:
            return await call_next(request)
        provided = _extract_api_key(request)
        if not provided or not compare_digest(provided, services.settings.api_secret_key):
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})
        limit = int(getattr(services.settings, "api_rate_limit_per_minute", 0) or 0)
        if limit > 0:
            limiter = app.state.rate_limiter
            if limiter is None or limiter._limit != limit:  # noqa: SLF001
                limiter = InMemoryRateLimiter(limit)
                app.state.rate_limiter = limiter
            if not limiter.is_allowed(provided):
                return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(jobs_router)
    if admin_router is not None:
        app.include_router(admin_router)
    _enable_metrics(app)
    return app


def _enable_metrics(app: FastAPI) -> None:
    if not bool(getattr(get_services().settings, "metrics_enabled", True)):
        return
    try:
        from prometheus_fastapi_instrumentator import Instrumentator
    except ImportError:
        try:
            from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
        except ImportError:
            @app.get("/metrics", include_in_schema=False)
            def metrics_endpoint() -> Response:
                return Response(
                    "# HELP ai_video_engine_metrics_available Metrics fallback availability.\n"
                    "# TYPE ai_video_engine_metrics_available gauge\n"
                    "ai_video_engine_metrics_available 0\n",
                    media_type="text/plain; version=0.0.4; charset=utf-8",
                )

            return

        @app.get("/metrics", include_in_schema=False)
        def metrics_endpoint() -> Response:
            return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

        return
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


app = create_app()

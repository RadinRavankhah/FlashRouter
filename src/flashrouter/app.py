"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from flashrouter import __version__
from flashrouter.api.admin import router as admin_router
from flashrouter.api.inference import router as inference_router
from flashrouter.api.models import router as models_router
from flashrouter.config import Settings, ensure_data_dirs
from flashrouter.core.contracts import NullUsageAccountant
from flashrouter.errors import GatewayError, error_body
from flashrouter.logging import (
    LoggingRequestLogSink,
    configure_logging,
    get_logger,
    new_request_id,
)
from flashrouter.protocols.openai_chat import OpenAIChatAdapter
from flashrouter.routing.models import ConfiguredModelResolver
from flashrouter.services.proxy import ChatCompletionsProxy
from flashrouter.storage.database import Database
from flashrouter.storage.repository import RequestRepository
from flashrouter.transport.http import HttpxTransport, create_http_client

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UI_DIST_DIR = PROJECT_ROOT / "ui" / "dist"


def create_app(
    settings: Settings,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    configure_logging(settings.server.log_level)
    logger = get_logger()

    resolver = ConfiguredModelResolver(settings.models)
    adapter = OpenAIChatAdapter()
    request_log = LoggingRequestLogSink()
    usage_accountant = NullUsageAccountant()

    database = Database(settings.data_dir / "flashrouter.db")
    repository = RequestRepository(database)
    owns_client = http_client is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ensure_data_dirs(settings)
        await database.connect()
        await database.migrate()
        client = http_client if http_client is not None else create_http_client(settings.upstream)
        transport = HttpxTransport(client)
        app.state.proxy = ChatCompletionsProxy(
            settings,
            resolver,
            adapter,
            transport,
            request_log,
            usage_accountant,
            repository,
        )
        app.state.request_repository = repository
        app.state.settings = settings
        app.state.model_resolver = resolver
        app.state.adapter = adapter
        logger.info(
            "gateway_started host=%s port=%s upstream=%s models=%s",
            settings.server.host,
            settings.server.port,
            settings.upstream.base_url,
            len(settings.models),
        )
        try:
            yield
        finally:
            if owns_client:
                await client.aclose()
            await database.close()
            logger.info("gateway_stopped")

    app = FastAPI(
        title="FlashRouter",
        version=__version__,
        lifespan=lifespan,
    )

    # Dashboard static files (built with `npm run build` in ui/).
    if UI_DIST_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(UI_DIST_DIR)), name="static")

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = new_request_id()
        response = await call_next(request)
        response.headers.setdefault("X-FlashRouter-Request-ID", request.state.request_id)
        return response

    @app.exception_handler(GatewayError)
    async def gateway_error_handler(request: Request, exc: GatewayError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        headers = dict(exc.headers)
        if request_id:
            headers["X-FlashRouter-Request-ID"] = request_id
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(
                exc.message,
                error_type=exc.type,
                code=exc.code,
                param=exc.param,
            ),
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.exception("unhandled_error request_id=%s", request_id)
        headers = {"X-FlashRouter-Request-ID": request_id} if request_id else {}
        return JSONResponse(
            status_code=500,
            content=error_body(
                "Internal gateway error",
                error_type="server_error",
                code="internal_error",
            ),
            headers=headers,
        )

    app.include_router(inference_router)
    app.include_router(models_router)
    app.include_router(admin_router)

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    # Single-page application fallback: serve index.html for any non-API path
    # so React Router can handle client-side routing.
    if UI_DIST_DIR.is_dir():

        @app.get("/")
        async def spa_root() -> FileResponse:
            return FileResponse(str(UI_DIST_DIR / "index.html"))

        @app.get("/{path:path}")
        async def spa_fallback(path: str) -> FileResponse:
            return FileResponse(str(UI_DIST_DIR / "index.html"))

    return app

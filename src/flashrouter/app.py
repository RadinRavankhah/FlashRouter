"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from flashrouter import __version__
from flashrouter.api.admin import router as admin_router
from flashrouter.api.inference import router as inference_router
from flashrouter.config import Settings, ensure_data_dirs
from flashrouter.errors import GatewayError, error_body
from flashrouter.logging import configure_logging, get_logger, new_request_id
from flashrouter.routing.engine import Router
from flashrouter.services.engine import Engine
from flashrouter.storage.database import Database
from flashrouter.storage.repository import Repository
from flashrouter.transport.http import create_client

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]


def _find_ui_dist() -> Path | None:
    candidates = [
        PROJECT_ROOT / "ui" / "dist",
        PACKAGE_DIR / "web",
    ]
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


_FALLBACK_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>FlashRouter</title>
<style>
body{font-family:system-ui,sans-serif;background:#0b0f14;color:#e6edf3;
display:grid;place-items:center;min-height:100vh;margin:0}
main{max-width:560px;padding:32px;border:1px solid #22303c;border-radius:16px;background:#111821}
code{background:#1b2430;padding:2px 6px;border-radius:6px}
a{color:#4c9aff}
</style></head><body><main>
<h1>FlashRouter</h1>
<p>The dashboard assets were not found at <code>ui/dist</code>.</p>
<p>The API is running. Build the dashboard once with:</p>
<pre><code>cd ui
npm install
npm run build</code></pre>
<p>API base: <a href="/healthz">/healthz</a> · <a href="/v1/models">/v1/models</a></p>
</main></body></html>"""


def create_app(
    settings: Settings, *, http_client: httpx.AsyncClient | None = None
) -> FastAPI:
    configure_logging(settings.server.log_level)
    logger = get_logger()

    database = Database(settings.database_path)
    ui_dist = _find_ui_dist()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ensure_data_dirs(settings)
        await database.connect()
        await database.migrate()
        repository = Repository(database)
        router = Router(repository)
        owns_client = http_client is None
        client = http_client if http_client is not None else create_client(settings)
        engine = Engine(settings, repository, router, client)

        app.state.settings = settings
        app.state.repository = repository
        app.state.router = router
        app.state.http_client = client
        app.state.engine = engine

        provider_count = len(await repository.list_providers())
        key_count = await repository.count_keys()
        logger.info(
            "flashrouter_started host=%s port=%s providers=%s keys=%s",
            settings.server.host,
            settings.server.port,
            provider_count,
            key_count,
        )
        try:
            yield
        finally:
            if owns_client:
                await client.aclose()
            await database.close()
            logger.info("flashrouter_stopped")

    app = FastAPI(
        title="FlashRouter",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
            openapi_url="/api/openapi.json",
    )

    if ui_dist is not None and (ui_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(ui_dist / "assets")), name="assets")

    @app.middleware("http")
    async def context_and_guards(request: Request, call_next):
        request.state.request_id = new_request_id()
        path = request.url.path

        # CSRF: block cross-site browser requests to the admin API.
        if path.startswith("/admin/api") and request.method in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }:
            expected = f"{request.url.scheme}://{request.url.netloc}"
            origin = request.headers.get("origin")
            referer = request.headers.get("referer")
            if origin and origin != expected:
                return JSONResponse(
                    status_code=403,
                    content=error_body("Cross-site admin request blocked", code="csrf_failed"),
                )
            if not origin and referer:
                ref = urlparse(referer)
                if f"{ref.scheme}://{ref.netloc}" != expected:
                    return JSONResponse(
                        status_code=403,
                        content=error_body(
                            "Cross-site admin request blocked", code="csrf_failed"
                        ),
                    )

        # Optional admin token.
        admin_token = settings.admin.token
        if admin_token and path.startswith("/admin/api"):
            exempt = {"/admin/api/health"}
            if path not in exempt:
                supplied = request.headers.get("x-admin-token", "")
                if supplied != admin_token:
                    return JSONResponse(
                        status_code=401,
                        content=error_body(
                            "Admin token required",
                            error_type="authentication_error",
                            code="admin_token_required",
                        ),
                    )

        response = await call_next(request)
        response.headers.setdefault("X-FlashRouter-Request-ID", request.state.request_id)
        return response

    @app.exception_handler(GatewayError)
    async def gateway_error_handler(request: Request, exc: GatewayError) -> JSONResponse:
        headers = dict(exc.headers)
        request_id = getattr(request.state, "request_id", None)
        if request_id:
            headers["X-FlashRouter-Request-ID"] = request_id
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(
                exc.message, error_type=exc.type, code=exc.code, param=exc.param
            ),
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error")
        return JSONResponse(
            status_code=500,
            content=error_body(
                "Internal gateway error", error_type="server_error", code="internal_error"
            ),
        )

    app.include_router(inference_router)
    app.include_router(admin_router)

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/", include_in_schema=False)
    @app.get("/dashboard", include_in_schema=False)
    async def dashboard():
        if ui_dist is not None:
            return FileResponse(str(ui_dist / "index.html"))
        return HTMLResponse(_FALLBACK_HTML)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        first = full_path.split("/", 1)[0]
        if first in {"v1", "admin", "healthz", "api", "assets"}:
            return JSONResponse(
                status_code=404,
                content=error_body("Not found", code="not_found"),
            )
        if ui_dist is not None:
            return FileResponse(str(ui_dist / "index.html"))
        return HTMLResponse(_FALLBACK_HTML)

    return app

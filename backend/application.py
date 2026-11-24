from contextlib import asynccontextmanager
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .api import api_router, page_router
from .config import Settings
from .services import Services

class UploadBodyLimit:
    """Reject an oversized multipart body while it is arriving, before parsing it."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/geo/jobs" or scope.get("method") != "POST":
            return await self.app(scope, receive, send)
        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise UploadTooLarge
            return message

        async def tracked_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        too_large = False
        try:
            await self.app(scope, limited_receive, tracked_send)
        except* UploadTooLarge:
            too_large = True
        if too_large:
            if response_started:
                raise RuntimeError("Upload excedeu o limite apos o inicio da resposta.")
            await PlainTextResponse("Upload acima do limite configurado.", status_code=413)(scope, receive, send)


class UploadTooLarge(Exception):
    pass


def create_app(settings: Settings | None = None, services: Services | None = None):
    settings = settings or Settings.from_env()
    os.environ.setdefault("GEOCNPJ_GEO_RUNTIME_DIR", str(settings.data_dir / "geo_runtime"))
    from geo_engine.main import app as geo_app

    @asynccontextmanager
    async def lifespan(app):
        active_services = services or Services.build(settings)
        active_services.startup()
        app.state.services = active_services
        try:
            yield
        finally:
            active_services.shutdown()

    app = FastAPI(title="GeoCNPJ", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8092", "http://localhost:8092"],
        allow_methods=["*"], allow_headers=["*"],
    )
    @app.middleware("http")
    async def protect_local_writes(request: Request, call_next):
        if request.method == "POST" and request.url.path == "/geo/jobs":
            size = request.headers.get("content-length")
            if size and size.isdigit():
                from geo_engine.main import MAX_UPLOAD_BYTES
                if int(size) > MAX_UPLOAD_BYTES + 1024 * 1024:
                    return PlainTextResponse("Upload acima do limite configurado.", status_code=413)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith(("/api", "/geo")):
            origin = request.headers.get("origin")
            if origin:
                parsed = urlsplit(origin)
                same_origin = (parsed.scheme == request.url.scheme and parsed.netloc == request.url.netloc)
                if not same_origin:
                    return PlainTextResponse("Origem não autorizada.", status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return PlainTextResponse("Requisição externa não autorizada.", status_code=403)
        return await call_next(request)

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    from geo_engine.main import MAX_UPLOAD_BYTES
    app.add_middleware(UploadBodyLimit, max_bytes=MAX_UPLOAD_BYTES + 1024 * 1024)
    app.mount("/assets", StaticFiles(directory=settings.frontend_dir / "assets"), name="assets")
    app.mount("/geo", geo_app, name="geo")
    app.include_router(page_router)
    app.include_router(api_router)

    @app.get("/api/health", tags=["sistema"])
    def health():
        return {"ok": True, "app": "GeoCNPJ", "project_root": str(settings.base_dir.resolve()), "data_dir": str(settings.data_dir)}

    return app

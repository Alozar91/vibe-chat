import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from app.config import get_settings
from app.core.errors import install_error_handlers
from app.core.valkey import close_valkey, get_valkey
from app.db.session import dispose_engine
from app.db.session import engine as db_engine
from app.log import setup_logging
from app.modules.admin.router import router as admin_router
from app.modules.auth.router import router as auth_router
from app.modules.bots.router import router as bots_router
from app.modules.chats.router import invites_router
from app.modules.chats.router import router as chats_router
from app.modules.media.router import router as media_router
from app.modules.messages.router import router as messages_router
from app.modules.notifications.router import router as devices_router
from app.modules.realtime import hub
from app.modules.realtime.router import router as ws_router
from app.modules.search.router import router as search_router
from app.modules.users.router import router as users_router

logger = logging.getLogger("vibe")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    settings = get_settings()
    setup_logging(settings.log_level)
    task = asyncio.create_task(hub.listen_valkey())
    try:
        yield
    finally:
        task.cancel()
        await close_valkey()
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Vibe.Chat API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info(
            "%s %s -> %s (%sms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    install_error_handlers(app)
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> Response:
        try:
            async with db_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await get_valkey().ping()
            return JSONResponse(content={"status": "ok"})
        except Exception as exc:
            return JSONResponse(status_code=503, content={"status": "degraded", "error": str(exc)})

    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(chats_router)
    app.include_router(invites_router)
    app.include_router(messages_router)
    app.include_router(media_router)
    app.include_router(devices_router)
    app.include_router(bots_router)
    app.include_router(search_router)
    app.include_router(admin_router)
    app.include_router(ws_router)
    return app


app = create_app()

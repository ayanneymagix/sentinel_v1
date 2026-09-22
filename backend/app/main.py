import asyncio
import sys
from contextlib import asynccontextmanager

# Silence Windows asyncio ConnectionResetError [WinError 10054] on client disconnects
if sys.platform == "win32":
    try:
        from asyncio.proactor_events import _ProactorBasePipeTransport
        _orig_call_connection_lost = _ProactorBasePipeTransport._call_connection_lost

        def _silence_connection_lost(self, exc):
            try:
                _orig_call_connection_lost(self, exc)
            except (ConnectionResetError, OSError):
                pass

        _ProactorBasePipeTransport._call_connection_lost = _silence_connection_lost
    except Exception:
        pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database.postgres import postgres
from app.database.redis import redis_client
from app.routers.events import router as events_router
from app.routers.health import router as health_router
from app.routers.tracking import router as tracking_router
from app.routers.watchlist import router as watchlist_router
from app.routers.websocket import router as websocket_router
from app.routers.cross_camera import router as cross_camera_router
from app.workers.event_worker import worker_loop


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):

    print("[Sentinel] Starting backend...")

    try:
        await postgres.connect()
        print("[Sentinel] PostgreSQL connected")
    except Exception as exc:
        print(f"[Sentinel] WARNING: PostgreSQL offline ({exc}). Backend running in standalone/proxy mode.")

    worker_task = None
    try:
        await redis_client.connect()
        print(
            "[Sentinel] Redis connected"
        )
        worker_task = asyncio.create_task(worker_loop())
        print(
            "[Sentinel] Event Worker background task active"
        )
    except Exception as exc:
        print(
            f"[Sentinel] WARNING: Redis offline ({exc}). Backend running without Redis streams/pubsub."
        )

    yield

    print(
        "[Sentinel] Shutting down..."
    )

    if worker_task:
        worker_task.cancel()
        try:
            await worker_task
        except (asyncio.CancelledError, Exception):
            pass

    await redis_client.disconnect()

    await postgres.disconnect()


app = FastAPI(
    title="Sentinel API",
    description=(
        "Edge-Cloud AI Surveillance "
        "Intelligence Platform — Gujarat Police Hackathon"
    ),
    version="1.0.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,

    allow_origins=["*"],

    allow_credentials=True,

    allow_methods=[
        "GET",
        "POST",
        "PUT",
        "DELETE",
        "OPTIONS",
    ],

    allow_headers=["*"],
)


app.include_router(
    health_router,
    prefix="/api",
)

app.include_router(
    events_router,
    prefix="/api",
)

app.include_router(
    events_router,
    prefix="/api/v1",
)

from pathlib import Path
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.routers.cameras import router as cameras_router

# Authoritative Dynamic Camera Registry & Telemetry APIs
app.include_router(
    cameras_router,
)

app.include_router(
    tracking_router,
    prefix="/api/v1",
)

app.include_router(
    watchlist_router,
    prefix="/api/v1",
)

app.include_router(
    cross_camera_router,
    prefix="/api/v1",
)

app.include_router(
    cross_camera_router,
    prefix="/api",
)

app.include_router(
    websocket_router,
)

frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    app.mount("/dashboard", StaticFiles(directory=str(frontend_dist), html=True), name="dashboard")

    @app.get("/")
    async def root():
        return RedirectResponse(url="/dashboard/")
else:
    @app.get("/")
    async def root():
        return {
            "service": "Sentinel",
            "status": "online",
            "version": "1.0.0",
        }
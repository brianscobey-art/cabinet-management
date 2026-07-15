import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.accounts import router as accounts_router
from app.api.documents import router as documents_router
from app.api.jobs import router as jobs_router
from app.api.notes import router as notes_router
from app.api.ordering import router as ordering_router
from app.api.orders import router as orders_router
from app.api.phases import router as phases_router
from app.api.quotes import router as quotes_router
from app.api.reports import router as reports_router
from app.api.schedule import router as schedule_router
from app.api.selections import router as selections_router
from app.api.sync import router as sync_router
from app.auth.router import router as auth_router
from app.config import get_settings

logger = logging.getLogger("uvicorn.error")


def _run_feed_sync() -> None:
    from app.database import SessionLocal
    from app.feeds import sync_all

    try:
        with SessionLocal() as db:
            result = sync_all(db)
        logger.info("Daily feed sync: %s", result)
    except Exception:
        logger.exception("Daily feed sync failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    scheduler = None
    if settings.feed_sync_enabled and Path(settings.vendorsuite_dir).is_dir():
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler()
        scheduler.add_job(_run_feed_sync, "cron", hour=settings.feed_sync_hour, minute=0)
        scheduler.start()
        logger.info("Feed sync scheduled daily at %02d:00", settings.feed_sync_hour)
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Carter Kitchen and Bath", version="0.1.0", lifespan=lifespan)


class StripApiPrefix:
    """Accept the same routes under /api/ — the frontend always calls /api/*.

    In dev, Vite proxies /api/* here after stripping the prefix; when this app
    serves the built frontend directly, this shim does the stripping instead.
    """

    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/api/"):
            scope = dict(scope)
            scope["path"] = scope["path"][4:]
            scope["raw_path"] = scope["path"].encode()
        await self.asgi_app(scope, receive, send)


app.add_middleware(StripApiPrefix)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(jobs_router)
app.include_router(selections_router)
app.include_router(quotes_router)
app.include_router(orders_router)
app.include_router(documents_router)
app.include_router(ordering_router)
app.include_router(sync_router)
app.include_router(schedule_router)
app.include_router(phases_router)
app.include_router(reports_router)
app.include_router(notes_router)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


# Serve the built frontend (frontend/dist) when present — single-port deployment.
# Mounts resolve after routes, so API paths always win.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")

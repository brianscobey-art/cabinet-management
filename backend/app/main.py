import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.accounts import router as accounts_router
from app.api.autobot import router as autobot_router
from app.api.documents import router as documents_router
from app.api.fieldmeasure import router as fieldmeasure_router
from app.api.jobs import router as jobs_router
from app.api.notes import router as notes_router
from app.api.ordering import router as ordering_router
from app.api.ordering_platform import router as ordering_platform_router
from app.api.orders import router as orders_router
from app.api.phases import router as phases_router
from app.api.quotes import router as quotes_router
from app.api.reports import router as reports_router
from app.api.schedule import router as schedule_router
from app.api.selections import router as selections_router
from app.api.service import router as service_router
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


def _run_autobot_sync() -> None:
    from datetime import date

    from app.autobot import auto_assign, generate_visits, geocode_missing_job_pins
    from app.database import SessionLocal

    try:
        with SessionLocal() as db:
            created = generate_visits(db, date.today(), created_by="auto-sync")
            assigned = auto_assign(db)
            pinned = geocode_missing_job_pins(db, limit=25)
        if created or assigned or pinned:
            logger.info(
                "Autobot auto-sync spawned=%s assigned=%s house-pins=%s", created, assigned, pinned
            )
    except Exception:
        logger.exception("Autobot auto-sync failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # Cloud disks (e.g. Render's /data) mount empty — make sure the generated-files
    # directory exists before any order/export tries to write into it.
    Path(settings.generated_dir).mkdir(parents=True, exist_ok=True)
    scheduler = None
    jobs = []
    if settings.feed_sync_enabled and (Path(settings.vendorsuite_dir).is_dir() or settings.r2_enabled):
        for hr in settings.feed_sync_hour_list:
            jobs.append(lambda s, h=hr: s.add_job(_run_feed_sync, "cron", hour=h, minute=0))
        logger.info(
            "Feed sync scheduled at %s (%s)",
            ", ".join(f"{h:02d}:00" for h in settings.feed_sync_hour_list),
            settings.feed_sync_tz,
        )
    if settings.autobot_sync_minutes > 0:
        jobs.append(lambda s: s.add_job(
            _run_autobot_sync, "interval", minutes=settings.autobot_sync_minutes
        ))
        logger.info("Autobot auto-sync every %d min", settings.autobot_sync_minutes)
    if jobs:
        from zoneinfo import ZoneInfo

        from apscheduler.schedulers.background import BackgroundScheduler

        try:
            tz = ZoneInfo(settings.feed_sync_tz)
        except Exception:  # noqa: BLE001 — bad tz name shouldn't crash startup
            logger.warning("Unknown feed_sync_tz %r; using UTC", settings.feed_sync_tz)
            tz = ZoneInfo("UTC")
        scheduler = BackgroundScheduler(timezone=tz)
        for add in jobs:
            add(scheduler)
        scheduler.start()
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
app.include_router(ordering_platform_router)
app.include_router(sync_router)
app.include_router(schedule_router)
app.include_router(phases_router)
app.include_router(reports_router)
app.include_router(notes_router)
app.include_router(fieldmeasure_router)
app.include_router(service_router)
app.include_router(autobot_router)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


# The Ordering Platform is a self-contained page (not part of the React bundle);
# registered as a route so it wins over the frontend static mount.
_static = Path(__file__).resolve().parent / "static"


@app.get("/ordering-platform", include_in_schema=False)
def ordering_platform_page():
    from fastapi.responses import FileResponse

    return FileResponse(_static / "ordering_platform.html")


# Autobot is the service tech's standalone app — its own login, its own PWA
# install, none of the office UI. Same backend, same database.
@app.get("/autobot", include_in_schema=False)
def autobot_page():
    from fastapi.responses import FileResponse

    return FileResponse(_static / "autobot.html")


@app.get("/autobot/manifest.webmanifest", include_in_schema=False)
def autobot_manifest():
    from fastapi.responses import FileResponse

    return FileResponse(_static / "autobot.webmanifest", media_type="application/manifest+json")


@app.get("/autobot/icon-{size}.png", include_in_schema=False)
def autobot_icon(size: int):
    from fastapi.responses import FileResponse

    if size not in (180, 192, 512):
        from fastapi import HTTPException

        raise HTTPException(404)
    return FileResponse(_static / f"autobot-icon-{size}.png")


# Serve the built frontend (frontend/dist) when present — single-port deployment.
# Mounts resolve after routes, so API paths always win.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")

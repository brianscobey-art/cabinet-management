from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.accounts import router as accounts_router
from app.api.documents import router as documents_router
from app.api.jobs import router as jobs_router
from app.api.orders import router as orders_router
from app.api.quotes import router as quotes_router
from app.api.selections import router as selections_router
from app.auth.router import router as auth_router
from app.config import get_settings

app = FastAPI(title="Carter Kitchen and Bath", version="0.1.0")


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


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


# Serve the built frontend (frontend/dist) when present — single-port deployment.
# Mounts resolve after routes, so API paths always win.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")

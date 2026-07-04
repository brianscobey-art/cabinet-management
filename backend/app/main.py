from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.accounts import router as accounts_router
from app.api.documents import router as documents_router
from app.api.jobs import router as jobs_router
from app.api.orders import router as orders_router
from app.api.quotes import router as quotes_router
from app.api.selections import router as selections_router
from app.auth.router import router as auth_router
from app.config import get_settings

app = FastAPI(title="Cabinet Management System", version="0.1.0")

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

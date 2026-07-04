# Backend — Cabinet Management System

FastAPI + SQLAlchemy + Alembic. Phase 0 scope: auth (JWT), roles, user admin, health check.

## Run locally (no Docker)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head                      # creates dev.db (SQLite) by default
python -m scripts.create_user you@townsendbuildingsupply.com "Your Name" admin
uvicorn app.main:app --reload             # http://localhost:8000, docs at /docs
```

Set `DATABASE_URL` in the repo-root `.env` to point at Postgres instead (see `.env.example`).

## Tests

```powershell
pytest
```

Tests run against in-memory SQLite; no external services.

## Roles

`sales`, `field`, `installer_coordinator`, `inspector`, `admin`. Guard endpoints with
`Depends(require_roles(Role.admin, ...))` from `app/auth/deps.py`.

## Migrations

Every schema change goes through Alembic:

```powershell
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

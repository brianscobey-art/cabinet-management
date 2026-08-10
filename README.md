# Carter Kitchen and Bath

One system for the entire cabinet lifecycle at Carter Lumber:
**quote → field measure → order → delivery → install → quality → punch → warranty/service**,
plus community phase tracking and a management dashboard.

Full spec: [CLAUDE.md](CLAUDE.md). Current status: **Phase 0 — Foundation** (auth, roles, app shell).

## Layout

| Path | What |
|---|---|
| `backend/` | FastAPI + SQLAlchemy + Alembic API ([README](backend/README.md)) |
| `frontend/` | React + Vite PWA ([README](frontend/README.md)) |
| `docker-compose.yml` | Postgres + backend + frontend for dockerized dev |

## Quick start (no Docker)

```powershell
# 1. Backend
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head
python -m scripts.create_user you@carterlumber.com "Your Name" admin
uvicorn app.main:app --reload

# 2. Frontend (second terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and sign in with the user you created.

## With Docker

```powershell
copy .env.example .env    # then edit SECRET_KEY etc.
docker compose up --build
```

## Configuration

Copy `.env.example` → `.env`. Secrets only ever live in `.env` / Azure Key Vault — never in code.
Without a `DATABASE_URL` the backend uses a local SQLite file (`backend/dev.db`) so you can develop
without Docker/Postgres; production and dockerized dev use PostgreSQL.

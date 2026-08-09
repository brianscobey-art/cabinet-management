# Cloud Deployment — independent, self-serve (no corporate IT)

This moves **Carter Kitchen and Bath** off the local PC + Tailscale setup onto a
managed host on **your own accounts**. Target stack:

- **Render** — hosts the app (Docker) + a **managed Postgres**, deploys from GitHub.
- **Cloudflare R2** — object storage for feed files + job documents (Phase 2 below).
- **Anthropic API** — powers the in-app AI assistant (Phase 3 below).

Estimated cost: **~$15–30/month** (Render web service + Postgres; R2 is a few
dollars once added).

The repo is already deploy-ready: `Dockerfile` builds the frontend and serves it
from the FastAPI backend on one port, runs `alembic upgrade head` on every boot,
reads `DATABASE_URL`/`SECRET_KEY` from the environment, and normalizes Render's
`postgres://` URL for SQLAlchemy. `render.yaml` wires the web service to a managed
Postgres and a 5 GB persistent disk.

> The steps below need **your** accounts and credentials — creating accounts,
> pushing to your GitHub, and provisioning the database are yours to do. Claude
> prepared the code and this runbook but cannot create accounts or push on your
> behalf.

---

## Phase 1 — Go live on Render (do this now)

### 1. Put the code in a private GitHub repo
Create a **private** repo under your personal GitHub, then from `cabinet-management/`:

```bash
git remote add origin https://github.com/<you>/cabinet-management.git
git push -u origin HEAD
```

`.gitignore` already excludes `.env`, `*.db`, `node_modules`, and `frontend/dist`,
so no secrets or build junk get pushed.

### 2. Deploy the Blueprint
In Render: **New + → Blueprint → connect the repo**. Render reads `render.yaml`
and provisions:
- the web service `carter-kitchen-and-bath` (builds the Dockerfile), and
- the managed Postgres `carter-kb-db`, injecting `DATABASE_URL` automatically.

`SECRET_KEY` is auto-generated. Add any optional keys under the service's
**Environment** (see `backend/.env.example`): `GOOGLE_MAPS_API_KEY`,
`DOMO_ACCESS_TOKEN`. First build takes a few minutes; the app comes up at
`https://carter-kitchen-and-bath.onrender.com` and `alembic upgrade head` creates
the schema on the fresh Postgres.

### 3. Create your login
The new database is empty. Create an admin user (Render service → **Shell**):

```bash
cd backend && python -m scripts.create_user
```

(Or run it locally against the external DB URL from Step 4.)

### 4. Bring your existing data over (optional but recommended)
To carry the ~600 jobs, service requests, workers, etc. from the local `dev.db`
into cloud Postgres:

1. Render → the **carter-kb-db** database → copy its **External Database URL**.
2. From `cabinet-management/backend/` on the PC (with the app's venv active):

```bash
python -m scripts.migrate_to_postgres "postgresql://USER:PASS@HOST:PORT/DB"
```

It refuses to run unless the target is empty, copies every table in
foreign-key order, and resets Postgres sequences so new inserts don't collide.
If you already created the admin user in Step 3, either do the data copy first
(into a truly empty DB) or create the admin user *after* migrating.

### 5. Custom domain + TLS (optional)
Buy a domain (~$12/yr) and add it under the Render service → **Settings →
Custom Domains**; Render issues TLS automatically. Then retire the Tailscale
Funnel and the `run-server.bat` watchdog on the PC.

### What works vs. what waits
- ✅ Everything users touch in the browser — Jobs, Ordering, Schedule, Phases,
  Forms, Reports, Service Requests, Autobot — runs in the cloud immediately.
- ⏳ The **daily tracker / Vendor Suite / Century sync** reads OneDrive folders
  that only exist on the PC. In the cloud it simply finds no files (it fails
  soft, nothing crashes). Phase 2 restores it.

---

## Phase 2 — Files to R2, so the feeds keep working (built ✓)

The tracker `.xlsm`, the VS Combined / Century reports, and the New Orders file
live in OneDrive, which the cloud app can't see. The bridge is now in the code:
an on-prem uploader pushes those files to **Cloudflare R2**, and the cloud app
pulls the newest of each into its feed dirs before every sync. Setup:

### 1. Create the R2 bucket + API token
Cloudflare dashboard → **R2** → create a bucket (e.g. `carter-kb-feeds`) → **Manage
R2 API Tokens** → create a token with **Object Read & Write**. Note the endpoint
`https://<accountid>.r2.cloudflarestorage.com`, the access key id, and the secret.

### 2. Set the R2 env vars in Render
On the web service → **Environment**, add (see `backend/.env.example`):
`R2_ENDPOINT`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`. Also point
the feed dirs at the persistent disk so the pulled files land somewhere writable:
`TRACKER_DIR=/data/feeds/tracker`, `VENDORSUITE_DIR=/data/feeds/vendorsuite`,
`CENTURY_DIR=/data/feeds/century`, `NEW_ORDERS_FILE=/data/feeds/new-orders/New Orders Status.xlsx`.
Once R2 is set, the daily sync (and the **Update** button) hydrate from R2 first,
then run exactly as before.

### 3. Run the uploader on the PC
On the machine with OneDrive synced, set the same four `R2_*` vars (in
`backend/.env` or the Task Scheduler action), then:

```bash
cd backend && python -m scripts.upload_feeds_to_r2
```

Schedule it in **Windows Task Scheduler** — every 30 min, or once after the cloud
reports land (~6 AM). It pushes only the newest few files per feed and skips
anything already in R2 with the same size. This tiny uploader is the only piece
that stays on the PC; everything else runs in the cloud.

### 4. Push job documents too (PDFs/photos on the job page)
Job documents are stored by their OneDrive path, which the cloud can't resolve —
so they go to R2 the same way. The serving endpoint already falls back to R2 when
the local file isn't present. To seed them, run on the PC (with `DATABASE_URL`
pointed at the cloud Postgres so it uploads exactly the docs the app knows about):

```bash
cd backend && python -m scripts.upload_documents_to_r2
```

Re-run it (or schedule it) whenever new documents are attached. Skips anything
already in R2 with the same size.

---

## Phase 3 — In-app AI assistant (future update)

A chat panel in the app backed by the Anthropic API (`claude-opus-5`) that can:
generate custom reports (read-only), create report/document templates, and make
**gated** database changes (preview + confirm + audit, through the same
validated endpoints the UI uses). Set `ANTHROPIC_API_KEY` in the Render
environment when this phase ships. Design notes: it runs inside the existing
FastAPI backend as a server-side tool-use loop — no new infrastructure.

---

## Operating notes

- **Backups:** turn on automatic backups for the Render Postgres.
- **Scheduler:** the app's daily sync uses in-process APScheduler, so keep the
  service on a paid (always-on) plan — no scale-to-zero.
- **Secrets:** all live in Render's env-var UI; nothing is committed. Register
  the domain and cloud accounts under identities you control — this data lives
  outside any corporate backup or governance, so that's your responsibility.
- **Redeploys:** every `git push` to the connected branch auto-deploys and
  re-runs migrations.

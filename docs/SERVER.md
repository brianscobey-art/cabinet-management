# Moving Carter Kitchen and Bath to a dedicated server PC

The app is one folder + one command, so the move is mostly copying and
re-pointing paths. Target: a Windows desktop that stays on 24/7.

## 1. Prerequisites on the server

- **Python 3.13+** (python.org installer, check "Add to PATH")
- **OneDrive** signed into the same account, syncing:
  - `Townsend Kitchen and Bath - Master Plans & Pricing` (job PDFs — mark "Always keep on this device")
  - `Townsend Shared File` (Vendor Suite / Century / New Orders feeds)
  - `Carter Kitchen and Bath` (generated orders + DB backups)
- **Tailscale** signed into the same tailnet (this is how the team reaches it)
- Node is NOT needed — the built frontend (`frontend/dist`) ships with the folder

## 2. Copy the app

Copy `cabinet-management\` to the server (e.g. `C:\CarterKB\cabinet-management`),
**excluding** `backend\.venv` and `frontend\node_modules`. Include `backend\dev.db`
(the live database) and `frontend\dist`.

## 3. Set up Python

```powershell
cd C:\CarterKB\cabinet-management\backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## 4. Re-point paths

`backend\.env` — copy from the old machine, then update any path that contains
the old username (`C:\Users\Brian SE6\...` -> the server's OneDrive paths):
`GENERATED_DIR`, and add overrides for `VENDORSUITE_DIR`, `CENTURY_DIR`,
`NEW_ORDERS_FILE` (defaults live in `app/config.py`).

Document paths stored in the database:

```powershell
.venv\Scripts\python -m scripts.rewrite_doc_paths "C:\Users\Brian SE6\OneDrive - carterlumber.com" "<server OneDrive root>" --apply
```

Also update the backup folder path (`BK=`) inside `run-server.bat`.

## 5. Run it — as a service, not a logon task

For a real server, use Task Scheduler set to run **at startup** (no login needed):

```powershell
schtasks /Create /F /SC ONSTART /RU SYSTEM /TN "Carter KB Server" /TR '"C:\CarterKB\cabinet-management\run-server.bat"'
```

Verify: `curl http://localhost:8000/health` after a reboot.

## 6. Team access

`tailscale status` on the server shows its name/IP — the team URL becomes
`http://<server-name>.tail6ad443.ts.net:8000`. Old bookmarks to brian-cmdctr
need updating. Optionally `tailscale funnel --bg 8000` for a public HTTPS URL.

## 7. Decommission the old machine

- Remove the "Carter KB Server" scheduled task on Brian's PC (if created)
- Keep the old `dev.db` as a dated backup in OneDrive
- The DB backup on every server start continues automatically via run-server.bat

## Later upgrades that get easier on a dedicated box

- **PostgreSQL** instead of SQLite: install Postgres, set `DATABASE_URL` in
  `.env`, run `alembic upgrade head`, re-run the importers (or migrate data).
- **HTTPS + real domain** via Tailscale Funnel or a reverse proxy.
- The Render/Azure configs in the repo root remain the cloud exit ramp.

# Carter Kitchen and Bath — Handoff (2026-08-04)

Continuation notes for picking this up in a new chat. Read `CLAUDE.md` for the full product
spec; this file is the "where we are right now + how to work on it" cheat sheet.

## 1. What it is / how it runs

- **App**: `Carter Kitchen and Bath` — cabinet lifecycle web app for Brian (K&B manager, Carter Lumber).
- **Stack**: FastAPI + SQLAlchemy 2.0 + Alembic (backend), React + Vite + TypeScript **PWA** (frontend, hash routing). SQLite `backend/dev.db` in dev (Postgres-ready; all schema via Alembic).
- **Serving**: the backend **serves the built frontend** from `frontend/dist` on **`http://localhost:8000`**. There is no separate prod frontend server. In dev you can also run Vite (`npm run dev`, proxies `/api` → :8000), but the deployed app = backend serving `dist`.
- **Hosting (pilot)**: Brian's PC `brian-cmdctr`, exposed publicly via **Tailscale Funnel → `https://brian-cmdctr.tail6ad443.ts.net`** (also `http://100.89.50.96:8000`, `localhost:8000`). `run-server.bat` = watchdog loop that keeps :8000 alive + backs up dev.db to OneDrive; auto-starts on login.
- **Auth**: JWT login form; roles `admin | sales | field | installer_coordinator | inspector`. Write access varies by feature (service/phase writes allow field roles).
- Migration head at handoff: **`c9d0e1f2a3b4`**. Server is running on :8000.

## 2. Dev workflow (what I've been doing every change)

```bash
# frontend change → rebuild the dist the backend serves
cd frontend && npm run build            # tsc + vite; watch for "error TS"
# backend change (models/endpoints) → restart the :8000 process
# (kill the listener; run-server.bat watchdog usually relaunches, else run it)
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 8000 -State Listen -EA SilentlyContinue|Select -First 1; if($c){Stop-Process -Id $c.OwningProcess -Force}"
# then poll:  curl -s http://localhost:8000/api/health
# schema change:
cd backend && ./.venv/Scripts/python.exe -m alembic upgrade head
```

- **Verifying in a browser without a password**: I mint a JWT server-side and inject it into `localStorage.cms_token`, rather than typing a password (entering passwords into forms is disallowed). Snippet:
  ```python
  from app.database import SessionLocal; from app.models import User
  from app.auth.security import create_access_token
  db=SessionLocal(); u=db.query(User).filter(User.is_active==True).first()
  print(create_access_token(u.email, u.role.value))   # sub = EMAIL (not id)
  ```
  Then in the preview browser: `localStorage.setItem("cms_token", "<jwt>")`.
- **Preview browser** = `mcp__Claude_Browser__*` pointed at `localhost:8000`. Screenshots often time out this session (pane not displayed) — verify via `read_page` / `javascript_tool` DOM checks instead.

## 3. ⚠️ Gotchas that cost real time

- **PWA service worker cache is the #1 trap.** The app precaches assets and serves them cache-first. **A hard refresh does NOT bypass a service worker** — the SW returns the old build. To see changes on a device you must clear/unregister the SW (or use the auto-update below). In the preview browser I always do:
  ```js
  const rs = await navigator.serviceWorker.getRegistrations(); await Promise.all(rs.map(r=>r.unregister()));
  await Promise.all((await caches.keys()).map(k=>caches.delete(k))); location.reload(true);
  ```
  **Just-added fix (commit `59bb007`, `frontend/src/main.tsx`)**: the app now auto-reloads when a new SW takes control + checks for updates on load/focus/30-min. **But it needs ONE manual reset on each existing device to pick up the fix** (old running code has no auto-reload). Phone PWA: delete + re-add the home-screen icon. After that, updates are automatic. **Brian has not confirmed doing the reset**, so on-screen changes may still look stale on his devices — the server IS serving the latest (verify by curling the built CSS/JS).
- **LF→CRLF git warnings** on Windows are harmless.
- **`.claude/`, logs, `*.tsbuildinfo`** are gitignored (see `c06f6cc`).

## 4. Domo cost data (P&L reports)

- Instance `carterlumber.domo.com`, dataset `c9b70636-b093-4bcd-90e4-8f4b99e12df5` (Sales Details PDP).
- **Server-side pull is blocked** — Brian's Domo account is viewer-level and can't mint an access token. So the flow is **browser-pull → file → import**:
  - `Downloads/domo-kb-tool/domo-cost-pull.js` — paste in Domo console (logged in) → downloads `KB Domo Raw MMDDYY.json` → move into `Downloads/domo-kb-tool/`.
  - `Downloads/domo-kb-tool/domo-txn-pull.js` — dated transactions for the "Domo P&L by Period" report.
  - App: Reports → **Job Cost P&L** → **Update from Domo** imports the newest raw dump (prefers a live token if one is ever added to `backend/.env` as `DOMO_ACCESS_TOKEN`).
- **Key modeling facts baked in** (`backend/app/domo.py`, `jobcosts.py`):
  - A house's dollars live on its **I-code while active**, rebilled to its **G-code when complete** — the pull **combines both** per house.
  - Installed-sales job codes are **whole-house (all trades)**, so product is restricted to **product category = "Kitchen and Bath"**; labor = C90xx SKUs.
  - Margin = product + **C9009** install labor + net of the other *real* non-C9009 cabinet labor. **C9091 (install-sales overhead) and C9002 (rebill) are "wash" codes — excluded from margin** (they net ~$0 company-wide but dump cost on cabinet jobs). Shown for transparency only.
  - **DR Horton revenue override**: for DRH jobs, revenue = the **actual paid PO amount** from the `DRH_Cabinets_Combined` report (VS feed), not Domo product sales (Domo posts $0 product on many DRH houses). Rule in `jobcosts.drh_po_revenue` / `DRH_PO_EXCLUDED_STATUSES = {"voided"}`.
- Known data-quality caveat: ~10 jobs have **duplicate/misassigned g/i codes** (a bare `G7530172`, codes used as both a G and an I, some `N/A`s) that slightly over-count. Cleanup was offered, not done.

## 5. Reports (Reports tab → categorized dropdown)

Backend `backend/app/api/reports.py`, frontend `frontend/src/pages/ReportsPage.tsx` (categorized card index: **Accounting / Operations / Sales**).
- **Accounting**: Job Cost P&L (Domo), Domo P&L by Period (builder/job/window/quarter/half/YTD/YoY, backed by `domo_txns`; "Calculate from last Domo pull" install-dates the JobCost snapshot when no txn file), Labor on Non-C9009 Codes, PO Status Summary.
- **Operations**: Phase Report, Install Schedule by Week, Needs Ordering, **Open Service Requests** (newest).
- **Sales**: Revenue by Builder & Community, Revenue by Salesperson, Open PO Report.

## 6. Service Requests — the current focus of the last many turns

Data model `backend/app/models/service.py`: `ServiceRequest` (title, status, `material_status`, `scheduled_date`, created_by/at) → `ServicePart` (part, cabinet, style, color, vendor, order_number, order_date, due_date, qty, notes) + `ServiceLine` (part_id, instruction, done/done_by/done_at, note). Endpoints in `backend/app/api/service.py`.

- **Status values**: `Installed | Warranty | Service Empty | Service Occupied`. **Material status**: `Not Ordered | Ordered | Received | N/A`. Both editable in the editor header, plus a **Scheduled** completion date.
- **Where to create one**:
  - Job detail page (`JobDetailPage`) — a service requests section per job.
  - **Forms tab → "Service Request Form"** (`#/forms/service`, `ServiceFormsPage`): pick builder→community→lot or search job code → creates one; **Print a blank** (`#/service-blank`, `BlankServiceForm`); **Download Excel template**; **Import filled Excel**.
- **Editor + printable report**: `frontend/src/pages/ServiceRequestPage.tsx` holds both the interactive editor **and** the `ServiceReportPrint` component (exported; reused for the blank form with `blank`/`screen` props). Layout mirrors a QC checklist: header (SERVICE REQUEST + logo + "Carter Kitchen and Bath"), **boxed** PROJECT/ADDRESS/LOT/JOB CODE/DATE/STATUS info grid (left-aligned), **Cabinet Specifications & Hardware** combined block (Room/Zone, Vendor, Series, Door Style, Color, Species, **Hardware Type** — hardware trimmed to just type), **Parts Needed** (Item#, Qty, Part, Cabinet, Style, Color, Vendor, Order#, Order Date, Due Date, Notes), **Service Needed** (Part#, Cabinet, Description, ✓, **Date, Tech**), one-line signatures, bottom footer.
  - **Colors are now LIGHT GRAY** section bars + column headers (not green), bar titles centered. Some Carter green accents remain (title/brand). CSS in `frontend/src/index.css` under `.qc-*` and `.service-*`.
  - **Print naming**: the Print button sets `document.title = "Service Request {job_code} {builder} {mmddyy}"` (names the PDF + replaces the browser header's redundant app title). Browser's own top date/URL headers can only be removed by the user's print-dialog "Headers and footers" toggle.
- **Excel template** (`backend/app/service_excel.py`): built on a **fine 60-column base grid**; each section merges cells to its own widths (so cabinet/parts/service don't share one grid). Gray bars to match online. Row 1 (above the print area) has a red **"FILE NAME"** cell + the naming rule `Service Request [Job Code] [Builder] [MMDDYY]`. Landscape, fit-to-one-page. **Round-trips**: `parse_import` reads Job Code + the Parts/Service tables by their base-column starts (`PART_STARTS`, `SERVICE_STARTS`) and creates a ServiceRequest matched to the job by Job Code. `POST /service-requests/import` (multipart), `GET /forms/service-template`.

## 7. Other recently-built features (context)

- **Phase Tracking** (`PhasesPage.tsx`, `api/phases.py`): builder→community board. Columns: Lot, Job code, Address, Plan, Current phase, Updated, **Field Measure {Requested | Completed}**, Correct / Incorrect / Super Notified checkboxes. Incorrect opens a dated+initialed note box; there's a **Field Measure Notes** section. Field-measure stamps show on the job detail page. **Re-selecting the same phase re-logs it** (bumps Updated) — the select keeps a neutral value so `onChange` always fires.
- **Field Measure** model/endpoints: `backend/app/models/fieldmeasure.py`, `api/fieldmeasure.py`.
- **Ordering board** (`OrderingPage.tsx`): pre-order worklist — hides jobs at `2.0-Ord` and beyond; "show ordered & completed" toggle.
- **Ordering Platform** (`ordering_platform.py`) + **daily feeds** (`feeds.py`: DRH VS Combined + Century SupplyPro) — see CLAUDE.md build status.
- **Mobile nav** wraps so no tabs are cut off (`App.tsx` header + `@media (max-width:720px)`).

## 8. Open / possible next items

- **Editable Cabinet & Hardware on the service request** — currently pulled **read-only from the job file**. Brian was asked whether he wants them editable with add-line buttons (deferred).
- **Excel exact-match tuning** — merge-grid is close; open the emailed `Service Request Template (preview).xlsx` and tune column spans in `COMBO_SPEC/PART_SPEC/SERVICE_SPEC/INFO_SPEC` if anything's off.
- **~10 mis-coded g/i-code jobs** cleanup (Domo P&L accuracy).
- **Domo access token** from an admin would enable one-click server-side P&L pulls (`backend/app/domo.py` is built + token-gated).
- **Confirm the PWA one-time reset** actually happened on Brian's devices; consider an on-screen "Updated — reloading…" toast when auto-update fires.
- Spec Phase 3+ still pending (DDMS delivery checks, quality/punch, warranty, dashboard, voice) — see CLAUDE.md §7.

## 9. Handy paths

- Backend venv python: `backend/.venv/Scripts/python.exe`
- Domo tools: `C:\Users\Brian SE6\Downloads\domo-kb-tool\` (pull scripts + `KB Domo Raw*.json`, `KB Job Costs*.json`, `KB Job Txns*.json`)
- DRH feed: `...\OneDrive - carterlumber.com\Townsend Shared File\AI Shared Folder\Vendor Suite\VS Combined PO and Schedules\DRH_Cabinets_Combined_*.xlsx`
- Logo: `frontend/public/carter-logo.png`; Carter colors: green `#125952`, orange `#df5822`, mint `#2bb99f`.

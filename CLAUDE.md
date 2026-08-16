# Cabinet Management System — Project Spec (Claude Code)

**Owner:** Brian, Kitchen & Bath Manager, Carter Lumber
**Purpose of this file:** This is the source of truth for what we're building. Read it fully before writing code. Build in the phases at the bottom — do **not** try to scaffold everything at once.

---

## 1. What we're building

A single end-to-end platform that runs the entire cabinet lifecycle for a production-builder + custom-remodel dealer operation: **quote → field measure → order → delivery → install → quality → punch → warranty/service**, plus live phase tracking across communities and a management dashboard.

Today these steps live in disconnected standalone automations (Python order scripts, Excel order forms, a separate installer scheduler, phase tracker workbooks). The goal is **one system, one data model, one job record** that every step reads from and writes to, so nobody has to go back to the salesperson two years later to find out what door style went in a master bath.

**Non-negotiables:**
- Web app, accessible from any browser across multiple offices and the field (FL Panhandle + Alabama).
- Mobile-friendly for iOS and Android (installable, works on a phone in a truck).
- Automate everything that a human currently re-keys. Humans make mistakes; the system shouldn't ask them to copy data twice.
- Voice input for field phase updates and office natural-language queries.
- Feeds Smartsheet so the rest of the company has visibility without logging into this app.

---

## 2. Recommended tech stack

Pick this stack unless you hit a hard blocker; it continues the tools Brian already uses (Python, Flask, openpyxl, Playwright, Smartsheet API).

| Layer | Choice | Why |
|---|---|---|
| **Backend** | Python + **FastAPI** | Continuation of existing Python automation; async; auto OpenAPI docs; easy to expose the endpoints the mobile/voice layers need. |
| **Database** | **PostgreSQL** | Real multi-user concurrency (Access falls over here), strong relational integrity, free, hosts anywhere. Use SQLAlchemy + Alembic migrations. |
| **Frontend** | **React + Vite**, built as a **PWA** (installable on iOS/Android home screen) | One responsive codebase covers desktop, tablet, and phone. PWA avoids maintaining separate App Store / Play Store builds up front. If native features are needed later, wrap in React Native — but do PWA first. |
| **Auth / roles** | JWT sessions, role-based (sales, field, installer-coordinator, inspector, admin) | Different people see and do different things. |
| **Notifications** | **Twilio** (SMS + voice) + **SendGrid/SMTP** (email) | Covers the email→text→voice escalation ladder. |
| **Voice capture** | Web Speech API in-browser for quick capture; **Whisper** (or Azure Speech) server-side for reliable field transcription | Field phase logging while driving. |
| **NL query** | Anthropic API (Claude) as a query-interpreter over a read-only view of the DB | "Where is Eddie today?" → structured query → spoken answer. |
| **Background jobs** | **Celery + Redis** (or APScheduler if we stay simple) | Nightly DDMS checks, escalation timers, the day-before delivery report. |
| **Hosting** | Azure (Brian is in the MS365 ecosystem) or any VPS. Azure SQL is an acceptable DB alternative if IT prefers it. | Keep it in an environment IT will support. |

> **Azure SQL alternative:** if corporate IT mandates Microsoft-only, swap Postgres → Azure SQL and keep everything else. The data model below is engine-agnostic.

---

## 3. Secrets & security (read before anything)

- **Never hardcode credentials.** All secrets go in `.env` / Azure Key Vault, loaded via env vars. `.env` is git-ignored.
- Smartsheet API token, Twilio keys, SendGrid key, Anthropic key, DB password → env vars only:
  `SMARTSHEET_API_TOKEN`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `SENDGRID_API_KEY`, `ANTHROPIC_API_KEY`, `DATABASE_URL`.
- Photos and job documents: store in object storage (S3 / Azure Blob), keep only URLs in the DB.
- The NL query layer must run against a **read-only** DB role — never let a spoken query mutate data.

---

## 4. Core data model

Design the schema first and migrate it before building features. Key entities and the relationships that matter:

**Account** — a builder (DR Horton division, Century, Jubilee) or a retail/remodel customer.
- Type: `builder` | `retail`. A builder has many Jobs; a retail customer typically has one.

**Job** — the central record everything hangs off.
- `account_id`, `community_id` (nullable for retail), `lot_number`, `address`, `job_type`, `status` (workflow stage), `install_date`, `warranty_start_date`.
- **Two contacts per job, set at creation:** `sales_contact` (whoever's paying / billing) and `field_contact` (who gets called about measure/install issues). Routing logic uses these.

**Community** — belongs to an Account (builder). Has many Lots/Jobs. Used for phase forecasting.

**RoomSelection** — the heart of "pull it up two years later."
- `job_id`, `room` (Kitchen Perimeter, Island, Master Bath, etc.), `cabinet_brand`, `series`, `door_style`, `finish`, `wood_species`.
- **One job has many room selections, and a single room can have multiple zones** (kitchen perimeter and island can be two different colors). Model as one row per room/zone so retrieval is exact.

**HardwareSelection** — separate from cabinets (different vendors). `job_id`, `room`, `vendor`, `item`, `qty`.

**Quote** — `job_id`, supports **multiple pricing scenarios** per job (Option A / B). Pricing computed in-system off the cabinet drawing using the dealer multiplier (**0.217** of list). One quote can be marked `accepted`.

**Order** — generated from the accepted quote. Links to supplier (Everluxe, Legacy, hardware vendor). Tracks `confirmation_status`, `ship_status`.

**FieldMeasure** — `job_id`, dimensions payload, `measured_by`, `office_verified_by`, `discrepancy_flag`. On discrepancy: auto-notify per contact-routing rules (DRH → superintendent; other → job's field_contact) and **log that contact was made**.

**Delivery** — `job_id`, `ddms_scheduled` (checked ~1 week out), `ddms_delivered` (checked evening before install), photos, notes, `condition`.

**InstallEvent** — `job_id`, `installer_id`, `scheduled_week`, `completion_status` ∈ {`complete`, `incomplete_trade_delay`, `incomplete_cosmetic`}. Installer submits before leaving site.

**QualityWalk** — `install_event_id`, `inspector_id`, checklist, photos, notes, `result` (pass / issues). Issues auto-notify installer with a correction deadline. `second_walk` flag for re-verification.

**PunchVisit** — `job_id`, occurs for all job types post-install; adjustments, caulking, finish.

**Warranty** — `job_id`, `warranty_start` (= install date), `labor_warranty_end` (1 yr default), `material_warranty_end` (per manufacturer — 5/10/lifetime, tracked **separately** from labor), `extended_purchased` (bool), `extended_terms`.

**WarrantyClaim** — `warranty_id`, reported date, issue type, defect-vs-installer classification (tracked for analytics, but **same team resolves all**), resolution status, labor hours, parts, `billable` (computed from warranty status), invoice link. Resolved claims: document completion; generate invoice automatically when billable; invoice later keyed into POS.

**PhaseUpdate** — `community_id`, `lot_number`, `phase` (frame, roof, etc.), `source` (voice/manual), timestamp. Powers both individual lookup and community rollups → install-demand forecast.

**Notification / Acknowledgment** — every escalating alert is a row: recipient, channel, sent_at, `acknowledged_at`. Drives the 24-hour escalation ladder and the audit trail.

---

## 5. Functional modules

### 5.1 Sales & Quoting
- Enter builder (multi-job) or retail (single-job) accounts.
- Build selections by room/zone: brand, series, door style, finish, wood species; hardware separately.
- Generate **multiple pricing scenarios**; all pricing in-system off the drawing using the 0.217 multiplier.
- On acceptance: auto-generate the **exact Excel file format the 2020→POS bridge expects** so orders push straight into the legacy POS with no re-keying. Also auto-generate the supplier order (replacing the manual Excel→Everluxe form step).

### 5.2 Field Measure & Verification
- Field measurer records all dimensions → sent to office → office verifies against the design.
- Discrepancy routing: DRH → auto-notify superintendent + log contact; other accounts → notify the job's designated field_contact.
- No order goes to the supplier until dimensions are verified.

### 5.3 Supplier Order & Delivery
- Auto-track order confirmations back onto the job record.
- **DDMS integration:** check ~1 week out that the order is submitted/scheduled; run an **evening-before report** confirming actual delivery. If not delivered → alert responsible party to reschedule/cancel the installer trip (this is the "installer shows up to no cabinets" problem we're solving).
- Delivery day-prior: capture photos + notes on the job record. Damage/missing → **manual review** before any replacement order.

### 5.4 Installation Scheduling & Phase Tracking
- Integrate Alex's installer-scheduling emails as the dispatch feed.
- **Voice phase logging in the field:** "Lot 5 is frame, lot 7 has roof on" → transcribe → update PhaseUpdate rows.
- Community rollup dashboards (count of lots per phase) → **install-demand forecast** so we staff ahead.
- **Proactive re-scheduling:** if phase progress shows a job ready before the builder's scheduled week AND an installer is free, flag it and allow moving it up to relieve overbooking. Schedule changes → auto-notify installer, superintendent, sales.

### 5.5 Quality, Punch, and the Notification Ladder
- Quality walk within 48h of install: checklist + photos + notes. Issues → auto-notify installer w/ deadline; second walk to verify.
- Punch visit for **all** job types after approval.
- **Escalation ladder (reusable service):** email first → no acknowledgment in 24h → secondary channel (SMS/voice) → still nothing → re-notify primary contact **and copy their manager** (e.g., area construction manager). Every send + ack is logged.

### 5.6 Warranty & Service
- Warranty starts at install date. Track **labor** (1 yr default) and **material** (manufacturer, 5/10/lifetime) windows separately.
- **Extended warranty** = flat fee, covers material + labor; offered at job setup. If declined and customer calls later out of window → labor is billable ("we did offer you the plan…").
- Claim intake: log it, auto-check status, compute charge. Billable → auto-generate invoice (keyed into POS later). Same team resolves all claims.
- **Analytics:** claims per job, common failure types, installer callback rates, warranty service cost.

### 5.7 Voice Query (office)
- Natural-language questions → Claude interprets → read-only DB query → spoken/typed answer.
- Examples: "Where is Eddie today and what's he installing?", "What's our current open DRH PO value?", "Latest reports on DR Horton."

### 5.8 Dashboard
- Top line: **open PO load + total value, trending daily (up/down)**, active job count.
- Job table: address, phase, PO status per house.
- Upcoming installs viewable **by installer, by community, and by week**.
- **Auto-flag anomalies:** jobs stuck in a phase too long, overbooked installers. Flags surface on the dashboard **and** fire alerts routed to whoever owns that piece of the job.

---

## 6. Integrations (build as adapters, not inline)

Put each behind a clean interface so they can be stubbed/tested independently:
- **2020 Design** → POS: reproduce the exact Excel export format the POS import expects.
- **Legacy POS**: Excel-file ingest (one-way push for orders; invoices keyed later).
- **DDMS**: report scraping/API for delivery scheduling + confirmation (Playwright is fine if there's no API — reuse the VendorSuite Downloader pattern).
- **Smartsheet**: push job/phase/PO data out for company visibility (token via `SMARTSHEET_API_TOKEN`).
- **Twilio / SendGrid**: notifications + escalation.
- **Installer scheduler** (Alex's email system): ingest as the dispatch source.

---

## 7. Phased build plan

Build and demo each phase before moving on. Each phase ends with something runnable.

**Phase 0 — Foundation**
Repo scaffold (FastAPI + Postgres + Alembic + React/Vite PWA shell). Auth + roles. CI, `.env` handling, dockerized dev. No business logic yet.

**Phase 1 — Data model + Job record**
Implement the schema in §4. CRUD for Accounts, Jobs, Communities, Room/Hardware selections. The "pull up any job and see every room's spec" view. This is the backbone — get it right.

**Phase 2 — Quoting → Order → POS/supplier files**
Multi-scenario pricing with the 0.217 multiplier. Generate the exact POS Excel format and the supplier (Everluxe) order file. This delivers immediate day-one value by killing manual re-entry.

**Phase 3 — Field measure, delivery, DDMS**
Measure capture + office verification + discrepancy routing. DDMS week-out and evening-before checks with the "no cabinets" alert. Delivery photos.

**Phase 4 — Install, quality, punch + escalation ladder**
Install completion statuses, quality walk w/ photos + second walk, punch. Build the reusable escalation/notification service here (email→SMS→voice→manager, with ack logging).

**Phase 5 — Phase tracking + scheduling intelligence**
Voice phase logging, community rollups, install-demand forecast, proactive move-up-a-week logic with auto-notify.

**Phase 6 — Warranty & service**
Dual warranty windows, extended-warranty flat fee, claim intake + billable calc + auto-invoice, analytics.

**Phase 7 — Dashboard + voice query + Smartsheet**
Management dashboard (PO trend, job status, install views, anomaly flags). Office NL voice query (read-only). Smartsheet push.

---

## 8. How to work (conventions for Claude Code)

- **Migrate the schema before building features.** Alembic for every schema change.
- Build **backend endpoint + test + frontend** for a slice, then move on — don't stub the whole app.
- Every integration behind an adapter interface with a fake for tests. No live DDMS/Smartsheet/Twilio calls in the test suite.
- Notifications and escalation live in **one reusable service** — quality issues, schedule changes, discrepancy routing, and dashboard alerts all call it.
- Keep pricing logic (multiplier, SKU exclusions, GM floor) in a single pricing module so rules change in one place.
- Ask before adding a heavy dependency. Prefer boring, maintainable choices — this system has to outlive any one developer here.
- Write a short `README` per module explaining what it does and how to run it.

---

## 9. Build status

- **Phase 0 — Foundation: done** (auth + roles, CI, dockerized dev config, PWA shell).
- **Phase 1 — Data model + Job record: done.** Accounts, communities, jobs (two contacts, workflow status), room selections (one row per room/zone), hardware selections. CRUD API with role guards (write = sales/admin), jobs list with filters/search, job detail "every room's spec" view in the frontend.
- **Phase 2 — Quoting → Order → supplier files: done** (POS half deferred). Multi-scenario quotes with 0.217 multiplier snapshot, accept flow (one accepted per job), Everluxe order .xlsx generation matching the dealer's order form (excluded appliance SKUs — RANGE1.30, REF.2D.36, DISHW24 — never reach the form), order confirmation/ship status tracking, download from the job page. All pricing rules live in `backend/app/pricing.py` only.
- **Deferred: 2020→POS bridge export** — format not yet captured. Stub with the intended interface is in `backend/app/integrations/pos.py`; implement when Brian provides a sample import file.
- **Job documents**: PDFs/files attach to jobs by path (OneDrive share), served inline through the API with auth. `scripts/import_sold_jobs.py` imports DRH sold-job folders (parses Summary/SO PDFs — each DRH division formats summaries differently, parser handles all three known variants). First 5 real jobs loaded 2026-07-04 from `OneDrive - carterlumber.com\Townsend Kitchen and Bath - Master Plans & Pricing\Sold Job Files`.
- **Job codes + tracker import**: `job_code` is a unique, searchable column on jobs — the universal key across the Sales Tracker, sold-job folders, and Everluxe POs (DR* = DR Horton; locals like WEL-0318). `scripts/import_tracker.py` imports the DATA table (Command Center sheet) from the 3.0 Online Sales Tracker .xlsm, keyed by job code, idempotent — re-run after tracker updates to pick up new rows. It honors the table's declared range (cells below it are dashboard buttons, not jobs). ~497 jobs loaded 2026-07-05; statuses derived from milestone dates (punch→closed, install→quality, receipt→install, order→ordered, measure→field_measure, else quote).
- **National Builder Ordering board** (Brian's request, mirrors his 4-step ordering process previously run as separate Claude projects): per-job checklist — 1. PO's & Selection File Creation, 2. Orders & Layouts, 3. SO's & Order Comparison, 4. POs Attached. "Ordering" nav tab shows all builder-account jobs with clickable stage toggles (write roles), builder/community filters, closed jobs hidden by default; job detail page shows the pipeline card for tract jobs. New checklists seed stages 1–3 from attached document types (po+selections / order+layout / sales_order); stage toggles stamp the date.
- **Daily feed sync** (`app/feeds.py`, APScheduler daily at 07:00, manual via POST /sync/feeds): ingests the outputs of Brian's two scheduled cloud reports from OneDrive — the Vendor Suite DRH merge (`...\AI Shared Folder\Vendor Suite\VS Combined PO and Schedules\DRH_Cabinets_Combined_*.xlsx`, ~3:45 AM) and the Century SupplyPro production report (`...\AI Shared Folder\Supply Pro - Century\Century Production Report*.xlsx`, ~6:00 AM). Jobs match on community + lot; feed data lives in a refreshed `VS:`/`SP:` notes segment; new lots become jobs with codes derived from coded siblings. Tracker import links by community+lot before creating so feed-created jobs adopt codes instead of duplicating.
- **Install scheduling is app-managed** (2026-07-07): install dates were seeded once from the tracker's "Actual Install Date" column; from then on the app is the source of truth — the daily feed sync NEVER updates install_date on existing jobs (the VS: note still shows the builder's schedule for reference; new feed-created jobs get an initial date). Scheduling UI: editable install date on the job detail page; Schedule tab shows month/week/day calendar views.
- **Phase tracking** (Phases nav tab, starts spec Phase 5): builder → community → active houses by lot, each with a dropdown over Brian's 18-phase construction ladder (0-Dirt/Staked … 4.x rough-ins … 12-IC Cab Installed; canonical list in `backend/app/phases.py`). Every change is a PhaseUpdate row (who/when preserved); the board shows current phase + date. Field and installer_coordinator roles can log phases; voice logging comes later in Phase 5.
- **Autobot** (2026-08-06/07, from the COAST suite brief in `Downloads\COAST-Autobot-Brief.md`): service-tech scheduling & routing, delivered as a **standalone app at `/autobot`** (self-contained page `backend/app/static/autobot.html` + its own PWA manifest/icons, pattern of `/ordering-platform`; NOT part of the React bundle — the office UI has no Autobot tab). **Access split**: new role `service_tech` sees only `/autobot/*` endpoints (`read_access` in `api/deps.py` now excludes it from the whole office API); Autobot itself is `service_tech` + `admin` only. The tech's job lookup is `GET /autobot/jobs`. The main SPA's service worker denylists `/autobot` (vite.config) so it never hijacks the page. Universal `visits` table (all visit types — field measures, 48h post-walks, punch-outs, blue-tape, 10-day community phase checks, tiered service, warranty); engine in `backend/app/autobot.py` builds a daily loop from the Dothan shop (868 Murray Rd, coords in config): hard anchors (due measures + expiring post-walks) routed first via nearest-neighbor + 2-opt, near-stale phase checks pulled forward when the detour ≤ 30 min, flexible work backfilled by cheapest insertion within the 7:00–17:00 day; overflow flag when anchors alone bust the day. Real drive times via public OSRM table API (haversine×1.3 fallback; estimate-only past 80 stops). Durations scale off `po_amount` ($2,500 reference, 0.5–3×). Phase checks use `phase_check_metrics`: 2 min/active house PLUS a nearest-neighbor lot-to-lot drive estimate over the pinned houses at 20 mph (sprawling communities like Compass Lakes cost their real time), anchored at the pinned houses' centroid instead of the community pin. Auto-sync geocodes up to 25 missing house pins per cycle via Google (`geocode_missing_job_pins`): exact hits only, the community's market is appended when the address has no city, and any result > `PIN_SANITY_MILES` (40) from the community pin is rejected (feed addresses like "3182 Sawgrass Street" once matched California and turned a 20-min sweep into 5 days). `phase_check_metrics` additionally drops pins > 15 mi from the pack's median before computing sweep time/centroid — one bad pin must never poison a route. TBD/lot-only addresses fall back to the community pin. "Sync from CabinetTron" spawns visits idempotently from job statuses (measure_date + pre-order → field_measure; 3.0-Nd QW with install ≤ 14 days old → post_walk; 4.0-Punch / 4.1-Blue → punch/blue visits; open service requests → service/warranty visits, parts-gated). Parts gating on `service_parts.trade_blocking`/`received` + confirmed `due_date` (scheduled off the factory's confirmed date, not arrival; any trade-blocking part in hand dispatches, cosmetic leftovers wait). Locations: communities AND jobs carry `lat`/`lon` pins (visit pin → house pin → community pin fallback). City pins bulk-seeded 2026-08-06 via Nominatim (spot-check ambiguous city names; "Baker FL" corrected to the Okaloosa one); remaining gaps filled 2026-08-07 via Google Maps lookups. Phase checks skip communities named "Retail" (catch-all bucket, not a subdivision). Route view links the whole loop into Google Maps for turn-by-turn. All displayed times are 12-hour (engine `_fmt`). **Forecast tab** (`plan_horizon`): plans consecutive workdays with each day's stops treated as completed, weekends skipped, so the backlog visibly drains; doesn't re-run generation, so future phase-check cycles aren't projected. **Auto-sync**: APScheduler runs `generate_visits` + `auto_assign` every 10 min (`AUTOBOT_SYNC_MINUTES`, 0=off); the route view self-refreshes on the same cadence. **Workers/assignment** (`workers` table + `visits.assigned_to`, Team tab): one `is_tech` worker is the default truck (also owns every unassigned visit); others have a home pin + `radius_miles`. `auto_assign` rules, manual assignments never overridden: (1) sold-it rule — on non-national accounts (`NATIONAL_PREFIXES`), field_measure/post_walk go to the worker whose `sales_match` prefixes `job.salesperson`; (2) territory — visit inside a worker's radius goes to the nearest such worker; (3) else tech pool. Route/Forecast take `worker_id` and plan that person's loop from their own home pin (home field accepts a full street address; "Find" geocodes it). Roster seeded 8/7/26: Service Tech (shop), Brian Scobey (Chipley, 30mi), Alex Talley (Freeport, 30mi, sales_match Alex), Paula Cook (sales_match Paula). **Geocoding**: one server-side `geocode_address()` (`GET /autobot/geocode`) — Google Geocoding API when `GOOGLE_MAPS_API_KEY` is set (rooftop-exact, knows new construction), OSM/Nominatim fallback with city-level downgrade; every Find/autosave in the app goes through it. **Duty chart** (`duty_assignments`, Duties tab): per-community × per-duty grid in Brian's column order (Phase/Measure/Post-Walk/Punch/Blue-Tape/Service; sticky headers + sticky community column) — a cell names a worker (beats the radius rule; how national territories really split), "Tech" pins the truck, "rules" falls back; saving a cell reassigns that community's pending visits immediately, clearing releases them to the rules. Assignment order: sold-it → duty chart → territory → tech pool. Punch + service duties NEVER auto-assign by territory (`TECH_DEFAULT_DUTIES` — they default to the truck; chart/manual can still move them). Workers carry `national_ok` — local-only people (Laurie Reel, Paula Cook) never receive DR Horton/Century work from the territory rule, and national rows in the chart don't offer them. Team-tab rows autosave on Enter (checkboxes on click) and re-geocode the pin whenever the home address changes; lat/lon hidden behind a 📍 link. **Expandable stops** (Today's Route): tapping a stop loads `GET /autobot/communities/{id}/detail` — all pending work there, and for phase checks the phase-tracked houses (lot + current phase, sorted by lot). Each house has the 18-phase dropdown + a ✓ confirm; ANY log (changed or not) writes a `PhaseUpdate` row (`source="autobot"`, noted_by/noted_at) via `POST /autobot/jobs/{id}/phase` — same table the office Phases board reads, so "verified unchanged today" leaves an audit stamp. Sync auto-cancels pending phase checks whose community has 0 phase-tracked houses left, AND the planner skips them independently (never rely on sync timing). Fuzz harness: `python -m scripts.simulate_autobot [runs] [days]` simulates randomized month-long scenarios (job evolution, voids, vacations, parts slips, duty charts) and checks ~12 routing/assignment invariants per plan — keep it green after engine changes. Duties tab: per-community "Tech" button assigns all six duties to the truck; unassigned cells are blank + light yellow; rows limited to communities with jobs in `TRACK_TO_BLUE_STATUSES`. **Time off** (`worker_time_off`, managed on the Team tab): the planner returns an empty flagged day for someone who's off; the truck rescues their due field-measures/post-walks ("covering for X — off" on the stop); flexible work waits for their return; pickers show "— OFF".
- **Sterling** (2026-08-11): the COAST pricing app, mounted at **`/sterling`** (page) + `/sterling/api/*` (Optimus/Autobot pattern; `backend/app/sterling_app/`, self-contained static page). Own storage on purpose: **the Excel workbook is the source of truth** (`sterling_app/xlsx_store.py`; a committed seed workbook boots fresh disks) with a disposable SQLite cache — none of it touches Postgres; data lives on `STERLING_DATA_DIR` → `/data` (Render) → `backend/sterling-data` (local). API requires an office login (`read_access`); the page sends `cms_token`. Features: room-by-room job pricing (DRH-matrix cost model: list × .21/.24 tier, 10%/11.8% freight, 7% materials tax, $10/box assembly, $25/box install, knob/handle hardware by SKU family 3910/156), National builder pricing (live Pricing Sheet + per-plan margins + laminate tops + sent-price snapshots), Everluxe SKU pricer with per-area pricing, 2020 Design imports (.xls/.pdf), printable quotes/contracts, CabinetTron job export. Migrated 2026-08-11 from the standalone `Downloads\ckb-pricing-platform` (:8010) app, which is now retired.
- **COAST suite launcher** (2026-08-07): login lands on `#/suite` — five tiles with Carter-green SVG marks: CabinetTron (→ #/jobs), Optimus (→ /ordering-platform), Autobot (→ /autobot), Sterling (→ /sterling, live 2026-08-11), Tailgate (coming-soon, disabled). The ⠿ button at the far left of the header reopens it from anywhere. `frontend/src/pages/SuitePage.tsx`.
- **Order Pack** (2026-08-16, **Phase A done**): Brian's private mode inside Optimus at **`/ordering-platform/pack`** — automates the 4-stage DR Horton cabinet ordering process that runs as four physical OneDrive folders under `Townsend Shared File\Sold Jobs\New Orders` ("1. POs and Selections" → "2. Orders and Layouts" → "3. SOs and Order Comparison" → "4. POs attached"). A job folder moves down the chain and **its position IS its status**. Full design doc: `ORDERPACK-SPEC.md`; the real work is documented in the four `CLAUDE.md` playbooks in those folders. Identity: no new app name, no COAST tile, no nav link — reached by typing the URL, gated to an owner allowlist (`ORDERPACK_OWNER_EMAILS`); a non-allowlisted admin gets 403. **Data lives on the existing `ordering_checklists` table**, never a parallel one, so `_rollup_stages()` and the 1.2→2.0 status sync keep Optimus correct with zero drift (new columns: buid/plan_abbr/elevation/swing/sub_number, folder_name/current_folder/folder_files/selections_file/po_file/summary_file, po_date/po_total/so_total, moved_to_sold_date/installer_pay_sheet/install_pay, exception/last_scan_at). New `pack_runs` table = the command queue + audit trail. **`agent\orderpack_agent.py` runs on Brian's PC** (only that machine sees OneDrive, Outlook, and the logged-in VendorSuite session): it polls `/agent/runs/next`, executes, streams log lines back, and every `ORDERPACK_SCAN_MINUTES` walks the four stage folders (+ "Century Orders", flat, no stage chain) reporting folder → files. Auth is a shared secret in the `X-Pack-Key` header (`ORDERPACK_AGENT_KEY`), the WALLPAPER_FEED_KEY pattern. Started by `start_orderpack_agent.bat`; `watchdog.py` supervises it via its 8791 single-instance lock. **Phase A's scan writes ONLY the Order Pack columns** — it never stamps `steps` and never moves a status, so the board surfaces drift instead of hiding it (first real scan, 8/16/26: 12 folders in stage 3, 11 Century, 23/23 matched, and it immediately showed jobs sitting in stage 3 that Optimus had at 1.4/2.0). Board never auto-archives (Brian's call); "Hide filed jobs" is a filter. `" REVIEW"` on a stage-3 folder name surfaces as a flag; a folder that leaves the chain without completing stage 4 becomes `missing`, not silently done. Hard rules carried into every later phase: the stage-4 SO-total == Carter-PO-total check is never bypassed, install pay is never invented (blank + note), the deprecated `Sold Jobs\Builders\DR Horton\...` tree is off limits, VendorSuite SSO stays manual (DR Horton WS-Fed — Brian clicks Sign On), and RANGE1.30 / REF.2D.36 / DISHW24 are always excluded. Build order from here: **B** stage 4 end to end (wrapping the existing `Pull_Carter_POs_from_Outlook.py` / `Process_Carter_POs.py`), **C** stage 1, **D** stage 3, **E** stage 2, **F** retire `New Orders Status.xlsx`. Stage 4 auto-run on a schedule is built as a setting (`ORDERPACK_AUTO_STAGE4`) but **off** — runs fire only when Brian presses Run.
- Next: **Phase 3 — Field measure, delivery, DDMS.**
- Local dev note: this machine has no Docker; `docker-compose.yml` is provided for when it's available, and local dev falls back to SQLite via `DATABASE_URL` (Postgres remains the deployment target — all schema goes through Alembic and stays engine-agnostic).

---

*Brand: **Carter Lumber**, everywhere — the app is named **"Carter Kitchen and Bath"** — logo (`frontend/public/carter-logo.png`), colors (deep green #125952, orange #df5822, mint K&B accent #2bb99f). The old Townsend name was scrubbed from all branding and defaults 2026-08-07 (Brian: "we are all Carter now"). The only place the word may still appear is in literal OneDrive folder paths (`...\Townsend Shared File`, `...\Townsend Kitchen and Bath - Master Plans & Pricing`) and existing user login emails — those are real identifiers; do not rename them in code, and never reintroduce the old name in anything user-facing. If Everluxe rejects order forms under the Carter dealer name, override `DEALER_NAME`/`SHIP_TO_NAME` in `.env` rather than editing the code defaults.*

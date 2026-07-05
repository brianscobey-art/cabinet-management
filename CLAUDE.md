# Cabinet Management System — Project Spec (Claude Code)

**Owner:** Brian, Kitchen & Bath Manager, Carter Lumber (formerly Townsend Building Supply — acquired 2026)
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
- Next: **Phase 3 — Field measure, delivery, DDMS.**
- Local dev note: this machine has no Docker; `docker-compose.yml` is provided for when it's available, and local dev falls back to SQLite via `DATABASE_URL` (Postgres remains the deployment target — all schema goes through Alembic and stays engine-agnostic).

---

*Brand: **Carter Lumber**; the app is named **"Carter Kitchen and Bath"** — logo (`frontend/public/carter-logo.png`), colors (deep green #125952, orange #df5822, mint K&B accent #2bb99f) as of the 2026 buyout. Townsend Building Supply is legacy; it may linger in supplier account names (e.g. the Everluxe dealer defaults in `backend/app/config.py`) until those accounts are renamed — update `.env` when they are.*

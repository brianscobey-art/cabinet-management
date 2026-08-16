# Order Pack (private mode inside Optimus) : Build Spec

**Owner:** Brian
**Status:** draft for review, nothing built yet
**Date:** 2026-08-16

---

## 1. In plain language

Today the cabinet ordering process runs as four Claude projects driving four OneDrive
folders. A job folder physically moves from folder to folder, and its position in that
chain IS its status. A spreadsheet (`New Orders Status.xlsx`) is supposed to mirror that,
but it corrupts and blocks constantly, so the real state and the recorded state drift.

Order Pack replaces the spreadsheet with a real database, gives one live board that shows
every job and what stage it is in, and puts Run buttons on the stages so the work fires
from any device while this PC does the file handling.

It is built as a **private mode inside Optimus**, not a separate app, because it may later
become part of Optimus outright.

### Decisions already made (2026-08-16)

| Question | Answer |
|---|---|
| Biggest pain | Updating `New Orders Status.xlsx` |
| Who reads that spreadsheet | Brian only, so the app can own the data |
| Where it runs from | Anywhere (phone, laptop, desk) |
| First version scope | Board AND run buttons together |
| Optimus | Stays, must remain accurate, no drift allowed |
| Identity | No new app name, no COAST tile. Lives inside Optimus, gated to Brian |

---

## 2. The real workflow being automated

Source of truth for this section: the four `CLAUDE.md` playbooks under
`OneDrive - carterlumber.com\Townsend Shared File\Sold Jobs\New Orders\`, plus
`DRH Ordering Process Flow Notes 041626.txt`.

The four folders in `Sold Jobs\New Orders\`:

1. `1. POs and Selections`
2. `2. Orders and Layouts`
3. `3. SOs and Order Comparison`
4. `4. POs attached`

### Stage 1 : POs and Selections

- Input: a list of 9 digit BUIDs.
- Pull the current Selected Options Sheet and current cabinet PO (cost code `45000.11`,
  prefer `IsOpen=true`, else newest by date) from VendorSuite.
- Save as `{BUID}_Selections.PDF` and `{BUID}_PO.PDF`.
- Create a BUID subfolder, move both files in.
- Highlight in yellow on the Selected Options Summary: Appliances, Cabinets, and
  Plumbing / Kitchen Sinks. Never highlight DELETED sections.
- Rename to `[Job Code] [Plan Abbr] Selections MMDDYY.PDF` and
  `[Job Code] [Plan Abbr] PO MMDDYY.PDF` (multiples become PO1, PO2, ...).
- Generate `[Job Code] [Plan Abbr] Summary MMDDYY.PDF` containing subdivision, address,
  buyer, plan/elevation/swing, the three highlighted sections, and per PO the work
  description, line items, and total.
- Exclusions that must never appear in cabinet lists: `RANGE1.30`, `REF.2D.36`, `DISHW24`.
- Rename the folder to `[Job Code] [Plan Abbr] MMDDYY` and move it to `2. Orders and Layouts`.
- Stamp stage 1 complete.

### Stage 2 : Orders and Layouts

- Brian creates the order form and drops the order PDF into the folder. **This stays manual.**
- Rename the order PDF to match the folder and move it in.
- Locate the matching floorplan layout, stamp job info onto the layout PDF.
- Brian emails the order to Everluxe. **This stays manual.**
- Stamp stage 2 complete.

### Stage 3 : SO's and Order Comparison

- Everluxe SO confirmations arrive by email and are copied into the folder.
- Compare order against SO (and layout), produce the comparison summary.
- Brian emails Leonard the approved SOs. **This stays manual.**
- Stamp stage 3 complete.

### Stage 4 : POs Attached

Already the most automated stage. Existing scripts: `Pull_Carter_POs_from_Outlook.py`,
`Process_Carter_POs.py`, launched by `Run_Pull_Carter_POs.bat` / VBS schedules.

- Read job codes from the folders staged in `3. SOs and Order Comparison`.
- Via Outlook COM (pywin32), find the newest inbox email whose subject contains each job
  code, save the attached `Purchase Order 7500xxxxx.pdf` into `4. POs attached`.
- For each Carter PO: extract PO number, SO number, PO total.
- Match to the job folder in stage 3 by SO number.
- **Verify the SO dollar total equals the Carter PO total exactly. On mismatch, flag and
  do not move.** This gate is mandatory.
- Move the job folder from stage 3 to stage 4.
- Copy the Carter PO into the folder as
  `[JOB ID] [SO#] [CARTER PO#] [MMDDYY].pdf`, delete the staging copy.
- Read the Sub # from the DR Horton PO inside the folder.
- Copy the whole job folder to
  `Townsend Kitchen and Bath - Master Plans & Pricing\Sold Job Files\National Accounts\DR Horton - All\[Region]\[Community] [Sub #]`.
  The old `Sold Jobs\Builders\DR Horton\...` tree is deprecated, never read or write it.
- After confirming the copy landed, delete the folder from `4. POs attached`.
- Record the installer pay sheet (present yes/no) and the install pay amount off that PDF.
  Never invent the amount: if unreadable, leave blank and note it.
- Stamp stage 4 complete and "moved to sold folder".

---

## 3. Architecture

Three pieces. Only the agent is new.

```
  any device                     Render (cloud)                    Brian's PC
 +-----------+   HTTPS    +-----------------------+   poll   +------------------+
 |  Order    |<---------->|  CabinetTron backend  |<---------|  Order Pack      |
 |  Pack     |            |  /ordering-platform/  |          |  Agent           |
 |  page     |            |    pack/*             |--------->|  (Python service)|
 +-----------+            |  Postgres (state)     |  result  +--------+---------+
                          +-----------------------+                   |
                                    ^                                 v
                                    |                        OneDrive folders,
                             Optimus reads the               PDFs, Outlook COM,
                             same records                    Chrome (VendorSuite)
```

### 3.1 Page: `/ordering-platform/pack`

- Self contained static page served by the CabinetTron backend, same pattern as
  `/ordering-platform`, `/autobot`, `/sterling`.
- Must be added to `navigateFallbackDenylist` in `vite.config.ts` or the SPA service
  worker will hijack it (this bit every previous standalone page).
- Auth: normal `cms_token` login, PLUS an allowlist check so only Brian's account can
  load it or hit its endpoints. No COAST tile, no nav link.
- Views:
  - **Board** (default): one row per active job, columns for the four stages showing
    date stamps, current physical folder, reference numbers (builder PO, SO, Carter PO),
    and flags. Filter by builder/community/stage. This is the `New Orders Status.xlsx`
    replacement.
  - **Run panel**: select jobs, choose a stage, fire it. Shows live agent log per run.
  - **Exceptions**: jobs the agent flagged (total mismatch, missing SO, unreadable pay
    sheet, BUID not found in VendorSuite). This is the queue that needs Brian.

### 3.2 Agent: `orderpack_agent.py` on Brian's PC

- Long running Python service, started at logon, wrapped by the existing watchdog pattern
  so it self heals.
- Authenticates with a shared secret (`ORDERPACK_AGENT_KEY`), same approach as
  `WALLPAPER_FEED_KEY`.
- Two duties:
  1. **Execute runs.** Poll `GET /ordering-platform/pack/runs/next`, claim a queued run,
     do the stage work locally, stream log lines back, post the structured result.
  2. **Scan folders.** Every N minutes, walk the four stage folders and report what job
     folders sit in each, with file inventories. This is what makes the board reflect
     physical reality instead of trusting a checkbox.
- The four `CLAUDE.md` playbooks become this agent's code, one module per stage:
  `stage1_intake.py`, `stage2_layout.py`, `stage3_compare.py`, `stage4_pos.py`.
- Stage 4 wraps the existing `Pull_Carter_POs_from_Outlook.py` and `Process_Carter_POs.py`
  rather than rewriting them.

### 3.3 Data

**Extend `ordering_checklists`** (do NOT create a parallel table, Optimus reads this one):

| New column | Type | Source |
|---|---|---|
| `buid` | String(9) | tracker / VendorSuite |
| `plan_abbr` | String(20) | tracker |
| `elevation` | String(10) | Selections PDF |
| `swing` | String(20) | tracker |
| `sub_number` | String(10) | DR Horton PO |
| `folder_name` | String(200) | agent |
| `current_folder` | String(40) | agent scan (`stage1`..`stage4`, `sold`, `missing`) |
| `selections_file` | String(200) | agent |
| `po_file` | String(200) | agent |
| `summary_file` | String(200) | agent |
| `po_date` | Date | PO PDF |
| `po_total` | Numeric(12,2) | PO PDF |
| `so_total` | Numeric(12,2) | SO |
| `moved_to_sold_date` | Date | stage 4 |
| `installer_pay_sheet` | Boolean | stage 4 |
| `install_pay` | Numeric(12,2) | pay sheet PDF |
| `exception` | Text | agent flag, null when clean |
| `last_scan_at` | DateTime | agent |

Everything already on `Job` (job_code, lot_number, plan, address, community, po_amount)
is referenced, not duplicated.

**New table `pack_runs`** (the command queue and audit trail):

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `stage` | int | 1..4 |
| `job_ids` | JSON | jobs in this batch |
| `status` | String(20) | queued, running, done, failed |
| `requested_by` | String | user email |
| `requested_at` / `started_at` / `finished_at` | DateTime | |
| `log` | Text | streamed agent output |
| `result` | JSON | per job outcome |
| `error` | Text | null unless failed |

All schema changes go through Alembic, per repo convention.

### 3.4 Keeping Optimus correct

The agent never writes checkboxes directly. When a stage completes, the **server** stamps
the matching sub-steps in `ordering_checklists.steps`, calls the existing
`_rollup_stages()`, and lets the existing two way status sync move the job through
1.2-NdOrd to 2.0-Ord exactly as it does today. Optimus therefore stays accurate with zero
extra work and zero drift, because there is only one set of records.

---

## 4. Build order

Each phase ends with something Brian can actually use.

**Phase A : board reads reality (no automation yet)**
Agent scans the four folders and reports. Page shows the live board. Schema migration in.
Value on day one: the spreadsheet stops being needed, and every job's true position is
visible from anywhere.

**Phase B : stage 4 end to end**
Wire the existing Outlook pull and PO processing behind a Run button. Total mismatch
becomes a visible exception rather than a silent stall. This proves the whole chain
(page to agent to PC to database to Optimus) with the least new logic.

**Phase C : stage 1**
VendorSuite pull, folder build, highlighting, Summary PDF, rename, move, stamp.

**Phase D : stage 3**
SO comparison and summary generation, with the diff surfaced on screen.

**Phase E : stage 2**
Order PDF rename/move and layout stamping. Smallest automation payoff, so it goes last.

**Phase F : retire the spreadsheet**
Export a read only copy on demand if it is ever wanted, delete the TSV fallback path,
remove the Excel Online workaround documentation.

---

## 5. Constraints and non goals

- **VendorSuite SSO cannot be automated.** DR Horton uses WS-Fed SSO and Brian must click
  Sign On himself. Stage 1 therefore depends on a live logged in Chrome session on the PC.
  If the session is expired, stage 1 waits for Brian at the desk. Every other stage is
  genuinely from anywhere. Credentials are never stored or requested.
- **Creating the order form stays manual** (judgment work in 2020 / Sterling).
- **Emailing Everluxe and Leonard stays manual.** The app prepares and stamps, Brian sends.
- **The dollar verification gate in stage 4 is never bypassed.** A mismatch stops the move
  and raises an exception. No auto resolution.
- **Install pay is never invented.** Unreadable means blank plus a note.
- The agent only ever touches the New Orders tree and the Sold Job Files destination.
  The deprecated `Sold Jobs\Builders\DR Horton\...` tree is off limits.

## 6. Open questions

1. Does the board need to show Century orders too, or DR Horton only for now?
   (`Century Orders` sits in the same New Orders folder.)
2. Should the agent auto run stage 4 on a schedule (the VBS schedules do this today), or
   only when Brian presses Run?
3. Retention: how long should completed jobs stay on the board before archiving?

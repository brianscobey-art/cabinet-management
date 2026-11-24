# Test environment

A second, fully separate copy of the app for trying changes before they reach
the live site. Brian's rule (11/5/26): build and prove it in test first, never
change live directly.

## Live vs. test

| | Live (unchanged) | Test |
|---|---|---|
| Render blueprint | `render.yaml` | `render.test.yaml` |
| Web service | `carter-kitchen-and-bath` | `cabinettron-test` |
| Deploys from | `main` (auto-deploy) | `staging` (auto-deploy) |
| Database | `carter-kb-db` | `cabinettron-test-db` |
| Disk (`/data`: Sterling workbook, generated files) | `kb-files` | `cabinettron-test-files` |
| Address | cabinettron.com | cabinettron-test-vjcp.onrender.com |
| `SECRET_KEY` | its own | its own (live logins do not work on test) |
| `APP_ENV` | unset = `production` | `test` |

## What `APP_ENV=test` does

Set in `render.test.yaml`. Enforced in `backend/app/config.py`, so it holds
even if a live key is pasted into the test service by mistake:

- red **TEST ENVIRONMENT** strip across the top of every page in the suite
  (CabinetTron, Sterling, Optimus, Order Pack, Autobot) and `[TEST]` in the tab title,
- no pushes to the CabinetTron Smartsheets (job tracker, PO tracker), and no Smartsheet reads,
- no invite emails (SendGrid off),
- no R2 (the live feed files are never read), no Domo token,
- Order Pack stage 4 auto-run forced off.

`GET /env` answers `{"env": "test"}` or `{"env": "production"}`.

## Getting data into test

The test database starts empty.

1. **Sample data** (made up, safe anywhere):
   `APP_ENV=test python -m scripts.seed_test_data you@example.com "Test Admin"`
   Creates a test admin login (asks for the password), a sample builder,
   a community and nine jobs at different stages. Refuses on live and refuses
   if test already has jobs.
2. **Real sold jobs, copied read-only from live** (Brian asked for this 11/5/26):
   set `LIVE_DATABASE_URL` on the test service to the live database's External
   Database URL, then
   `APP_ENV=test python -m scripts.copy_jobs_from_live --pick 25 --dry-run`
   and, if the counts look right, again without `--dry-run`.
   `--codes A,B,C` copies specific jobs instead. Live is opened read-only (the
   database itself refuses writes), contact emails and phones are masked unless
   `--keep-contacts`, user logins are never copied, a job already in test is
   skipped, and the whole copy is one transaction. Job documents come over as
   paths only; the files live in OneDrive/R2, which test cannot read.
   Remove `LIVE_DATABASE_URL` from the test service when done.

## Promoting a change

1. Work on a feature branch, open a PR into `staging`.
2. Merge it: Render deploys it to the test service only.
3. Check it on cabinettron-test-vjcp.onrender.com.
4. When it is right, open a PR `staging` -> `main`. Merging that is the only
   step that changes the live site.

Data fixes for live still ship as Sterling `DATA_FIXES` boot migrations; try
them on test first (the test disk boots from the same committed seed workbook).

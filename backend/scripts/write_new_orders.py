"""Push CabinetTron's values into New Orders Status.xlsx (runs on Brian's PC).

The cloud app can't see OneDrive and the PC has no database credentials, so the
split is: the app serves the values over /reports/new-orders-export/public, and
this script applies them to the workbook.

Only the app-owned columns are overwritten. Identity columns (PO #, Lot #,
Swing, Subdivision, BUID, Plan Name, Elevation, Floorplan Abbr) are filled only
when blank; a disagreement is reported, never silently resolved. Columns the
app has no home for at all — Zip, Folder Location, Status, Superintendent — are
never touched, which is why this updates in place instead of rebuilding.

Config: scripts/tracker_export.config.json  {"url": "...", "token": "..."}

    python -m scripts.write_new_orders [--dry-run]
"""

import json
import sys
import urllib.request
from pathlib import Path

from app.config import get_settings
from app.new_orders import write_workbook

# The config lives at the repo root, beside update_tracker_import.ps1,
# which has used it since the phase write-back was built.
CONFIG = Path(__file__).resolve().parents[2] / "tracker_export.config.json"


def main() -> None:
    dry = "--dry-run" in sys.argv
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    url = f"{cfg['url'].rstrip('/')}/api/reports/new-orders-export/public?token={cfg['token']}"
    with urllib.request.urlopen(url, timeout=120) as resp:
        values = json.loads(resp.read())
    if not values:
        raise SystemExit("export returned nothing — refusing to touch the workbook")

    path = get_settings().new_orders_file
    result = write_workbook(path, values, dry_run=dry)
    print(f"{'DRY RUN' if dry else 'wrote'}: {result['rows_changed']} rows, "
          f"{result['cells_changed']} cells, {len(result['conflicts'])} conflicts")
    for c in result["conflicts"]:
        print(f"  CONFLICT {c[0]} {' '.join(str(c[1]).split())}: sheet={c[2]!r} app={c[3]!r}")
    if result["unknown_job_codes"]:
        print(f"  {len(result['unknown_job_codes'])} sheet rows have no job in CabinetTron")


if __name__ == "__main__":
    main()

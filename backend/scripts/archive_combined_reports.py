"""Archive the DRH Cabinets Combined reports to R2 — one place, kept forever.

Brian's call (9/1/26): only the COMBINED reports go to the cloud. The raw
VendorSuite pulls behind them (VS Open POs, VS Schedule, VS All POs — roughly
1,840 files) stay on the PC; only the newest of those is ever read, so copying
every day's would move the sprawl rather than fix it.

Keys are reports/drh-cabinets-combined/YYYY/DRH_Cabinets_Combined_MMDDYY.xlsx —
year folders so a decade of dailies stays browsable.

Distinct from the feed uploader, which pushes the newest 5 to vendorsuite/ for
the app to READ. This is the archive: every report, kept.

    python -m scripts.archive_combined_reports [--commit] [--since MMDDYY]
"""

import argparse
import re
from pathlib import Path

PREFIX = "reports/drh-cabinets-combined/"
# The date, wherever it sits in the name. Alongside the clean dailies the folder
# holds working copies — "_022526 - Copy", "_031626-2", "_050426.1",
# "_050526_with_summary" — which are still real reports for a real date, so they
# are filed by that date under their own name rather than dumped as undated.
NAME_RE = re.compile(r"_(\d{2})(\d{2})(\d{2})", re.I)


def year_of(name: str) -> str:
    """MMDDYY in the filename -> 20YY. Never guesses from mtime: OneDrive
    rewrites that on sync, so it says when the file synced, not when it is for."""
    m = NAME_RE.search(name)
    return f"20{m.group(3)}" if m else "undated"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="upload; otherwise dry run")
    ap.add_argument("--since", help="only files dated on/after this MMDDYY")
    args = ap.parse_args()

    from app.config import get_settings
    from app.storage import _client, _list

    s = get_settings()
    if not s.r2_enabled:
        raise SystemExit("R2 not configured — set R2_ENDPOINT / R2_BUCKET / keys.")

    folder = Path(s.vendorsuite_dir)
    if not folder.is_dir():
        raise SystemExit(f"folder not found: {folder}")

    files = sorted(f for f in folder.glob("DRH_Cabinets_Combined*.xlsx")
                   if not f.name.startswith("~"))
    # ".corrupt_MMDDYY" marks a build that failed; archiving it preserves nothing.
    corrupt = [f for f in folder.glob("DRH_Cabinets_Combined*corrupt*")]
    if corrupt:
        print(f"skipping {len(corrupt)} file(s) marked corrupt: "
              f"{', '.join(c.name for c in corrupt[:3])}")
    if args.since:
        def sortable(n: str) -> str:
            m = NAME_RE.search(n)
            return f"{m.group(3)}{m.group(1)}{m.group(2)}" if m else ""
        cut = args.since[4:6] + args.since[0:2] + args.since[2:4]
        files = [f for f in files if sortable(f.name) >= cut]

    client = _client(s)
    have = {k: sz for k, sz, _ in _list(client, s.r2_bucket, PREFIX)}
    print(f"{len(files)} combined reports on disk | {len(have)} already archived\n")

    todo, skip = [], 0
    for f in files:
        key = f"{PREFIX}{year_of(f.name)}/{f.name}"
        if have.get(key) == f.stat().st_size:
            skip += 1
        else:
            todo.append((f, key))

    by_year = {}
    for f, key in todo:
        by_year.setdefault(key.split("/")[2], []).append(f)
    for yr in sorted(by_year):
        mb = sum(x.stat().st_size for x in by_year[yr]) / 1024 / 1024
        print(f"  {yr}: {len(by_year[yr]):>4} files  {mb:>7.1f} MB")

    total_mb = sum(f.stat().st_size for f, _ in todo) / 1024 / 1024
    print(f"\n  to upload: {len(todo)} files, {total_mb:.1f} MB | already there: {skip}")

    if not args.commit:
        print("\ndry run — nothing uploaded (pass --commit)")
        return

    done = 0
    for f, key in todo:
        client.upload_file(str(f), s.r2_bucket, key,
                           ExtraArgs={"Metadata": {"src-mtime": str(int(f.stat().st_mtime))}})
        done += 1
        if done % 25 == 0:
            print(f"    {done}/{len(todo)} …")
    print(f"\narchived {done} reports to {PREFIX}")


if __name__ == "__main__":
    main()

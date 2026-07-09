"""Rewrite stored file paths after moving the app to a new machine.

Job documents and feed folders store absolute paths (e.g. into OneDrive).
On a new server the OneDrive root moves (different username), so run:

    python -m scripts.rewrite_doc_paths "C:\\Users\\Brian SE6\\OneDrive - carterlumber.com" "C:\\Users\\kbserver\\OneDrive - carterlumber.com"

Dry-runs by default; add --apply to write.
"""

import sys

from app.database import SessionLocal
from app.models import JobDocument, Order


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--apply"]
    apply = "--apply" in sys.argv
    if len(args) != 2:
        print('Usage: python -m scripts.rewrite_doc_paths "<old prefix>" "<new prefix>" [--apply]')
        sys.exit(1)
    old, new = args

    with SessionLocal() as db:
        docs = db.query(JobDocument).filter(JobDocument.file_path.like(f"{old}%")).all()
        orders = db.query(Order).filter(Order.file_path.like(f"{old}%")).all()
        print(f"{len(docs)} documents and {len(orders)} order files start with the old prefix")
        for item in docs + orders:
            item.file_path = new + item.file_path[len(old):]
        if apply:
            db.commit()
            print("applied")
        else:
            db.rollback()
            print("(dry run — re-run with --apply to write)")


if __name__ == "__main__":
    main()

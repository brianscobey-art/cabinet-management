"""Legacy POS export adapter — NOT YET IMPLEMENTED.

The 2020 Design → POS bridge file format hasn't been captured yet. When Brian
provides a sample of the exact Excel file the POS import expects, implement
`build_pos_export` to reproduce it byte-for-byte and wire it into the
quote-acceptance flow next to the Everluxe order generation.
"""

from pathlib import Path

from app.models import Job, Quote


def build_pos_export(job: Job, quote: Quote, out_dir: Path) -> Path:
    raise NotImplementedError(
        "POS export format not yet captured — provide a sample 2020->POS bridge file."
    )

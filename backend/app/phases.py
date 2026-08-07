"""Construction phase ladder — mirrors Brian's tracker columns exactly."""

PHASES: list[tuple[str, str]] = [
    ("0", "0 - Dirt/Staked"),
    ("1", "1 - Slab Formed"),
    ("2", "2 - Slab Poured"),
    ("3", "3 - Framing Start"),
    ("4", "4 - Framing Complete (Measure)"),
    ("4.1", "4.1 - Windows Installed"),
    ("4.2", "4.2 - Roof Complete"),
    ("4.3", "4.3 - Electrical Rough Complete"),
    ("4.4", "4.4 - Plumbing Rough Complete"),
    ("4.5", "4.5 - Insulation Complete"),
    ("5", "5 - Drywall Ready"),
    ("6", "6 - Drywall Hung"),
    ("7", "7 - Drywall Tape/Float"),
    ("8", "8 - Textured"),
    ("9", "9 - Trim"),
    ("10", "10 - Paint"),
    ("11", "11 - Cab Delivered"),
    ("12", "12 - IC Cab Installed"),
]

PHASE_CODES = {code for code, _ in PHASES}
PHASE_LABELS = dict(PHASES)

# The phase board/report follows a house through construction only until punch.
# Punch and everything after (blue tape, EPO, closed, warranty, void) drop off —
# their cabinets are in, so there's nothing left to phase-track.
from app.models import JobStatus  # noqa: E402  (kept here to avoid an import cycle)

PHASE_TRACKED_STATUSES = (
    JobStatus.track, JobStatus.preord, JobStatus.ndord, JobStatus.ordprcss,
    JobStatus.ordsub, JobStatus.ordpo, JobStatus.ord, JobStatus.inst,
    JobStatus.ndqw, JobStatus.parts,
)
PHASE_HIDDEN_STATUSES = tuple(s for s in JobStatus if s not in PHASE_TRACKED_STATUSES)

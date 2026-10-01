"""Construction phase ladder — mirrors Brian's tracker columns exactly."""

PHASES: list[tuple[str, str]] = [
    ("0", "0 - Dirt/Staked"),
    ("1", "1 - Slab Formed"),
    ("2", "2 - Slab Poured"),
    ("3", "3 - Framing Start"),
    ("4", "4 - Framing Complete (Measure)"),
    # 10/1/26: Pre Walk added as 4.1 and Electrical + Plumbing merged into
    # Mechanicals, so the 4.x codes shifted (migration i3j4k5l6m7n8 moved
    # the logged updates). Whole numbers never moved.
    ("4.1", "4.1 - Pre Walk Complete"),
    ("4.2", "4.2 - Windows Installed"),
    ("4.3", "4.3 - Roof Complete"),
    ("4.4", "4.4 - Mechanicals Complete"),
    ("4.5", "4.5 - Insulation Complete"),
    ("5", "5 - Drywall Ready"),
    ("6", "6 - Drywall Hung"),
    ("7", "7 - Drywall Tape/Float"),
    ("8", "8 - Textured"),
    ("9", "9 - Trim"),
    ("10", "10 - Paint"),
    ("11", "11 - Cab Delivered"),
    ("12", "12 - Cabinets Installed"),
    ("13", "13 - Post Walk Complete"),
    ("14", "14 - 1st Punch Complete"),
    ("15", "15 - Blue Tape Complete"),
    ("16", "16 - Closed"),
]

# Phases from Cabinets Installed on are the finished tail of the ladder: the
# cabinets are in and what remains is walk, punch, blue tape, close. Boards
# tuck these away by default.
FINISHED_PHASES = {"12", "13", "14", "15", "16"}

PHASE_CODES = {code for code, _ in PHASES}
PHASE_LABELS = dict(PHASES)

# The phase board/report follows a house through construction and the
# post-install tail (phases 13-16 are post walk, punch, blue tape, closed), so
# houses in the punch / blue tape / EPO statuses stay on the board. Closed,
# warranty and void drop off.
from app.models import JobStatus  # noqa: E402  (kept here to avoid an import cycle)

PHASE_TRACKED_STATUSES = (
    JobStatus.track, JobStatus.preord, JobStatus.ndord, JobStatus.ordprcss,
    JobStatus.ordsub, JobStatus.ordpo, JobStatus.ord, JobStatus.inst,
    JobStatus.ndqw, JobStatus.parts, JobStatus.punch, JobStatus.blue, JobStatus.epo,
)
PHASE_HIDDEN_STATUSES = tuple(s for s in JobStatus if s not in PHASE_TRACKED_STATUSES)

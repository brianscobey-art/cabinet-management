"""The one status rule. Every hand-off moves the job's status through here.

- The ladder is the JobStatus order (1.0-Track ... 7.0-War); 8.0-Void sits apart.
- Hand-offs only move a job forward. Moving back needs an office reopen (admin).
- Void and Closed are locked to hand-offs. Closed may still go to 7.0-War.
- A move to the status the job already has is a no-op, not an error.
"""

from app.models import JobStatus

ORDER = [s for s in JobStatus if s is not JobStatus.void]
RANK = {s: i for i, s in enumerate(ORDER)}


class LadderError(ValueError):
    pass


def rank(s: JobStatus) -> int:
    return RANK.get(s, -1)


def check_move(current: JobStatus, target: JobStatus, *, reopen: bool = False) -> bool:
    """Return True if the status should change, False for a no-op. Raise LadderError if refused."""
    if current == target:
        return False
    if current is JobStatus.void:
        raise LadderError("job is 8.0-Void; hand-offs cannot change a voided job")
    if target is JobStatus.void:
        if not reopen:
            raise LadderError("only the office can void a job")
        return True
    if current is JobStatus.closed and target is not JobStatus.war:
        raise LadderError("job is 6.0-Clsd; only a warranty move is allowed")
    if rank(target) < rank(current) and not reopen:
        raise LadderError(
            f"would move the job back from {current.value} to {target.value}; the office has to reopen it"
        )
    return True


def is_between(s: JobStatus, low: JobStatus, high: JobStatus) -> bool:
    return rank(low) <= rank(s) <= rank(high)


def at_least(s: JobStatus, low: JobStatus) -> bool:
    return s is not JobStatus.void and rank(s) >= rank(low)

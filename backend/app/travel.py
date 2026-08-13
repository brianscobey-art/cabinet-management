"""Driving miles from the Chipley store to each job — for the manager report's
travel/field-capacity section.

Real OSRM driving distance is cached on Job.base_drive_miles (computed in
batches, only written on an OSRM success so the cache is always "real"). Until a
job is cached, the report falls back live to a straight-line estimate so a number
always shows.
"""

import json
import logging
import urllib.request

from app.config import Settings, get_settings

logger = logging.getLogger("uvicorn.error")
METERS_PER_MILE = 1609.34


def _base(s: Settings) -> tuple[float, float]:
    return (s.chipley_lat, s.chipley_lon)


def fill_base_miles(db, settings: Settings | None = None, max_jobs: int = 400) -> int:
    """Cache real OSRM driving miles from Chipley for active jobs missing it.
    Batches ≤90 (OSRM's public table cap) and only writes on success."""
    s = settings or get_settings()
    from app.autobot import OSRM_URL
    from app.models import Job, JobStatus

    pending = (
        db.query(Job)
        .filter(
            Job.status.notin_((JobStatus.closed, JobStatus.void)),
            Job.lat.isnot(None), Job.lon.isnot(None),
            Job.base_drive_miles.is_(None),
        )
        .limit(max_jobs)
        .all()
    )
    if not pending:
        return 0
    base = _base(s)
    filled = 0
    for i in range(0, len(pending), 90):
        batch = pending[i:i + 90]
        coords = [base] + [(j.lat, j.lon) for j in batch]
        pairs = ";".join(f"{lon},{lat}" for lat, lon in coords)
        url = f"{OSRM_URL}/table/v1/driving/{pairs}?sources=0&annotations=distance"
        try:
            with urllib.request.urlopen(url, timeout=25) as resp:
                data = json.load(resp)
            dists = data["distances"][0][1:]  # meters from Chipley to each job
            for j, m in zip(batch, dists):
                if m is not None:
                    j.base_drive_miles = round(m / METERS_PER_MILE, 1)
                    filled += 1
        except Exception as exc:  # noqa: BLE001 — leave uncached; report estimates live
            logger.warning("OSRM base-miles batch failed: %s", exc)
    if filled:
        db.commit()
    return filled


def job_miles(job, settings: Settings | None = None) -> float | None:
    """Cached real driving miles, else a live straight-line estimate, else None."""
    if job.base_drive_miles is not None:
        return job.base_drive_miles
    if job.lat is None or job.lon is None:
        return None
    from app.autobot import ROAD_FACTOR, haversine_miles

    s = settings or get_settings()
    return round(haversine_miles(_base(s), (job.lat, job.lon)) * ROAD_FACTOR, 1)

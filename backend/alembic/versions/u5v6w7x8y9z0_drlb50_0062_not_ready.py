"""DRLB50-0062 too: its bare Done on 10/29 was a not-ready trip, same as the
four Compass Lakes houses in t4u5v6w7x8y9 (Brian 11/2/26). Same fix:
the old bare Done meant "I went to the site", not "measured". Re-close it as
Not ready and put the measure back on the schedule the way the Not ready
button does: pinned 2 days after the visit, next workday (a pin day that has
passed rolls to today in the planner).

Only DRLB50-0062 (the other Liberty bare Dones were real measures), and
only while each is still a bare-Done measure with no later trip and no
completed measure in CabinetTron.

Revision ID: u5v6w7x8y9z0
Revises: t4u5v6w7x8y9
"""
from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa
from alembic import op

revision = "u5v6w7x8y9z0"
down_revision = "t4u5v6w7x8y9"
branch_labels = None
depends_on = None

FIXED_BY = "Autobot — bare Done read as Not ready (DRLB50-0062)"


def _as_date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.fromisoformat(str(v)[:19]).date()


def _workday_on_or_after(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("""
        SELECT v.id, v.job_id, v.community_id, v.assigned_to, v.lat, v.lon,
               v.priority, v.trip, v.completed_at, v.completed_by
        FROM visits v JOIN jobs j ON j.id = v.job_id
        WHERE j.job_code IN ('DRLB50-0062')
          AND v.visit_type = 'field_measure' AND v.status = 'done'
          AND v.result IS NULL AND v.job_id IS NOT NULL AND v.completed_at IS NOT NULL
          AND (v.completed_by IS NULL OR v.completed_by NOT LIKE 'CabinetTron%')
          AND NOT EXISTS (
              SELECT 1 FROM visits w
              WHERE w.job_id = v.job_id AND w.visit_type = 'field_measure' AND w.id <> v.id
                AND (w.status = 'pending' OR COALESCE(w.trip, 1) > COALESCE(v.trip, 1)))
          AND NOT EXISTS (
              SELECT 1 FROM field_measures f
              WHERE f.job_id = v.job_id AND f.complete_date IS NOT NULL)
    """)).fetchall()
    now = datetime.now(timezone.utc)
    for r in rows:
        day = _as_date(r.completed_at)
        back = _workday_on_or_after(day + timedelta(days=2))
        md = f"{day.month}/{day.day}"
        bind.execute(sa.text(
            "UPDATE visits SET result = 'rescheduled', result_notes = :n WHERE id = :id"
        ), {"id": r.id, "n": "Visited — not ready (marked Done before the Not ready button)"})
        bind.execute(sa.text("""
            INSERT INTO visits (visit_type, job_id, community_id, assigned_to, lat, lon,
                                open_date, close_date, scheduled_date, priority, status, notes,
                                parent_visit_id, trip, created_by, created_at)
            VALUES ('field_measure', :job, :comm, :who, :lat, :lon, :back, :back, :back, :pri,
                    'pending', :notes, :parent, :trip, :by, :now)
        """), {
            "job": r.job_id, "comm": r.community_id, "who": r.assigned_to, "lat": r.lat,
            "lon": r.lon, "back": back, "pri": r.priority or 0,
            "notes": f"not ready {md}", "parent": r.id, "trip": (r.trip or 1) + 1,
            "by": FIXED_BY, "now": now,
        })
        bind.execute(sa.text(
            "INSERT INTO field_measure_notes (job_id, body, author, created_at) "
            "VALUES (:job, :body, :author, :now)"
        ), {"job": r.job_id, "author": r.completed_by, "now": now,
            "body": f"Not ready: visited {md}/{str(day.year)[2:]} (marked Done before the Not ready button)"})


def downgrade() -> None:
    bind = op.get_bind()
    parents = [r[0] for r in bind.execute(sa.text(
        "SELECT parent_visit_id FROM visits WHERE created_by = :by"), {"by": FIXED_BY}).fetchall()]
    bind.execute(sa.text("DELETE FROM visits WHERE created_by = :by AND status = 'pending'"),
                 {"by": FIXED_BY})
    for pid in parents:
        bind.execute(sa.text(
            "UPDATE visits SET result = NULL, result_notes = NULL WHERE id = :id"), {"id": pid})

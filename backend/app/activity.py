"""Activity log — records who changed what.

Every state-changing API call (POST/PATCH/PUT/DELETE) and every sign-in is
written to activity_log with a plain-English description. Read-only page views
are deliberately NOT logged: they'd bury the useful rows in noise.

Best-effort by design: a logging failure must never break the request.
"""

import logging
import re

import jwt

from app.auth.security import ALGORITHM
from app.config import get_settings

logger = logging.getLogger("uvicorn.error")

SKIP_PREFIXES = ("/auth/token",)  # handled specially (sign-in), see below

# path fragment -> (entity name, human verb by method)
ENTITIES = [
    (r"^/jobs/(\d+)/documents", "document"),
    (r"^/jobs/(\d+)/service-requests", "service request"),
    (r"^/jobs/(\d+)/ordering", "ordering checklist"),
    (r"^/jobs/(\d+)/field-measure", "field measure"),
    (r"^/jobs/(\d+)/phase", "phase"),
    (r"^/jobs/(\d+)/quotes", "quote"),
    (r"^/jobs/(\d+)/orders", "order"),
    (r"^/jobs/(\d+)/notes", "job note"),
    (r"^/jobs/(\d+)/rooms", "room selection"),
    (r"^/jobs/(\d+)/hardware", "hardware"),
    (r"^/jobs/(\d+)", "job"),
    (r"^/jobs\b", "job"),
    (r"^/accounts/(\d+)", "account"),
    (r"^/accounts\b", "account"),
    (r"^/communities", "community"),
    (r"^/service-requests/(\d+)", "service request"),
    (r"^/service-lines/(\d+)", "service line"),
    (r"^/service-parts/(\d+)", "service part"),
    (r"^/quotes/(\d+)", "quote"),
    (r"^/orders/(\d+)", "order"),
    (r"^/documents/(\d+)", "document"),
    (r"^/auth/users/(\d+)/password", "user password"),
    (r"^/auth/users/(\d+)/invite", "user invite"),
    (r"^/auth/users/(\d+)", "user"),
    (r"^/auth/users\b", "user"),
    (r"^/autobot/visits/(\d+)", "visit"),
    (r"^/autobot/visits\b", "visit"),
    (r"^/autobot/workers/(\d+)", "worker"),
    (r"^/autobot/workers\b", "worker"),
    (r"^/autobot/duties", "duty chart"),
    (r"^/autobot/jobs/(\d+)/phase", "phase"),
    (r"^/autobot/generate", "Autobot sync"),
    (r"^/sync/feeds", "data refresh"),
    (r"^/reports/manager/share", "report share link"),
    (r"^/reports/po-receipts/refresh", "PO receipts refresh"),
    (r"^/reports/job-pl/refresh", "job P&L refresh"),
    (r"^/reports/domo-pl/refresh", "Domo P&L refresh"),
    (r"^/service-requests/import", "service request import"),
]

VERBS = {"POST": "Created", "PATCH": "Updated", "PUT": "Updated", "DELETE": "Deleted"}


def describe(method: str, path: str) -> tuple[str, str | None, str | None]:
    """-> (action text, entity, entity_id). Tolerates the /api prefix either way."""
    if path.startswith("/api/"):
        path = path[4:]
    for pattern, entity in ENTITIES:
        m = re.match(pattern, path)
        if m:
            eid = m.group(1) if m.groups() else None
            # Refresh/sync style endpoints read better as "Ran X"
            if entity.endswith(("refresh", "sync")) or entity in ("data refresh",):
                return (f"Ran {entity}", entity, eid)
            verb = VERBS.get(method, method.title())
            return (f"{verb} {entity}" + (f" #{eid}" if eid else ""), entity, eid)
    return (f"{VERBS.get(method, method)} {path}", None, None)


def user_from_token(auth_header: str | None) -> dict:
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return {}
    try:
        payload = jwt.decode(
            auth_header.split(" ", 1)[1], get_settings().secret_key, algorithms=[ALGORITHM]
        )
        return {"email": payload.get("sub"), "role": payload.get("role")}
    except jwt.PyJWTError:
        return {}


def record(
    *, action: str, method: str, path: str, status_code: int,
    email: str | None = None, role: str | None = None,
    entity: str | None = None, entity_id: str | None = None, ip: str | None = None,
) -> None:
    """Write one row on its own session — never raises."""
    from app.database import SessionLocal
    from app.models import ActivityLog, User

    try:
        with SessionLocal() as db:
            name = None
            if email:
                u = db.query(User).filter(User.email == email).first()
                if u:
                    name = u.full_name
                    role = role or u.role.value
            db.add(ActivityLog(
                user_email=email, user_name=name, role=role,
                action=action[:160], method=method, path=path[:300],
                entity=entity, entity_id=entity_id,
                status_code=status_code, ip=ip,
            ))
            db.commit()
    except Exception as exc:  # noqa: BLE001 — logging must never break a request
        logger.warning("activity log write failed: %s", exc)

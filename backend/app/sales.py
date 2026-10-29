"""Salesperson attribution rules.

Alex Talley is the salesperson for ALL national accounts (DR Horton, Century).
Paula Cook handles retail. Brian Scobey is the K&B manager, NOT a salesperson,
so he is never attributed as one (his jobs resolve to the real rep or none).
"""

CANONICAL = {
    "alex t.": "Alex Talley",
    "alex talley": "Alex Talley",
    "alex": "Alex Talley",
    "paula c.": "Paula Cook",
    "paula cook": "Paula Cook",
    "paula": "Paula Cook",
    "laurie reel": "Laurie Reel",
    "laurie r.": "Laurie Reel",
    # Brian is the manager — deliberately maps to nothing
    "brian s.": None,
    "brian scobey": None,
    "brian": None,
}


def resolve_salesperson(account_name: str | None, raw: str | None = None) -> str | None:
    """National accounts are always Alex; otherwise normalize the raw name."""
    if account_name and (account_name.startswith("DR Horton") or account_name.startswith("Century")):
        return "Alex Talley"
    if raw:
        return CANONICAL.get(raw.strip().lower(), raw.strip())
    return None


# --- KSR (Kitchen Sales Rep) attribution for the manager sales report ---------
# Unlike `salesperson` above (Brian is deliberately excluded), the KSR roster is
# the real selling team — Brian sells too. Attribution: job.ksr override, else
# the account's default ksr. Paula & Laurie are new in Q2 2026.
KSR_ROSTER = ["Alex Talley", "Paula Cook", "Laurie Reel", "Brian Scobey"]

_KSR_CANON = {
    "alex t.": "Alex Talley", "alex talley": "Alex Talley", "alex": "Alex Talley",
    "paula c.": "Paula Cook", "paula cook": "Paula Cook", "paula": "Paula Cook",
    "laurie r.": "Laurie Reel", "laurie reel": "Laurie Reel", "laurie": "Laurie Reel",
    "brian s.": "Brian Scobey", "brian scobey": "Brian Scobey", "brian": "Brian Scobey",
}


def canonical_ksr(raw: str | None) -> str | None:
    if not raw:
        return None
    return _KSR_CANON.get(raw.strip().lower(), raw.strip())


# Phones the user table doesn't carry. Emails come from the KSR's login.
KSR_PHONES = {"Brian Scobey": "850-890-0482"}


def ksr_contact(db, ksr: str) -> tuple[str, str | None, str | None]:
    """(name, phone, email) for a KSR -- the job's sales contact once a KSR is
    picked on it (Brian 10/29/26)."""
    from sqlalchemy import func

    from app.models import User

    name = canonical_ksr(ksr) or ksr
    user = db.query(User).filter(func.lower(User.full_name) == name.lower(), User.is_active.is_(True)).first()
    return name, KSR_PHONES.get(name), user.email if user else None


def effective_ksr(job) -> str | None:
    """The KSR credited for a job: its own override, else the account default."""
    return job.ksr or (job.account.ksr if job.account is not None else None)

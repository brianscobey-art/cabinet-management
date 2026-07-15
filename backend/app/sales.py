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

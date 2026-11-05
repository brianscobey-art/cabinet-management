"""One role guard for the whole COAST suite.

Each role gets a level per app: none, own (only the user's own visits or
installs), view (read only) or full. Pages and their APIs check the same table,
so a page and its API always refuse the same people.

This is the STARTING list proposed 11/5/26; Brian confirms it and assigns people.
Cost and margin reporting stays admin only (`finance_access` in api/deps.py).
"""

from fastapi import Depends, HTTPException, status

from app.auth.deps import get_current_user
from app.models import Role, User

APPS = ("cabinettron", "sterling", "optimus", "autobot", "tailgate")
LEVELS = ("none", "own", "view", "full")
_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}

SUITE_ACCESS: dict[Role, dict[str, str]] = {
    Role.admin: {"cabinettron": "full", "sterling": "full", "optimus": "full", "autobot": "full", "tailgate": "full"},
    Role.sales: {"cabinettron": "full", "sterling": "full", "optimus": "view", "autobot": "none", "tailgate": "none"},
    Role.ordering: {"cabinettron": "view", "sterling": "view", "optimus": "full", "autobot": "none", "tailgate": "none"},
    Role.field: {"cabinettron": "view", "sterling": "none", "optimus": "view", "autobot": "full", "tailgate": "view"},
    Role.installer_coordinator: {"cabinettron": "view", "sterling": "none", "optimus": "view", "autobot": "view", "tailgate": "full"},
    Role.inspector: {"cabinettron": "view", "sterling": "none", "optimus": "none", "autobot": "full", "tailgate": "none"},
    Role.service_tech: {"cabinettron": "none", "sterling": "none", "optimus": "none", "autobot": "own", "tailgate": "none"},
    Role.installer: {"cabinettron": "none", "sterling": "none", "optimus": "none", "autobot": "none", "tailgate": "own"},
}


def level_for(role: Role, app: str) -> str:
    if app not in APPS:
        raise ValueError(f"unknown app {app!r}")
    # A role missing from the table gets nothing: fail closed, never open.
    return SUITE_ACCESS.get(role, {}).get(app, "none")


def allows(role: Role, app: str, needed: str) -> bool:
    return _RANK[level_for(role, app)] >= _RANK[needed]


def suite_access(app: str, needed: str = "view"):
    """FastAPI dependency: suite_access("optimus", "full")."""
    if needed not in _RANK or needed == "none":
        raise ValueError(f"bad level {needed!r}")

    def checker(user: User = Depends(get_current_user)) -> User:
        if not allows(user.role, app, needed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your role ({user.role.value}) does not have {needed} access to {app}",
            )
        return user

    return checker


def access_map(role: Role) -> dict[str, str]:
    return {app: level_for(role, app) for app in APPS}

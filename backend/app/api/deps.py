"""Shared API dependencies: read = any office user, write = sales/admin for Phase 1.

The service_tech role is Autobot-only: it never passes read_access, so the whole
office API stays closed to it. Autobot's router carries its own role guards.
"""

from app.auth.deps import require_roles
from app.models import Role

read_access = require_roles(
    Role.sales, Role.field, Role.installer_coordinator, Role.inspector, Role.admin
)
write_access = require_roles(Role.sales, Role.admin)
# P&L / margin / cost reporting and the manager sales report are management-only —
# salespeople and the field don't see house-by-house profit or the exec summary.
finance_access = require_roles(Role.admin)

# National builders (DR Horton divisions, Century); everything else is local/retail.
NATIONAL_BUILDER_PREFIXES = ("DR Horton", "Century")

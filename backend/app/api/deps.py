"""Shared API dependencies: read = any active user, write = sales/admin for Phase 1."""

from app.auth.deps import get_current_user, require_roles
from app.models import Role

read_access = get_current_user
write_access = require_roles(Role.sales, Role.admin)

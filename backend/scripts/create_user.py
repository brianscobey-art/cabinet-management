"""Create a user from the command line (bootstrap the first admin).

Usage (from backend/):
    python -m scripts.create_user admin@townsendbuildingsupply.com "Brian Scobey" admin
Prompts for the password so it never lands in shell history.
"""

import getpass
import sys

from app.auth.security import hash_password
from app.database import SessionLocal
from app.models import Role, User


def main() -> None:
    if len(sys.argv) != 4:
        roles = ", ".join(r.value for r in Role)
        print(f'Usage: python -m scripts.create_user <email> "<full name>" <role>\nRoles: {roles}')
        sys.exit(1)

    email, full_name, role_arg = sys.argv[1].lower().strip(), sys.argv[2], sys.argv[3]
    try:
        role = Role(role_arg)
    except ValueError:
        print(f"Unknown role '{role_arg}'. Roles: {', '.join(r.value for r in Role)}")
        sys.exit(1)

    password = getpass.getpass("Password: ")
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        sys.exit(1)

    with SessionLocal() as db:
        if db.query(User).filter(User.email == email).first():
            print(f"User {email} already exists.")
            sys.exit(1)
        db.add(User(email=email, full_name=full_name, hashed_password=hash_password(password), role=role))
        db.commit()
    print(f"Created {role.value} user {email}")


if __name__ == "__main__":
    main()

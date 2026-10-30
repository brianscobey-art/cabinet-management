import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.database import get_db
from app.models import Role, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

# An admin sends this header (a user id) to see the app exactly as that user
# would (Brian 10/30/26). Read-only: anything but a GET is refused, so nothing
# is ever saved under the other person's name.
VIEW_AS_HEADER = "X-View-As"
READ_METHODS = ("GET", "HEAD", "OPTIONS")


def get_real_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    """The signed-in user from the token, ignoring any view-as header."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise credentials_error
    user = db.query(User).filter(User.email == payload.get("sub")).first()
    if user is None or not user.is_active:
        raise credentials_error
    return user


def view_as_target(request: Request, real: User, db: Session) -> User | None:
    """The user an admin is viewing as, or None. Non-admins' headers are ignored."""
    raw = request.headers.get(VIEW_AS_HEADER)
    if not raw or real.role != Role.admin:
        return None
    try:
        target = db.get(User, int(raw))
    except ValueError:
        target = None
    if target is None or not target.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="View-as user not found")
    return None if target.id == real.id else target


def get_current_user(
    request: Request, real: User = Depends(get_real_user), db: Session = Depends(get_db)
) -> User:
    target = view_as_target(request, real, db)
    if target is None:
        return real
    if request.method not in READ_METHODS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Viewing as {target.full_name} is read-only — switch back to yourself to make changes.",
        )
    return target


def require_roles(*roles: Role):
    """Dependency factory: require_roles(Role.admin) or require_roles(Role.sales, Role.admin)."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(r.value for r in roles)}",
            )
        return user

    return checker

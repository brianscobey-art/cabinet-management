from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, require_roles
from app.auth.schemas import PasswordReset, Token, UserCreate, UserOut, UserUpdate
from app.auth.security import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models import Role, User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form.username.lower().strip()).first()
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    return Token(access_token=create_access_token(user.email, user.role.value))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(Role.admin))],
)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(
        email=email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get(
    "/users",
    response_model=list[UserOut],
    dependencies=[Depends(require_roles(Role.admin))],
)
def list_users(db: Session = Depends(get_db)):
    return db.query(User).order_by(User.id).all()


def _get_user_or_404(user_id: int, db: Session) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _guard_last_admin(target: User, db: Session, *, removing: bool) -> None:
    """Refuse a change that would leave the system with zero active admins."""
    if not removing or target.role != Role.admin or not target.is_active:
        return
    other_admins = (
        db.query(User)
        .filter(User.role == Role.admin, User.is_active.is_(True), User.id != target.id)
        .count()
    )
    if other_admins == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Can't remove the last active admin — promote someone else first.",
        )


@router.patch(
    "/users/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require_roles(Role.admin))],
)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    target = _get_user_or_404(user_id, db)

    # Don't let an admin lock themselves out mid-session.
    if target.id == current.id:
        if payload.is_active is False:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You can't disable your own account.")
        if payload.role is not None and payload.role != Role.admin:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You can't change your own role.")

    # Don't strand the system with no admins.
    demoting = payload.role is not None and payload.role != Role.admin
    disabling = payload.is_active is False
    _guard_last_admin(target, db, removing=demoting or disabling)

    if payload.full_name is not None:
        target.full_name = payload.full_name
    if payload.role is not None:
        target.role = payload.role
    if payload.is_active is not None:
        target.is_active = payload.is_active
    db.commit()
    db.refresh(target)
    return target


@router.post(
    "/users/{user_id}/password",
    response_model=UserOut,
    dependencies=[Depends(require_roles(Role.admin))],
)
def reset_password(user_id: int, payload: PasswordReset, db: Session = Depends(get_db)):
    target = _get_user_or_404(user_id, db)
    target.hashed_password = hash_password(payload.password)
    db.commit()
    db.refresh(target)
    return target

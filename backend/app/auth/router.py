import secrets

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_real_user, require_roles, view_as_target
from app.auth.schemas import (
    PasswordReset,
    SetPassword,
    Token,
    UserCreate,
    MeOut,
    UserCreatedOut,
    UserOut,
    ViewAsOption,
    UserUpdate,
)
from app.auth.security import (
    create_access_token,
    create_invite_token,
    decode_invite_token,
    hash_password,
    verify_password,
)
from app.config import get_settings
from app.database import get_db
from app.email import send_invite_email
from app.models import Role, User

router = APIRouter(prefix="/auth", tags=["auth"])


def derive_username(full_name: str, email: str) -> str:
    """'Brian Scobey' -> 'brian.scobey'; a one-word name falls back to the email's local part."""
    import re
    import unicodedata

    name = unicodedata.normalize("NFKD", full_name or "").encode("ascii", "ignore").decode()
    words = [w for w in (re.sub(r"[^a-z0-9]", "", x.lower()) for x in name.split()) if w]
    if len(words) >= 2:
        return f"{words[0]}.{words[-1]}"
    local = re.sub(r"[^a-z0-9.]", "", (email or "").split("@")[0].lower())
    return local or (words[0] if words else "user")


def _unique_username(db: Session, base: str) -> str:
    name, n = base, 2
    while db.query(User).filter(User.username == name).first():
        name = f"{base}{n}"
        n += 1
    return name


def _send_invite(user: User) -> None:
    """Build the set-password link and email it. Raises on any failure."""
    settings = get_settings()
    token = create_invite_token(user.email)
    url = f"{settings.app_base_url.rstrip('/')}/#/set-password?token={token}"
    send_invite_email(user.email, user.full_name, url, settings)


@router.post("/token", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    from app.activity import record

    email = form.username.lower().strip()
    # Sign in with the "first.last" username or the full email address.
    user = db.query(User).filter(User.email == email).first()
    if user is None and "@" not in email:
        user = db.query(User).filter(User.username == email).first()
    if user is None or not verify_password(form.password, user.hashed_password):
        record(action="Sign-in failed", method="POST", path="/auth/token",
               status_code=401, email=email, entity="session")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        record(action="Sign-in blocked (account disabled)", method="POST", path="/auth/token",
               status_code=403, email=email, entity="session")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    record(action="Signed in", method="POST", path="/auth/token", status_code=200,
           email=user.email, role=user.role.value, entity="session")
    return Token(access_token=create_access_token(user.email, user.role.value))


@router.get("/me", response_model=MeOut)
def me(request: Request, real: User = Depends(get_real_user), db: Session = Depends(get_db)):
    """The user the app should render as -- the admin's view-as pick when one
    is set, with `viewed_by` naming the real admin so the header can say so."""
    target = view_as_target(request, real, db)
    if target is None:
        return MeOut.model_validate(real)
    return MeOut.model_validate(target).model_copy(update={"viewed_by": real.full_name})


@router.get("/view-as", response_model=list[ViewAsOption])
def view_as_options(real: User = Depends(get_real_user), db: Session = Depends(get_db)):
    """Who an admin can view the app as. Keyed on the REAL user, so the list
    still loads while the admin is already viewing as someone else. Leaves out
    the admin themself -- "yourself" is the picker's blank option."""
    if real.role != Role.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins only")
    users = (db.query(User).filter(User.is_active.is_(True), User.id != real.id)
             .order_by(User.full_name).all())
    return [ViewAsOption(id=u.id, full_name=u.full_name, role=u.role) for u in users]


@router.get("/invite-status", dependencies=[Depends(require_roles(Role.admin))])
def invite_status():
    """Whether email invites are configured — the UI adapts the add-user form."""
    return {"email_enabled": get_settings().email_enabled}


@router.post(
    "/users",
    response_model=UserCreatedOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(Role.admin))],
)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    settings = get_settings()
    use_invite = payload.send_invite and not payload.password
    if use_invite and not settings.email_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email invites aren't set up yet — set a temporary password for this user instead.",
        )
    # With an invite, they set their own password via the emailed link, so the
    # account starts with an unguessable random one that no one ever uses.
    raw_password = payload.password or secrets.token_urlsafe(32)

    user = User(
        email=email,
        username=_unique_username(db, derive_username(payload.full_name, email)),
        full_name=payload.full_name,
        hashed_password=hash_password(raw_password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    invite_sent = False
    invite_error = None
    if use_invite:
        try:
            _send_invite(user)
            invite_sent = True
        except Exception as exc:  # noqa: BLE001 — surface it; the user still exists
            invite_error = str(exc)

    return UserCreatedOut(user=user, invite_sent=invite_sent, invite_error=invite_error)


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
    if payload.username is not None:
        wanted = payload.username.lower().strip()
        clash = db.query(User).filter(User.username == wanted, User.id != target.id).first()
        if clash:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That username is taken.")
        target.username = wanted
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


@router.post(
    "/users/{user_id}/invite",
    dependencies=[Depends(require_roles(Role.admin))],
)
def resend_invite(user_id: int, db: Session = Depends(get_db)):
    """Re-email the set-password link (new user, or an expired/lost invite)."""
    if not get_settings().email_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email invites aren't set up yet.",
        )
    target = _get_user_or_404(user_id, db)
    try:
        _send_invite(target)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return {"invite_sent": True, "email": target.email}


@router.get("/activity", dependencies=[Depends(require_roles(Role.admin))])
def activity_log(
    limit: int = 200,
    user_email: str | None = None,
    entity: str | None = None,
    db: Session = Depends(get_db),
):
    """Who did what, newest first — admin only."""
    from app.models import ActivityLog

    q = db.query(ActivityLog)
    if user_email:
        q = q.filter(ActivityLog.user_email == user_email)
    if entity:
        q = q.filter(ActivityLog.entity == entity)
    rows = q.order_by(ActivityLog.at.desc()).limit(min(limit, 1000)).all()
    return [
        {
            "id": r.id,
            "at": r.at.isoformat() if r.at else None,
            "user_name": r.user_name,
            "user_email": r.user_email,
            "role": r.role,
            "action": r.action,
            "entity": r.entity,
            "entity_id": r.entity_id,
            "status_code": r.status_code,
            "method": r.method,
            "path": r.path,
        }
        for r in rows
    ]


@router.post("/set-password", response_model=Token)
def set_password(payload: SetPassword, db: Session = Depends(get_db)):
    """Public: a new user sets their own password from the emailed invite link."""
    try:
        email = decode_invite_token(payload.token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This link is invalid or has expired. Ask your admin to resend the invite.",
        )
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    user.hashed_password = hash_password(payload.password)
    user.is_active = True
    db.commit()
    # Log them straight in so they land in the app after choosing a password.
    return Token(access_token=create_access_token(user.email, user.role.value))

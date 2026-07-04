from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.api.deps import read_access, write_access
from app.api.schemas import (
    AccountCreate,
    AccountDetail,
    AccountOut,
    AccountUpdate,
    CommunityCreate,
    CommunityOut,
)
from app.database import get_db
from app.models import Account, Community

router = APIRouter(tags=["accounts"])


def get_account_or_404(account_id: int, db: Session) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


@router.get("/accounts", response_model=list[AccountOut], dependencies=[Depends(read_access)])
def list_accounts(db: Session = Depends(get_db)):
    return db.query(Account).order_by(Account.name).all()


@router.post(
    "/accounts",
    response_model=AccountOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(write_access)],
)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if db.query(Account).filter(Account.name == name).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account already exists")
    account = Account(name=name, type=payload.type, notes=payload.notes)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("/accounts/{account_id}", response_model=AccountDetail, dependencies=[Depends(read_access)])
def get_account(account_id: int, db: Session = Depends(get_db)):
    account = (
        db.query(Account)
        .options(selectinload(Account.communities))
        .filter(Account.id == account_id)
        .first()
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


@router.patch("/accounts/{account_id}", response_model=AccountOut, dependencies=[Depends(write_access)])
def update_account(account_id: int, payload: AccountUpdate, db: Session = Depends(get_db)):
    account = get_account_or_404(account_id, db)
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        updates["name"] = updates["name"].strip()
        clash = db.query(Account).filter(Account.name == updates["name"], Account.id != account_id).first()
        if clash:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account name already in use")
    for key, value in updates.items():
        setattr(account, key, value)
    db.commit()
    db.refresh(account)
    return account


@router.get("/communities", response_model=list[CommunityOut], dependencies=[Depends(read_access)])
def list_communities(account_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(Community)
    if account_id is not None:
        q = q.filter(Community.account_id == account_id)
    return q.order_by(Community.name).all()


@router.post(
    "/communities",
    response_model=CommunityOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(write_access)],
)
def create_community(payload: CommunityCreate, db: Session = Depends(get_db)):
    get_account_or_404(payload.account_id, db)
    name = payload.name.strip()
    exists = (
        db.query(Community)
        .filter(Community.account_id == payload.account_id, Community.name == name)
        .first()
    )
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Community already exists for this account",
        )
    community = Community(account_id=payload.account_id, name=name, market=payload.market)
    db.add(community)
    db.commit()
    db.refresh(community)
    return community

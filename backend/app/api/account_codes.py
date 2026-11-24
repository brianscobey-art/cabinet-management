"""Code Check report: jobs whose I-/G-code doesn't match DOMO (app.account_codes)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import account_codes
from app.api.deps import read_access, write_access
from app.database import get_db
from app.models import User

router = APIRouter(tags=["code-check"])


@router.get("/reports/code-check", dependencies=[Depends(read_access)])
def code_check(status: str = "open", db: Session = Depends(get_db)):
    return {"summary": account_codes.last_summary(db), "today": account_codes.daily(db),
            "flags": account_codes.flags(db, status)}


@router.post("/reports/code-check/run", dependencies=[Depends(write_access)])
def code_check_run(db: Session = Depends(get_db)):
    return account_codes.run(db)


@router.post("/reports/code-check/{flag_id}/fix")
def code_check_fix(flag_id: int, db: Session = Depends(get_db), user: User = Depends(write_access)):
    """Write the suggested DOMO code onto the job (the one-click approve)."""
    try:
        return account_codes.apply_fix(db, flag_id, user.full_name or user.email)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class StatusIn(BaseModel):
    status: str  # "ignored" or "open"


@router.post("/reports/code-check/{flag_id}/status")
def code_check_status(flag_id: int, payload: StatusIn, db: Session = Depends(get_db),
                      user: User = Depends(write_access)):
    try:
        return account_codes.set_status(db, flag_id, payload.status, user.full_name or user.email)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import read_access, write_access
from app.api.jobs import get_job_or_404
from app.api.schemas import (
    HardwareSelectionCreate,
    HardwareSelectionOut,
    HardwareSelectionUpdate,
    RoomSelectionCreate,
    RoomSelectionOut,
    RoomSelectionUpdate,
)
from app.database import get_db
from app.models import HardwareSelection, RoomSelection

router = APIRouter(tags=["selections"])


# --- Room selections (one row per room/zone) ---

@router.get(
    "/jobs/{job_id}/rooms",
    response_model=list[RoomSelectionOut],
    dependencies=[Depends(read_access)],
)
def list_rooms(job_id: int, db: Session = Depends(get_db)):
    get_job_or_404(job_id, db)
    return db.query(RoomSelection).filter(RoomSelection.job_id == job_id).order_by(RoomSelection.id).all()


@router.post(
    "/jobs/{job_id}/rooms",
    response_model=RoomSelectionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(write_access)],
)
def add_room(job_id: int, payload: RoomSelectionCreate, db: Session = Depends(get_db)):
    get_job_or_404(job_id, db)
    selection = RoomSelection(job_id=job_id, **payload.model_dump())
    db.add(selection)
    db.commit()
    db.refresh(selection)
    return selection


@router.patch("/rooms/{selection_id}", response_model=RoomSelectionOut, dependencies=[Depends(write_access)])
def update_room(selection_id: int, payload: RoomSelectionUpdate, db: Session = Depends(get_db)):
    selection = db.get(RoomSelection, selection_id)
    if selection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room selection not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(selection, key, value)
    db.commit()
    db.refresh(selection)
    return selection


@router.delete(
    "/rooms/{selection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(write_access)],
)
def delete_room(selection_id: int, db: Session = Depends(get_db)):
    selection = db.get(RoomSelection, selection_id)
    if selection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room selection not found")
    db.delete(selection)
    db.commit()


# --- Hardware selections ---

@router.get(
    "/jobs/{job_id}/hardware",
    response_model=list[HardwareSelectionOut],
    dependencies=[Depends(read_access)],
)
def list_hardware(job_id: int, db: Session = Depends(get_db)):
    get_job_or_404(job_id, db)
    return (
        db.query(HardwareSelection)
        .filter(HardwareSelection.job_id == job_id)
        .order_by(HardwareSelection.id)
        .all()
    )


@router.post(
    "/jobs/{job_id}/hardware",
    response_model=HardwareSelectionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(write_access)],
)
def add_hardware(job_id: int, payload: HardwareSelectionCreate, db: Session = Depends(get_db)):
    get_job_or_404(job_id, db)
    selection = HardwareSelection(job_id=job_id, **payload.model_dump())
    db.add(selection)
    db.commit()
    db.refresh(selection)
    return selection


@router.patch(
    "/hardware/{selection_id}",
    response_model=HardwareSelectionOut,
    dependencies=[Depends(write_access)],
)
def update_hardware(selection_id: int, payload: HardwareSelectionUpdate, db: Session = Depends(get_db)):
    selection = db.get(HardwareSelection, selection_id)
    if selection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hardware selection not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(selection, key, value)
    db.commit()
    db.refresh(selection)
    return selection


@router.delete(
    "/hardware/{selection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(write_access)],
)
def delete_hardware(selection_id: int, db: Session = Depends(get_db)):
    selection = db.get(HardwareSelection, selection_id)
    if selection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hardware selection not found")
    db.delete(selection)
    db.commit()

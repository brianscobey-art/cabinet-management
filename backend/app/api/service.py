"""Service requests: a per-job parts list plus labor lines that reference those
parts. Printed for the tech so they gather every part in the morning, then work
each labor line against its part.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, joinedload

from app.api.deps import read_access
from app.api.schemas import HardwareSelectionOut, RoomSelectionOut
from app.auth.deps import require_roles
from app.database import get_db
from app.models import Job, Role, ServiceLine, ServicePart, ServiceRequest, User
from app.service_excel import build_blank_template, parse_import

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter(tags=["service"])

# Office + field can build/run service requests.
service_write = require_roles(Role.sales, Role.field, Role.installer_coordinator, Role.admin)


class PartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    part: str
    cabinet: str | None
    qty: int
    notes: str | None


class LineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    part_id: int | None
    instruction: str
    done: bool
    done_by: str | None
    done_at: datetime | None
    note: str | None


class ServiceRequestSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    title: str | None
    status: str
    created_by: str | None
    created_at: datetime
    part_count: int
    line_count: int


class ServiceRequestDetail(BaseModel):
    id: int
    job_id: int
    job_code: str | None
    address: str
    community_name: str | None
    lot_number: str | None
    title: str | None
    status: str
    created_by: str | None
    created_at: datetime
    parts: list[PartOut]
    lines: list[LineOut]
    rooms: list[RoomSelectionOut]
    hardware: list[HardwareSelectionOut]


class RequestIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class RequestPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, max_length=20)


class PartIn(BaseModel):
    part: str = Field(min_length=1, max_length=200)
    cabinet: str | None = Field(default=None, max_length=100)
    qty: int = Field(default=1, ge=1)
    notes: str | None = Field(default=None, max_length=300)


class LineIn(BaseModel):
    part_id: int | None = None
    instruction: str = Field(min_length=1)


class LinePatch(BaseModel):
    done: bool | None = None
    note: str | None = None
    instruction: str | None = Field(default=None, min_length=1)


def _summary(sr: ServiceRequest) -> ServiceRequestSummary:
    return ServiceRequestSummary(
        id=sr.id, job_id=sr.job_id, title=sr.title, status=sr.status,
        created_by=sr.created_by, created_at=sr.created_at,
        part_count=len(sr.parts), line_count=len(sr.lines),
    )


def _detail(sr: ServiceRequest) -> ServiceRequestDetail:
    job = sr.job
    return ServiceRequestDetail(
        id=sr.id, job_id=sr.job_id, job_code=job.job_code, address=job.address,
        community_name=job.community.name if job.community else None,
        lot_number=job.lot_number, title=sr.title, status=sr.status,
        created_by=sr.created_by, created_at=sr.created_at,
        parts=[PartOut.model_validate(p) for p in sr.parts],
        lines=[LineOut.model_validate(l) for l in sr.lines],
        rooms=[RoomSelectionOut.model_validate(r) for r in job.room_selections],
        hardware=[HardwareSelectionOut.model_validate(h) for h in job.hardware_selections],
    )


def _get_request(db: Session, sr_id: int) -> ServiceRequest:
    sr = (
        db.query(ServiceRequest)
        .options(joinedload(ServiceRequest.job), joinedload(ServiceRequest.parts),
                 joinedload(ServiceRequest.lines))
        .filter(ServiceRequest.id == sr_id)
        .first()
    )
    if sr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service request not found")
    return sr


@router.get("/jobs/{job_id}/service-requests", response_model=list[ServiceRequestSummary],
            dependencies=[Depends(read_access)])
def list_requests(job_id: int, db: Session = Depends(get_db)):
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    reqs = (
        db.query(ServiceRequest)
        .options(joinedload(ServiceRequest.parts), joinedload(ServiceRequest.lines))
        .filter(ServiceRequest.job_id == job_id)
        .order_by(ServiceRequest.id.desc())
        .all()
    )
    return [_summary(sr) for sr in reqs]


@router.post("/jobs/{job_id}/service-requests", response_model=ServiceRequestDetail,
             status_code=status.HTTP_201_CREATED)
def create_request(job_id: int, payload: RequestIn, db: Session = Depends(get_db),
                   user: User = Depends(service_write)):
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    sr = ServiceRequest(job_id=job_id, title=payload.title, created_by=user.full_name)
    db.add(sr)
    db.commit()
    return _detail(_get_request(db, sr.id))


@router.get("/forms/service-template", dependencies=[Depends(read_access)])
def service_template():
    """Download a blank Service Request Excel template (fill + re-import)."""
    return Response(
        content=build_blank_template(),
        media_type=_XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="Service Request Template.xlsx"'},
    )


@router.post("/service-requests/import", response_model=ServiceRequestDetail,
             status_code=status.HTTP_201_CREATED)
def import_excel(file: UploadFile = File(...), db: Session = Depends(get_db),
                 user: User = Depends(service_write)):
    """Import a filled Service Request template — matches the job by Job Code."""
    try:
        parsed = parse_import(file.file.read())
    except Exception as e:  # noqa: BLE001 - surface a friendly parse error
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Could not read that file: {e}")
    job_code = (parsed.get("job_code") or "").strip()
    if not job_code:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="No Job Code in the sheet — add one so it can attach to a job.")
    job = db.query(Job).filter(Job.job_code == job_code).first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Job code '{job_code}' not found in the app.")
    sr = ServiceRequest(job_id=job.id, title=parsed.get("title"), created_by=user.full_name)
    db.add(sr)
    db.flush()
    part_by_num: dict[int, int] = {}
    for p in parsed["parts"]:
        part = ServicePart(service_request_id=sr.id, part=p["part"], cabinet=p.get("cabinet"),
                           qty=p.get("qty") or 1, notes=p.get("notes"))
        db.add(part)
        db.flush()
        if p.get("item_num"):
            part_by_num[p["item_num"]] = part.id
    for ln in parsed["lines"]:
        pid = part_by_num.get(ln["part_num"]) if ln.get("part_num") else None
        db.add(ServiceLine(service_request_id=sr.id, part_id=pid, instruction=ln["instruction"]))
    db.commit()
    return _detail(_get_request(db, sr.id))


@router.get("/service-requests/{sr_id}", response_model=ServiceRequestDetail,
            dependencies=[Depends(read_access)])
def get_request(sr_id: int, db: Session = Depends(get_db)):
    return _detail(_get_request(db, sr_id))


@router.patch("/service-requests/{sr_id}", response_model=ServiceRequestDetail)
def patch_request(sr_id: int, payload: RequestPatch, db: Session = Depends(get_db),
                  user: User = Depends(service_write)):
    sr = _get_request(db, sr_id)
    data = payload.model_dump(exclude_unset=True)
    if "title" in data:
        sr.title = data["title"]
    if "status" in data and data["status"]:
        sr.status = data["status"]
    db.commit()
    return _detail(_get_request(db, sr_id))


@router.delete("/service-requests/{sr_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_request(sr_id: int, db: Session = Depends(get_db), user: User = Depends(service_write)):
    sr = _get_request(db, sr_id)
    db.delete(sr)
    db.commit()


@router.post("/service-requests/{sr_id}/parts", response_model=PartOut,
             status_code=status.HTTP_201_CREATED)
def add_part(sr_id: int, payload: PartIn, db: Session = Depends(get_db),
             user: User = Depends(service_write)):
    _get_request(db, sr_id)
    part = ServicePart(service_request_id=sr_id, part=payload.part.strip(),
                       cabinet=(payload.cabinet or None), qty=payload.qty,
                       notes=(payload.notes or None))
    db.add(part)
    db.commit()
    db.refresh(part)
    return part


@router.delete("/service-parts/{part_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_part(part_id: int, db: Session = Depends(get_db), user: User = Depends(service_write)):
    part = db.get(ServicePart, part_id)
    if part is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")
    db.delete(part)
    db.commit()


@router.post("/service-requests/{sr_id}/lines", response_model=LineOut,
             status_code=status.HTTP_201_CREATED)
def add_line(sr_id: int, payload: LineIn, db: Session = Depends(get_db),
             user: User = Depends(service_write)):
    _get_request(db, sr_id)
    if payload.part_id is not None:
        part = db.get(ServicePart, payload.part_id)
        if part is None or part.service_request_id != sr_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="Part is not on this service request")
    line = ServiceLine(service_request_id=sr_id, part_id=payload.part_id,
                       instruction=payload.instruction.strip())
    db.add(line)
    db.commit()
    db.refresh(line)
    return line


@router.patch("/service-lines/{line_id}", response_model=LineOut)
def patch_line(line_id: int, payload: LinePatch, db: Session = Depends(get_db),
               user: User = Depends(service_write)):
    line = db.get(ServiceLine, line_id)
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line not found")
    data = payload.model_dump(exclude_unset=True)
    if "instruction" in data and data["instruction"]:
        line.instruction = data["instruction"].strip()
    if "note" in data:
        line.note = (data["note"] or None)
    if "done" in data and data["done"] is not None:
        line.done = data["done"]
        line.done_by = user.full_name if data["done"] else None
        line.done_at = datetime.now(timezone.utc) if data["done"] else None
    db.commit()
    db.refresh(line)
    return line


@router.delete("/service-lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_line(line_id: int, db: Session = Depends(get_db), user: User = Depends(service_write)):
    line = db.get(ServiceLine, line_id)
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line not found")
    db.delete(line)
    db.commit()

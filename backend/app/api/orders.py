from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.deps import read_access, write_access
from app.api.jobs import get_job_or_404
from app.api.quotes import get_quote_or_404
from app.config import get_settings
from app.database import get_db
from app.integrations.everluxe import OrderFormInfo, write_order_file
from app.models import ConfirmationStatus, Job, Order, QuoteStatus, ShipStatus, Supplier

router = APIRouter(tags=["orders"])


class OrderCreate(BaseModel):
    """Generate an Everluxe order from an accepted quote. Form fields default from
    settings / the job record; anything here overrides."""

    quote_id: int
    customer_po: str = ""
    plan_name: str = ""
    area: str = ""
    freight: str = ""
    delivery_type: str = "Everluxe Truck"
    assembly: bool = True
    door_style: str | None = None   # default: first room selection's door style
    door_color: str | None = None   # default: first room selection's finish
    ship_to_name: str | None = None
    delivery_address: str | None = None
    delivery_city_st_zip: str | None = None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    quote_id: int
    supplier: Supplier
    po_number: str | None
    confirmation_status: ConfirmationStatus
    ship_status: ShipStatus
    has_file: bool = False


class OrderCreateResult(OrderOut):
    skipped_skus: list[str]  # excluded appliance placeholders left off the form


class OrderUpdate(BaseModel):
    po_number: str | None = Field(default=None, max_length=100)
    confirmation_status: ConfirmationStatus | None = None
    ship_status: ShipStatus | None = None


def _out(order: Order, cls=OrderOut, **extra):
    return cls(
        id=order.id,
        job_id=order.job_id,
        quote_id=order.quote_id,
        supplier=order.supplier,
        po_number=order.po_number,
        confirmation_status=order.confirmation_status,
        ship_status=order.ship_status,
        has_file=bool(order.file_path),
        **extra,
    )


@router.get("/jobs/{job_id}/orders", response_model=list[OrderOut], dependencies=[Depends(read_access)])
def list_orders(job_id: int, db: Session = Depends(get_db)):
    get_job_or_404(job_id, db)
    orders = db.query(Order).filter(Order.job_id == job_id).order_by(Order.id).all()
    return [_out(o) for o in orders]


@router.post(
    "/jobs/{job_id}/orders",
    response_model=OrderCreateResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(write_access)],
)
def create_order(job_id: int, payload: OrderCreate, db: Session = Depends(get_db)):
    job: Job = (
        db.query(Job)
        .options(joinedload(Job.account), selectinload(Job.room_selections))
        .filter(Job.id == job_id)
        .first()
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    quote = get_quote_or_404(payload.quote_id, db)
    if quote.job_id != job_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Quote belongs to a different job"
        )
    if quote.status != QuoteStatus.accepted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an accepted quote can generate a supplier order",
        )
    if not quote.lines:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quote has no line items")

    settings = get_settings()
    first_room = job.room_selections[0] if job.room_selections else None
    lot = f" Lot {job.lot_number}" if job.lot_number else ""
    info = OrderFormInfo(
        dealer_name=settings.dealer_name,
        dealer_contact=settings.dealer_contact,
        dealer_phone=settings.dealer_phone,
        dealer_email=settings.dealer_email,
        ship_to_name=payload.ship_to_name or settings.ship_to_name,
        delivery_address=payload.delivery_address or settings.ship_to_address,
        delivery_city_st_zip=payload.delivery_city_st_zip or settings.ship_to_city_st_zip,
        delivery_type=payload.delivery_type,
        assembly=payload.assembly,
        customer_po=payload.customer_po,
        job_code=f"{job.account.name}{lot} — {job.address}",
        plan_name=payload.plan_name,
        area=payload.area,
        door_style=payload.door_style or (first_room.door_style if first_room else "") or "",
        door_color=payload.door_color or (first_room.finish if first_room else "") or "",
        freight=payload.freight,
        order_date=date.today().isoformat(),
    )

    order = Order(job_id=job_id, quote_id=quote.id, supplier=Supplier.everluxe, po_number=payload.customer_po or None)
    db.add(order)
    db.flush()

    path = write_order_file(job, quote, info, Path(settings.generated_dir))
    order.file_path = str(path)
    db.commit()
    db.refresh(order)
    return _out(order, cls=OrderCreateResult, skipped_skus=info.skipped_skus)


@router.get("/orders/{order_id}/file", dependencies=[Depends(read_access)])
def download_order_file(order_id: int, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if not order.file_path or not Path(order.file_path).exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order file not found")
    path = Path(order.file_path)
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.patch("/orders/{order_id}", response_model=OrderOut, dependencies=[Depends(write_access)])
def update_order(order_id: int, payload: OrderUpdate, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(order, key, value)
    db.commit()
    db.refresh(order)
    return _out(order)

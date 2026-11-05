"""What each COAST app sends to CabinetTron at its hand-off."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class RoomIn(BaseModel):
    room: str
    zone: str | None = None
    cabinet_brand: str | None = None
    series: str | None = None
    door_style: str | None = None
    finish: str | None = None


class LineIn(BaseModel):
    sku: str
    qty: int = 1
    list_price: Decimal = Decimal(0)
    room: str | None = None


class SoldIn(BaseModel):
    """Sterling: a quote was sold. CabinetTron makes (or updates) the job."""

    job_code: str
    account_name: str
    account_type: str = "builder"  # builder | retail
    job_type: str = "tract"  # tract | custom | remodel
    community: str | None = None
    lot_number: str | None = None
    address: str | None = None
    plan: str | None = None
    sales_contact_name: str = ""
    field_contact_name: str = ""
    field_contact_phone: str | None = None
    builder_po: str | None = None
    po_amount: Decimal | None = None
    sold_date: date | None = None
    quote_total: Decimal | None = None  # Sterling's dealer total, re-figured here
    rooms: list[RoomIn] = Field(default_factory=list)
    lines: list[LineIn] = Field(default_factory=list)


class OrderLineIn(BaseModel):
    sku: str
    qty: int = 1
    price: Decimal = Decimal(0)  # net each, as ordered


class OrderSentIn(BaseModel):
    """Optimus: the cabinet order went to the supplier."""

    job_code: str
    vendor: str | None = None
    po_number: str | None = None  # builder PO the order is placed against
    order_total: Decimal
    lines: list[OrderLineIn] = Field(default_factory=list)


class SoBackIn(BaseModel):
    """Optimus: the supplier's sales order (SO) came back."""

    job_code: str
    so_number: str
    so_subtotal: Decimal  # cabinets only, before build charge and freight
    so_total: Decimal | None = None  # grand total incl. build charge + freight
    lines: list[OrderLineIn] = Field(default_factory=list)
    out_of_stock: list[str] = Field(default_factory=list)


class PoBackIn(BaseModel):
    """Optimus: Carter's PO to the supplier was cut."""

    job_code: str
    carter_po_number: str
    carter_po_total: Decimal
    carter_po_date: date
    so_number: str


class ScheduleIn(BaseModel):
    """Builder feed (DRH schedule / Century / VendorSuite) for one lot."""

    job_code: str | None = None
    builder_po: str | None = None
    po_amount: Decimal | None = None
    community: str | None = None
    lot_number: str | None = None
    measure_date: date | None = None
    install_date: date | None = None
    po_cancelled: bool = False


class JobSetupIn(BaseModel):
    """Job setup request email (Carter G/I codes for a builder PO)."""

    request_number: str
    builder_po: str
    po_amount: Decimal | None = None
    lot_number: str | None = None
    ashley_code: str | None = None  # e.g. "CAB OMD60 135"
    g_code: str | None = None
    i_code: str | None = None


class FieldCheckIn(BaseModel):
    """Autobot: a field visit finished."""

    job_code: str
    visit_type: str  # field_measure | post_walk | punch_out | blue_tape
    done_on: date
    passed: bool
    discrepancies: list[str] = Field(default_factory=list)
    parts_needed: list[str] = Field(default_factory=list)
    notes: str | None = None


class InstallIn(BaseModel):
    """Tailgate: an install day finished."""

    job_code: str
    installed_on: date
    complete: bool
    notes: str | None = None
    photos: int = 0
    install_pay: Decimal | None = None

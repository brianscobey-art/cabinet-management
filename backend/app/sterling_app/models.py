import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.sterling_app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(500))


class CatalogItem(Base):
    """Master price catalog — one row per SKU per vendor."""

    __tablename__ = "catalog_items"
    __table_args__ = (UniqueConstraint("vendor", "sku", name="uq_vendor_sku"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str | None] = mapped_column(String(500), default=None)
    vendor: Mapped[str] = mapped_column(String(100), default="Everluxe")
    category: Mapped[str | None] = mapped_column(String(100), default=None)
    list_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    # Blank = use the settings default (0.217).
    multiplier: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), default=None)
    # Everluxe price-group prices (group chosen by the room's door style).
    # list_price stays the fallback when a group price is blank.
    price_g1: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    price_g2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    price_g3: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    price_g4: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    price_g5: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    # Hardware usage drivers: pieces per single cabinet (knob/pull count = doors + drawers).
    doors: Mapped[int] = mapped_column(default=0)
    drawers: Mapped[int] = mapped_column(default=0)
    # Per-SKU labor units (Everluxe Install-Hardware Pricing file):
    # assemble/install value = boxes for that SKU; None = not covered by the file.
    install_group: Mapped[str | None] = mapped_column(String(40), default=None)
    assemble_value: Mapped[int | None] = mapped_column(default=None)
    install_value: Mapped[int | None] = mapped_column(default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class DoorStyle(Base):
    """Door style / color -> Everluxe price group (1-5)."""

    __tablename__ = "door_styles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    code: Mapped[str | None] = mapped_column(String(60), default=None)  # SW, TD/TW, SS-...
    price_group: Mapped[int] = mapped_column(default=1)  # 1-5
    vendor: Mapped[str] = mapped_column(String(100), default="Everluxe")


class PlanInstall(Base):
    """Per-plan install rates (from the DRH All Division Pricing workbook)."""

    __tablename__ = "plan_installs"
    __table_args__ = (UniqueConstraint("division", "plan", name="uq_division_plan"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    division: Mapped[str] = mapped_column(String(100), index=True)  # DRH PC, DRH Montgomery...
    plan: Mapped[str] = mapped_column(String(100), index=True)
    cabinet_install: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    knob_install: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    handle_install: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    # Labor units from the workbook's Table8 (Floorplan SKU AE:AO); dollars = units x rate.
    assembly_units: Mapped[int] = mapped_column(default=0)
    install_units: Mapped[int] = mapped_column(default=0)
    # National-pricing margin override for this plan; blank = the default (15%).
    margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), default=None)


class PlanTops(Base):
    """Laminate top pricing for a plan (the Top Pricing Sheet, per division)."""

    __tablename__ = "plan_tops"
    __table_args__ = (UniqueConstraint("division", "plan", name="uq_tops_division_plan"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    division: Mapped[str] = mapped_column(String(100), index=True)  # "Jobs" for job-level tops
    plan: Mapped[str] = mapped_column(String(100), index=True)      # "Job {id}" for job-level tops
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True, default=None)
    material: Mapped[str] = mapped_column(String(100), default="Laminate")
    rate_sqft: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), default=None)  # blank = $26
    k_sinks: Mapped[int] = mapped_column(default=0)  # kitchen sinks (cutouts match)
    v_sinks: Mapped[int] = mapped_column(default=0)  # vanity sinks (cutouts match)

    pieces: Mapped[list["TopPiece"]] = relationship(
        back_populates="tops", cascade="all, delete-orphan", order_by="TopPiece.id"
    )


class TopPiece(Base):
    """One measured piece: top, backsplash, or side splash (W x D/H / 144 = sqft)."""

    __tablename__ = "top_pieces"

    id: Mapped[int] = mapped_column(primary_key=True)
    tops_id: Mapped[int] = mapped_column(ForeignKey("plan_tops.id"), index=True)
    area: Mapped[str] = mapped_column(String(20), default="Kitchen")  # Kitchen | Vanity
    kind: Mapped[str] = mapped_column(String(20), default="top")  # top | backsplash | side_splash
    qty: Mapped[int] = mapped_column(default=1)
    width: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    depth: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))  # depth or height

    tops: Mapped[PlanTops] = relationship(back_populates="pieces")


class PriceSnapshot(Base):
    """Frozen copy of national pricing as sent to a division — never repriced."""

    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    division: Mapped[str] = mapped_column(String(100), index=True)  # or "All"
    door_style: Mapped[str | None] = mapped_column(String(255), default=None)
    label: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    rows: Mapped[list["PriceSnapshotRow"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan", order_by="PriceSnapshotRow.id"
    )


class PriceSnapshotRow(Base):
    __tablename__ = "price_snapshot_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("price_snapshots.id"), index=True)
    division: Mapped[str] = mapped_column(String(100))
    plan: Mapped[str] = mapped_column(String(100))
    cogs: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    margin_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=Decimal("0"))
    sale: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    tops: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))

    snapshot: Mapped[PriceSnapshot] = relationship(back_populates="rows")


class PlanTemplateItem(Base):
    """One cabinet line of a builder plan's standard SKU list (Floorplan SKU sheet)."""

    __tablename__ = "plan_template_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    division: Mapped[str] = mapped_column(String(100), index=True)
    plan: Mapped[str] = mapped_column(String(100), index=True)
    sku: Mapped[str] = mapped_column(String(100))
    qty: Mapped[int] = mapped_column(default=1)
    area: Mapped[str | None] = mapped_column(String(100), default=None)  # room; "All" = one room
    doors: Mapped[int] = mapped_column(default=0)   # total for the line (qty included)
    drawers: Mapped[int] = mapped_column(default=0)


class PlanBid(Base):
    """Fixed per-plan bid price for a tract builder (e.g. DRH Madison STD)."""

    __tablename__ = "plan_bids"
    __table_args__ = (UniqueConstraint("builder", "plan", name="uq_builder_plan"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    builder: Mapped[str] = mapped_column(String(255), index=True)
    plan: Mapped[str] = mapped_column(String(100))
    bid_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Stage(str, enum.Enum):
    lead = "Lead"
    design = "Design"
    quoted = "Quoted"
    revision = "Revision"
    sold = "Sold"
    lost = "Lost"


class PricingMode(str, enum.Enum):
    margin = "margin"  # sell = cost / (1 - margin%)
    plan = "plan"      # sell = fixed plan/bid price


class InstallMode(str, enum.Enum):
    none = "none"
    cabinet_only = "cabinet_only"
    with_knobs = "with_knobs"
    with_handles = "with_handles"


class CostModel(str, enum.Enum):
    simple = "simple"  # cabinets + hardware + install (retail/custom quoting)
    matrix = "matrix"  # full DRH pricing matrix: + freight, sales tax, assembly, delivery


class JobType(str, enum.Enum):
    tract = "tract"
    custom = "custom"
    remodel = "remodel"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))  # display name / customer
    builder: Mapped[str | None] = mapped_column(String(255), default=None)  # account name
    community: Mapped[str | None] = mapped_column(String(255), default=None)
    lot_number: Mapped[str | None] = mapped_column(String(32), default=None)
    address: Mapped[str | None] = mapped_column(String(500), default=None)
    plan: Mapped[str | None] = mapped_column(String(100), default=None)
    job_type: Mapped[JobType] = mapped_column(
        Enum(JobType, native_enum=False, length=16), default=JobType.tract
    )
    stage: Mapped[Stage] = mapped_column(
        Enum(Stage, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e]),
        default=Stage.lead,
        index=True,
    )
    pricing_mode: Mapped[PricingMode] = mapped_column(
        Enum(PricingMode, native_enum=False, length=8), default=PricingMode.margin
    )
    margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), default=None)
    plan_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    # Per-quote rate overrides (blank = settings default). Tiers: DRH/Century
    # 0.21 mult + 10% freight; everyone else 0.24 + 11.8%.
    multiplier_override: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), default=None)
    freight_pct_override: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), default=None)
    assembly_boxes: Mapped[int | None] = mapped_column(default=None)  # $10/box; blank = plan units
    install_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), default=None)  # $/box; blank = $25
    hardware_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), default=None)  # $/pc labor; blank = $1 knob / $2 handle
    assembly_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), default=None)  # $/box; blank = $10
    pia_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)  # flat add-on to install
    ksr: Mapped[str | None] = mapped_column(String(120), default=None)  # Kitchen Sales Rep

    # Installation + hardware (rates seeded from the DRH pricing workbook).
    cost_model: Mapped[CostModel] = mapped_column(
        Enum(CostModel, native_enum=False, length=8), default=CostModel.simple
    )
    install_mode: Mapped[InstallMode] = mapped_column(
        Enum(InstallMode, native_enum=False, length=16), default=InstallMode.none
    )
    install_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)  # override; blank = plan lookup
    hardware_sku: Mapped[str | None] = mapped_column(String(100), default=None)  # knob/pull catalog SKU
    hardware_qty_override: Mapped[int | None] = mapped_column(default=None)  # blank = doors+drawers from lines

    sales_contact_name: Mapped[str | None] = mapped_column(String(255), default=None)
    sales_contact_phone: Mapped[str | None] = mapped_column(String(50), default=None)
    sales_contact_email: Mapped[str | None] = mapped_column(String(255), default=None)
    field_contact_name: Mapped[str | None] = mapped_column(String(255), default=None)
    field_contact_phone: Mapped[str | None] = mapped_column(String(50), default=None)
    field_contact_email: Mapped[str | None] = mapped_column(String(255), default=None)

    notes: Mapped[str | None] = mapped_column(Text, default=None)

    # Set once the job is pushed into CabinetTron.
    exported_job_id: Mapped[int | None] = mapped_column(default=None)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    rooms: Mapped[list["Room"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="Room.id"
    )


class Room(Base):
    """One priced room/zone on a job (kitchen perimeter and island are two rows)."""

    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    zone: Mapped[str | None] = mapped_column(String(100), default=None)
    cabinet_brand: Mapped[str | None] = mapped_column(String(100), default=None)
    series: Mapped[str | None] = mapped_column(String(100), default=None)
    door_style: Mapped[str | None] = mapped_column(String(100), default=None)
    finish: Mapped[str | None] = mapped_column(String(100), default=None)
    wood_species: Mapped[str | None] = mapped_column(String(100), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    job: Mapped[Job] = relationship(back_populates="rooms")
    lines: Mapped[list["LineItem"]] = relationship(
        back_populates="room", cascade="all, delete-orphan", order_by="LineItem.id"
    )


class LineItem(Base):
    __tablename__ = "line_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), index=True)
    sku: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500), default=None)
    qty: Mapped[int] = mapped_column(default=1)
    list_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    # Blank = catalog/default multiplier at time of pricing.
    multiplier: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), default=None)
    notes: Mapped[str | None] = mapped_column(String(500), default=None)

    room: Mapped[Room] = relationship(back_populates="lines")


class CoverVendor(Base):
    """PO-type presets for the Sales Order Cover Sheet (Type -> abbr/vendor/code)."""

    __tablename__ = "cover_vendors"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), default="product")  # product | labor
    po_type: Mapped[str] = mapped_column(String(60))
    po_abb: Mapped[str | None] = mapped_column(String(10), default=None)
    vendor: Mapped[str | None] = mapped_column(String(120), default=None)
    vendor_code: Mapped[str | None] = mapped_column(String(30), default=None)


class Superintendent(Base):
    """Builder superintendents picked on the cover sheet."""

    __tablename__ = "superintendents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40), default=None)
    email: Mapped[str | None] = mapped_column(String(160), default=None)
    company: Mapped[str | None] = mapped_column(String(120), default=None)


class CoverSheet(Base):
    """Sales Order Cover Sheet — standalone, or tied to a Sterling job."""

    __tablename__ = "cover_sheets"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True, default=None)

    job_code: Mapped[str | None] = mapped_column(String(40), default=None)
    sale_date: Mapped[str | None] = mapped_column(String(20), default=None)  # m/d/yy as typed
    plan_type: Mapped[str | None] = mapped_column(String(80), default=None)
    customer_account: Mapped[str | None] = mapped_column(String(40), default=None)
    job_number: Mapped[str | None] = mapped_column(String(40), default=None)   # G-code
    install_code: Mapped[str | None] = mapped_column(String(40), default=None)  # I-code
    scope: Mapped[str | None] = mapped_column(String(200), default=None)  # typed per job

    # Job Information (the house)
    ji_name: Mapped[str | None] = mapped_column(String(120), default=None)
    ji_contact: Mapped[str | None] = mapped_column(String(120), default=None)
    ji_address: Mapped[str | None] = mapped_column(String(200), default=None)
    ji_city: Mapped[str | None] = mapped_column(String(80), default=None)
    ji_state: Mapped[str | None] = mapped_column(String(10), default=None)
    ji_zip: Mapped[str | None] = mapped_column(String(15), default=None)
    ji_phone: Mapped[str | None] = mapped_column(String(40), default=None)
    ji_email: Mapped[str | None] = mapped_column(String(160), default=None)

    # Customer (who is billed)
    cu_company: Mapped[str | None] = mapped_column(String(120), default=None)
    cu_name: Mapped[str | None] = mapped_column(String(120), default=None)
    cu_address: Mapped[str | None] = mapped_column(String(200), default=None)
    cu_city: Mapped[str | None] = mapped_column(String(80), default=None)
    cu_state: Mapped[str | None] = mapped_column(String(10), default=None)
    cu_zip: Mapped[str | None] = mapped_column(String(15), default=None)
    cu_phone: Mapped[str | None] = mapped_column(String(40), default=None)
    cu_email: Mapped[str | None] = mapped_column(String(160), default=None)

    super_name: Mapped[str | None] = mapped_column(String(120), default=None)
    super_phone: Mapped[str | None] = mapped_column(String(40), default=None)
    super_email: Mapped[str | None] = mapped_column(String(160), default=None)

    tax_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=Decimal("9"))  # materials tax
    sale_cabinets: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    sale_countertops: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    sale_other: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    pos: Mapped[list["CoverSheetPO"]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan", order_by="CoverSheetPO.id"
    )


class CoverSheetPO(Base):
    """One PO line. Products: amount1=Cost, amount2=Freight.
    Labor: amount1=Assemble, amount2=Install. Total = amount1+amount2 unless overridden."""

    __tablename__ = "cover_sheet_pos"

    id: Mapped[int] = mapped_column(primary_key=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("cover_sheets.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="product")  # product | labor
    po_type: Mapped[str | None] = mapped_column(String(60), default=None)
    po_abb: Mapped[str | None] = mapped_column(String(10), default=None)
    vendor: Mapped[str | None] = mapped_column(String(120), default=None)
    vendor_code: Mapped[str | None] = mapped_column(String(30), default=None)
    amount1: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    amount2: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total_override: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)

    sheet: Mapped[CoverSheet] = relationship(back_populates="pos")


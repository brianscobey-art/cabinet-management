from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.sterling_app.models import CostModel, InstallMode, JobType, PricingMode, Stage


# --- Settings ---

class SettingsOut(BaseModel):
    default_multiplier: Decimal
    default_margin_pct: Decimal
    cabinettron_url: str
    cabinettron_email: str
    cabinettron_password_set: bool
    ksr_list: str  # comma-separated Kitchen Sales Rep names
    national_margin: Decimal


class SettingsUpdate(BaseModel):
    default_multiplier: Decimal | None = Field(default=None, gt=0, le=1)
    default_margin_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    cabinettron_url: str | None = None
    cabinettron_email: str | None = None
    cabinettron_password: str | None = None
    ksr_list: str | None = None
    national_margin: Decimal | None = Field(default=None, ge=0, lt=100)


# --- Catalog ---

class CatalogCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    description: str | None = None
    vendor: str = Field(default="Everluxe", max_length=100)
    category: str | None = None
    list_price: Decimal = Field(default=Decimal("0"), ge=0)
    multiplier: Decimal | None = Field(default=None, gt=0, le=1)
    price_g1: Decimal | None = Field(default=None, ge=0)
    price_g2: Decimal | None = Field(default=None, ge=0)
    price_g3: Decimal | None = Field(default=None, ge=0)
    price_g4: Decimal | None = Field(default=None, ge=0)
    price_g5: Decimal | None = Field(default=None, ge=0)
    doors: int = Field(default=0, ge=0)
    drawers: int = Field(default=0, ge=0)
    install_group: str | None = Field(default=None, max_length=40)
    assemble_value: int | None = Field(default=None, ge=0)
    install_value: int | None = Field(default=None, ge=0)


class CatalogUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    vendor: str | None = None
    category: str | None = None
    list_price: Decimal | None = Field(default=None, ge=0)
    multiplier: Decimal | None = Field(default=None, gt=0, le=1)
    price_g1: Decimal | None = Field(default=None, ge=0)
    price_g2: Decimal | None = Field(default=None, ge=0)
    price_g3: Decimal | None = Field(default=None, ge=0)
    price_g4: Decimal | None = Field(default=None, ge=0)
    price_g5: Decimal | None = Field(default=None, ge=0)
    doors: int | None = Field(default=None, ge=0)
    drawers: int | None = Field(default=None, ge=0)
    install_group: str | None = Field(default=None, max_length=40)
    assemble_value: int | None = Field(default=None, ge=0)
    install_value: int | None = Field(default=None, ge=0)


class CatalogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    description: str | None
    vendor: str
    category: str | None
    list_price: Decimal
    multiplier: Decimal | None
    price_g1: Decimal | None
    price_g2: Decimal | None
    price_g3: Decimal | None
    price_g4: Decimal | None
    price_g5: Decimal | None
    doors: int
    drawers: int
    install_group: str | None
    assemble_value: int | None
    install_value: int | None
    updated_at: datetime


class DoorStyleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str | None
    price_group: int
    vendor: str


class PlanInstallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    division: str
    plan: str
    cabinet_install: Decimal
    knob_install: Decimal
    handle_install: Decimal
    assembly_units: int
    install_units: int


class PlanTemplateSummary(BaseModel):
    division: str
    plan: str
    line_count: int
    total_qty: int


class JobFromPlan(BaseModel):
    division: str
    plan: str
    name: str | None = None  # default: "<plan> — new"
    builder: str | None = None
    community: str | None = None
    lot_number: str | None = None
    door_style: str | None = None  # applied to the created room(s)


# --- Plan bids ---

class PlanBidCreate(BaseModel):
    builder: str = Field(min_length=1, max_length=255)
    plan: str = Field(min_length=1, max_length=100)
    bid_price: Decimal = Field(ge=0)
    notes: str | None = None


class PlanBidUpdate(BaseModel):
    builder: str | None = Field(default=None, min_length=1)
    plan: str | None = Field(default=None, min_length=1)
    bid_price: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class PlanBidOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    builder: str
    plan: str
    bid_price: Decimal
    notes: str | None


# --- Line items ---

class LineCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    description: str | None = None
    qty: int = Field(default=1, ge=1)
    list_price: Decimal | None = Field(default=None, ge=0)  # None -> catalog lookup
    multiplier: Decimal | None = Field(default=None, gt=0, le=1)
    notes: str | None = None
    for_room_id: int | None = None   # lumber: the room it was bought for


class LineUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    qty: int | None = Field(default=None, ge=1)
    list_price: Decimal | None = Field(default=None, ge=0)
    multiplier: Decimal | None = Field(default=None, gt=0, le=1)
    notes: str | None = None
    for_room_id: int | None = None


class LineOut(BaseModel):
    id: int
    room_id: int
    sku: str
    description: str | None
    qty: int
    list_price: Decimal
    multiplier: Decimal | None
    notes: str | None
    for_room_id: int | None = None
    # computed
    effective_multiplier: Decimal
    net_each: Decimal
    cost: Decimal
    excluded: bool


# --- Rooms ---

class RoomCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    zone: str | None = None
    cabinet_brand: str | None = None
    series: str | None = None
    door_style: str | None = None
    finish: str | None = None
    wood_species: str | None = None
    notes: str | None = None
    pia_amount: Decimal | None = Field(default=None, ge=0)


class RoomUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    zone: str | None = None
    cabinet_brand: str | None = None
    series: str | None = None
    door_style: str | None = None
    finish: str | None = None
    wood_species: str | None = None
    notes: str | None = None
    pia_amount: Decimal | None = Field(default=None, ge=0)


class RoomCosts(BaseModel):
    """One room's own money — what it costs, sells for, and earns."""

    room_id: int
    name: str
    zone: str | None = None
    line_count: int = 0
    list: Decimal
    cabinets: Decimal
    lumber: Decimal
    hardware_qty: int
    hardware_material: Decimal
    freight: Decimal
    tax: Decimal
    boxes: int
    assembly: Decimal
    install_units: int
    install: Decimal
    pia: Decimal
    cost: Decimal
    sell: Decimal
    margin_amount: Decimal
    margin_pct: Decimal | None = None


class TopRoomRow(BaseModel):
    room: str
    rate_class: str
    sqft: Decimal
    rate: Decimal
    surface: Decimal
    extras: Decimal
    extra_qty: int
    total: Decimal


class RoomOut(BaseModel):
    id: int
    job_id: int
    name: str
    zone: str | None
    cabinet_brand: str | None
    series: str | None
    door_style: str | None
    finish: str | None
    wood_species: str | None
    notes: str | None
    pia_amount: Decimal | None = None
    lines: list[LineOut]
    # computed
    list_total: Decimal
    cost: Decimal
    sell: Decimal


# --- Jobs ---

class JobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    builder: str | None = None
    community: str | None = None
    lot_number: str | None = Field(default=None, max_length=32)
    address: str | None = None
    plan: str | None = None
    job_type: JobType = JobType.tract
    stage: Stage = Stage.lead
    pricing_mode: PricingMode = PricingMode.margin
    margin_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    plan_price: Decimal | None = Field(default=None, ge=0)
    multiplier_override: Decimal | None = Field(default=None, gt=0, le=1)
    freight_pct_override: Decimal | None = Field(default=None, ge=0, le=1)
    assembly_boxes: int | None = Field(default=None, ge=0)
    install_rate: Decimal | None = Field(default=None, ge=0)
    hardware_rate: Decimal | None = Field(default=None, ge=0)
    assembly_rate: Decimal | None = Field(default=None, ge=0)
    pia_amount: Decimal | None = Field(default=None, ge=0)
    ksr: str | None = Field(default=None, max_length=120)
    cost_model: CostModel = CostModel.simple
    install_mode: InstallMode = InstallMode.none
    install_price: Decimal | None = Field(default=None, ge=0)
    hardware_sku: str | None = None
    hardware_qty_override: int | None = Field(default=None, ge=0)
    sales_contact_name: str | None = None
    sales_contact_phone: str | None = None
    sales_contact_email: str | None = None
    field_contact_name: str | None = None
    field_contact_phone: str | None = None
    field_contact_email: str | None = None
    notes: str | None = None


class JobUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    builder: str | None = None
    community: str | None = None
    lot_number: str | None = None
    address: str | None = None
    plan: str | None = None
    job_type: JobType | None = None
    stage: Stage | None = None
    pricing_mode: PricingMode | None = None
    margin_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    plan_price: Decimal | None = Field(default=None, ge=0)
    multiplier_override: Decimal | None = Field(default=None, gt=0, le=1)
    freight_pct_override: Decimal | None = Field(default=None, ge=0, le=1)
    assembly_boxes: int | None = Field(default=None, ge=0)
    install_rate: Decimal | None = Field(default=None, ge=0)
    hardware_rate: Decimal | None = Field(default=None, ge=0)
    assembly_rate: Decimal | None = Field(default=None, ge=0)
    pia_amount: Decimal | None = Field(default=None, ge=0)
    ksr: str | None = Field(default=None, max_length=120)
    cost_model: CostModel | None = None
    install_mode: InstallMode | None = None
    install_price: Decimal | None = Field(default=None, ge=0)
    hardware_sku: str | None = None
    hardware_qty_override: int | None = Field(default=None, ge=0)
    sales_contact_name: str | None = None
    sales_contact_phone: str | None = None
    sales_contact_email: str | None = None
    field_contact_name: str | None = None
    field_contact_phone: str | None = None
    field_contact_email: str | None = None
    notes: str | None = None


class JobListItem(BaseModel):
    id: int
    name: str
    builder: str | None
    community: str | None
    lot_number: str | None
    plan: str | None
    ksr: str | None
    job_type: JobType
    stage: Stage
    room_count: int
    cost: Decimal
    sell: Decimal
    margin_amount: Decimal
    margin_pct_actual: Decimal | None
    exported_job_id: int | None
    updated_at: datetime
    last_activity: datetime | None = None


class JobDetail(BaseModel):
    id: int
    name: str
    builder: str | None
    community: str | None
    lot_number: str | None
    address: str | None
    plan: str | None
    job_type: JobType
    stage: Stage
    pricing_mode: PricingMode
    margin_pct: Decimal | None
    plan_price: Decimal | None
    multiplier_override: Decimal | None
    freight_pct_override: Decimal | None
    assembly_boxes: int | None
    multiplier_effective: Decimal
    freight_pct_effective: Decimal
    assembly_boxes_effective: int
    install_rate: Decimal | None
    install_rate_effective: Decimal
    hardware_rate: Decimal | None
    hardware_rate_effective: Decimal
    assembly_rate: Decimal | None
    assembly_rate_effective: Decimal
    pia_amount: Decimal | None
    pia: Decimal
    ksr: str | None
    install_units_effective: int
    cost_model: CostModel
    install_mode: InstallMode
    install_price: Decimal | None
    hardware_sku: str | None
    hardware_qty_override: int | None
    sales_contact_name: str | None
    sales_contact_phone: str | None
    sales_contact_email: str | None
    field_contact_name: str | None
    field_contact_phone: str | None
    field_contact_email: str | None
    notes: str | None
    exported_job_id: int | None
    exported_at: datetime | None
    created_at: datetime
    updated_at: datetime
    rooms: list[RoomOut]
    rooms_breakdown: list[RoomCosts] = []
    tops_rows: list[TopRoomRow] = []
    job_level_cost: Decimal = Decimal("0")
    job_level_sell: Decimal = Decimal("0")
    job_pia: Decimal = Decimal("0")
    # computed rollups
    cost: Decimal
    sell: Decimal
    margin_amount: Decimal
    margin_pct_actual: Decimal | None
    list_total: Decimal
    lumber_cost: Decimal
    cabinets_cost: Decimal
    hardware_qty: int
    hardware_unit_cost: Decimal
    hardware_material: Decimal
    hardware_labor: Decimal
    hardware_cost: Decimal
    freight: Decimal
    tax: Decimal
    assembly: Decimal
    delivery: Decimal
    install_cost: Decimal
    install_hw_sell: Decimal  # sell allocated to install+hardware (rooms + this = cabinet sell)
    tops: Decimal  # countertops at charge rates — added after margin

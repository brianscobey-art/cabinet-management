from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import AccountType, JobStatus, JobType


# --- Accounts ---

class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: AccountType
    notes: str | None = None


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    notes: str | None = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: AccountType
    notes: str | None
    created_at: datetime


# --- Communities ---

class CommunityCreate(BaseModel):
    account_id: int
    name: str = Field(min_length=1, max_length=255)
    market: str | None = None


class CommunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    name: str
    market: str | None


class AccountDetail(AccountOut):
    communities: list[CommunityOut]


# --- Selections ---

class RoomSelectionCreate(BaseModel):
    room: str = Field(min_length=1, max_length=100)
    zone: str | None = Field(default=None, max_length=100)
    cabinet_brand: str | None = None
    series: str | None = None
    door_style: str | None = None
    finish: str | None = None
    wood_species: str | None = None
    notes: str | None = None


class RoomSelectionUpdate(BaseModel):
    room: str | None = Field(default=None, min_length=1, max_length=100)
    zone: str | None = None
    cabinet_brand: str | None = None
    series: str | None = None
    door_style: str | None = None
    finish: str | None = None
    wood_species: str | None = None
    notes: str | None = None


class RoomSelectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    room: str
    zone: str | None
    cabinet_brand: str | None
    series: str | None
    door_style: str | None
    finish: str | None
    wood_species: str | None
    notes: str | None


class HardwareSelectionCreate(BaseModel):
    room: str | None = Field(default=None, max_length=100)
    vendor: str | None = Field(default=None, max_length=100)
    item: str = Field(min_length=1, max_length=255)
    qty: int = Field(default=1, ge=1)


class HardwareSelectionUpdate(BaseModel):
    room: str | None = None
    vendor: str | None = None
    item: str | None = Field(default=None, min_length=1, max_length=255)
    qty: int | None = Field(default=None, ge=1)


class HardwareSelectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    room: str | None
    vendor: str | None
    item: str
    qty: int


# --- Jobs ---

class JobCreate(BaseModel):
    account_id: int
    community_id: int | None = None
    lot_number: str | None = Field(default=None, max_length=32)
    address: str = Field(min_length=1, max_length=500)
    job_type: JobType
    install_date: date | None = None
    sales_contact_name: str = Field(min_length=1, max_length=255)
    sales_contact_phone: str | None = Field(default=None, max_length=50)
    sales_contact_email: EmailStr | None = None
    field_contact_name: str = Field(min_length=1, max_length=255)
    field_contact_phone: str | None = Field(default=None, max_length=50)
    field_contact_email: EmailStr | None = None
    notes: str | None = None


class JobUpdate(BaseModel):
    community_id: int | None = None
    lot_number: str | None = None
    address: str | None = Field(default=None, min_length=1, max_length=500)
    job_type: JobType | None = None
    status: JobStatus | None = None
    install_date: date | None = None
    warranty_start_date: date | None = None
    sales_contact_name: str | None = Field(default=None, min_length=1, max_length=255)
    sales_contact_phone: str | None = None
    sales_contact_email: EmailStr | None = None
    field_contact_name: str | None = Field(default=None, min_length=1, max_length=255)
    field_contact_phone: str | None = None
    field_contact_email: EmailStr | None = None
    notes: str | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    community_id: int | None
    lot_number: str | None
    address: str
    job_type: JobType
    status: JobStatus
    install_date: date | None
    warranty_start_date: date | None
    sales_contact_name: str
    sales_contact_phone: str | None
    sales_contact_email: str | None
    field_contact_name: str
    field_contact_phone: str | None
    field_contact_email: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class JobListItem(BaseModel):
    """Compact row for the jobs table."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    account_name: str
    community_name: str | None
    lot_number: str | None
    address: str
    job_type: JobType
    status: JobStatus
    install_date: date | None


class JobDetail(JobOut):
    """The 'pull up any job and see every room's spec' view."""

    account_name: str
    community_name: str | None
    room_selections: list[RoomSelectionOut]
    hardware_selections: list[HardwareSelectionOut]

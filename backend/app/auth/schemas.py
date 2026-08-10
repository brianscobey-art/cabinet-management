from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import Role


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    role: Role
    # Password is optional: when email invites are on, we email a set-password
    # link instead. Supply a password only to set one directly (no email).
    password: str | None = Field(default=None, min_length=8, max_length=128)
    send_invite: bool = True


class SetPassword(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    """Admin edits to an existing user. Every field optional — send only what changes."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: Role | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # plain str: responses must never 500 on an address already in the DB
    # (EmailStr rejects things like .local); strictness belongs on input only
    email: str
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime


class UserCreatedOut(BaseModel):
    """Result of creating a user: the user plus whether the invite email went out."""

    user: UserOut
    invite_sent: bool = False
    invite_error: str | None = None

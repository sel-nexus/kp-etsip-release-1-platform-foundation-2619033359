"""Define validated administration requests and public responses."""
import re
from typing import Annotated, Literal
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator
from app.auth.schemas import PublicUser, Role

Permission = Literal['view', 'create', 'edit', 'delete', 'export', 'administer']


class UserInput(BaseModel):
    """Validate editable account fields without accepting database operators."""
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=254)
    role: Role
    portfolioAccess: list[str] = Field(default_factory=list, max_length=500)
    status: Literal['Active', 'Inactive'] = 'Active'
    managerName: str | None = Field(default=None, max_length=200)
    vendorIndicator: bool = False
    password: str | None = Field(default=None, min_length=12, max_length=72)

    @field_validator('name')
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Require a nonblank display name."""
        value = value.strip()
        if not value:
            raise ValueError('Name is required')
        return value

    @field_validator('email')
    @classmethod
    def validate_email(cls, value: str) -> str:
        """Normalize local email addresses before uniqueness checks."""
        value = value.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Enter a valid email address')
        return value

    @field_validator('password')
    @classmethod
    def validate_password(cls, value: str | None) -> str | None:
        """Prevent bcrypt from silently truncating UTF-8 passwords."""
        if value is not None and len(value.encode('utf-8')) > 72:
            raise ValueError('Password must be at most 72 UTF-8 bytes')
        return value


class UserPage(BaseModel):
    """Return a bounded page of public accounts."""
    items: list[PublicUser]
    total: int
    limit: int
    offset: int


class RoleInput(BaseModel):
    """Accept a predefined role and its restricted permission set."""
    model_config = ConfigDict(extra='forbid')
    name: Role
    description: str = Field(default='', max_length=1000)
    permissions: list[Permission] = Field(max_length=6)

    @field_validator('permissions')
    @classmethod
    def unique_permissions(cls, value: list[str]) -> list[str]:
        """Reject duplicate permission entries."""
        if len(value) != len(set(value)):
            raise ValueError('Permissions must be unique')
        return value


class PublicRole(RoleInput):
    """Expose a role identifier and validated role fields."""
    model_config = ConfigDict(populate_by_name=True, extra='ignore')
    id: Annotated[str, BeforeValidator(str)] = Field(validation_alias='_id', serialization_alias='id')


class RolePage(BaseModel):
    """Return a bounded page of roles."""
    items: list[PublicRole]
    total: int
    limit: int
    offset: int

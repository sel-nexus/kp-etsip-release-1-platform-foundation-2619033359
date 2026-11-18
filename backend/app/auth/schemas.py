"""Define the public identity and profile contracts."""
from typing import Annotated, Literal
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

Role = Literal["Administrator", "Executive", "Portfolio Leader", "Engineer", "Auditor", "Read Only"]
LandingPage = Literal["dashboard", "applications"]


class LoginRequest(BaseModel):
    """Accept local credentials without permitting query operators."""
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class PublicUser(BaseModel):
    """Expose only safe account fields."""
    model_config = ConfigDict(populate_by_name=True)
    id: Annotated[str, BeforeValidator(str)] = Field(validation_alias="_id", serialization_alias="id")
    name: str
    email: str
    role: Role
    portfolioAccess: list[str]
    status: Literal["Active", "Inactive"]
    authSource: Literal["local"]
    managerName: str | None = None
    vendorIndicator: bool = False
    lastLogin: str | None = None
    mustChangePassword: bool = False
    defaultLandingPage: LandingPage | None = None


class LoginResponse(BaseModel):
    """Return the issued bearer token and public account."""
    token: str
    user: PublicUser


class PasswordRequest(BaseModel):
    """Accept current and replacement credentials."""
    model_config = ConfigDict(extra="forbid")
    currentPassword: str = Field(min_length=1, max_length=256)
    newPassword: str = Field(min_length=12, max_length=72)

    @field_validator("newPassword")
    @classmethod
    def password_byte_limit(cls, value: str) -> str:
        """Reject values bcrypt would truncate."""
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes")
        return value


class PreferencesRequest(BaseModel):
    """Accept a supported default landing destination."""
    model_config = ConfigDict(extra="forbid")
    defaultLandingPage: LandingPage

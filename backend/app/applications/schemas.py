"""Define validated application inventory contracts."""
from typing import Annotated, Literal
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, HttpUrl, field_validator

Criticality = Literal["Low", "Medium", "High", "Critical"]
Lifecycle = Literal["Active", "Deprecated", "Retired"]
Risk = Literal["Low", "Medium", "High"]


class ApplicationInput(BaseModel):
    """Accept the editable application fields and validate their boundaries."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    portfolioId: str = Field(min_length=1)
    description: str = Field(default="", max_length=4000)
    productArea: str = Field(default="", max_length=200)
    businessOwner: str = Field(default="", max_length=200)
    technologyOwner: str = Field(default="", max_length=200)
    etsOwner: str = Field(default="", max_length=200)
    criticality: Criticality = "Medium"
    tier: int = Field(default=1, ge=1, le=4, strict=True)
    lifecycleStatus: Lifecycle = "Active"
    technologyStack: str = Field(default="", max_length=4000)
    repositoryLink: HttpUrl | None = None
    pipelineLink: HttpUrl | None = None
    applicationHealthScore: int = Field(default=0, ge=0, le=100, strict=True)
    qualityScore: int = Field(default=0, ge=0, le=100, strict=True)
    automationCoverage: int = Field(default=0, ge=0, le=100, strict=True)
    unitTestCoverage: int = Field(default=0, ge=0, le=100, strict=True)
    openDefects: int = Field(default=0, ge=0, strict=True)
    openCriticalDefects: int = Field(default=0, ge=0, strict=True)
    riskLevel: Risk = "Low"

    @field_validator("repositoryLink", "pipelineLink", mode="before")
    @classmethod
    def empty_link(cls, value):
        """Treat an empty form link as an absent link."""
        return None if value == "" else value


class Application(ApplicationInput):
    """Expose persisted application data and metadata."""
    model_config = ConfigDict(populate_by_name=True)
    id: Annotated[str, BeforeValidator(str)] = Field(validation_alias="_id", serialization_alias="id")
    createdAt: str
    updatedAt: str


class ApplicationPage(BaseModel):
    """Return a bounded page of application records."""
    items: list[Application]
    total: int
    limit: int
    offset: int

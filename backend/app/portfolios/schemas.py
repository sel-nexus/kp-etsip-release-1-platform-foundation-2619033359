"""Define validated portfolio requests and public responses."""
from typing import Annotated, Literal
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


class PortfolioInput(BaseModel):
    """Accept editable portfolio attributes."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    owner: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=4000)
    productArea: str = Field(default="", max_length=200)
    status: Literal["Active", "Archived"] = "Active"


class Portfolio(PortfolioInput):
    """Expose inventory data and computed application metrics."""
    model_config = ConfigDict(populate_by_name=True)
    id: Annotated[str, BeforeValidator(str)] = Field(validation_alias="_id", serialization_alias="id")
    createdAt: str
    updatedAt: str
    applicationCount: int
    qualityScore: int | None


class PortfolioPage(BaseModel):
    """Return a bounded portfolio page."""
    items: list[Portfolio]
    total: int
    limit: int
    offset: int


class ApplicationPage(BaseModel):
    """Return a bounded page of linked application records."""
    items: list[dict]
    total: int
    limit: int
    offset: int

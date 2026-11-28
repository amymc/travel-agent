"""Typed schemas for geocoding, POI search, and their cached responses."""

from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

PlaceCategory = Literal["attraction", "restaurant", "lodging"]


class CityLocation(TypedDict):
    lat: float
    lng: float
    display_name: str
    osm_id: int | None


class CachedGeocode(TypedDict):
    location: CityLocation | None


class PlaceRecord(TypedDict):
    place_id: str
    city: str
    name: str
    category: PlaceCategory
    neighborhood: str
    lat: float
    lng: float
    estimated_cost: None
    currency: None
    pricing_available: bool
    typical_duration_mins: int
    opening_hours: str
    closed_days: list[str]
    tags: list[str]
    summary: str


class CachedPlaceSearch(TypedDict):
    city: str
    matches: list[PlaceRecord]


class PlaceSearchResult(TypedDict):
    city: str
    count: int
    matches: list[PlaceRecord]
    note: str


class NominatimPlace(BaseModel):
    lat: str
    lon: str
    display_name: str
    osm_id: int | None = None


class OverpassElement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    id: int
    lat: float | None = None
    lon: float | None = None
    center: dict[str, float] | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class OverpassResponse(BaseModel):
    elements: list[OverpassElement]

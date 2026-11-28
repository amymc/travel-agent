"""Typed schemas for OSRM responses, cached routes, and travel-tool results."""

from typing import Literal, NotRequired, TypedDict

from pydantic import BaseModel

TravelMode = Literal["walking", "transit", "taxi"]


class CachedRoute(TypedDict):
    distance_km: float
    duration_mins: int


class RouteError(TypedDict):
    error: str


class TravelTimeSuccess(TypedDict):
    origin: str
    destination: str
    mode: TravelMode
    distance_km: float
    duration_mins: int
    estimated_cost: float | None
    currency: str | None
    source: Literal["OpenStreetMap / OSRM"]
    note: NotRequired[str]


class OSRMRoute(BaseModel):
    distance: float
    duration: float


class OSRMResponse(BaseModel):
    code: str
    routes: list[OSRMRoute]

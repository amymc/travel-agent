import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "places.json"


class PlaceRecord(BaseModel):
    """Normalized place record returned from our places dataset (or future API)."""

    place_id: str
    city: str
    name: str
    category: Literal["attraction", "restaurant", "lodging"]
    neighborhood: str
    lat: float
    lng: float
    estimated_cost: float
    currency: str
    typical_duration_mins: int
    opening_hours: str
    closed_days: list[str]
    tags: list[str]
    summary: str


@lru_cache(maxsize=1)
def load_places() -> list[PlaceRecord]:
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return [PlaceRecord.model_validate(item) for item in raw]


def supported_cities() -> list[str]:
    return sorted({place.city for place in load_places()})


def find_place(identifier: str) -> PlaceRecord | None:
    """Lookup a place by exact place_id or case-insensitive name match."""
    needle = identifier.strip().lower()
    if not needle:
        return None
    for place in load_places():
        if place.place_id.lower() == needle or place.name.lower() == needle:
            return place
    for place in load_places():
        if needle in place.name.lower():
            return place
    return None


def search_places(
    city: str,
    category: Literal["attraction", "restaurant", "lodging"] | None = None,
    query: str | None = None,
    max_cost: float | None = None,
    limit: int = 8,
) -> dict:
    """Search normalized places in the mock dataset and return a compact summary for the LLM."""
    city_clean = city.strip().lower()
    places = [p for p in load_places() if p.city.lower() == city_clean]

    if not places:
        return {
            "city": city,
            "matches": [],
            "note": (
                f"No mock dataset entries found for '{city}'. Currently available cities: "
                f"{', '.join(supported_cities())}."
            ),
        }

    if category:
        places = [p for p in places if p.category == category]

    if max_cost is not None:
        places = [p for p in places if p.estimated_cost <= max_cost]

    if query and query.strip():
        terms = [t.strip().lower() for t in query.split() if t.strip()]
        scored: list[tuple[int, PlaceRecord]] = []
        for place in places:
            haystack = " ".join(
                [place.name, place.neighborhood, place.summary, " ".join(place.tags)]
            ).lower()
            score = sum(1 for term in terms if term in haystack)
            if score > 0:
                scored.append((score, place))
        scored.sort(key=lambda pair: (-pair[0], pair[1].estimated_cost))
        places = [pair[1] for pair in scored]

    results = [
        {
            "place_id": p.place_id,
            "name": p.name,
            "category": p.category,
            "neighborhood": p.neighborhood,
            "estimated_cost": p.estimated_cost,
            "currency": p.currency,
            "typical_duration_mins": p.typical_duration_mins,
            "opening_hours": p.opening_hours,
            "closed_days": p.closed_days,
            "tags": p.tags,
            "summary": p.summary,
        }
        for p in places[:limit]
    ]

    note = None
    if not results:
        note = (
            "0 places matched those filters. Try omitting 'query' or raising 'max_cost' "
            "to broaden results."
        )

    return {
        "city": city,
        "count": len(results),
        "matches": results,
        **({"note": note} if note else {}),
    }

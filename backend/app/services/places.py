"""Geocoding and point-of-interest search backed by OpenStreetMap APIs."""

import json
import re
import time
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from pydantic import TypeAdapter

from app.config import settings
from app.services.cache import cache_path, get_cached, set_cached
from app.services.place_types import (
    CachedGeocode,
    CachedPlaceSearch,
    CityLocation,
    NominatimPlace,
    OverpassResponse,
    PlaceCategory,
    PlaceRecord,
    PlaceSearchResult,
)

Category = PlaceCategory
_NOMINATIM_RESULTS = TypeAdapter(list[NominatimPlace])
_CACHED_GEOCODE = TypeAdapter(CachedGeocode)
_CACHED_PLACE_SEARCH = TypeAdapter(CachedPlaceSearch)
_nominatim_lock = Lock()
_last_nominatim_request = 0.0


def _get_json(url: str, *, timeout: float = 20) -> object:
    request = Request(url, headers={"User-Agent": settings.osm_user_agent, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def geocode_city(city: str) -> CityLocation | None:
    """Resolve a city to coordinates and a display name; successful and empty results are cached."""
    global _last_nominatim_request
    cleaned = " ".join(city.split())
    key = f"v2:nominatim:city:{cleaned.casefold()}"
    cached = get_cached(key)
    if cached is not None:
        return _CACHED_GEOCODE.validate_python(cached)["location"]

    # Respect the public Nominatim service's maximum request rate across threads in this process.
    with _nominatim_lock:
        delay = 1.05 - (time.monotonic() - _last_nominatim_request)
        if delay > 0:
            time.sleep(delay)
        params = urlencode({"q": cleaned, "format": "jsonv2", "limit": 1, "addressdetails": 1})
        try:
            result = _get_json(f"{settings.nominatim_url}/search?{params}")
            _last_nominatim_request = time.monotonic()
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"OpenStreetMap geocoding failed: {exc}") from exc

    search_results = _NOMINATIM_RESULTS.validate_python(result)
    place: CityLocation | None = None
    if search_results:
        item = search_results[0]
        place = {
            "lat": float(item.lat),
            "lng": float(item.lon),
            "display_name": item.display_name,
            "osm_id": item.osm_id,
        }
    set_cached(key, {"location": place})
    return place


def _category_tags(category: Category | None) -> list[str]:
    if category == "restaurant":
        return ['"amenity"~"restaurant|cafe|fast_food|food_court|pub|bar"']
    if category == "lodging":
        return ['"tourism"~"hotel|hostel|guest_house|motel|apartment"']
    if category == "attraction":
        return ['"tourism"~"museum|attraction|gallery|viewpoint|zoo|theme_park"', '"historic"', '"leisure"="park"']
    return [
        '"amenity"~"restaurant|cafe|fast_food|food_court|pub|bar"',
        '"tourism"~"hotel|hostel|guest_house|motel|apartment|museum|attraction|gallery|viewpoint|zoo|theme_park"',
        '"historic"',
        '"leisure"="park"',
    ]


def _classify(tags: dict[str, str]) -> Category | None:
    if tags.get("amenity") in {"restaurant", "cafe", "fast_food", "food_court", "pub", "bar"}:
        return "restaurant"
    if tags.get("tourism") in {"hotel", "hostel", "guest_house", "motel", "apartment"}:
        return "lodging"
    if tags.get("tourism") or tags.get("historic") or tags.get("leisure") == "park":
        return "attraction"
    return None


def search_places(
    city: str,
    category: Category | None = None,
    query: str | None = None,
    max_cost: float | None = None,
    limit: int = 8,
) -> PlaceSearchResult:
    """Find real OpenStreetMap POIs near a geocoded city and cache the normalized response."""
    city_clean = " ".join(city.split())
    # Cache one city-wide POI result so later category and keyword searches stay local.
    key = f"v2:overpass:poi:{city_clean.casefold()}"
    cached_payload = get_cached(key)
    if cached_payload is None:
        city_location = geocode_city(city_clean)
        if city_location is None:
            return {
                "city": city,
                "count": 0,
                "matches": [],
                "note": f"Could not geocode '{city}'.",
            }

        lat, lng = city_location["lat"], city_location["lng"]
        selector = "\n".join(
            f"  {kind}(around:7000,{lat},{lng})[{tag}];"
            for tag in _category_tags(None)
            for kind in ("node", "way", "relation")
        )
        query_text = f"[out:json][timeout:18];(\n{selector}\n);out center tags;"
        request = Request(
            settings.overpass_url,
            data=urlencode({"data": query_text}).encode(),
            headers={"User-Agent": settings.osm_user_agent, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=25) as response:
                raw_data: object = json.loads(response.read().decode())
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"OpenStreetMap POI search failed: {exc}") from exc

        data = OverpassResponse.model_validate(raw_data)
        records: list[PlaceRecord] = []
        for item in data.elements:
            tags = item.tags
            name = tags.get("name") or tags.get("brand")
            item_category = _classify(tags)
            if not name or item_category is None:
                continue
            item_lat = item.center.get("lat") if item.center else item.lat
            item_lng = item.center.get("lon") if item.center else item.lon
            if item_lat is None or item_lng is None:
                continue
            osm_type, osm_id = item.type, item.id
            address = ", ".join(filter(None, [tags.get("addr:suburb"), tags.get("addr:city")])) or ""
            records.append({
                "place_id": f"osm:{osm_type}:{osm_id}",
                "city": city_clean,
                "name": name,
                "category": item_category,
                "neighborhood": address,
                "lat": float(item_lat),
                "lng": float(item_lng),
                # OSM has no reliable admission/meal pricing field; do not invent prices.
                "estimated_cost": None,
                "currency": None,
                "pricing_available": False,
                "typical_duration_mins": 90 if item_category == "attraction" else 60,
                "opening_hours": tags.get("opening_hours", "Unknown"),
                "closed_days": [],
                "tags": [
                    value
                    for key_name, value in tags.items()
                    if key_name in {"cuisine", "historic", "tourism", "amenity"}
                ],
                "summary": tags.get("description") or tags.get("cuisine") or f"OpenStreetMap listing ({item_category})",
            })
        # Remove duplicate nodes/areas with the same name while preserving first result.
        deduped = list({(row["name"].casefold(), row["category"]): row for row in reversed(records)}.values())
        cached_search: CachedPlaceSearch = {"city": city_clean, "matches": deduped}
        set_cached(key, cached_search)
    else:
        cached_search = _CACHED_PLACE_SEARCH.validate_python(cached_payload)

    records = cached_search["matches"]
    if category:
        records = [row for row in records if row["category"] == category]
    if query and query.strip():
        terms = [term.casefold() for term in re.findall(r"[\w'-]+", query)]
        scored = [(sum(term in (row["name"] + " " + row["summary"] + " " + " ".join(row["tags"])).casefold() for term in terms), row) for row in records]
        records = [row for score, row in sorted(scored, key=lambda pair: (-pair[0], pair[1]["name"])) if score]
    matches = records[:limit]
    if matches:
        note = (
            "OpenStreetMap does not provide prices; max_cost could not be verified. "
            "Check admission and meal costs."
        )
    else:
        note = "No named OpenStreetMap places matched those filters. Try a broader query or category."
    return {"city": city, "count": len(matches), "matches": matches, "note": note}


def find_place(identifier: str) -> PlaceRecord | None:
    """Resolve a place from previously cached POI searches by OSM id or exact name."""
    needle = identifier.strip().casefold()
    if not needle:
        return None
    import sqlite3

    path = cache_path()
    if not path.exists():
        return None
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT payload FROM api_cache WHERE cache_key LIKE 'v2:overpass:poi:%'"
        ).fetchall()
    records: list[PlaceRecord] = []
    for (payload,) in rows:
        cached_payload = _CACHED_PLACE_SEARCH.validate_python(json.loads(payload))
        records.extend(cached_payload["matches"])
    return next(
        (record for record in records if record["place_id"].casefold() == needle or record["name"].casefold() == needle),
        None,
    )

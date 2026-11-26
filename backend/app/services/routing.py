"""Road and walking directions from OSRM, cached by place and transport mode."""

import json
import time
from threading import Lock
from typing import TypeAlias
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from pydantic import TypeAdapter

from app.config import settings
from app.services.cache import get_cached, set_cached
from app.services.places import find_place
from app.services.routing_types import (
    CachedRoute,
    OSRMResponse,
    RouteError,
    TravelMode,
    TravelTimeSuccess,
)

TravelTimeResult: TypeAlias = RouteError | TravelTimeSuccess
_CACHED_ROUTE = TypeAdapter(CachedRoute)
_osrm_lock = Lock()
_last_osrm_request = 0.0


def estimate_travel_time(
    origin: str,
    destination: str,
    mode: TravelMode = "transit",
) -> TravelTimeResult:
    """Get a real road/walking route; transit time is a clearly labeled road-distance estimate."""
    origin_place = find_place(origin)
    dest_place = find_place(destination)
    if origin_place is None:
        return {"error": f"Origin '{origin}' was not found. Search for the place first."}
    if dest_place is None:
        return {"error": f"Destination '{destination}' was not found. Search for the place first."}

    route_profile = "foot" if mode == "walking" else "driving"
    key = f"v2:osrm:route:{route_profile}:{origin_place['place_id']}:{dest_place['place_id']}"
    cached_route = get_cached(key)
    if cached_route is None:
        global _last_osrm_request
        base_url = settings.osrm_foot_url if route_profile == "foot" else settings.osrm_driving_url
        coords = (
            f"{origin_place['lng']},{origin_place['lat']};"
            f"{dest_place['lng']},{dest_place['lat']}"
        )
        # The public FOSSGIS instances select foot vs car by host path; they expect
        # the conventional OSRM `driving` URL profile segment for both instances.
        url_profile = "driving" if route_profile == "foot" else route_profile
        url = f"{base_url}/route/v1/{url_profile}/{quote(coords, safe=',;')}?overview=false&steps=false"
        request = Request(url, headers={"User-Agent": settings.osm_user_agent})
        try:
            with _osrm_lock:
                delay = 1.05 - (time.monotonic() - _last_osrm_request)
                if delay > 0:
                    time.sleep(delay)
                with urlopen(request, timeout=20) as response:
                    raw_payload: object = json.loads(response.read().decode())
                _last_osrm_request = time.monotonic()
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"OSRM route lookup failed: {exc}") from exc
        payload = OSRMResponse.model_validate(raw_payload)
        if payload.code != "Ok" or not payload.routes:
            return {"error": "No route was found between those places."}
        first = payload.routes[0]
        route: CachedRoute = {
            "distance_km": round(first.distance / 1000, 2),
            "duration_mins": round(first.duration / 60),
        }
        set_cached(key, route)
    else:
        route = _CACHED_ROUTE.validate_python(cached_route)

    distance = route["distance_km"]
    duration = route["duration_mins"]
    currency = origin_place.get("currency", "EUR")
    if mode == "walking":
        cost = 0.0
    elif mode == "taxi":
        cost = None
    else:
        # OSRM has no public-transport profile; this is an estimate over the routed road distance.
        duration = max(5, round(distance / 16 * 60 + 8))
        cost = None

    result: TravelTimeSuccess = {
        "origin": origin_place["name"],
        "destination": dest_place["name"],
        "mode": mode,
        "distance_km": distance,
        "duration_mins": duration,
        "estimated_cost": cost,
        "currency": currency if cost is not None else None,
        "source": "OpenStreetMap / OSRM",
    }
    if mode == "transit":
        result["note"] = "Transit duration is estimated from road distance; OSRM does not provide transit routes or fares."
    elif mode == "taxi":
        result["note"] = "OSRM provides the driving route, but not a taxi fare estimate."
    return result

import math
from typing import Literal

from app.services.places import find_place

TravelMode = Literal["walking", "transit", "taxi"]

# Average effective urban speeds (km/h) including waiting/intersection overhead.
MODE_SPEED_KMH: dict[TravelMode, float] = {
    "walking": 4.5,
    "transit": 16.0,
    "taxi": 24.0,
}

# Overhead minutes (e.g. metro/tram waiting or taxi pickup).
MODE_OVERHEAD_MINS: dict[TravelMode, int] = {
    "walking": 2,
    "transit": 8,
    "taxi": 5,
}


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometers between two coordinates."""
    earth_radius_km = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lng / 2) ** 2
    )
    return 2 * earth_radius_km * math.asin(math.sqrt(a))


def estimate_travel_time(
    origin: str,
    destination: str,
    mode: TravelMode = "transit",
) -> dict:
    """Estimate travel duration and cost between two places from our dataset."""
    origin_place = find_place(origin)
    dest_place = find_place(destination)

    if origin_place is None:
        return {"error": f"Origin place '{origin}' was not found. Use a place_id or exact name from search_places."}
    if dest_place is None:
        return {"error": f"Destination place '{destination}' was not found. Use a place_id or exact name from search_places."}

    straight_km = haversine_km(
        origin_place.lat,
        origin_place.lng,
        dest_place.lat,
        dest_place.lng,
    )
    # Street distance is typically ~1.3x straight-line distance in cities.
    route_km = round(straight_km * 1.3, 2)

    if origin_place.place_id == dest_place.place_id:
        duration_mins = 0
    else:
        speed = MODE_SPEED_KMH[mode]
        overhead = MODE_OVERHEAD_MINS[mode]
        duration_mins = max(5, round((route_km / speed) * 60 + overhead))

    if mode == "walking":
        estimated_cost = 0.0
    elif mode == "transit":
        estimated_cost = 2.5 if origin_place.currency == "EUR" else 3.0
    else:
        estimated_cost = round(4.0 + route_km * 1.8, 2)

    return {
        "origin": origin_place.name,
        "destination": dest_place.name,
        "mode": mode,
        "distance_km": route_km,
        "duration_mins": duration_mins,
        "estimated_cost": estimated_cost,
        "currency": origin_place.currency,
    }

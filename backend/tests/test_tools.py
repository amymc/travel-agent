import json
from io import BytesIO

from app.agent.tools import ToolExecutionContext, execute_tool_call
from app.domain.models import TripRequest
from app.config import settings
from app.services import places, routing
from app.services.cache import set_cached
from app.services.places import search_places
from app.services.routing import estimate_travel_time


def _sample_request(max_budget: float = 150.0) -> TripRequest:
    return TripRequest(
        prompt="1 day in Lisbon",
        num_days=1,
        max_budget=max_budget,
        currency="EUR",
        pace="relaxed",
        interests=["seafood", "history"],
    )


def test_search_places_filters_live_api_results_and_reuses_city_cache(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "cache_db_path", str(tmp_path / "cache.sqlite3"))
    monkeypatch.setattr(
        places,
        "geocode_city",
        lambda city: {"lat": 41.15, "lng": -8.61, "display_name": city},
    )
    api_calls = 0

    def fake_urlopen(_request, timeout):
        nonlocal api_calls
        api_calls += 1
        return BytesIO(
            json.dumps(
                {
                    "elements": [
                        {
                            "type": "node",
                            "id": 100,
                            "lat": 41.15,
                            "lon": -8.61,
                            "tags": {
                                "name": "Seafood Corner",
                                "amenity": "restaurant",
                                "cuisine": "seafood",
                            },
                        },
                        {
                            "type": "node",
                            "id": 200,
                            "lat": 41.16,
                            "lon": -8.62,
                            "tags": {"name": "Old Castle", "historic": "castle"},
                        },
                    ]
                }
            ).encode()
        )

    monkeypatch.setattr(places, "urlopen", fake_urlopen)
    restaurant_results = search_places("Porto", category="restaurant", query="seafood")
    attraction_results = search_places("Porto", category="attraction")

    assert restaurant_results["count"] == 1
    assert restaurant_results["matches"][0]["name"] == "Seafood Corner"
    assert restaurant_results["matches"][0]["estimated_cost"] is None
    assert "note" in restaurant_results
    assert "prices" in restaurant_results["note"].lower()
    assert attraction_results["matches"][0]["name"] == "Old Castle"
    assert api_calls == 1


def test_search_places_returns_note_when_city_cannot_be_geocoded(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "cache_db_path", str(tmp_path / "cache.sqlite3"))
    monkeypatch.setattr(places, "geocode_city", lambda _city: None)

    res = search_places(city="Atlantis")
    assert res["matches"] == []
    assert "geocode" in res["note"]


def test_estimate_travel_time_uses_osrm_and_caches_route(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "cache_db_path", str(tmp_path / "cache.sqlite3"))
    set_cached(
        "v2:overpass:poi:lisbon",
        {
            "city": "Lisbon",
            "matches": [
                {
                    "place_id": "osm:node:1",
                    "city": "Lisbon",
                    "name": "Belem Tower",
                    "category": "attraction",
                    "neighborhood": "Belem",
                    "lat": 38.6916,
                    "lng": -9.2160,
                    "currency": None,
                    "estimated_cost": None,
                    "pricing_available": False,
                    "typical_duration_mins": 90,
                    "opening_hours": "Unknown",
                    "closed_days": [],
                    "tags": ["attraction"],
                    "summary": "OpenStreetMap listing",
                },
                {
                    "place_id": "osm:node:2",
                    "city": "Lisbon",
                    "name": "Castle",
                    "category": "attraction",
                    "neighborhood": "Alfama",
                    "lat": 38.7139,
                    "lng": -9.1335,
                    "currency": None,
                    "estimated_cost": None,
                    "pricing_available": False,
                    "typical_duration_mins": 90,
                    "opening_hours": "Unknown",
                    "closed_days": [],
                    "tags": ["historic"],
                    "summary": "OpenStreetMap listing",
                },
            ],
        },
    )
    api_calls = 0

    def fake_urlopen(_request, timeout):
        nonlocal api_calls
        api_calls += 1
        return BytesIO(json.dumps({"code": "Ok", "routes": [{"distance": 7000, "duration": 1200}]}).encode())

    monkeypatch.setattr(routing, "urlopen", fake_urlopen)
    res = estimate_travel_time("Belem Tower", "Castle", mode="transit")
    cached = estimate_travel_time("Belem Tower", "Castle", mode="taxi")

    assert "error" not in res
    assert res["duration_mins"] == 34
    assert res["distance_km"] == 7
    assert res["estimated_cost"] is None
    assert "estimated" in res["note"]
    assert cached["distance_km"] == 7
    assert cached["estimated_cost"] is None
    assert api_calls == 1


def test_estimate_travel_time_handles_unknown_place(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "cache_db_path", str(tmp_path / "cache.sqlite3"))
    res = estimate_travel_time("Unknown Spot", "Belem Tower", mode="walking")
    assert "error" in res


def test_submit_itinerary_rejects_over_budget_for_repair_then_accepts() -> None:
    ctx = ToolExecutionContext(request=_sample_request(max_budget=40.0), max_repairs=1)

    expensive_draft = {
        "destination": "Lisbon",
        "title": "Over Budget Day",
        "summary": "Too pricey",
        "currency": "EUR",
        "days": [
            {
                "day_number": 1,
                "theme": "Food",
                "items": [
                    {
                        "start_time": "12:00",
                        "end_time": "14:00",
                        "title": "Cervejaria Ramiro",
                        "category": "restaurant",
                        "location": "Intendente",
                        "description": "Shellfish feast",
                        "estimated_cost": 60.0,
                    }
                ],
            }
        ],
    }

    result1, summary1 = execute_tool_call("submit_itinerary", expensive_draft, ctx)
    assert result1["accepted"] is False
    assert "Rejected for repair 1/1" in summary1
    assert ctx.submitted_draft is None

    cheaper_draft = {
        **expensive_draft,
        "days": [
            {
                "day_number": 1,
                "theme": "Food",
                "items": [
                    {
                        "start_time": "12:00",
                        "end_time": "13:30",
                        "title": "Time Out Market",
                        "category": "restaurant",
                        "location": "Cais do Sodre",
                        "description": "Food hall lunch",
                        "estimated_cost": 22.0,
                    }
                ],
            }
        ],
    }

    result2, summary2 = execute_tool_call("submit_itinerary", cheaper_draft, ctx)
    assert result2["accepted"] is True
    assert "Submitted" in summary2
    assert ctx.submitted_draft is not None
    assert ctx.submitted_draft.days[0].items[0].estimated_cost == 22.0


def test_execute_tool_call_handles_unknown_tool_and_bad_args() -> None:
    ctx = ToolExecutionContext(request=_sample_request())

    res_unknown, _ = execute_tool_call("book_flight", {}, ctx)
    assert "Unknown tool" in res_unknown["error"]

    res_bad, _ = execute_tool_call("search_places", {"max_cost": -10}, ctx)
    assert "Invalid arguments" in res_bad["error"]

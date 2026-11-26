from app.agent.tools import ToolExecutionContext, execute_tool_call
from app.domain.models import TripRequest
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


def test_search_places_filters_by_city_category_and_query() -> None:
    res = search_places(city="Lisbon", category="restaurant", query="seafood")
    assert res["count"] >= 2
    assert all(place["category"] == "restaurant" for place in res["matches"])


def test_search_places_returns_helpful_note_for_unsupported_city() -> None:
    res = search_places(city="Atlantis")
    assert res["matches"] == []
    assert "Lisbon" in res["note"]


def test_estimate_travel_time_between_belem_and_alfama() -> None:
    res = estimate_travel_time("Belem Tower", "Castelo de Sao Jorge", mode="transit")
    assert "error" not in res
    assert res["duration_mins"] > 15
    assert res["distance_km"] > 5
    assert res["estimated_cost"] == 2.5


def test_estimate_travel_time_handles_unknown_place() -> None:
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

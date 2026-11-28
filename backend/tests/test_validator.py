from app.domain.models import (
    ActivityCategory,
    DayPlan,
    ItineraryDraft,
    ItineraryItem,
    JsonValue,
    TripRequest,
)
from app.domain.validator import parse_minutes, validate_itinerary
from pydantic import ValidationError
import pytest


def _make_request(**overrides: JsonValue) -> TripRequest:
    defaults = {
        "prompt": "3 days in Lisbon",
        "num_days": 2,
        "max_budget": 500.0,
        "currency": "EUR",
        "pace": "moderate",
        "interests": ["food", "history"],
    }
    defaults.update(overrides)
    return TripRequest(**defaults)


def _make_item(
    start: str,
    end: str,
    title: str = "Activity",
    cost: float = 20.0,
    category: ActivityCategory = "attraction",
) -> ItineraryItem:
    return ItineraryItem(
        start_time=start,
        end_time=end,
        title=title,
        category=category,
        location="Lisbon",
        description="Test stop",
        estimated_cost=cost,
        opening_hours="24/7",
    )


def test_parse_minutes_valid_and_invalid() -> None:
    assert parse_minutes("09:05") == 545
    assert parse_minutes("23:59") == 1439
    assert parse_minutes("24:00") is None
    assert parse_minutes("9:00") is None
    assert parse_minutes("invalid") is None


def test_itinerary_model_rejects_nested_days_instead_of_silently_dropping_items() -> None:
    with pytest.raises(ValidationError):
        ItineraryDraft.model_validate(
            {
                "destination": "New York",
                "title": "Broken itinerary",
                "summary": "Activities are under the wrong key",
                "currency": "EUR",
                "days": [
                    {
                        "day_number": 1,
                        "theme": "Art",
                        "days": [{"items": []}],
                    }
                ],
            }
        )


def test_valid_itinerary_passes_with_exact_cost_math() -> None:
    request = _make_request(num_days=2, max_budget=200.0)
    draft = ItineraryDraft(
        destination="Lisbon",
        title="Lisbon Weekend",
        summary="A relaxed two-day trip.",
        currency="EUR",
        days=[
            DayPlan(
                day_number=1,
                theme="Historic Center",
                items=[
                    _make_item("09:00", "11:00", "Alfama Walk", cost=0.0),
                    _make_item("12:00", "13:30", "Seafood Corner", cost=45.5, category="restaurant"),
                ],
            ),
            DayPlan(
                day_number=2,
                theme="Belem",
                items=[
                    _make_item("10:00", "12:00", "Jeronimos Monastery", cost=18.0),
                ],
            ),
        ],
    )

    total_cost, remaining, issues = validate_itinerary(draft, request)
    assert total_cost == 63.5
    assert remaining == 136.5
    assert issues == []


def test_detects_budget_exceeded() -> None:
    request = _make_request(num_days=1, max_budget=100.0)
    draft = ItineraryDraft(
        destination="Lisbon",
        title="Expensive Day",
        summary="Over budget",
        currency="EUR",
        days=[
            DayPlan(
                day_number=1,
                theme="Luxury",
                items=[
                    _make_item("10:00", "12:00", "Private Tour", cost=80.0),
                    _make_item("19:00", "21:00", "Fine Dining", cost=50.0, category="restaurant"),
                ],
            )
        ],
    )

    total_cost, remaining, issues = validate_itinerary(draft, request)
    assert total_cost == 130.0
    assert remaining == -30.0
    assert any(issue.code == "BUDGET_EXCEEDED" and issue.severity == "error" for issue in issues)


def test_detects_overlapping_times_and_day_mismatch() -> None:
    request = _make_request(num_days=2, max_budget=500.0)
    draft = ItineraryDraft(
        destination="Lisbon",
        title="Overlap",
        summary="Broken schedule",
        currency="EUR",
        days=[
            DayPlan(
                day_number=1,
                theme="Rushed",
                items=[
                    _make_item("09:00", "11:30", "Museum", cost=15.0),
                    _make_item("11:00", "12:30", "Lunch", cost=25.0, category="restaurant"),
                ],
            )
        ],
    )

    _, _, issues = validate_itinerary(draft, request)
    codes = {issue.code for issue in issues}
    assert "DAY_COUNT_MISMATCH" in codes
    assert "TIME_OVERLAP" in codes


def test_warns_when_pace_exceeded() -> None:
    request = _make_request(num_days=1, max_budget=500.0, pace="relaxed")
    items = [
        _make_item(f"{9 + i * 2:02d}:00", f"{10 + i * 2:02d}:00", f"Stop {i}", cost=10.0)
        for i in range(5)
    ]
    draft = ItineraryDraft(
        destination="Lisbon",
        title="Packed Day",
        summary="Too busy for relaxed",
        currency="EUR",
        days=[DayPlan(day_number=1, theme="Busy", items=items)],
    )

    _, _, issues = validate_itinerary(draft, request)
    assert any(issue.code == "PACE_EXCEEDED" and issue.severity == "warning" for issue in issues)


def test_checks_measured_travel_gap_and_opening_hours() -> None:
    request = _make_request(num_days=1, start_date="2026-11-30")
    draft = ItineraryDraft(
        destination="Lisbon",
        title="Hours and Travel",
        summary="Validation case",
        currency="EUR",
        days=[
            DayPlan(
                day_number=1,
                theme="Center",
                items=[
                    _make_item("09:00", "10:00", "Museum"),
                    ItineraryItem(
                        start_time="10:30",
                        end_time="12:00",
                        title="Castle",
                        category="attraction",
                        location="Alfama",
                        description="Hilltop visit",
                        estimated_cost=10,
                        opening_hours="Mo-Su 09:00-18:00",
                        travel_time_mins_from_previous=45,
                    ),
                    ItineraryItem(
                        start_time="18:00",
                        end_time="19:00",
                        title="Evening Museum",
                        category="attraction",
                        location="Baixa",
                        description="Late visit",
                        estimated_cost=0,
                        opening_hours="Mo-Su 09:00-18:00",
                    ),
                ],
            )
        ],
    )

    _, _, issues = validate_itinerary(draft, request)
    codes = {issue.code for issue in issues}
    assert "INSUFFICIENT_TRAVEL_TIME" in codes
    assert "OUTSIDE_OPENING_HOURS" in codes


def test_rushed_day_revision_requires_fewer_stops() -> None:
    request = _make_request(num_days=2, pace="moderate")
    draft = ItineraryDraft(
        destination="Lisbon",
        title="Busy Trip",
        summary="Current itinerary",
        currency="EUR",
        days=[
            DayPlan(
                day_number=1,
                theme="Day one",
                items=[_make_item(f"{9 + index:02d}:00", f"{10 + index:02d}:00", f"Stop {index}") for index in range(5)],
            ),
            DayPlan(
                day_number=2,
                theme="Day two",
                items=[_make_item(f"{9 + index:02d}:00", f"{10 + index:02d}:00", f"Day two stop {index}") for index in range(5)],
            ),
        ],
    )

    _, _, issues = validate_itinerary(draft, request, "Day 2 feels too rushed")
    assert any(
        issue.code == "REVISION_PACE_EXCEEDED"
        and issue.severity == "error"
        and issue.day_number == 2
        for issue in issues
    )


def test_opening_hours_use_trip_weekday_when_date_is_provided() -> None:
    request = _make_request(num_days=1, start_date="2026-12-01")
    draft = ItineraryDraft(
        destination="Lisbon",
        title="Closed day",
        summary="Weekday opening check",
        currency="EUR",
        days=[
            DayPlan(
                day_number=1,
                theme="Museum",
                items=[
                    ItineraryItem(
                        start_time="10:00",
                        end_time="11:00",
                        title="Monday-only museum",
                        category="attraction",
                        location="Lisbon",
                        description="Closed Tuesday",
                        estimated_cost=0,
                        opening_hours="Mo 09:00-17:00",
                    )
                ],
            )
        ],
    )

    _, _, issues = validate_itinerary(draft, request)
    assert any(issue.code == "OUTSIDE_OPENING_HOURS" for issue in issues)


def test_restaurant_entry_requires_a_specific_venue_name() -> None:
    request = _make_request(num_days=1)
    draft = ItineraryDraft(
        destination="Lisbon",
        title="Lunch plan",
        summary="Named restaurant validation",
        currency="EUR",
        days=[
            DayPlan(
                day_number=1,
                theme="Food",
                items=[
                    ItineraryItem(
                        start_time="12:00",
                        end_time="13:00",
                        title="Lunch in Alfama",
                        category="restaurant",
                        location="Alfama",
                        description="Try local seafood",
                        estimated_cost=20,
                        opening_hours="12:00-22:00",
                    )
                ],
            )
        ],
    )

    _, _, issues = validate_itinerary(draft, request)
    assert any(issue.code == "RESTAURANT_NEEDS_NAMED_VENUE" for issue in issues)

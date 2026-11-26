from app.domain.models import (
    ActivityCategory,
    DayPlan,
    ItineraryDraft,
    ItineraryItem,
    JsonValue,
    TripRequest,
)
from app.domain.validator import parse_minutes, validate_itinerary


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
    )


def test_parse_minutes_valid_and_invalid() -> None:
    assert parse_minutes("09:05") == 545
    assert parse_minutes("23:59") == 1439
    assert parse_minutes("24:00") is None
    assert parse_minutes("9:00") is None
    assert parse_minutes("invalid") is None


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
                    _make_item("12:00", "13:30", "Seafood Lunch", cost=45.5, category="restaurant"),
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

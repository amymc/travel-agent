from fastapi.testclient import TestClient

from app.api.routes_trips import get_llm_client
from app.domain.models import DayPlan, ItineraryDraft, ItineraryItem, TripRequest
from app.main import app
from app.services.llm_client import LLMConfigurationError


class FakeLLMClient:
    def __init__(self, draft: ItineraryDraft) -> None:
        self.draft = draft

    def generate_itinerary(self, request: TripRequest) -> tuple[ItineraryDraft, str]:
        return self.draft, "gemini-3.8-flash"


class MissingKeyLLMClient:
    def generate_itinerary(self, request: TripRequest) -> tuple[ItineraryDraft, str]:
        raise LLMConfigurationError("GEMINI_API_KEY is not configured.")


def test_health_endpoint() -> None:
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_plan_trip_returns_validated_itinerary() -> None:
    fake_draft = ItineraryDraft(
        destination="Lisbon",
        title="2 Days in Lisbon",
        summary="Seafood and historic neighborhoods.",
        currency="EUR",
        days=[
            DayPlan(
                day_number=1,
                theme="Alfama & Baixa",
                items=[
                    ItineraryItem(
                        start_time="09:30",
                        end_time="11:30",
                        title="Castelo de Sao Jorge",
                        category="attraction",
                        location="Alfama",
                        description="Hilltop castle overlooking Lisbon.",
                        estimated_cost=15.0,
                        transit_note="Take Tram 28E uphill.",
                    ),
                    ItineraryItem(
                        start_time="12:30",
                        end_time="14:00",
                        title="Seafood Lunch",
                        category="restaurant",
                        location="Baixa",
                        description="Grilled sardines and pastel de nata.",
                        estimated_cost=35.0,
                        transit_note="15 min walk downhill.",
                    ),
                ],
            ),
            DayPlan(
                day_number=2,
                theme="Belem",
                items=[
                    ItineraryItem(
                        start_time="10:00",
                        end_time="12:00",
                        title="Belem Tower",
                        category="attraction",
                        location="Belem",
                        description="16th-century riverside fortress.",
                        estimated_cost=12.0,
                        transit_note="25 min via tram 15E.",
                    )
                ],
            ),
        ],
    )

    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient(fake_draft)
    try:
        client = TestClient(app)
        res = client.post(
            "/api/trips/plan",
            json={
                "prompt": "A 2-day Lisbon food and history getaway",
                "num_days": 2,
                "max_budget": 200,
                "currency": "EUR",
                "pace": "relaxed",
                "interests": ["seafood", "history"],
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["total_estimated_cost"] == 62.0
        assert body["budget_remaining"] == 138.0
        assert body["is_valid"] is True
        assert body["issues"] == []
        assert body["model_used"] == "gemini-3.8-flash"
    finally:
        app.dependency_overrides.clear()


def test_plan_trip_returns_503_when_api_key_missing() -> None:
    app.dependency_overrides[get_llm_client] = lambda: MissingKeyLLMClient()
    try:
        client = TestClient(app)
        res = client.post(
            "/api/trips/plan",
            json={"prompt": "3 days in Kyoto", "num_days": 3, "max_budget": 900},
        )
        assert res.status_code == 503
        assert "GEMINI_API_KEY" in res.json()["detail"]
    finally:
        app.dependency_overrides.clear()

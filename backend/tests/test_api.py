from fastapi.testclient import TestClient

from app.agent.loop import AgentRunResult
from app.api.routes_trips import get_agent_loop, get_llm_client
from app.domain.models import (
    AgentStepTrace,
    AgentToolCall,
    DayPlan,
    ItineraryDraft,
    ItineraryItem,
    TripRequest,
)
from app.main import app
from app.services.llm_client import LLMConfigurationError


class FakeAgentLoop:
    def __init__(self, draft: ItineraryDraft) -> None:
        self.draft = draft

    def run(self, request: TripRequest) -> AgentRunResult:
        return AgentRunResult(
            draft=self.draft,
            model_used="gemini-3.8-flash",
            trace=[
                AgentStepTrace(
                    step=1,
                    model_used="gemini-3.8-flash",
                    tool_calls=[
                        AgentToolCall(
                            name="search_places",
                            args={"city": "Lisbon", "category": "attraction"},
                            result_summary="Found 8 place(s) in Lisbon",
                        )
                    ],
                )
            ],
        )


class MissingKeyLLMClient:
    model = "gemini-3.8-flash"

    def call_with_fallback(self, *, contents, config):
        raise LLMConfigurationError("GEMINI_API_KEY is not configured.")


def test_health_endpoint() -> None:
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_plan_trip_returns_validated_itinerary_and_agent_trace() -> None:
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
                        title="Cervejaria Ramiro",
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

    app.dependency_overrides[get_agent_loop] = lambda: FakeAgentLoop(fake_draft)
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
        assert {issue["code"] for issue in body["issues"]} == {
            "OPENING_HOURS_UNVERIFIED",
            "TRAVEL_TIME_UNVERIFIED",
        }
        assert body["model_used"] == "gemini-3.8-flash"
        assert len(body["agent_trace"]) == 1
        assert body["agent_trace"][0]["tool_calls"][0]["name"] == "search_places"
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


def test_revision_endpoint_sends_existing_itinerary_and_applies_budget_cut() -> None:
    existing = ItineraryDraft(
        destination="Lisbon",
        title="Current Lisbon plan",
        summary="Original stops",
        currency="EUR",
        days=[
            DayPlan(
                day_number=1,
                theme="Historic center",
                items=[
                    ItineraryItem(
                        start_time="09:00",
                        end_time="10:00",
                        title="Castle",
                        category="attraction",
                        location="Alfama",
                        description="Original stop",
                        estimated_cost=40,
                    )
                ],
            )
        ],
    )
    revised = ItineraryDraft.model_validate(existing.model_dump())
    revised.title = "Less expensive Lisbon plan"
    revised.days[0].items[0].estimated_cost = 20

    class RevisionAgent:
        def run(self, request, *, existing_draft=None, revision_instruction=None):
            assert existing_draft == existing
            assert revision_instruction == "Cut $300 from the budget"
            assert request.max_budget == 200
            return AgentRunResult(
                draft=revised,
                model_used="gemini-3.8-flash",
                trace=[AgentStepTrace(step=1, model_used="gemini-3.8-flash")],
            )

    app.dependency_overrides[get_agent_loop] = lambda: RevisionAgent()
    try:
        client = TestClient(app)
        res = client.post(
            "/api/trips/revise",
            json={
                "trip_request": {
                    "prompt": "One day in Lisbon",
                    "num_days": 1,
                    "max_budget": 500,
                    "currency": "EUR",
                    "pace": "moderate",
                },
                "itinerary": existing.model_dump(mode="json"),
                "instruction": "Cut $300 from the budget",
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["itinerary"]["title"] == "Less expensive Lisbon plan"
        assert body["budget_remaining"] == 180
        assert body["is_valid"] is True
    finally:
        app.dependency_overrides.clear()

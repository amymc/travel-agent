from types import SimpleNamespace
from google.genai import types

from app.agent.loop import TravelAgentLoop
from app.agent import tools as agent_tools
from app.domain.models import DayPlan, ItineraryDraft, ItineraryItem, JsonValue, TripRequest


def _make_response(
    function_calls: list[tuple[str, dict[str, JsonValue]]] | None = None,
    text: str | None = None,
) -> SimpleNamespace:
    calls = [SimpleNamespace(name=name, args=args) for name, args in (function_calls or [])]
    parts = [types.Part.from_text(text=text)] if text else []
    content = types.Content(role="model", parts=parts)
    return SimpleNamespace(
        function_calls=calls,
        candidates=[SimpleNamespace(content=content)],
        text=text,
        parsed=None,
    )


def test_agent_loop_researches_repairs_budget_and_submits(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_tools,
        "search_places",
        lambda **_kwargs: {"count": 1, "matches": [{"name": "Seafood Spot"}]},
    )
    monkeypatch.setattr(
        agent_tools,
        "estimate_travel_time",
        lambda **_kwargs: {
            "duration_mins": 24,
            "distance_km": 6.0,
            "estimated_cost": None,
            "currency": None,
            "mode": "transit",
            "note": "Transit duration is estimated.",
        },
    )
    over_budget_draft = {
        "destination": "Lisbon",
        "title": "Lisbon Trip",
        "summary": "Seafood day",
        "currency": "EUR",
        "days": [
            {
                "day_number": 1,
                "theme": "Seafood",
                "items": [
                    {
                        "start_time": "19:00",
                        "end_time": "21:00",
                        "title": "Cervejaria Ramiro",
                        "category": "restaurant",
                        "location": "Intendente",
                        "description": "Shellfish splurge",
                        "estimated_cost": 60.0,
                    }
                ],
            }
        ],
    }
    fixed_draft = {
        "destination": "Lisbon",
        "title": "Lisbon Trip",
        "summary": "Affordable seafood day",
        "currency": "EUR",
        "days": [
            {
                "day_number": 1,
                "theme": "Seafood",
                "items": [
                    {
                        "start_time": "19:00",
                        "end_time": "20:30",
                        "title": "Time Out Market Lisboa",
                        "category": "restaurant",
                        "location": "Cais do Sodre",
                        "description": "Seafood stalls",
                        "estimated_cost": 22.0,
                    }
                ],
            }
        ],
    }

    scripted_responses = [
        _make_response(
            function_calls=[
                ("search_places", {"city": "Lisbon", "category": "restaurant", "query": "seafood"}),
                ("get_travel_time", {"origin": "Belem Tower", "destination": "Time Out Market Lisboa", "mode": "transit"}),
            ]
        ),
        _make_response(function_calls=[("submit_itinerary", over_budget_draft)]),
        _make_response(function_calls=[("submit_itinerary", fixed_draft)]),
    ]

    class FakeLLMClient:
        model = "gemini-3.8-flash"

        def __init__(self) -> None:
            self.turn = 0

        def call_with_fallback(self, *, contents, config):
            resp = scripted_responses[self.turn]
            self.turn += 1
            return resp, "gemini-3.8-flash"

        def generate_itinerary(self, request):
            raise AssertionError("Fallback should not be needed when submit_itinerary succeeds")

    loop = TravelAgentLoop(llm_client=FakeLLMClient(), max_steps=6, max_repairs=2)
    request = TripRequest(
        prompt="1 day in Lisbon for seafood",
        num_days=1,
        max_budget=40.0,
        currency="EUR",
        pace="relaxed",
        interests=["seafood"],
    )

    result = loop.run(request)
    assert result.model_used == "gemini-3.8-flash"
    assert result.draft.days[0].items[0].title == "Time Out Market Lisboa"
    assert len(result.trace) == 3
    assert [c.name for c in result.trace[0].tool_calls] == ["search_places", "get_travel_time"]
    assert "Rejected for repair 1/2" in result.trace[1].tool_calls[0].result_summary
    assert "Submitted" in result.trace[2].tool_calls[0].result_summary


def test_agent_loop_falls_back_to_structured_output_if_no_tools_called() -> None:
    fallback_draft = ItineraryDraft(
        destination="Kyoto",
        title="Kyoto Day",
        summary="Temples",
        currency="USD",
        days=[
            DayPlan(
                day_number=1,
                theme="Shrines",
                items=[
                    ItineraryItem(
                        start_time="08:00",
                        end_time="10:00",
                        title="Fushimi Inari Taisha",
                        category="attraction",
                        location="Fushimi",
                        description="Torii gates",
                        estimated_cost=0.0,
                    )
                ],
            )
        ],
    )

    class TextOnlyLLMClient:
        model = "gemini-3.6-flash"

        def call_with_fallback(self, *, contents, config):
            return _make_response(text="Here is an idea for Kyoto..."), "gemini-3.6-flash"

        def generate_itinerary(self, request):
            return fallback_draft, "gemini-3.6-flash"

    loop = TravelAgentLoop(llm_client=TextOnlyLLMClient(), max_steps=2)
    result = loop.run(TripRequest(prompt="1 day in Kyoto", num_days=1, max_budget=200, currency="USD"))

    assert result.draft == fallback_draft
    assert any("Fallback structured-output" in (step.note or "") for step in result.trace)


def test_revision_loop_supplies_existing_itinerary_and_instruction() -> None:
    current = ItineraryDraft(
        destination="Lisbon",
        title="Original plan",
        summary="Existing stops",
        currency="EUR",
        days=[
            DayPlan(
                day_number=1,
                theme="Packed",
                items=[
                    ItineraryItem(
                        start_time="09:00",
                        end_time="10:00",
                        title="Original stop",
                        category="attraction",
                        location="Lisbon",
                        description="Keep this stop",
                        estimated_cost=10,
                    )
                ],
            )
        ],
    )
    revised = ItineraryDraft.model_validate(current.model_dump())
    revised.title = "Slower plan"
    response = _make_response(
        function_calls=[("submit_itinerary", revised.model_dump(mode="json"))]
    )

    class RevisionLLMClient:
        model = "gemini-3.8-flash"

        def call_with_fallback(self, *, contents, config):
            initial_prompt = contents[0].parts[0].text
            assert "Day 1 feels too rushed" in initial_prompt
            assert "Original stop" in initial_prompt
            return response, self.model

        def generate_itinerary(self, request):
            raise AssertionError("Revision must not fall back to a fresh plan")

    request = TripRequest(
        prompt="One day in Lisbon",
        num_days=1,
        max_budget=100,
        currency="EUR",
        pace="moderate",
    )
    events: list[dict[str, JsonValue]] = []
    result = TravelAgentLoop(llm_client=RevisionLLMClient()).run(
        request,
        existing_draft=current,
        revision_instruction="Day 1 feels too rushed",
        event_callback=events.append,
    )
    assert result.draft.title == "Slower plan"
    assert [event["type"] for event in events] == [
        "status",
        "tool_call_started",
        "tool_call_completed",
        "step_completed",
    ]
    assert result.trace[0].tool_calls[0].result_payload is not None

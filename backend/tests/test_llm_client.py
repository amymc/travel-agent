from types import SimpleNamespace
import pytest
from google.genai import errors as genai_errors

from app.domain.models import DayPlan, ItineraryDraft, ItineraryItem, TripRequest
from app.services.llm_client import (
    GeminiItineraryClient,
    LLMGenerationError,
    LLMUnavailableError,
)


def _sample_request() -> TripRequest:
    return TripRequest(prompt="2 days in Lisbon", num_days=1, max_budget=300)


def _sample_draft() -> ItineraryDraft:
    return ItineraryDraft(
        destination="Lisbon",
        title="Lisbon Day",
        summary="A nice day.",
        currency="EUR",
        days=[
            DayPlan(
                day_number=1,
                theme="Center",
                items=[
                    ItineraryItem(
                        start_time="10:00",
                        end_time="12:00",
                        title="Castelo",
                        category="attraction",
                        location="Alfama",
                        description="Hilltop castle.",
                        estimated_cost=15.0,
                    )
                ],
            )
        ],
    )


def _api_error(code: int, message: str, status: str) -> genai_errors.APIError:
    return genai_errors.APIError(
        code,
        {"error": {"code": code, "message": message, "status": status}},
    )


def test_retries_primary_then_falls_back_on_503() -> None:
    calls: list[str] = []
    sleeps: list[float] = []
    draft = _sample_draft()

    class FakeModels:
        def generate_content(self, *, model: str, **kwargs):
            calls.append(model)
            if model == "gemini-3.8-flash":
                raise _api_error(503, "High demand", "UNAVAILABLE")
            return SimpleNamespace(parsed=draft, text=None)

    fake_client = SimpleNamespace(models=FakeModels())
    client = GeminiItineraryClient(
        api_key="test-key",
        model="gemini-3.8-flash",
        fallback_models=["gemini-3.6-flash", "gemini-3.5-flash-lite"],
        client_factory=lambda _: fake_client,
        sleep_fn=sleeps.append,
    )

    result, model_used = client.generate_itinerary(_sample_request())
    assert result == draft
    assert model_used == "gemini-3.6-flash"
    assert calls == ["gemini-3.8-flash", "gemini-3.8-flash", "gemini-3.6-flash"]
    assert sleeps == [1.0]


def test_fails_immediately_on_non_retryable_400() -> None:
    calls: list[str] = []

    class FakeModels:
        def generate_content(self, *, model: str, **kwargs):
            calls.append(model)
            raise _api_error(400, "Invalid API key", "INVALID_ARGUMENT")

    fake_client = SimpleNamespace(models=FakeModels())
    client = GeminiItineraryClient(
        api_key="bad-key",
        model="gemini-3.8-flash",
        fallback_models=["gemini-3.6-flash"],
        client_factory=lambda _: fake_client,
        sleep_fn=lambda _: None,
    )

    with pytest.raises(LLMGenerationError, match="Gemini request failed"):
        client.generate_itinerary(_sample_request())
    assert calls == ["gemini-3.8-flash"]


def test_raises_unavailable_when_all_models_return_503() -> None:
    calls: list[str] = []

    class FakeModels:
        def generate_content(self, *, model: str, **kwargs):
            calls.append(model)
            raise _api_error(503, "High demand", "UNAVAILABLE")

    fake_client = SimpleNamespace(models=FakeModels())
    client = GeminiItineraryClient(
        api_key="test-key",
        model="gemini-3.8-flash",
        fallback_models=["gemini-3.6-flash", "gemini-3.5-flash-lite"],
        client_factory=lambda _: fake_client,
        sleep_fn=lambda _: None,
    )

    with pytest.raises(LLMUnavailableError, match="gemini-3.8-flash, gemini-3.6-flash"):
        client.generate_itinerary(_sample_request())
    assert calls == [
        "gemini-3.8-flash",
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
    ]

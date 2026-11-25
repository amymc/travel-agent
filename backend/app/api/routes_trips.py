from fastapi import APIRouter, Depends, HTTPException, status

from app.domain.models import ItineraryResponse, TripRequest
from app.domain.validator import validate_itinerary
from app.services.llm_client import (
    GeminiItineraryClient,
    LLMConfigurationError,
    LLMGenerationError,
    LLMUnavailableError,
)

router = APIRouter(prefix="/api/trips", tags=["trips"])


def get_llm_client() -> GeminiItineraryClient:
    return GeminiItineraryClient()


@router.post("/plan", response_model=ItineraryResponse)
def plan_trip(
    request: TripRequest,
    llm_client: GeminiItineraryClient = Depends(get_llm_client),
) -> ItineraryResponse:
    """Generate a structured itinerary and validate it against user constraints."""
    try:
        draft, model_used = llm_client.generate_itinerary(request)
    except (LLMConfigurationError, LLMUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except LLMGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    total_cost, budget_remaining, issues = validate_itinerary(draft, request)
    has_errors = any(issue.severity == "error" for issue in issues)

    return ItineraryResponse(
        itinerary=draft,
        total_estimated_cost=total_cost,
        budget_remaining=budget_remaining,
        is_valid=not has_errors,
        issues=issues,
        model_used=model_used,
    )

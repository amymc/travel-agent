from fastapi import APIRouter, Depends, HTTPException, status

from app.agent.loop import TravelAgentLoop
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


def get_agent_loop(
    llm_client: GeminiItineraryClient = Depends(get_llm_client),
) -> TravelAgentLoop:
    return TravelAgentLoop(llm_client=llm_client)


@router.post("/plan", response_model=ItineraryResponse)
def plan_trip(
    request: TripRequest,
    agent: TravelAgentLoop = Depends(get_agent_loop),
) -> ItineraryResponse:
    """Run the iterative travel agent loop and validate the resulting itinerary."""
    try:
        result = agent.run(request)
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

    total_cost, budget_remaining, issues = validate_itinerary(result.draft, request)
    has_errors = any(issue.severity == "error" for issue in issues)

    return ItineraryResponse(
        itinerary=result.draft,
        total_estimated_cost=total_cost,
        budget_remaining=budget_remaining,
        is_valid=not has_errors,
        issues=issues,
        model_used=result.model_used,
        agent_trace=result.trace,
    )

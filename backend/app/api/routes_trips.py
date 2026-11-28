import re

from fastapi import APIRouter, Depends, HTTPException, status

from app.agent.loop import TravelAgentLoop
from app.domain.models import (
    ItineraryDraft,
    ItineraryResponse,
    ItineraryRevisionRequest,
    TripRequest,
)
from app.domain.validator import validate_itinerary
from app.services.llm_client import (
    GeminiItineraryClient,
    LLMConfigurationError,
    LLMGenerationError,
    LLMTimeoutError,
    LLMUnavailableError,
)

router = APIRouter(prefix="/api/trips", tags=["trips"])

_MONEY = r"(?P<amount>[$€£]?\s*\d[\d,]*(?:\.\d{1,2})?)\s*(?:USD|EUR|GBP)?"


def _apply_budget_instruction(request: TripRequest, instruction: str) -> TripRequest:
    """Apply explicit budget changes using the original request's currency."""
    normalized = instruction.strip()
    patterns = (
        (
            re.compile(
                rf"\b(?:cut|reduce|lower|decrease)\s+(?:the\s+)?{_MONEY}"
                r"\s+(?:from|off)\s+(?:the\s+)?budget\b",
                re.I,
            ),
            "subtract",
        ),
        (
            re.compile(
                rf"\b(?:reduce|lower|decrease|cut)\s+(?:the\s+)?budget\s+by\s+{_MONEY}",
                re.I,
            ),
            "subtract",
        ),
        (
            re.compile(rf"\b(?:set|change|make)\s+(?:the\s+)?budget\s+to\s+{_MONEY}", re.I),
            "set",
        ),
    )
    for pattern, operation in patterns:
        match = pattern.search(normalized)
        if match is None:
            continue
        amount_text = (
            match.group("amount")
            .replace("$", "")
            .replace("€", "")
            .replace("£", "")
            .replace(",", "")
            .strip()
        )
        amount = float(amount_text)
        revised_budget = request.max_budget - amount if operation == "subtract" else amount
        if revised_budget <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The revised budget must remain greater than zero.",
            )
        return TripRequest(
            **{**request.model_dump(), "max_budget": round(revised_budget, 2)}
        )
    return request


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
    return _run_plan(agent, request)


@router.post("/revise", response_model=ItineraryResponse)
def revise_trip(
    revision: ItineraryRevisionRequest,
    agent: TravelAgentLoop = Depends(get_agent_loop),
) -> ItineraryResponse:
    """Revise the supplied itinerary using its current state and a natural-language instruction."""
    request = _apply_budget_instruction(revision.trip_request, revision.instruction)
    return _run_plan(
        agent,
        request,
        existing_draft=revision.itinerary,
        revision_instruction=revision.instruction,
    )


def _run_plan(
    agent: TravelAgentLoop,
    request: TripRequest,
    *,
    existing_draft: ItineraryDraft | None = None,
    revision_instruction: str | None = None,
) -> ItineraryResponse:
    try:
        if existing_draft is None:
            result = agent.run(request)
        else:
            result = agent.run(
                request,
                existing_draft=existing_draft,
                revision_instruction=revision_instruction,
            )
    except (LLMConfigurationError, LLMUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except LLMTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc),
        ) from exc
    except LLMGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    total_cost, budget_remaining, issues = validate_itinerary(
        result.draft, request, revision_instruction
    )
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

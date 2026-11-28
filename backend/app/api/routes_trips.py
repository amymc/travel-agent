import re
import json
import logging
from collections.abc import Callable, Iterator
from queue import Empty, Queue
from threading import Thread
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.agent.loop import TravelAgentLoop
from app.domain.models import (
    ItineraryDraft,
    ItineraryRevisionInstruction,
    ItineraryResponse,
    ItineraryRevisionRequest,
    JsonValue,
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
from app.services.trip_store import (
    add_message,
    create_thread,
    get_thread,
    latest_snapshot,
    list_threads,
    record_event,
    save_snapshot,
    ThreadDetail,
    ThreadSummary,
)
router = APIRouter(prefix="/api/trips", tags=["trips"])
logger = logging.getLogger(__name__)

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
    thread_id = create_thread(request.prompt)
    add_message(thread_id, "user", request.prompt)
    response = _run_plan(agent, request)
    response = save_snapshot(thread_id, request, response)
    add_message(thread_id, "assistant", response.itinerary.summary)
    return response


@router.post("/revise", response_model=ItineraryResponse)
def revise_trip(
    revision: ItineraryRevisionRequest,
    agent: TravelAgentLoop = Depends(get_agent_loop),
) -> ItineraryResponse:
    """Revise the supplied itinerary using its current state and a natural-language instruction."""
    request = _apply_budget_instruction(revision.trip_request, revision.instruction)
    thread_id = create_thread(revision.itinerary.title)
    add_message(thread_id, "user", revision.instruction)
    response = _run_plan(
        agent,
        request,
        existing_draft=revision.itinerary,
        revision_instruction=revision.instruction,
    )
    response = save_snapshot(thread_id, request, response)
    add_message(thread_id, "assistant", response.itinerary.summary)
    return response


@router.get("/threads")
def get_trip_threads() -> list[ThreadSummary]:
    """Return recent saved trip conversations."""
    return list_threads()


@router.get("/threads/{thread_id}")
def get_trip_thread(thread_id: str) -> ThreadDetail:
    thread = get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Trip thread not found.")
    return thread


@router.post("/stream")
def stream_plan_trip(
    request: TripRequest,
    agent: TravelAgentLoop = Depends(get_agent_loop),
) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(agent, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/threads/{thread_id}/revise/stream")
def stream_revise_trip(
    thread_id: str,
    revision: ItineraryRevisionInstruction,
    agent: TravelAgentLoop = Depends(get_agent_loop),
) -> StreamingResponse:
    if get_thread(thread_id) is None:
        raise HTTPException(status_code=404, detail="Trip thread not found.")
    saved = latest_snapshot(thread_id)
    if saved is None:
        raise HTTPException(status_code=409, detail="This thread has no saved itinerary to revise.")
    request, previous_response = saved
    request = _apply_budget_instruction(request, revision.instruction)
    add_message(thread_id, "user", revision.instruction)
    return StreamingResponse(
        _event_stream(
            agent,
            request,
            thread_id=thread_id,
            existing_draft=previous_response.itinerary,
            revision_instruction=revision.instruction,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _event_stream(
    agent: TravelAgentLoop,
    request: TripRequest,
    *,
    thread_id: str | None = None,
    existing_draft: ItineraryDraft | None = None,
    revision_instruction: str | None = None,
) -> Iterator[str]:
    """Run the synchronous agent in a worker and forward durable events as SSE."""
    active_thread_id = thread_id or create_thread(request.prompt)
    if thread_id is None:
        add_message(active_thread_id, "user", request.prompt)
    event_queue: Queue[dict[str, JsonValue] | None] = Queue()

    def publish(event: dict[str, JsonValue]) -> None:
        event_type = event.get("type")
        record_event(
            active_thread_id,
            event_type if isinstance(event_type, str) else "event",
            event,
        )
        event_queue.put(event)

    publish({"type": "started", "thread_id": active_thread_id})

    def work() -> None:
        try:
            response = _run_plan(
                agent,
                request,
                existing_draft=existing_draft,
                revision_instruction=revision_instruction,
                event_callback=publish,
            )
            response = save_snapshot(active_thread_id, request, response)
            add_message(active_thread_id, "assistant", response.itinerary.summary)
            publish(
                {
                    "type": "complete",
                    "response": cast(
                        dict[str, JsonValue], json.loads(response.model_dump_json())
                    ),
                }
            )
        except HTTPException as exc:
            message = str(exc.detail)
            add_message(active_thread_id, "assistant", message)
            publish({"type": "error", "message": message})
        except Exception:
            logger.exception("Streaming trip request failed")
            message = "Trip planning failed. Check the backend logs and try again."
            add_message(active_thread_id, "assistant", message)
            publish({"type": "error", "message": message})
        finally:
            event_queue.put(None)

    Thread(target=work, daemon=True).start()
    while True:
        try:
            event = event_queue.get(timeout=15)
        except Empty:
            yield ": keep-alive\n\n"
            continue
        if event is None:
            break
        yield f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _run_plan(
    agent: TravelAgentLoop,
    request: TripRequest,
    *,
    existing_draft: ItineraryDraft | None = None,
    revision_instruction: str | None = None,
    event_callback: Callable[[dict[str, JsonValue]], None] | None = None,
) -> ItineraryResponse:
    try:
        if existing_draft is None:
            if event_callback is None:
                result = agent.run(request)
            else:
                result = agent.run(request, event_callback=event_callback)
        else:
            if event_callback is None:
                result = agent.run(
                    request,
                    existing_draft=existing_draft,
                    revision_instruction=revision_instruction,
                )
            else:
                result = agent.run(
                    request,
                    existing_draft=existing_draft,
                    revision_instruction=revision_instruction,
                    event_callback=event_callback,
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

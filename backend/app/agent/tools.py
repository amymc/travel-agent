from dataclasses import dataclass
from typing import Any, Literal

from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from app.domain.models import ItineraryDraft, JsonValue, TripRequest, ValidationIssue
from app.domain.validator import validate_itinerary
from app.services.places import search_places
from app.services.routing import TravelMode, estimate_travel_time


class SearchPlacesArgs(BaseModel):
    city: str = Field(..., description="Target city name, e.g. 'Lisbon', 'Kyoto', or 'Barcelona'.")
    category: Literal["attraction", "restaurant", "lodging"] | None = Field(
        default=None,
        description="Optional filter for place category.",
    )
    query: str | None = Field(
        default=None,
        description="Optional keywords such as 'seafood', 'temples', 'history', or 'ramen'.",
    )
    max_cost: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Optional maximum cost preference. OpenStreetMap usually has no pricing, so this "
            "cannot be reliably enforced for returned places."
        ),
    )


class GetTravelTimeArgs(BaseModel):
    origin: str = Field(..., description="Origin place_id or exact place name from search_places.")
    destination: str = Field(
        ..., description="Destination place_id or exact place name from search_places."
    )
    mode: TravelMode = Field(
        default="transit",
        description="Transport mode: 'walking', 'transit', or 'taxi'.",
    )


@dataclass
class ToolExecutionContext:
    """Mutable state shared across tool calls within a single agent run."""

    request: TripRequest
    max_repairs: int = 2
    repair_attempts: int = 0
    last_draft: ItineraryDraft | None = None
    submitted_draft: ItineraryDraft | None = None


def build_tool_declarations() -> list[types.FunctionDeclaration]:
    """Build Gemini function declarations from Pydantic schemas."""
    return [
        types.FunctionDeclaration(
            name="search_places",
            description=(
                "Search real OpenStreetMap attractions, restaurants, and lodging near a city. "
                "Returns normalized place details, coordinates, available hours, and tags. "
                "Prices are generally unavailable and must not be treated as confirmed."
            ),
            parameters_json_schema=SearchPlacesArgs.model_json_schema(),
        ),
        types.FunctionDeclaration(
            name="get_travel_time",
            description=(
                "Route between places returned by search_places using OpenStreetMap/OSRM. "
                "Walking and taxi use routed networks; transit duration and fare are estimates."
            ),
            parameters_json_schema=GetTravelTimeArgs.model_json_schema(),
        ),
        types.FunctionDeclaration(
            name="validate_draft_itinerary",
            description=(
                "Check a draft ItineraryDraft against user constraints (budget total, day count, "
                "overlapping times, and pace) without finalizing."
            ),
            parameters_json_schema=ItineraryDraft.model_json_schema(),
        ),
        types.FunctionDeclaration(
            name="submit_itinerary",
            description=(
                "Finalize and submit the completed ItineraryDraft. Runs deterministic validation "
                "and rejects with specific errors if budget or schedule constraints fail."
            ),
            parameters_json_schema=ItineraryDraft.model_json_schema(),
        ),
    ]


def _format_issue_summary(issues: list[ValidationIssue]) -> str:
    codes = [issue.code for issue in issues]
    return ", ".join(codes) if codes else "none"


def execute_tool_call(
    name: str,
    raw_args: dict[str, JsonValue] | None,
    ctx: ToolExecutionContext,
) -> tuple[dict[str, Any], str]:
    """Execute one agent tool call safely and return (payload_for_llm, trace_summary)."""
    args = raw_args or {}

    try:
        if name == "search_places":
            parsed = SearchPlacesArgs.model_validate(args)
            result = search_places(
                city=parsed.city,
                category=parsed.category,
                query=parsed.query,
                max_cost=parsed.max_cost,
            )
            matches = result.get("matches", [])
            summary = f"Found {len(matches)} place(s) in {parsed.city}"
            if result.get("note"):
                summary = f"{summary} ({result['note']})"
            return dict(result), summary

        if name == "get_travel_time":
            parsed = GetTravelTimeArgs.model_validate(args)
            result = estimate_travel_time(
                origin=parsed.origin,
                destination=parsed.destination,
                mode=parsed.mode,
            )
            if "error" in result:
                return dict(result), f"Lookup error: {result['error']}"
            cost = result.get("estimated_cost")
            price_text = (
                "no fare"
                if result["mode"] == "walking"
                else f"{result['currency']} {cost:.2f}"
                if cost is not None and result.get("currency")
                else "fare unavailable"
            )
            summary = (
                f"{result['duration_mins']} mins ({result['distance_km']} km, "
                f"{price_text}) via {result['mode']}"
            )
            return dict(result), summary

        if name in {"validate_draft_itinerary", "submit_itinerary"}:
            draft = ItineraryDraft.model_validate(args)
            ctx.last_draft = draft
            total_cost, remaining, issues = validate_itinerary(draft, ctx.request)
            serialized_issues = [issue.model_dump() for issue in issues]
            errors = [issue for issue in issues if issue.severity == "error"]

            if name == "validate_draft_itinerary":
                summary = (
                    f"Valid ({ctx.request.currency} {total_cost:.2f})"
                    if not errors
                    else f"{len(errors)} error(s): {_format_issue_summary(errors)}"
                )
                return {
                    "is_valid": len(errors) == 0,
                    "total_estimated_cost": total_cost,
                    "budget_remaining": remaining,
                    "issues": serialized_issues,
                }, summary

            # submit_itinerary
            if errors and ctx.repair_attempts < ctx.max_repairs:
                ctx.repair_attempts += 1
                summary = (
                    f"Rejected for repair {ctx.repair_attempts}/{ctx.max_repairs}: "
                    f"{_format_issue_summary(errors)}"
                )
                return {
                    "accepted": False,
                    "error": (
                        "Itinerary failed deterministic validation. Fix the error(s) below and "
                        "call submit_itinerary again."
                    ),
                    "total_estimated_cost": total_cost,
                    "budget_remaining": remaining,
                    "issues": serialized_issues,
                }, summary

            ctx.submitted_draft = draft
            summary = (
                f"Submitted ({ctx.request.currency} {total_cost:.2f}, valid)"
                if not errors
                else f"Submitted with {len(errors)} remaining error(s)"
            )
            return {
                "accepted": True,
                "total_estimated_cost": total_cost,
                "budget_remaining": remaining,
                "issues": serialized_issues,
            }, summary

        return {
            "error": f"Unknown tool '{name}'. Use search_places, get_travel_time, validate_draft_itinerary, or submit_itinerary."
        }, f"Unknown tool '{name}'"

    except ValidationError as exc:
        error_text = f"Invalid arguments for '{name}': {exc.errors()}"
        return {"error": error_text}, f"Argument error on {name}"
    except Exception as exc:
        detail = " ".join(str(exc).split())
        if len(detail) > 200:
            detail = f"{detail[:197]}..."
        summary = f"Tool failure on {name}: {type(exc).__name__}"
        if detail:
            summary = f"{summary}: {detail}"
        return {"error": f"Tool '{name}' failed: {exc}"}, summary

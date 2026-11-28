from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Pace = Literal["relaxed", "moderate", "packed"]
ActivityCategory = Literal["attraction", "restaurant", "transport", "lodging", "free_time"]
type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


class TripRequest(BaseModel):
    """User input describing the desired holiday and hard/soft constraints."""

    prompt: str = Field(..., min_length=3, max_length=2000)
    num_days: int = Field(default=3, ge=1, le=14)
    max_budget: float = Field(default=1000.0, gt=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    pace: Pace = Field(default="moderate")
    interests: list[str] = Field(default_factory=list)
    start_date: date | None = Field(default=None, description="Optional first travel date for weekday opening-hours checks.")


class ItineraryItem(BaseModel):
    """A single scheduled block within a day."""

    model_config = ConfigDict(extra="forbid")

    start_time: str = Field(..., description="24-hour start time in HH:MM format, e.g. 09:00")
    end_time: str = Field(..., description="24-hour end time in HH:MM format, e.g. 11:30")
    title: str
    category: ActivityCategory
    location: str
    description: str
    estimated_cost: float = Field(default=0.0, ge=0)
    transit_note: str | None = Field(
        default=None,
        description="Optional short note on how to reach this place from the previous stop.",
    )
    opening_hours: str | None = Field(
        default=None,
        description="Known source opening hours for this place, copied from place search when available.",
    )
    travel_time_mins_from_previous: int | None = Field(
        default=None,
        ge=0,
        description="Measured travel minutes from the previous itinerary stop when available.",
    )


class DayPlan(BaseModel):
    """All scheduled items for a single day of the trip."""

    model_config = ConfigDict(extra="forbid")

    day_number: int = Field(..., ge=1)
    theme: str
    items: list[ItineraryItem] = Field(..., min_length=1)


class ItineraryDraft(BaseModel):
    """Structured itinerary produced by the LLM."""

    model_config = ConfigDict(extra="forbid")

    destination: str
    title: str
    summary: str
    currency: str
    days: list[DayPlan]


class ValidationIssue(BaseModel):
    """A deterministic constraint violation or warning."""

    severity: Literal["warning", "error"]
    code: str
    message: str
    day_number: int | None = None


class AgentToolCall(BaseModel):
    """Record of a single tool invocation made by the agent during planning."""

    name: str
    args: dict[str, JsonValue] = Field(default_factory=dict)
    result_summary: str


class AgentStepTrace(BaseModel):
    """Observability trace for one iteration of the agent loop."""

    step: int
    model_used: str
    tool_calls: list[AgentToolCall] = Field(default_factory=list)
    note: str | None = None


class ItineraryResponse(BaseModel):
    """API response combining the structured itinerary with deterministic validation."""

    itinerary: ItineraryDraft
    total_estimated_cost: float
    budget_remaining: float
    is_valid: bool
    issues: list[ValidationIssue]
    model_used: str
    agent_trace: list[AgentStepTrace] = Field(default_factory=list)


class ItineraryRevisionRequest(BaseModel):
    """An instruction to revise a specific existing itinerary."""

    trip_request: TripRequest
    itinerary: ItineraryDraft
    instruction: str = Field(..., min_length=3, max_length=2000)

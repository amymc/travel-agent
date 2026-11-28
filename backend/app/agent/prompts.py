from app.domain.models import TripRequest

SYSTEM_PROMPT = """You are an expert AI travel planner operating in an agentic tool-calling loop.

Available tools:
- search_places: Search real OpenStreetMap attractions, restaurants, and lodging near any geocodable city.
- get_travel_time: Get routed walking/driving distances; transit times and fares may be estimates or unavailable.
- validate_draft_itinerary: Run deterministic Python checks on budget, day count, overlapping times, and pace.
- submit_itinerary: Finalize and submit the complete ItineraryDraft.

Workflow:
1. First, call search_places (you can batch multiple calls in one turn for attractions, restaurants, and lodging) to ground your plan in real candidates and available opening hours.
   - If a search returns no results, broaden your query or explain the limitation.
   - OpenStreetMap usually has no prices. Never treat missing prices or a placeholder cost as proof a place is free; state that costs need verification and use cautious estimates for the requested currency.
2. Call get_travel_time between key candidate stops so transit_note and schedule gaps are realistic. Respect any note that says transit or fare data is estimated or unavailable.
3. Assemble a realistic day-by-day ItineraryDraft:
   - Exact number of days requested (day_number 1 through N).
   - Strict 24-hour HH:MM times, non-overlapping and sequential, leaving travel time between stops.
   - Keep total estimated_cost at or below max_budget (if tight, swap pricier restaurants/activities for free or budget options found via search_places).
   - Match the requested pace (relaxed: 3-4 stops/day, moderate: 4-6 stops/day, packed: 6-8 stops/day).
   - Copy known opening_hours from search results and measured travel_time_mins_from_previous from route results into each applicable itinerary item. Use null when unavailable; never invent these values.
   - Every restaurant stop must have the specific venue name as its title (for example, “Cervejaria Ramiro”), with the neighborhood only in location. Never use labels such as “Lunch in Alfama”, “Seafood dinner”, or “local restaurant” as the title. If search fails, use a specific venue only when you can identify one; say its details were not verified.
4. Call submit_itinerary with your complete ItineraryDraft. If submit_itinerary reports validation errors (such as BUDGET_EXCEEDED or TIME_OVERLAP), fix the offending items and call submit_itinerary again.
"""


def build_trip_prompt(request: TripRequest) -> str:
    """Format the user's TripRequest into a clear prompt for the agent."""
    interests_text = (
        ", ".join(request.interests) if request.interests else "general sightseeing and local food"
    )
    return (
        f"Plan a {request.num_days}-day trip.\n"
        f"Trip description: {request.prompt}\n"
        f"Budget ceiling: {request.max_budget:.2f} {request.currency} total\n"
        f"Preferred pace: {request.pace}\n"
        f"Interests: {interests_text}\n"
        f"First travel date: {request.start_date.isoformat() if request.start_date else 'not specified'}\n"
        f"Use currency code '{request.currency}' for all cost estimates.\n\n"
        "Use your tools to research places and check travel times before calling submit_itinerary."
    )


def build_revision_prompt(
    request: TripRequest,
    existing_itinerary_json: str,
    instruction: str,
) -> str:
    """Tell the agent to edit the supplied draft while retaining unaffected choices."""
    return (
        "REVISION REQUEST: Modify the existing itinerary below. Do not plan the trip from scratch. "
        "Keep every day, stop, and detail that does not need to change to satisfy the request. "
        "For 'too rushed', reduce the number of stops and add breathing room on the named day. "
        "For budget changes, adjust costs and/or replace expensive stops while preserving the trip's character. "
        "Use the normal research, deterministic validation, repair, and submission tools.\n\n"
        f"User instruction: {instruction}\n"
        f"Current budget ceiling: {request.max_budget:.2f} {request.currency}\n"
        f"Current itinerary JSON:\n{existing_itinerary_json}"
    )

import re
from app.domain.models import ItineraryDraft, Pace, TripRequest, ValidationIssue

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

MAX_ACTIVITIES_BY_PACE: dict[Pace, int] = {
    "relaxed": 4,
    "moderate": 6,
    "packed": 8,
}


def parse_minutes(time_str: str) -> int | None:
    """Convert HH:MM (24-hour) to minutes since midnight, or None if invalid."""
    match = TIME_PATTERN.match(time_str.strip())
    if not match:
        return None
    hours, minutes = int(match.group(1)), int(match.group(2))
    return hours * 60 + minutes


def validate_itinerary(
    draft: ItineraryDraft,
    request: TripRequest,
) -> tuple[float, float, list[ValidationIssue]]:
    """
    Deterministically validate an LLM-generated itinerary against user constraints.

    LLMs frequently miscalculate sums and overlapping time blocks, so this function
    serves as the source of truth for budget totals and schedule consistency.
    """
    issues: list[ValidationIssue] = []
    total_cost = 0.0

    if len(draft.days) != request.num_days:
        issues.append(
            ValidationIssue(
                severity="error",
                code="DAY_COUNT_MISMATCH",
                message=(
                    f"Expected {request.num_days} days, but itinerary contains {len(draft.days)}."
                ),
            )
        )

    pace_limit = MAX_ACTIVITIES_BY_PACE[request.pace]

    for day in draft.days:
        prev_end: int | None = None
        prev_title: str | None = None
        active_count = 0

        for item in day.items:
            total_cost += item.estimated_cost
            if item.category != "free_time":
                active_count += 1

            start_mins = parse_minutes(item.start_time)
            end_mins = parse_minutes(item.end_time)

            if start_mins is None or end_mins is None:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="INVALID_TIME_FORMAT",
                        day_number=day.day_number,
                        message=(
                            f"Day {day.day_number} ('{item.title}'): invalid time format "
                            f"'{item.start_time} - {item.end_time}'. Expected HH:MM."
                        ),
                    )
                )
                continue

            if end_mins <= start_mins:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="INVALID_TIME_RANGE",
                        day_number=day.day_number,
                        message=(
                            f"Day {day.day_number} ('{item.title}'): end time {item.end_time} "
                            f"must be after start time {item.start_time}."
                        ),
                    )
                )

            if prev_end is not None and start_mins < prev_end:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="TIME_OVERLAP",
                        day_number=day.day_number,
                        message=(
                            f"Day {day.day_number}: '{item.title}' starts at {item.start_time}, "
                            f"which overlaps with '{prev_title}'."
                        ),
                    )
                )

            prev_end = end_mins
            prev_title = item.title

        if active_count > pace_limit:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="PACE_EXCEEDED",
                    day_number=day.day_number,
                    message=(
                        f"Day {day.day_number} has {active_count} scheduled stops, which may feel "
                        f"rushed for a '{request.pace}' pace (recommended max {pace_limit})."
                    ),
                )
            )

    total_cost = round(total_cost, 2)
    budget_remaining = round(request.max_budget - total_cost, 2)

    if total_cost > request.max_budget:
        overage = round(total_cost - request.max_budget, 2)
        issues.append(
            ValidationIssue(
                severity="error",
                code="BUDGET_EXCEEDED",
                message=(
                    f"Estimated total cost ({request.currency} {total_cost:.2f}) exceeds "
                    f"budget ({request.currency} {request.max_budget:.2f}) by "
                    f"{request.currency} {overage:.2f}."
                ),
            )
        )

    return total_cost, budget_remaining, issues

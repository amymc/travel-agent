import re
from datetime import date, timedelta

from app.domain.models import ItineraryDraft, Pace, TripRequest, ValidationIssue

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
OPENING_INTERVAL_PATTERN = re.compile(r"^(\d{1,2}:\d{2})-(\d{1,2}:\d{2})$")
DAY_NAMES = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
DAY_TOKEN_PATTERN = r"(?:Mo|Tu|We|Th|Fr|Sa|Su)"
DAY_SELECTOR_PATTERN = rf"{DAY_TOKEN_PATTERN}(?:-{DAY_TOKEN_PATTERN})?(?:,{DAY_TOKEN_PATTERN}(?:-{DAY_TOKEN_PATTERN})?)*"
OPENING_DAY_PATTERN = re.compile(rf"^({DAY_SELECTOR_PATTERN})\s+(.+)$")
GENERIC_MEAL_TERMS = re.compile(
    r"\b(?:a|the|local|traditional|authentic|seafood|casual|budget|fine|upscale|"
    r"expensive|cheap|fancy|quick|popular|recommended|"
    r"lunch|dinner|breakfast|brunch|meal|restaurant|cafe|café|dining|food|stop)\b",
    re.I,
)

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


def _parse_clock(value: str) -> int | None:
    if value == "24:00":
        return 24 * 60
    return parse_minutes(value)


def _parse_day_selector(selector: str) -> set[int] | None:
    days: set[int] = set()
    for part in selector.split(","):
        endpoints = part.split("-")
        if len(endpoints) > 2 or any(day not in DAY_NAMES for day in endpoints):
            return None
        first = DAY_NAMES.index(endpoints[0])
        last = DAY_NAMES.index(endpoints[-1])
        if len(endpoints) == 1:
            days.add(first)
        else:
            index = first
            while True:
                days.add(index)
                if index == last:
                    break
                index = (index + 1) % 7
    return days


def _opening_hours_match(
    opening_hours: str,
    start_minute: int,
    end_minute: int,
    weekday: int | None,
) -> bool | None:
    """Check common OSM opening-hours syntax; None means syntax/day is unverifiable."""
    normalized = opening_hours.strip()
    if not normalized or normalized.casefold() in {"unknown", "open by appointment"}:
        return None
    if normalized == "24/7":
        return True
    if normalized.casefold() in {"off", "closed"}:
        return False

    intervals: list[tuple[int, int]] = []
    recognized_any = False
    for rule in normalized.split(";"):
        rule = rule.strip()
        day_match = OPENING_DAY_PATTERN.match(rule)
        days: set[int] | None = None
        hours = rule
        if day_match:
            days = _parse_day_selector(day_match.group(1))
            hours = day_match.group(2)
            if days is None:
                return None
        elif re.match(r"^(?:Mo|Tu|We|Th|Fr|Sa|Su)", rule):
            return None

        if weekday is None and days is not None and len(days) != 7:
            return None
        if weekday is not None and days is not None and weekday not in days:
            recognized_any = True
            continue
        if hours.casefold() in {"off", "closed"}:
            recognized_any = True
            continue

        for interval in hours.split(","):
            match = OPENING_INTERVAL_PATTERN.match(interval.strip())
            if not match:
                return None
            opening = _parse_clock(match.group(1))
            closing = _parse_clock(match.group(2))
            if opening is None or closing is None or closing <= opening:
                return None
            intervals.append((opening, closing))
            recognized_any = True

    if not recognized_any:
        return None
    return any(start_minute >= opening and end_minute <= closing for opening, closing in intervals)


def _needs_named_restaurant(item_title: str, location: str) -> bool:
    """Detect generic meal/area labels that do not identify a restaurant venue."""
    title = item_title.strip().casefold()
    place = location.strip().casefold()
    if not title or title == place:
        return True
    remainder = GENERIC_MEAL_TERMS.sub(" ", title)
    remainder = re.sub(r"[\s,;:|–—-]+", " ", remainder).strip()
    if not remainder:
        return True
    if remainder in {"at", "in", "near"}:
        return True
    if re.match(r"^(?:in|near)\s+", remainder):
        return True
    at_match = re.match(r"^at\s+(.+)$", remainder)
    if at_match:
        venue_or_area = at_match.group(1).strip()
        return venue_or_area == place or venue_or_area in place or place in venue_or_area
    return False


def validate_itinerary(
    draft: ItineraryDraft,
    request: TripRequest,
    revision_instruction: str | None = None,
) -> tuple[float, float, list[ValidationIssue]]:
    """Validate budget, daily schedule, travel gaps, hours, and requested pace."""
    issues: list[ValidationIssue] = []
    total_cost = 0.0

    if len(draft.days) != request.num_days:
        issues.append(
            ValidationIssue(
                severity="error",
                code="DAY_COUNT_MISMATCH",
                message=f"Expected {request.num_days} days, but itinerary contains {len(draft.days)}.",
            )
        )
    seen_days: set[int] = set()
    pace_limit = MAX_ACTIVITIES_BY_PACE[request.pace]
    rushed_revision = bool(
        revision_instruction
        and re.search(r"rushed|too busy|too many stops|slow(?:er| down)|less packed", revision_instruction, re.I)
    )
    requested_days = {
        int(match)
        for match in re.findall(r"\bday\s+(\d+)\b", revision_instruction or "", re.I)
    }

    for day in draft.days:
        if not day.items:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="EMPTY_DAY",
                    day_number=day.day_number,
                    message=f"Day {day.day_number} has no scheduled activities.",
                )
            )
        if day.day_number in seen_days or not 1 <= day.day_number <= request.num_days:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="INVALID_DAY_NUMBER",
                    day_number=day.day_number,
                    message=f"Day number {day.day_number} is duplicated or outside the requested trip.",
                )
            )
        seen_days.add(day.day_number)
        previous_end: int | None = None
        previous_title: str | None = None
        previous_location: str | None = None
        active_count = 0
        weekday: int | None = None
        if request.start_date is not None:
            weekday = (request.start_date + timedelta(days=day.day_number - 1)).weekday()

        for item in day.items:
            total_cost += item.estimated_cost
            if item.category != "free_time":
                active_count += 1

            if item.category == "restaurant" and _needs_named_restaurant(item.title, item.location):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="RESTAURANT_NEEDS_NAMED_VENUE",
                        day_number=day.day_number,
                        message=(
                            f"Day {day.day_number}: replace '{item.title}' with a specific restaurant name; "
                            "keep only the neighborhood in the location field."
                        ),
                    )
                )

            start_minute = parse_minutes(item.start_time)
            end_minute = parse_minutes(item.end_time)
            if start_minute is None or end_minute is None:
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

            if end_minute <= start_minute:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="INVALID_TIME_RANGE",
                        day_number=day.day_number,
                        message=f"Day {day.day_number} ('{item.title}') must end after it starts.",
                    )
                )
            if previous_end is not None and start_minute < previous_end:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="TIME_OVERLAP",
                        day_number=day.day_number,
                        message=f"Day {day.day_number}: '{item.title}' overlaps with '{previous_title}'.",
                    )
                )
            if (
                previous_end is not None
                and item.travel_time_mins_from_previous is not None
                and start_minute - previous_end < item.travel_time_mins_from_previous
            ):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="INSUFFICIENT_TRAVEL_TIME",
                        day_number=day.day_number,
                        message=(
                            f"Day {day.day_number}: allow {item.travel_time_mins_from_previous} minutes "
                            f"to travel before '{item.title}'."
                        ),
                    )
                )
            elif (
                previous_end is not None
                and item.travel_time_mins_from_previous is None
                and previous_location is not None
            ):
                if previous_location.casefold() != item.location.casefold():
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="TRAVEL_TIME_UNVERIFIED",
                            day_number=day.day_number,
                            message=(
                                f"Travel time before '{item.title}' was not verified from "
                                f"'{previous_location}'."
                            ),
                        )
                    )
            if item.opening_hours and end_minute > start_minute:
                is_open = _opening_hours_match(
                    item.opening_hours, start_minute, end_minute, weekday
                )
                if is_open is False:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="OUTSIDE_OPENING_HOURS",
                            day_number=day.day_number,
                            message=(
                                f"Day {day.day_number}: '{item.title}' is scheduled outside its "
                                f"listed opening hours ({item.opening_hours})."
                            ),
                        )
                    )
                elif is_open is None:
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="OPENING_HOURS_UNVERIFIED",
                            day_number=day.day_number,
                            message=f"Could not verify opening hours for '{item.title}'.",
                        )
                    )
            if not item.opening_hours and item.category in {"attraction", "restaurant"}:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="OPENING_HOURS_UNVERIFIED",
                        day_number=day.day_number,
                        message=f"No source opening hours are available for '{item.title}'.",
                    )
                )

            previous_end = end_minute
            previous_title = item.title
            previous_location = item.location

        targeted_rushed_day = rushed_revision and (
            not requested_days or day.day_number in requested_days
        )
        day_pace_limit = max(1, pace_limit - 2) if targeted_rushed_day else pace_limit
        if active_count > day_pace_limit:
            issues.append(
                ValidationIssue(
                    severity="error" if targeted_rushed_day else "warning",
                    code="REVISION_PACE_EXCEEDED" if targeted_rushed_day else "PACE_EXCEEDED",
                    day_number=day.day_number,
                    message=(
                        f"Day {day.day_number} has {active_count} scheduled stops, which may feel "
                        f"rushed for a '{request.pace}' pace (maximum for this revision: {day_pace_limit})."
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

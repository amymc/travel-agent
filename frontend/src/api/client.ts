import type { ItineraryResponse, TripRequest } from "../types/trip";

export async function planTrip(request: TripRequest): Promise<ItineraryResponse> {
  const response = await fetch("/api/trips/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Fall back to default error message when response body is not JSON.
    }
    throw new Error(detail);
  }

  return (await response.json()) as ItineraryResponse;
}

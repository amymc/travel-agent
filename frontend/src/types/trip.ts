export type Pace = "relaxed" | "moderate" | "packed";

export type ActivityCategory =
  | "attraction"
  | "restaurant"
  | "transport"
  | "lodging"
  | "free_time";

export interface TripRequest {
  prompt: string;
  num_days: number;
  max_budget: number;
  currency: string;
  pace: Pace;
  interests: string[];
}

export interface ItineraryItem {
  start_time: string;
  end_time: string;
  title: string;
  category: ActivityCategory;
  location: string;
  description: string;
  estimated_cost: number;
  transit_note?: string | null;
}

export interface DayPlan {
  day_number: number;
  theme: string;
  items: ItineraryItem[];
}

export interface ItineraryDraft {
  destination: string;
  title: string;
  summary: string;
  currency: string;
  days: DayPlan[];
}

export interface ValidationIssue {
  severity: "warning" | "error";
  code: string;
  message: string;
  day_number?: number | null;
}

export interface ItineraryResponse {
  itinerary: ItineraryDraft;
  total_estimated_cost: number;
  budget_remaining: number;
  is_valid: boolean;
  issues: ValidationIssue[];
  model_used: string;
}

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
  start_date?: string | null;
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
  opening_hours?: string | null;
  travel_time_mins_from_previous?: number | null;
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

export interface AgentToolCall {
  name: string;
  args: Record<string, unknown>;
  result_summary: string;
  result_payload?: Record<string, unknown> | null;
}

export interface AgentStepTrace {
  step: number;
  model_used: string;
  tool_calls: AgentToolCall[];
  note?: string | null;
}

export interface ItineraryResponse {
  itinerary: ItineraryDraft;
  total_estimated_cost: number;
  budget_remaining: number;
  is_valid: boolean;
  issues: ValidationIssue[];
  model_used: string;
  agent_trace: AgentStepTrace[];
  thread_id?: string | null;
  trip_id?: string | null;
  revision_number?: number | null;
}

export interface AgentStreamEvent {
  type: string;
  [key: string]: unknown;
}

export interface TripThreadSummary {
  thread_id: string;
  title: string;
  updated_at: string;
  revision_number: number | null;
  itinerary_title: string | null;
}

export interface TripThreadSnapshot {
  trip_id: string;
  revision_number: number;
  request: TripRequest;
  response: ItineraryResponse;
  created_at: string;
}

export interface TripThreadMessage {
  message_id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface TripThreadDetail {
  thread_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: TripThreadMessage[];
  snapshots: TripThreadSnapshot[];
  events: Array<{
    event_id: number;
    event_type: string;
    payload: AgentStreamEvent;
    created_at: string;
  }>;
}

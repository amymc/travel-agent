import { useEffect, useState, type SubmitEventHandler } from "react";
import type { ActivityCategory, ItineraryResponse } from "../types/trip";
import { AgentTracePanel } from "./AgentTracePanel";

interface ItineraryViewProps {
  data: ItineraryResponse | null;
  maxBudget: number;
  isLoading: boolean;
  onRevise: (instruction: string) => void;
}

const CATEGORY_STYLES: Record<ActivityCategory, string> = {
  attraction: "bg-indigo-50 text-indigo-700 border-indigo-200",
  restaurant: "bg-amber-50 text-amber-700 border-amber-200",
  transport: "bg-sky-50 text-sky-700 border-sky-200",
  lodging: "bg-emerald-50 text-emerald-700 border-emerald-200",
  free_time: "bg-slate-100 text-slate-700 border-slate-200",
};

const CATEGORY_CHART_COLORS: Record<ActivityCategory, string> = {
  attraction: "bg-indigo-500",
  restaurant: "bg-amber-500",
  transport: "bg-sky-500",
  lodging: "bg-emerald-500",
  free_time: "bg-slate-400",
};

export function ItineraryView({ data, maxBudget, isLoading, onRevise }: ItineraryViewProps) {
  const [selectedDay, setSelectedDay] = useState<number | "all">("all");
  const [selectedCategory, setSelectedCategory] = useState<ActivityCategory | "all">("all");
  const [revisionInstruction, setRevisionInstruction] = useState("");

  useEffect(() => {
    setSelectedDay("all");
    setSelectedCategory("all");
  }, [data?.trip_id]);

  if (!data) {
    return (
      <div className="flex h-full min-h-[420px] flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white/70 p-8 text-center">
        <p className="text-base font-semibold text-slate-800">No itinerary generated yet</p>
        <p className="mt-2 max-w-md text-sm text-slate-500">
          Describe your trip on the left and click <strong>Generate Itinerary</strong>. Gemini will
          return a structured JSON plan, and the Python validator will verify budget and schedule
          consistency.
        </p>
      </div>
    );
  }

  const {
    itinerary,
    total_estimated_cost,
    budget_remaining,
    is_valid,
    issues,
    model_used,
    agent_trace,
  } = data;
  const budgetRatio = Math.min(
    100,
    Math.round((total_estimated_cost / Math.max(1, maxBudget)) * 100),
  );
  const overBudget = budget_remaining < 0;

  const visibleDays =
    selectedDay === "all"
      ? itinerary.days
      : itinerary.days.filter((day) => day.day_number === selectedDay);
  const costByCategory = (Object.keys(CATEGORY_STYLES) as ActivityCategory[])
    .map((category) => ({
      category,
      cost: itinerary.days
        .flatMap((day) => day.items)
        .filter((item) => item.category === category)
        .reduce((sum, item) => sum + item.estimated_cost, 0),
    }))
    .filter((entry) => entry.cost > 0);
  const largestCategoryCost = Math.max(1, ...costByCategory.map((entry) => entry.cost));

  const handleRevision: SubmitEventHandler<HTMLFormElement> = (event) => {
    event.preventDefault();
    const instruction = revisionInstruction.trim();
    if (!instruction || isLoading) return;
    onRevise(instruction);
    setRevisionInstruction("");
  };

  return (
    <div className="space-y-5">
      {/* Header & Budget Card */}
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <span className="inline-flex items-center rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-medium text-indigo-700">
              {itinerary.destination}
            </span>
            <h2 className="mt-1.5 text-xl font-bold text-slate-900">{itinerary.title}</h2>
            <p className="mt-1 text-sm text-slate-600">{itinerary.summary}</p>
          </div>
          <div className="flex flex-col items-end gap-1">
            <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-mono text-slate-600">
              {model_used}
            </span>
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                is_valid ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"
              }`}
            >
              {is_valid
                ? issues.length > 0
                  ? "Valid · review warnings"
                  : "Constraints Valid"
                : "Constraint Issues Found"}
            </span>
          </div>
        </div>

        {/* Deterministic Budget Meter */}
        <div className="rounded-xl bg-slate-50 p-4 border border-slate-200/80">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium text-slate-700">Estimated Cost (Python verified)</span>
            <span className={`font-semibold ${overBudget ? "text-rose-600" : "text-slate-900"}`}>
              {itinerary.currency} {total_estimated_cost.toFixed(2)} / {itinerary.currency}{" "}
              {maxBudget.toFixed(2)}
            </span>
          </div>
          <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-200">
            <div
              className={`h-full transition-all ${overBudget ? "bg-rose-500" : "bg-emerald-500"}`}
              style={{ width: `${budgetRatio}%` }}
            />
          </div>
          <p className={`mt-1.5 text-xs ${overBudget ? "text-rose-600" : "text-slate-500"}`}>
            {overBudget
              ? `Over budget by ${itinerary.currency} ${Math.abs(budget_remaining).toFixed(2)}`
              : `${itinerary.currency} ${budget_remaining.toFixed(2)} remaining under budget`}
          </p>
        </div>

        {/* Validation Issues */}
        {issues.length > 0 && (
          <div className="space-y-2">
            {issues.map((issue, idx) => (
              <div
                key={`${issue.code}-${idx}`}
                className={`rounded-xl border px-3.5 py-2.5 text-xs ${
                  issue.severity === "error"
                    ? "border-rose-200 bg-rose-50 text-rose-800"
                    : "border-amber-200 bg-amber-50 text-amber-800"
                }`}
              >
                <span className="font-semibold uppercase mr-1.5">[{issue.code}]</span>
                {issue.message}
              </div>
            ))}
          </div>
        )}
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Estimated cost breakdown</h3>
            <p className="mt-0.5 text-xs text-slate-500">
              Select a category to filter the itinerary below.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setSelectedCategory("all")}
            aria-pressed={selectedCategory === "all"}
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              selectedCategory === "all" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700"
            }`}
          >
            All categories
          </button>
        </div>
        {costByCategory.length === 0 ? (
          <p className="mt-4 text-xs text-slate-500">No estimated activity costs are recorded.</p>
        ) : (
          <div className="mt-4 space-y-2.5">
            {costByCategory.map(({ category, cost }) => (
              <button
                key={category}
                type="button"
                onClick={() =>
                  setSelectedCategory(category === selectedCategory ? "all" : category)
                }
                aria-pressed={selectedCategory === category}
                className="grid w-full grid-cols-[6rem_1fr_auto] items-center gap-3 rounded-lg px-2 py-1 text-left hover:bg-slate-50"
              >
                <span className="text-xs capitalize text-slate-700">
                  {category.replace("_", " ")}
                </span>
                <span className="h-2 overflow-hidden rounded-full bg-slate-100">
                  <span
                    className={`block h-full rounded-full ${CATEGORY_CHART_COLORS[category]}`}
                    style={{ width: `${Math.max(2, (cost / largestCategoryCost) * 100)}%` }}
                  />
                </span>
                <span className="text-xs font-semibold tabular-nums text-slate-800">
                  {itinerary.currency} {cost.toFixed(2)}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      <form
        onSubmit={handleRevision}
        className="rounded-2xl border border-indigo-200 bg-indigo-50/70 p-5 shadow-sm"
      >
        <label
          htmlFor="revision-instruction"
          className="block text-sm font-semibold text-slate-900"
        >
          Revise this itinerary
        </label>
        <p className="mt-1 text-xs text-slate-600">
          Ask for a change and the agent will edit this plan while keeping the parts that still
          work. Budget changes automatically use the original trip currency ({itinerary.currency}).
        </p>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <input
            id="revision-instruction"
            value={revisionInstruction}
            onChange={(event) => setRevisionInstruction(event.target.value)}
            placeholder="Day 2 feels too rushed, or reduce the budget by 300"
            minLength={3}
            maxLength={2000}
            required
            className="min-w-0 flex-1 rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          />
          <button
            type="submit"
            disabled={isLoading || revisionInstruction.trim().length < 3}
            className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isLoading ? "Revising..." : "Revise itinerary"}
          </button>
        </div>
      </form>

      {/* Agent Execution Trace */}
      <AgentTracePanel trace={agent_trace} />

      {/* Day Filter Tabs */}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setSelectedDay("all")}
          className={`rounded-full px-3.5 py-1.5 text-xs font-semibold transition ${
            selectedDay === "all"
              ? "bg-slate-900 text-white"
              : "bg-white border border-slate-200 text-slate-700 hover:bg-slate-100"
          }`}
        >
          All Days ({itinerary.days.length})
        </button>
        {itinerary.days.map((day) => (
          <button
            key={day.day_number}
            type="button"
            onClick={() => setSelectedDay(day.day_number)}
            className={`rounded-full px-3.5 py-1.5 text-xs font-semibold transition ${
              selectedDay === day.day_number
                ? "bg-slate-900 text-white"
                : "bg-white border border-slate-200 text-slate-700 hover:bg-slate-100"
            }`}
          >
            Day {day.day_number}
          </button>
        ))}
      </div>

      {/* Day Cards */}
      <div className="space-y-4">
        {visibleDays.map((day) => (
          <section
            key={day.day_number}
            className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm space-y-4"
          >
            <div className="border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900">
                Day {day.day_number}: {day.theme}
              </h3>
            </div>

            <div className="space-y-3">
              {day.items
                .filter((item) => selectedCategory === "all" || item.category === selectedCategory)
                .map((item, idx) => (
                  <div
                    key={`${day.day_number}-${item.start_time}-${idx}`}
                    className="rounded-xl border border-slate-100 bg-slate-50/60 p-4"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-semibold text-slate-700">
                          {item.start_time} – {item.end_time}
                        </span>
                        <span
                          className={`rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize ${
                            CATEGORY_STYLES[item.category]
                          }`}
                        >
                          {item.category.replace("_", " ")}
                        </span>
                      </div>
                      <span className="text-xs font-semibold text-slate-700">
                        {itinerary.currency} {item.estimated_cost.toFixed(2)}
                      </span>
                    </div>

                    <h4 className="mt-1.5 text-sm font-semibold text-slate-900">{item.title}</h4>
                    <p className="text-xs font-medium text-slate-500">{item.location}</p>
                    <p className="mt-1.5 text-sm text-slate-700">{item.description}</p>

                    {item.transit_note && (
                      <p className="mt-2 text-xs text-slate-500 italic">
                        Transit: {item.transit_note}
                      </p>
                    )}
                    {item.opening_hours && (
                      <p className="mt-1 text-xs text-slate-500">
                        Listed hours: {item.opening_hours}
                      </p>
                    )}
                    {item.travel_time_mins_from_previous != null && (
                      <p className="mt-1 text-xs text-slate-500">
                        Verified travel gap: {item.travel_time_mins_from_previous} min
                      </p>
                    )}
                  </div>
                ))}
              {day.items.every(
                (item) => selectedCategory !== "all" && item.category !== selectedCategory,
              ) && (
                <p className="rounded-lg bg-slate-50 px-3 py-4 text-center text-xs text-slate-500">
                  No {selectedCategory.replace("_", " ")} stops on this day.
                </p>
              )}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

import { useState, type SubmitEventHandler } from "react";
import type { Pace, TripRequest } from "../types/trip";

interface TripPromptFormProps {
  isLoading: boolean;
  onSubmit: (request: TripRequest) => void;
}

const EXAMPLE_TRIPS: Array<{
  label: string;
  prompt: string;
  num_days: number;
  max_budget: number;
  currency: string;
  pace: Pace;
  interests: string;
}> = [
  {
    label: "Lisbon Food & History",
    prompt:
      "A long weekend in Lisbon focused on historic neighborhoods, viewpoints, tram rides, and authentic seafood.",
    num_days: 3,
    max_budget: 650,
    currency: "EUR",
    pace: "relaxed",
    interests: "seafood, history, viewpoints",
  },
  {
    label: "Kyoto Temples & Ramen",
    prompt:
      "Cultural trip to Kyoto visiting shrines, bamboo groves, tea houses, and great local ramen spots.",
    num_days: 4,
    max_budget: 900,
    currency: "USD",
    pace: "moderate",
    interests: "temples, ramen, gardens",
  },
];

export function TripPromptForm({ isLoading, onSubmit }: TripPromptFormProps) {
  const [prompt, setPrompt] = useState(EXAMPLE_TRIPS[0].prompt);
  const [numDays, setNumDays] = useState(EXAMPLE_TRIPS[0].num_days);
  const [maxBudget, setMaxBudget] = useState(EXAMPLE_TRIPS[0].max_budget);
  const [currency, setCurrency] = useState(EXAMPLE_TRIPS[0].currency);
  const [pace, setPace] = useState<Pace>(EXAMPLE_TRIPS[0].pace);
  const [startDate, setStartDate] = useState("");
  const [interestsInput, setInterestsInput] = useState(
    EXAMPLE_TRIPS[0].interests,
  );

  const handleSubmit: SubmitEventHandler<HTMLFormElement> = (event) => {
    event.preventDefault();
    const interests = interestsInput
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);

    onSubmit({
      prompt: prompt.trim(),
      num_days: numDays,
      max_budget: maxBudget,
      currency,
      pace,
      interests,
      start_date: startDate || undefined,
    });
  };

  const applyExample = (example: (typeof EXAMPLE_TRIPS)[number]) => {
    setPrompt(example.prompt);
    setNumDays(example.num_days);
    setMaxBudget(example.max_budget);
    setCurrency(example.currency);
    setPace(example.pace);
    setInterestsInput(example.interests);
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm space-y-5"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-slate-900">
          Describe Your Holiday
        </h2>
        <div className="flex flex-wrap gap-1.5">
          {EXAMPLE_TRIPS.map((example) => (
            <button
              key={example.label}
              type="button"
              onClick={() => applyExample(example)}
              className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100 transition"
            >
              {example.label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label
          htmlFor="trip-prompt"
          className="block text-sm font-medium text-slate-700 mb-1.5"
        >
          Holiday description
        </label>
        <textarea
          id="trip-prompt"
          rows={4}
          required
          minLength={3}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Where do you want to go, what kind of vibe are you looking for, and any must-sees?"
          className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label
            htmlFor="num-days"
            className="block text-sm font-medium text-slate-700 mb-1.5"
          >
            Days
          </label>
          <input
            id="num-days"
            type="number"
            min={1}
            max={14}
            value={numDays}
            onChange={(e) =>
              setNumDays(Math.max(1, Math.min(14, Number(e.target.value) || 1)))
            }
            className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          />
        </div>

        <div>
          <label
            htmlFor="pace"
            className="block text-sm font-medium text-slate-700 mb-1.5"
          >
            Pace
          </label>
          <select
            id="pace"
            value={pace}
            onChange={(e) => setPace(e.target.value as Pace)}
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          >
            <option value="relaxed">Relaxed (3–4 stops/day)</option>
            <option value="moderate">Moderate (4–6 stops/day)</option>
            <option value="packed">Packed (6–8 stops/day)</option>
          </select>
        </div>
      </div>

      <div>
        <label htmlFor="start-date" className="block text-sm font-medium text-slate-700 mb-1.5">
          First travel date <span className="font-normal text-slate-500">(optional, for opening-hour checks)</span>
        </label>
        <input
          id="start-date"
          type="date"
          value={startDate}
          onChange={(event) => setStartDate(event.target.value)}
          className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
        />
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2">
          <label
            htmlFor="max-budget"
            className="block text-sm font-medium text-slate-700 mb-1.5"
          >
            Max budget
          </label>
          <input
            id="max-budget"
            type="number"
            min={10}
            step="10"
            value={maxBudget}
            onChange={(e) =>
              setMaxBudget(Math.max(1, Number(e.target.value) || 1))
            }
            className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          />
        </div>

        <div>
          <label
            htmlFor="currency"
            className="block text-sm font-medium text-slate-700 mb-1.5"
          >
            Currency
          </label>
          <select
            id="currency"
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          >
            <option value="EUR">EUR</option>
            <option value="USD">USD</option>
            <option value="GBP">GBP</option>
            <option value="JPY">JPY</option>
          </select>
        </div>
      </div>

      <div>
        <label
          htmlFor="interests"
          className="block text-sm font-medium text-slate-700 mb-1.5"
        >
          Interests (comma-separated)
        </label>
        <input
          id="interests"
          type="text"
          value={interestsInput}
          onChange={(e) => setInterestsInput(e.target.value)}
          placeholder="e.g. museums, street food, architecture"
          className="w-full rounded-xl border border-slate-300 px-3.5 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
        />
      </div>

      <button
        type="submit"
        disabled={isLoading}
        className="w-full rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60 transition"
      >
        {isLoading ? "Agent researching & planning..." : "Generate Itinerary"}
      </button>
    </form>
  );
}

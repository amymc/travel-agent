import { useState } from "react";
import type { AgentStepTrace } from "../types/trip";

interface AgentTracePanelProps {
  trace: AgentStepTrace[];
}

export function AgentTracePanel({ trace }: AgentTracePanelProps) {
  const [expanded, setExpanded] = useState(true);

  if (trace.length === 0) {
    return null;
  }

  const totalToolCalls = trace.reduce((sum, step) => sum + step.tool_calls.length, 0);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex w-full items-center justify-between px-5 py-3.5 text-left hover:bg-slate-50 transition"
      >
        <div className="flex items-center gap-2.5">
          <span className="text-sm font-semibold text-slate-900">Agent Tool-Calling Trace</span>
          <span className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-medium text-indigo-700">
            {trace.length} {trace.length === 1 ? "step" : "steps"} · {totalToolCalls}{" "}
            {totalToolCalls === 1 ? "tool call" : "tool calls"}
          </span>
        </div>
        <span className="text-xs font-medium text-slate-500">
          {expanded ? "Hide" : "Show"}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-slate-100 divide-y divide-slate-100">
          {trace.map((step) => (
            <div key={step.step} className="px-5 py-3.5 space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-slate-700">Step {step.step}</span>
                <span className="font-mono text-slate-500">{step.model_used}</span>
              </div>

              {step.note && (
                <p className="text-xs text-slate-600 italic">{step.note}</p>
              )}

              {step.tool_calls.length > 0 && (
                <ul className="space-y-1.5">
                  {step.tool_calls.map((call, idx) => (
                    <li
                      key={`${step.step}-${call.name}-${idx}`}
                      className="rounded-lg bg-slate-50 border border-slate-200/70 px-3 py-2 text-xs"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-mono font-semibold text-indigo-700">
                          {call.name}()
                        </span>
                        <span className="text-slate-600">{call.result_summary}</span>
                      </div>
                      {call.name !== "submit_itinerary" &&
                        call.name !== "validate_draft_itinerary" && (
                          <p className="mt-1 font-mono text-[11px] text-slate-500 break-all">
                            args: {JSON.stringify(call.args)}
                          </p>
                        )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

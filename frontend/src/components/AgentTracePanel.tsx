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
        <span className="text-xs font-medium text-slate-500">{expanded ? "Hide" : "Show"}</span>
      </button>

      {expanded && (
        <div className="border-t border-slate-100 divide-y divide-slate-100">
          {trace.map((step) => (
            <div key={step.step} className="px-5 py-3.5 space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-slate-700">Step {step.step}</span>
                <span className="font-mono text-slate-500">{step.model_used}</span>
              </div>

              {step.note && <p className="text-xs text-slate-600 italic">{step.note}</p>}

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
                      <details className="mt-2">
                        <summary className="cursor-pointer select-none text-[11px] font-medium text-indigo-700">
                          Inspect arguments and full result
                        </summary>
                        <div className="mt-2 grid gap-2 lg:grid-cols-2">
                          <div>
                            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                              Arguments
                            </p>
                            <pre className="max-h-64 overflow-auto rounded-md bg-slate-900 p-2 text-[10px] text-slate-100">
                              {JSON.stringify(call.args, null, 2)}
                            </pre>
                          </div>
                          <div>
                            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                              Tool result
                            </p>
                            <pre className="max-h-64 overflow-auto rounded-md bg-slate-900 p-2 text-[10px] text-slate-100">
                              {JSON.stringify(call.result_payload ?? {}, null, 2)}
                            </pre>
                          </div>
                        </div>
                      </details>
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

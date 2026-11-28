from dataclasses import dataclass
import time

from google.genai import types

from app.agent.prompts import SYSTEM_PROMPT, build_trip_prompt
from app.agent.tools import (
    ToolExecutionContext,
    build_tool_declarations,
    execute_tool_call,
)
from app.domain.models import (
    AgentStepTrace,
    AgentToolCall,
    ItineraryDraft,
    TripRequest,
)
from app.config import settings
from app.services.llm_client import GeminiItineraryClient, LLMGenerationError, LLMTimeoutError


@dataclass
class AgentRunResult:
    """Output of a complete multi-step agent loop execution."""

    draft: ItineraryDraft
    model_used: str
    trace: list[AgentStepTrace]


class TravelAgentLoop:
    """
    Iterative tool-calling agent loop (Plan -> Call Tools -> Validate -> Repair -> Submit).

    Disables Gemini's automatic function calling so we explicitly control step limits,
    record an observability trace, and enforce deterministic validation before finalizing.
    """

    def __init__(
        self,
        llm_client: GeminiItineraryClient | None = None,
        max_steps: int = 7,
        max_repairs: int = 2,
    ) -> None:
        self.llm_client = llm_client or GeminiItineraryClient()
        self.max_steps = max_steps
        self.max_repairs = max_repairs

    def run(self, request: TripRequest) -> AgentRunResult:
        deadline = time.monotonic() + settings.agent_run_timeout_seconds

        def ensure_time_remaining() -> None:
            if time.monotonic() >= deadline:
                raise LLMTimeoutError(
                    f"Travel planning exceeded {settings.agent_run_timeout_seconds} seconds. "
                    "Please try again."
                )

        ctx = ToolExecutionContext(request=request, max_repairs=self.max_repairs)
        declarations = build_tool_declarations()
        tool_config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.3,
        )

        contents: list[types.Content] = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=build_trip_prompt(request))],
            )
        ]

        trace: list[AgentStepTrace] = []
        last_model_used = self.llm_client.model
        nudged_for_submission = False

        for step in range(1, self.max_steps + 1):
            ensure_time_remaining()
            response, model_used = self.llm_client.call_with_fallback(
                contents=contents,
                config=tool_config,
            )
            ensure_time_remaining()
            last_model_used = model_used

            candidates = getattr(response, "candidates", None) or []
            if candidates and getattr(candidates[0], "content", None) is not None:
                contents.append(candidates[0].content)

            function_calls = getattr(response, "function_calls", None) or []

            if function_calls:
                step_calls: list[AgentToolCall] = []
                response_parts: list[types.Part] = []

                for call in function_calls:
                    ensure_time_remaining()
                    call_name = call.name or ""
                    call_args = dict(call.args) if call.args else {}
                    tool_result, summary = execute_tool_call(call_name, call_args, ctx)
                    ensure_time_remaining()

                    step_calls.append(
                        AgentToolCall(
                            name=call_name,
                            args=call_args,
                            result_summary=summary,
                        )
                    )
                    response_parts.append(
                        types.Part.from_function_response(
                            name=call_name,
                            response=tool_result,
                        )
                    )

                trace.append(
                    AgentStepTrace(
                        step=step,
                        model_used=model_used,
                        tool_calls=step_calls,
                    )
                )

                if ctx.submitted_draft is not None:
                    return AgentRunResult(
                        draft=ctx.submitted_draft,
                        model_used=model_used,
                        trace=trace,
                    )

                contents.append(types.Content(role="user", parts=response_parts))
                continue

            # Model responded without calling any tool.
            if ctx.last_draft is not None:
                trace.append(
                    AgentStepTrace(
                        step=step,
                        model_used=model_used,
                        note="Finalized using last validated draft after text response.",
                    )
                )
                return AgentRunResult(
                    draft=ctx.last_draft,
                    model_used=model_used,
                    trace=trace,
                )

            if not nudged_for_submission and step < self.max_steps:
                nudged_for_submission = True
                trace.append(
                    AgentStepTrace(
                        step=step,
                        model_used=model_used,
                        note="Model replied with text; nudged to call submit_itinerary.",
                    )
                )
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(
                                text="Please finalize by calling submit_itinerary with your complete ItineraryDraft."
                            )
                        ],
                    )
                )
                continue

            break

        if ctx.last_draft is not None:
            trace.append(
                AgentStepTrace(
                    step=len(trace) + 1,
                    model_used=last_model_used,
                    note="Reached max_steps; returning last validated draft.",
                )
            )
            return AgentRunResult(
                draft=ctx.last_draft,
                model_used=last_model_used,
                trace=trace,
            )

        # Safety net: fall back to a structured-output call if tool calling didn't yield a draft.
        ensure_time_remaining()
        draft, fallback_model = self.llm_client.generate_itinerary(request)
        ensure_time_remaining()
        trace.append(
            AgentStepTrace(
                step=len(trace) + 1,
                model_used=fallback_model,
                note="Fallback structured-output generation after max_steps.",
            )
        )
        if draft is None:
            raise LLMGenerationError("Agent loop failed to produce an itinerary.")
        return AgentRunResult(draft=draft, model_used=fallback_model, trace=trace)

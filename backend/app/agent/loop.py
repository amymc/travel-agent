from dataclasses import dataclass
import time
from collections.abc import Callable
from typing import Protocol, cast

from google.genai import types

from app.agent.prompts import SYSTEM_PROMPT, build_revision_prompt, build_trip_prompt
from app.agent.tools import (
    ToolExecutionContext,
    build_tool_declarations,
    execute_tool_call,
)
from app.domain.models import (
    AgentStepTrace,
    AgentToolCall,
    ItineraryDraft,
    JsonValue,
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


class AgentLLMClient(Protocol):
    """Interface used by the loop, also implemented by deterministic test clients."""

    model: str

    def call_with_fallback(
        self,
        *,
        contents: list[types.Content],
        config: types.GenerateContentConfig,
    ) -> tuple[object, str]: ...

    def generate_itinerary(self, request: TripRequest) -> tuple[ItineraryDraft, str]: ...


class TravelAgentLoop:
    """
    Iterative tool-calling agent loop (Plan -> Call Tools -> Validate -> Repair -> Submit).

    Disables Gemini's automatic function calling so we explicitly control step limits,
    record an observability trace, and enforce deterministic validation before finalizing.
    """

    def __init__(
        self,
        llm_client: AgentLLMClient | None = None,
        max_steps: int = 7,
        max_repairs: int = 2,
    ) -> None:
        self.llm_client = llm_client or GeminiItineraryClient()
        self.max_steps = max_steps
        self.max_repairs = max_repairs

    def run(
        self,
        request: TripRequest,
        *,
        existing_draft: ItineraryDraft | None = None,
        revision_instruction: str | None = None,
        event_callback: Callable[[dict[str, JsonValue]], None] | None = None,
    ) -> AgentRunResult:
        if (existing_draft is None) != (revision_instruction is None):
            raise ValueError("Existing itinerary and revision instruction must be supplied together.")
        deadline = time.monotonic() + settings.agent_run_timeout_seconds

        def ensure_time_remaining() -> None:
            if time.monotonic() >= deadline:
                raise LLMTimeoutError(
                    f"Travel planning exceeded {settings.agent_run_timeout_seconds} seconds. "
                    "Please try again."
                )

        ctx = ToolExecutionContext(
            request=request,
            max_repairs=self.max_repairs,
            revision_instruction=revision_instruction,
        )
        declarations = build_tool_declarations()
        tool_config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.3,
        )

        initial_prompt = build_trip_prompt(request)
        if existing_draft is not None and revision_instruction is not None:
            initial_prompt += "\n\n" + build_revision_prompt(
                request,
                existing_draft.model_dump_json(indent=2),
                revision_instruction,
            )
        contents: list[types.Content] = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=initial_prompt)],
            )
        ]

        trace: list[AgentStepTrace] = []
        last_model_used = self.llm_client.model
        nudged_for_submission = False

        for step in range(1, self.max_steps + 1):
            ensure_time_remaining()
            if event_callback:
                event_callback(
                    {
                        "type": "status",
                        "status": "model_request",
                        "message": f"Working on step {step}",
                        "step": step,
                    }
                )
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
                    if event_callback:
                        event_callback(
                            {
                                "type": "tool_call_started",
                                "step": step,
                                "name": call_name,
                                "args": call_args,
                            }
                        )
                    tool_result, summary = execute_tool_call(call_name, call_args, ctx)
                    ensure_time_remaining()
                    result_payload = cast(dict[str, JsonValue], tool_result)

                    step_calls.append(
                        AgentToolCall(
                            name=call_name,
                            args=call_args,
                            result_summary=summary,
                            result_payload=result_payload,
                        )
                    )
                    if event_callback:
                        event_callback(
                            {
                                "type": "tool_call_completed",
                                "step": step,
                                "name": call_name,
                                "args": call_args,
                                "result_summary": summary,
                                "result": result_payload,
                            }
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
                if event_callback:
                    serialized_calls = [
                        cast(dict[str, JsonValue], call.model_dump(mode="json"))
                        for call in step_calls
                    ]
                    event_callback(
                        {
                            "type": "step_completed",
                            "step": step,
                            "model_used": model_used,
                            "tool_calls": cast(JsonValue, serialized_calls),
                        }
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
            if event_callback:
                event_callback(
                    {
                        "type": "status",
                        "status": "model_response",
                        "message": f"Received response for step {step}",
                        "step": step,
                        "model_used": model_used,
                    }
                )
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

        if existing_draft is not None:
            raise LLMGenerationError(
                "The revision agent did not submit a revised itinerary. Please try the revision again."
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

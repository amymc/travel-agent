import time
from collections.abc import Callable
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.agent.prompts import SYSTEM_PROMPT, build_trip_prompt
from app.config import settings
from app.domain.models import ItineraryDraft, TripRequest


class LLMConfigurationError(RuntimeError):
    """Raised when the Gemini API key is missing or invalid."""


class LLMUnavailableError(RuntimeError):
    """Raised when all configured Gemini models are temporarily overloaded or rate-limited."""


class LLMGenerationError(RuntimeError):
    """Raised when the LLM fails to return a valid structured itinerary."""


class LLMTimeoutError(LLMGenerationError):
    """Raised when a Gemini request or complete agent run exceeds its time limit."""


RETRYABLE_STATUS_CODES = {429, 503}
FALLBACK_STATUS_CODES = {404, 429, 503, 504}


def _extract_error_code(exc: Exception) -> int | None:
    if isinstance(exc, genai_errors.APIError):
        return exc.code
    code = getattr(exc, "code", None)
    return code if isinstance(code, int) else None


def _is_retryable_capacity_error(exc: Exception) -> bool:
    code = _extract_error_code(exc)
    if code in RETRYABLE_STATUS_CODES:
        return True
    msg = str(exc)
    return "503" in msg or "UNAVAILABLE" in msg or "429" in msg or "RESOURCE_EXHAUSTED" in msg


def _should_try_fallback(exc: Exception) -> bool:
    code = _extract_error_code(exc)
    if code in FALLBACK_STATUS_CODES:
        return True
    return _is_retryable_capacity_error(exc)


def _is_timeout_error(exc: Exception) -> bool:
    return (
        isinstance(exc, TimeoutError)
        or "timeout" in type(exc).__name__.casefold()
        or "timed out" in str(exc).casefold()
    )


class GeminiItineraryClient:
    """Thin wrapper around the google-genai SDK with retry and model fallback."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        fallback_models: list[str] | None = None,
        client_factory: Callable[[str], genai.Client] | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = (api_key if api_key is not None else settings.gemini_api_key).strip()
        self.model = (model if model is not None else settings.gemini_model).strip()
        self.fallback_models = (
            fallback_models if fallback_models is not None else settings.fallback_model_list
        )
        self._client_factory = client_factory or (
            lambda key: genai.Client(
                api_key=key,
                http_options=types.HttpOptions(timeout=settings.gemini_request_timeout_ms),
            )
        )
        self._sleep = sleep_fn

    def _ensure_configured(self) -> genai.Client:
        if not self.api_key or self.api_key == "your_google_ai_studio_api_key_here":
            raise LLMConfigurationError(
                "GEMINI_API_KEY is not configured. Copy .env.example to .env and add your "
                "free Google AI Studio API key."
            )
        return self._client_factory(self.api_key)

    def _candidate_models(self) -> list[str]:
        seen: set[str] = set()
        models: list[str] = []
        for name in [self.model, *self.fallback_models]:
            cleaned = name.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                models.append(cleaned)
        return models

    def call_with_fallback(
        self,
        *,
        contents: Any,
        config: types.GenerateContentConfig,
    ) -> tuple[Any, str]:
        """Execute generate_content with primary retry and automatic model fallback."""
        client = self._ensure_configured()
        models = self._candidate_models()
        last_error: Exception | None = None
        models_tried: list[str] = []
        deadline_exceeded_seen = False

        for idx, model_name in enumerate(models):
            # A server deadline usually indicates that this request/model is too slow.
            # Try one alternate model, then return promptly instead of spending the
            # entire agent-run budget timing out every configured model.
            if deadline_exceeded_seen and idx > 1:
                break
            models_tried.append(model_name)
            is_primary = idx == 0
            max_attempts = 2 if is_primary else 1
            thinking_level = (
                types.ThinkingLevel.MINIMAL
                if "flash-lite" in model_name
                else types.ThinkingLevel.LOW
            )
            # The SDK's Pydantic `model_copy()` annotation currently triggers a
            # self-referential type error in Pylance. Rebuild through the public
            # constructor after replacing only the model-specific thinking setting.
            config_data = config.model_dump(exclude_none=True)
            config_data["thinking_config"] = types.ThinkingConfig(
                thinking_level=thinking_level
            )
            model_config = types.GenerateContentConfig(**config_data)

            for attempt in range(max_attempts):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=model_config,
                    )
                    return response, model_name
                except Exception as exc:
                    last_error = exc
                    if _extract_error_code(exc) == 504:
                        deadline_exceeded_seen = True
                    if _is_timeout_error(exc):
                        timeout_seconds = settings.gemini_request_timeout_ms / 1000
                        raise LLMTimeoutError(
                            f"Gemini did not respond within {timeout_seconds:g} seconds. "
                            "Please try again."
                        ) from exc
                    if _is_retryable_capacity_error(exc) and attempt + 1 < max_attempts:
                        self._sleep(1.0)
                        continue
                    if _should_try_fallback(exc):
                        break
                    raise LLMGenerationError(f"Gemini request failed: {exc}") from exc

        tried = ", ".join(models_tried)
        raise LLMUnavailableError(
            f"All configured Gemini models ({tried}) are currently overloaded, rate-limited, or "
            f"timing out. Please try again shortly. Last error: {last_error}"
        ) from last_error

    def generate_itinerary(self, request: TripRequest) -> tuple[ItineraryDraft, str]:
        """Single-shot structured itinerary generation (used as fallback or direct mode)."""
        prompt = build_trip_prompt(request)
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=ItineraryDraft,
            temperature=0.4,
        )
        response, model_name = self.call_with_fallback(contents=prompt, config=config)

        if isinstance(response.parsed, ItineraryDraft):
            return response.parsed, model_name

        if response.text:
            try:
                return ItineraryDraft.model_validate_json(response.text), model_name
            except Exception as exc:
                raise LLMGenerationError(
                    f"Gemini returned JSON that did not match ItineraryDraft: {exc}"
                ) from exc

        raise LLMGenerationError("Gemini returned an empty response.")

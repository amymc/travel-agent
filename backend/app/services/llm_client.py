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


RETRYABLE_STATUS_CODES = {429, 503}
FALLBACK_STATUS_CODES = {404, 429, 503}


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
        self._client_factory = client_factory or (lambda key: genai.Client(api_key=key))
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

        for idx, model_name in enumerate(models):
            is_primary = idx == 0
            max_attempts = 2 if is_primary else 1

            for attempt in range(max_attempts):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=config,
                    )
                    return response, model_name
                except Exception as exc:
                    last_error = exc
                    if _is_retryable_capacity_error(exc) and attempt + 1 < max_attempts:
                        self._sleep(1.0)
                        continue
                    if _should_try_fallback(exc):
                        break
                    raise LLMGenerationError(f"Gemini request failed: {exc}") from exc

        tried = ", ".join(models)
        raise LLMUnavailableError(
            f"All configured Gemini models ({tried}) are currently experiencing high demand or "
            f"rate limits. Please try again in a few seconds. Last error: {last_error}"
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

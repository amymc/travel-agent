from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env files."""

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_fallback_models: str = "gemini-3.6-flash,gemini-3.5-flash-lite"
    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=(ROOT_ENV, BACKEND_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def fallback_model_list(self) -> list[str]:
        return [m.strip() for m in self.gemini_fallback_models.split(",") if m.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()

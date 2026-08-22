from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed configuration shared across project milestones."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: SecretStr = SecretStr("")
    tavily_api_key: SecretStr = SecretStr("")
    agent_model: str = "gpt-4.1-mini"
    synthesis_model: str = "gpt-4.1"
    search_results_per_agent: int = Field(default=5, ge=1, le=20)
    agent_timeout_seconds: float = Field(default=20.0, gt=0)
    agent_max_tokens: int = Field(default=1200, ge=100)
    recent_news_days: int = Field(default=30, ge=1)

    confidence_weight_agreement: float = Field(default=0.35, ge=0, le=1)
    confidence_weight_source_quality: float = Field(default=0.25, ge=0, le=1)
    confidence_weight_independence: float = Field(default=0.20, ge=0, le=1)
    confidence_weight_recency: float = Field(default=0.10, ge=0, le=1)
    confidence_weight_contradiction: float = Field(default=0.10, ge=0, le=1)
    confidence_threshold_high: float = Field(default=0.75, ge=0, le=1)
    confidence_threshold_medium: float = Field(default=0.50, ge=0, le=1)

    database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/research"
    redis_url: str = "redis://redis:6379/0"
    redis_cache_ttl_seconds: int = Field(default=3600, ge=1)
    rate_limit_jobs: int = Field(default=10, ge=1)
    rate_limit_window_seconds: int = Field(default=3600, ge=1)
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("")
    session_ttl_seconds: int = Field(default=86400, ge=300)
    app_env: Literal["development", "test", "production"] = "development"
    allow_dev_auth: bool = True

    @model_validator(mode="after")
    def validate_confidence_thresholds(self) -> "Settings":
        if self.confidence_threshold_high < self.confidence_threshold_medium:
            raise ValueError("High confidence threshold must be at least the medium threshold")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

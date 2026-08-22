from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
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

    confidence_weight_agreement: float = 0.35
    confidence_weight_source_quality: float = 0.25
    confidence_weight_independence: float = 0.20
    confidence_weight_recency: float = 0.10
    confidence_weight_contradiction: float = 0.10
    confidence_threshold_high: float = 0.75
    confidence_threshold_medium: float = 0.50

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


@lru_cache
def get_settings() -> Settings:
    return Settings()

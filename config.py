"""RetroTube application configuration using Pydantic Settings."""
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    YT_API_KEY: str = Field(..., description="YouTube Data API v3 key")
    SECRET_KEY: str = Field(
        ..., min_length=32, description="Secret key for signing sessions (min 32 chars)"
    )
    DATABASE_URL: str = Field(
        "postgresql+asyncpg://retro:retro@localhost:5432/retrotube",
        description="Async PostgreSQL connection string",
    )
    REDIS_URL: str = Field(
        "redis://localhost:6379/0",
        description="Redis connection string",
    )
    FEATURED_REGION: str = Field(
        "US", min_length=2, max_length=2, description="2-letter ISO country code"
    )
    ENABLE_RELATED: bool = Field(
        False, description="Enable related video lookups (costs 100 quota units)"
    )
    HTTPS_ONLY: bool = Field(
        False, description="Enforce secure cookies on HTTPS"
    )
    YT_DAILY_BUDGET: int = Field(
        9000, ge=100, le=100000, description="Daily YouTube quota budget (Pacific Time)"
    )

    @field_validator("YT_API_KEY")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("YT_API_KEY must not be empty")
        return v


def get_settings() -> Settings:
    return Settings()

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).with_name(".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str
    jwt_secret: str | None = None
    jwt_expiry_minutes: int = Field(default=60, ge=5, le=43_200)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    auth_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    login_rate_limit: int = Field(default=10, ge=1, le=10_000)
    register_rate_limit: int = Field(default=5, ge=1, le=10_000)
    auth_rate_limit_max_keys: int = Field(default=10_000, ge=100, le=1_000_000)

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        secret = self.jwt_secret.strip() if self.jwt_secret else ""
        placeholder = (
            not secret
            or len(secret) < 32
            or "replace-with" in secret.casefold()
            or "change-me" in secret.casefold()
            or secret == "development-only-secret-change-me-now"
        )
        if placeholder:
            raise ValueError(
                "JWT_SECRET must be an explicit, non-placeholder value of at least 32 characters"
            )
        self.jwt_secret = secret
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

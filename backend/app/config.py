"""Application settings.

Every secret is read from the environment (or a local, git-ignored `.env`).
Nothing sensitive is ever hard-coded here — see `.env.example` for the keys.
"""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Quik"
    environment: Literal["dev", "staging", "prod"] = "dev"
    public_base_url: str = "http://localhost:8000"
    cors_origins: str = "*"

    # Database — SQLite for local dev, Postgres URL in prod.
    database_url: str = "sqlite:///./quik.db"

    # Auth
    jwt_secret: str = "dev-only-change-me"
    jwt_expiry_minutes: int = 60 * 24 * 7

    # Providers: "mock" works offline; switch to real ones when keys exist.
    flight_provider: Literal["mock", "duffel"] = "mock"
    hotel_provider: Literal["mock"] = "mock"
    payment_provider: Literal["mock", "paystack"] = "mock"

    duffel_api_key: str | None = None
    duffel_base_url: str = "https://api.duffel.com"
    duffel_webhook_secret: str | None = None

    paystack_secret_key: str | None = None
    paystack_base_url: str = "https://api.paystack.co"

    # Quik's margin on top of the airline fare (the main revenue line).
    service_fee_flat_ngn: int = 3_500
    service_fee_percent: float = 1.5

    # Price watch
    price_watch_interval_seconds: int = 60 * 30
    price_drop_threshold_percent: float = 3.0

    # Email — if SMTP isn't configured, mail is written to ./outbox for dev.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    mail_from: str = "Quik <tickets@quik.local>"

    # Optional LLM for the voice/chat assistant. Without it, a rule-based parser runs.
    anthropic_api_key: str | None = None
    assistant_model: str = "claude-sonnet-5-5"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.environment != "dev" and s.jwt_secret == "dev-only-change-me":
        raise RuntimeError("Set JWT_SECRET before running outside dev")
    return s

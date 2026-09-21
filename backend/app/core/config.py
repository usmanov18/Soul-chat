"""Central application configuration.

Everything the platform needs to know at runtime lives here and can be
overridden through environment variables (or a local ``.env`` file), which is
what makes the same container image usable in dev, staging and production.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["dev", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", env_nested_delimiter="__"
    )

    # ------------------------------------------------------------------ app
    app_name: str = "SoulChat AI"
    app_version: str = "1.0.0"
    environment: Environment = "dev"
    debug: bool = True
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    secret_key: str = "change-me-in-production-please-use-32-bytes"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60
    refresh_token_ttl_days: int = 30

    # ------------------------------------------------------------- database
    database_url: str = "sqlite+aiosqlite:///./data/soulchat.db"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ---------------------------------------------------------------- redis
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True

    # --------------------------------------------------------------- celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # -------------------------------------------------------------- telegram
    bot_token: str = ""
    bot_webhook_url: str = ""
    bot_webhook_secret: str = ""
    bot_use_polling: bool = True
    forum_chat_id: int = 0
    forum_chat_username: str = ""
    channel_id: int = 0
    channel_username: str = ""
    bot_invite_base: str = "https://t.me"
    telegram_api_retries: int = 3

    # ---------------------------------------------------- subscription gate
    subscription_required: bool = True
    subscription_cache_ttl: int = 120

    # --------------------------------------------------------- topic codes
    # Code schemes are DB driven (CodePrefix), these are only the defaults that
    # are seeded on first boot.
    default_code_scheme: Literal["sequential", "gender", "random"] = "gender"
    male_prefix_letters: str = "ABCDEFGHIJKLM"
    female_prefix_letters: str = "NOPQRSTUVWXYZ"
    code_zero_pad: int = 4
    code_separator: str = "-"
    code_emoji: str = ""
    code_prefix_length: int = 1

    # --------------------------------------------------------- topic policy
    topic_icon_color: int = 0x6FB9F0
    max_participants: int = 2
    delete_pending_hours: int = 96
    close_code_ttl_minutes: int = 15
    close_code_length: int = 6
    invite_ttl_hours: int = 48
    max_topics_per_user: int = 3
    reactions_enabled: bool = True
    forward_enabled: bool = False
    copy_enabled: bool = False

    # ------------------------------------------------------------- security
    rate_limit_per_minute: int = 20
    rate_limit_burst: int = 5
    flood_threshold: int = 12
    flood_window_seconds: int = 30
    captcha_after_violations: int = 3
    max_warns: int = 3
    ai_risk_block_threshold: float = 0.85
    ai_risk_review_threshold: float = 0.55

    # ------------------------------------------------------------------- ai
    ai_provider: Literal["builtin", "openai"] = "builtin"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # ------------------------------------------------------------- archiving
    archive_dir: str = "./data/archives"
    media_dir: str = "./data/media"
    archive_formats: list[str] = Field(default_factory=lambda: ["json", "html", "txt", "pdf"])
    object_storage_backend: Literal["local", "s3", "gdrive"] = "local"

    # --------------------------------------------------------------- backup
    backup_enabled: bool = True
    backup_target: Literal["local", "s3", "gdrive"] = "local"
    backup_dir: str = "./data/backups"

    # ----------------------------------------------------------- monitoring
    sentry_dsn: str = ""
    metrics_enabled: bool = True

    # ------------------------------------------------------------- scheduler
    scheduler_tick_seconds: int = 60

    @field_validator("cors_origins", "archive_formats", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

"""Configuration management for Food Memory Bot."""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    google_places_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_PLACES_API_KEY", ""))

    allowed_chat_ids: list[int] = field(default_factory=list)
    default_location_bias: str = field(default_factory=lambda: os.getenv("DEFAULT_LOCATION_BIAS", "Orange County, CA"))
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "foodmemory.db"))

    def __post_init__(self):
        # Parse allowed chat IDs from comma-separated string
        chat_ids_str = os.getenv("ALLOWED_CHAT_IDS", "")
        if chat_ids_str:
            self.allowed_chat_ids = [int(id.strip()) for id in chat_ids_str.split(",") if id.strip()]

        # Validate required fields
        if not self.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        if not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")
        if not self.google_places_api_key:
            raise ValueError("GOOGLE_PLACES_API_KEY is required")

    def is_chat_allowed(self, chat_id: int) -> bool:
        """Check if a chat ID is allowed. Returns True if no restrictions set."""
        if not self.allowed_chat_ids:
            return True
        return chat_id in self.allowed_chat_ids


def get_config() -> Config:
    """Get application configuration."""
    return Config()

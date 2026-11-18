"""Load environment-specific application settings."""
from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Hold deployment settings without embedded credentials."""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    MONGODB_URI: str
    MONGODB_DB: str
    JWT_SECRET: str

    CORS_ORIGINS: str = ""
    SEED_ON_STARTUP: bool = False
    ADMIN_INITIAL_PASSWORD: str = ""
    DEMO_INITIAL_PASSWORD: str = ""

    @model_validator(mode="after")
    def validate_secrets(self) -> "Settings":
        """Reject weak or missing deployment credentials."""
        if len(self.JWT_SECRET) < 32 or self.JWT_SECRET.lower() in {"dev-secret-change-in-production", "change-me"}:
            raise ValueError("JWT_SECRET must be a unique secret of at least 32 characters")
        if self.JWT_SECRET == "local-example-secret-please-replace-32-characters":
            raise ValueError("JWT_SECRET must not be the public local example; generate a unique secret")
        if self.SEED_ON_STARTUP and (min(len(self.ADMIN_INITIAL_PASSWORD), len(self.DEMO_INITIAL_PASSWORD)) < 12 or max(len(self.ADMIN_INITIAL_PASSWORD.encode()), len(self.DEMO_INITIAL_PASSWORD.encode())) > 72):
            raise ValueError("Seed passwords must be 12 characters or more and at most 72 bytes")
        return self

    @property
    def origins(self) -> list[str]:
        """Return explicit CORS origins."""
        return [value.strip() for value in self.CORS_ORIGINS.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return cached process configuration."""
    return Settings()

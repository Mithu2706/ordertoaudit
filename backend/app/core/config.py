"""Application settings, loaded from environment variables / .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://ota:ota_password@localhost:5432/order_to_audit"
    # No default secret: the app must be configured explicitly outside tests.
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 480
    bcrypt_rounds: int = 12  # tests lower this for speed
    cors_origins: str = "http://localhost:5173"
    # Browser sessions use an httpOnly cookie. "auto" marks it Secure when the request arrived over
    # HTTPS (directly or via a trusted proxy's X-Forwarded-Proto); "true"/"false" force it.
    cookie_secure: str = "auto"
    # "production" turns on start-up safety checks (strong JWT secret).
    app_env: str = "development"
    # Directory with the built frontend (index.html + assets). When set, the API also serves the
    # single-page app, so production needs one container and no CORS. Empty in development (Vite).
    static_dir: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def check_production_settings(settings: Settings) -> None:
    """Refuse to start in production with an unsafe configuration."""
    if settings.app_env != "production":
        return
    secret = settings.jwt_secret_key
    if len(secret) < 32 or "change-me" in secret:
        raise RuntimeError("JWT_SECRET_KEY must be set to a random value of at least 32 characters in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()

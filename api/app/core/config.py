from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = API_ROOT.parent
STORAGE_ROOT = PROJECT_ROOT / "storage"


class Settings(BaseSettings):
    app_name: str = "Sistema de Trazabilidad Documental"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_name: str = "sistema_trazabilidad"
    db_user: str = "root"
    db_password: str = ""

    jwt_secret_key: str = "replace-with-a-long-random-secret"
    jwt_algorithm: str = "HS256"
    rate_limit_login_requests_per_minute: int = Field(default=120, ge=1, le=100000)
    rate_limit_identifier_requests_per_minute: int = Field(default=10, ge=1, le=100000)
    rate_limit_failure_window_seconds: int = Field(default=600, ge=1, le=1200)
    rate_limit_challenge_failures: int = Field(default=5, ge=1, le=100000)
    rate_limit_argon2_per_minute: int = Field(default=60, ge=1, le=100000)
    rate_limit_argon2_concurrency: int = Field(default=2, ge=1, le=32)
    turnstile_mode: Literal["disabled", "test", "enabled"] = "disabled"
    turnstile_secret_key: SecretStr = Field(default=SecretStr(""), repr=False)
    # Comma-separated EXACT frontend hostnames; never request/proxy-derived.
    turnstile_expected_hostnames: str = ""
    turnstile_verify_timeout_seconds: float = Field(default=5, ge=0.1, le=10)
    turnstile_verify_global_per_minute: int = Field(default=60, ge=1, le=100000)
    turnstile_verify_concurrency: int = Field(default=4, ge=1, le=32)
    # 6C settings may tighten, never silently exceed the agreed safety ceilings.
    reset_request_per_hour: int = Field(default=3, ge=1, le=3)
    reset_request_global_per_minute: int = Field(default=20, ge=1, le=20)
    access_request_per_day: int = Field(default=2, ge=1, le=2)
    access_request_global_per_minute: int = Field(default=10, ge=1, le=10)
    action_confirm_per_minute: int = Field(default=5, ge=1, le=5)
    action_confirm_global_per_minute: int = Field(default=30, ge=1, le=30)
    action_hash_per_minute: int = Field(default=5, ge=1, le=5)
    smtp_host: str = ''
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ''
    smtp_password: SecretStr = SecretStr('')
    smtp_security: str = 'starttls'
    smtp_from_address: str = ''
    smtp_from_name: str = 'Sistema de Trazabilidad'
    smtp_timeout_seconds: int = Field(default=5, ge=1, le=10)
    public_frontend_url: str = ''
    password_reset_ttl_seconds: int = Field(default=1800, ge=60, le=1800)
    storage_path: Path = STORAGE_ROOT

    @field_validator("storage_path", mode="before")
    @classmethod
    def canonical_storage(cls, value: object) -> Path:
        # The application always uses the existing project storage directory.
        # Tests can still inject a temporary base_path into StorageService.
        return STORAGE_ROOT

    model_config = SettingsConfigDict(
        env_file=API_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        username = quote_plus(self.db_user)
        password = quote_plus(self.db_password)
        database = quote_plus(self.db_name)
        return (
            f"mysql+pymysql://{username}:{password}@{self.db_host}:{self.db_port}/"
            f"{database}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

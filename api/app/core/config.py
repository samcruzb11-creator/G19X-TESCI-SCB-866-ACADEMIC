from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    storage_path: str = "storage"

    model_config = SettingsConfigDict(
        env_file=".env",
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

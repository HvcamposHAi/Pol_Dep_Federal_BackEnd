"""Configuração da aplicação via pydantic-settings (lê o arquivo .env)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Variáveis de ambiente. Nomes documentados em .env.example."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Banco (Supabase / PostgreSQL) — scheme precisa ser postgresql+asyncpg://
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"

    # Apollo.io
    apollo_api_key: str = ""
    apollo_base_url: str = "https://api.apollo.io/v1"
    apollo_rate_limit: int = 46  # req/min
    apollo_min_interval_ms: int = 1300

    # ViaCEP
    viacep_base_url: str = "https://viacep.com.br/ws"
    viacep_rate_limit: int = 120  # req/min

    # HTTP
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 4

    # Enriquecimento
    enrich_checkpoint_every: int = 25
    enrich_batch_size: int = 500
    default_phone_country: str = "BR"

    # App
    app_env: str = "dev"
    log_level: str = "INFO"
    max_upload_mb: int = 50

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Singleton de configuração (cacheado) usado por DI e CLI."""
    return Settings()

"""Configuração da aplicação via pydantic-settings (lê o arquivo .env)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core import runtime_config

# Valor de exemplo do .env.example — tratado como "não configurado".
APOLLO_KEY_PLACEHOLDER = "cole_sua_chave_aqui"


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

    # Google Maps Platform (Places + Geocoding)
    google_maps_api_key: str = ""
    google_maps_base_url: str = "https://maps.googleapis.com/maps/api"
    google_maps_rate_limit: int = 600  # req/min (~10 QPS, folga sobre o limite da API)
    # Chamada extra de Place Details no match por telefone (traz address_components).
    google_maps_place_details: bool = True

    # HTTP
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 4

    # Enriquecimento
    enrich_checkpoint_every: int = 25
    enrich_batch_size: int = 500  # tamanho do lote no import (upsert)
    enrich_run_batch_size: int = 50  # leads processados/commit por lote no enriquecimento
    default_phone_country: str = "BR"

    # App
    app_env: str = "dev"
    log_level: str = "INFO"
    max_upload_mb: int = 50

    # CORS — origens permitidas quando front e back rodam em domínios diferentes.
    # Em dev (proxy same-origin do Vite) é inócuo. Aceita lista separada por vírgula.
    cors_origins: str = "http://localhost:5173"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Singleton de configuração (cacheado) usado por DI e CLI.

    Aplica o override de runtime (definido na tela de Configurações) por cima do
    ``.env``. Após mudar o override, chame ``get_settings.cache_clear()``.
    """
    settings = Settings()
    apollo_override = runtime_config.get_apollo_key()
    if apollo_override:
        settings.apollo_api_key = apollo_override
    google_override = runtime_config.get_google_maps_key()
    if google_override:
        settings.google_maps_api_key = google_override
    # Normaliza placeholder/vazio -> "" (= não configurado) em todo o sistema.
    if settings.apollo_api_key.strip() in ("", APOLLO_KEY_PLACEHOLDER):
        settings.apollo_api_key = ""
    if settings.google_maps_api_key.strip() in ("", APOLLO_KEY_PLACEHOLDER):
        settings.google_maps_api_key = ""
    return settings

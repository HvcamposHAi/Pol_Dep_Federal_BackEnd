"""Configuração de integrações pela UI (ex.: chave do Apollo).

A chave é persistida no servidor (runtime_config) e NUNCA devolvida ao cliente —
apenas o status e um valor mascarado. Tem precedência sobre o ``.env``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import APOLLO_KEY_PLACEHOLDER, Settings, get_settings
from app.core import runtime_config
from app.db.session import get_db
from app.repositories import enrichment_repo

router = APIRouter(prefix="/config", tags=["config"])


def _mask(key: str) -> str:
    key = key.strip()
    if len(key) <= 4:
        return "••••"
    return "••••" + key[-4:]


class ApolloKeyIn(BaseModel):
    api_key: str = Field(min_length=8, description="API key do Apollo.io")


class GoogleMapsKeyIn(BaseModel):
    api_key: str = Field(min_length=8, description="API key do Google Maps Platform")


class IntegrationsOut(BaseModel):
    apollo_configured: bool
    apollo_source: str  # "runtime" | "env" | "none"
    apollo_masked: str | None = None
    google_maps_configured: bool = False
    google_maps_source: str = "none"  # "runtime" | "env" | "none"
    google_maps_masked: str | None = None
    viacep_active: bool = True


class ApolloBudgetIn(BaseModel):
    budget: int = Field(ge=0, description="créditos do plano Apollo (0 = não informado)")


class ApolloUsageOut(BaseModel):
    """Estimativa de consumo (Apollo não expõe saldo via API)."""

    consumed: int  # ~créditos usados = total de matches do Apollo
    budget: int  # informado pelo operador (0 = desconhecido)
    remaining: int | None = None  # None quando budget desconhecido


def _provider_status(
    runtime_key: str | None, env_key: str, effective: str
) -> tuple[bool, str, str | None]:
    """(configured, source, masked) para um provider com override de runtime."""
    if runtime_key:
        source = "runtime"
    elif env_key and env_key != APOLLO_KEY_PLACEHOLDER:
        source = "env"
    else:
        source = "none"
    configured = source != "none"
    return configured, source, (_mask(effective) if configured else None)


def _status() -> IntegrationsOut:
    env = Settings()  # só .env, sem override
    eff = get_settings()

    apollo_configured, apollo_source, apollo_masked = _provider_status(
        runtime_config.get_apollo_key(),
        (env.apollo_api_key or "").strip(),
        (eff.apollo_api_key or "").strip(),
    )
    gmaps_configured, gmaps_source, gmaps_masked = _provider_status(
        runtime_config.get_google_maps_key(),
        (env.google_maps_api_key or "").strip(),
        (eff.google_maps_api_key or "").strip(),
    )
    return IntegrationsOut(
        apollo_configured=apollo_configured,
        apollo_source=apollo_source,
        apollo_masked=apollo_masked,
        google_maps_configured=gmaps_configured,
        google_maps_source=gmaps_source,
        google_maps_masked=gmaps_masked,
    )


@router.get("/integrations", response_model=IntegrationsOut)
async def get_integrations() -> IntegrationsOut:
    return _status()


@router.put("/integrations/apollo", response_model=IntegrationsOut)
async def set_apollo_key(body: ApolloKeyIn) -> IntegrationsOut:
    runtime_config.set_apollo_key(body.api_key)
    get_settings.cache_clear()  # próximas chamadas usam a nova chave
    return _status()


@router.delete("/integrations/apollo", response_model=IntegrationsOut)
async def clear_apollo_key() -> IntegrationsOut:
    runtime_config.clear_apollo_key()
    get_settings.cache_clear()
    return _status()


@router.put("/integrations/google-maps", response_model=IntegrationsOut)
async def set_google_maps_key(body: GoogleMapsKeyIn) -> IntegrationsOut:
    runtime_config.set_google_maps_key(body.api_key)
    get_settings.cache_clear()  # próximas chamadas usam a nova chave
    return _status()


@router.delete("/integrations/google-maps", response_model=IntegrationsOut)
async def clear_google_maps_key() -> IntegrationsOut:
    runtime_config.clear_google_maps_key()
    get_settings.cache_clear()
    return _status()


async def _usage(session: AsyncSession) -> ApolloUsageOut:
    consumed = await enrichment_repo.sum_matched(session)
    budget = runtime_config.get_apollo_budget()
    remaining = max(0, budget - consumed) if budget else None
    return ApolloUsageOut(consumed=consumed, budget=budget, remaining=remaining)


@router.get("/apollo-usage", response_model=ApolloUsageOut)
async def apollo_usage(session: AsyncSession = Depends(get_db)) -> ApolloUsageOut:
    return await _usage(session)


@router.put("/integrations/apollo-budget", response_model=ApolloUsageOut)
async def set_apollo_budget(
    body: ApolloBudgetIn, session: AsyncSession = Depends(get_db)
) -> ApolloUsageOut:
    runtime_config.set_apollo_budget(body.budget)
    return await _usage(session)

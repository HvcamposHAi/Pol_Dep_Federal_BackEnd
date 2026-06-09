"""Cliente ViaCEP (GET /{cep}/json/) — gratuito, sem chave.

Cliente puro: dado um CEP, devolve endereço mapeado para colunas do banco.
Não escreve no banco. Não bloqueia o Apollo (erros são reportados, não levantados).
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.core.http_client import request_with_retry
from app.core.normalize import clean_cep, clean_value
from app.core.rate_limiter import AsyncRateLimiter
from app.models.lead import Lead
from app.services.result import ProviderResult

# Campo ViaCEP -> coluna do banco
_FIELD_MAP = {
    "logradouro": "endereco",
    "bairro": "bairro",
    "localidade": "cidade",
    "uf": "estado",
}


class ViaCepService:
    def __init__(self, settings: Settings, rate_limiter: AsyncRateLimiter):
        self._settings = settings
        self._rate = rate_limiter

    async def enrich(self, lead: Lead) -> ProviderResult:
        cep = clean_cep(lead.cep)
        if not cep:
            return ProviderResult(provider="viacep", matched=False, error="sem CEP válido")

        await self._rate.acquire()
        url = f"{self._settings.viacep_base_url.rstrip('/')}/{cep}/json/"
        try:
            resp = await request_with_retry("GET", url)
        except httpx.HTTPError as exc:
            return ProviderResult(provider="viacep", error=str(exc))

        if resp.status_code != 200:
            return ProviderResult(
                provider="viacep", http_status=resp.status_code, error=f"HTTP {resp.status_code}"
            )

        data = resp.json() or {}
        if data.get("erro"):
            return ProviderResult(provider="viacep", http_status=200, matched=False)

        candidate: dict = {}
        for src, col in _FIELD_MAP.items():
            value = clean_value(data.get(src))
            if value:
                candidate[col] = value

        return ProviderResult(
            provider="viacep", http_status=200, matched=bool(candidate), candidate=candidate
        )

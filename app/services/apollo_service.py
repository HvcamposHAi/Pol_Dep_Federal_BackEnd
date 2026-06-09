"""Cliente Apollo.io People Enrichment (POST /people/match).

Cliente puro: monta a requisição, respeita rate limit e retry, mapeia a resposta
para colunas do banco e devolve um ``ProviderResult``. NÃO escreve no banco.
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.core.http_client import request_with_retry
from app.core.normalize import clean_value
from app.core.rate_limiter import AsyncRateLimiter
from app.models.lead import Lead
from app.services.result import ProviderResult

# Campo da resposta Apollo (person.*) -> coluna do banco
_FIELD_MAP = {
    "email": "email",
    "linkedin_url": "linkedin",
    "title": "profissao",
    "twitter_url": "twitter",
    "facebook_url": "facebook",
    "city": "cidade",
    "state": "estado",
    "last_name": "sobrenome",
}

# E-mails "não revelados" devolvidos pelo Apollo como placeholder
_EMAIL_PLACEHOLDERS = ("email_not_unlocked", "not_unlocked")


class ApolloEnrichmentService:
    def __init__(self, settings: Settings, rate_limiter: AsyncRateLimiter):
        self._settings = settings
        self._rate = rate_limiter

    def _build_payload(self, lead: Lead) -> dict:
        payload: dict = {"reveal_personal_emails": True}
        if lead.nome:
            payload["first_name"] = lead.nome
        if lead.sobrenome:
            payload["last_name"] = lead.sobrenome
        if lead.email:
            payload["email"] = lead.email
        if lead.phone_e164:
            payload["phone_numbers"] = [lead.phone_e164]
        if lead.cidade:
            payload["city"] = lead.cidade
        if lead.estado:
            payload["state"] = lead.estado
        return payload

    @staticmethod
    def _map_person(person: dict) -> dict:
        candidate: dict = {}
        for src, col in _FIELD_MAP.items():
            value = clean_value(person.get(src))
            if not value:
                continue
            if col == "email" and any(p in value.lower() for p in _EMAIL_PLACEHOLDERS):
                continue
            candidate[col] = value
        return candidate

    async def enrich(self, lead: Lead) -> ProviderResult:
        if not self._settings.apollo_api_key:
            return ProviderResult(provider="apollo", error="APOLLO_API_KEY ausente")

        await self._rate.acquire()
        url = f"{self._settings.apollo_base_url.rstrip('/')}/people/match"
        headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self._settings.apollo_api_key,
        }
        try:
            resp = await request_with_retry(
                "POST", url, json=self._build_payload(lead), headers=headers
            )
        except httpx.HTTPError as exc:
            return ProviderResult(provider="apollo", error=str(exc))

        if resp.status_code != 200:
            return ProviderResult(
                provider="apollo",
                http_status=resp.status_code,
                error=f"HTTP {resp.status_code}",
            )

        person = (resp.json() or {}).get("person")
        if not person:
            return ProviderResult(provider="apollo", http_status=200, matched=False)

        candidate = self._map_person(person)
        return ProviderResult(
            provider="apollo",
            http_status=200,
            matched=True,
            candidate=candidate,
            payload={"linkedin_url": person.get("linkedin_url"), "title": person.get("title")},
        )

"""E2E: sem APOLLO_API_KEY, o orquestrador pula o Apollo (sem 403/rate limit).

Garante que: nenhuma chamada Apollo é feita, o run completa, ViaCEP enriquece
normalmente e um evento "skipped" do orquestrador explica o motivo.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.core.http_client import close_client
from app.repositories import enrichment_repo, lead_repo
from app.services.enrichment_orchestrator import EnrichmentOrchestrator

pytestmark = pytest.mark.e2e

VIACEP_BODY = {
    "logradouro": "Praça da Sé",
    "bairro": "Sé",
    "localidade": "São Paulo",
    "uf": "SP",
}


@respx.mock
async def test_apollo_pulado_sem_chave(sessionmaker_fixture, test_settings):
    sm = sessionmaker_fixture
    test_settings.apollo_api_key = ""  # sem chave -> Apollo deve ser pulado

    async with sm() as s:
        await lead_repo.upsert_many(s, [{"phone_e164": "+5541999990000", "cep": "01001000"}])
        await s.commit()

    # Só ViaCEP é mockado. Se o Apollo fosse chamado, respx levantaria (rota não mockada).
    respx.get(url__regex=r"https://viacep\.test/ws/\d{8}/json/").mock(
        return_value=httpx.Response(200, json=VIACEP_BODY)
    )

    async with sm() as s:
        run = await enrichment_repo.create_run(
            s, provider_scope=["viacep", "apollo"], params={}
        )
        await s.commit()
        run_id = run.id

    await close_client()
    orch = EnrichmentOrchestrator(test_settings, sm)
    await orch.run(run_id, filters={})

    async with sm() as s:
        run = await enrichment_repo.get_run(s, run_id)
        assert run.status == "completed"
        assert run.matched_count == 0
        assert run.error_count == 0

        events = await enrichment_repo.list_events(s, run_id)
        providers = {e.provider for e in events}
        assert "apollo" not in providers  # Apollo nunca foi chamado
        assert any(e.provider == "orchestrator" and e.event_type == "skipped" for e in events)

        lead = await lead_repo.get_by_phone(s, "+5541999990000")
        assert lead.cidade == "São Paulo"  # ViaCEP preencheu
        assert lead.enrichment_status == "enriched"

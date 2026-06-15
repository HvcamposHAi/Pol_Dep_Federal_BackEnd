"""E2E: disjuntor do Apollo — ao primeiro 403, para de chamar o Apollo na execução.

Evita 403 em toda a base (cenário do plano Apollo sem acesso a /people/match).
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.core.http_client import close_client
from app.repositories import enrichment_repo, lead_repo
from app.services.enrichment_orchestrator import EnrichmentOrchestrator

pytestmark = pytest.mark.e2e

_INACCESSIBLE = {
    "error": "api/v1/people/match is not accessible with this api_key",
    "error_code": "API_INACCESSIBLE",
}


@respx.mock
async def test_apollo_para_no_primeiro_403(sessionmaker_fixture, test_settings):
    sm = sessionmaker_fixture
    test_settings.apollo_api_key = "valida-mas-sem-acesso"

    rows = [{"phone_e164": f"+554199900000{i}", "email": f"a{i}@x.com"} for i in range(4)]
    async with sm() as s:
        await lead_repo.upsert_many(s, rows)
        await s.commit()

    apollo_route = respx.post("https://apollo.test/v1/people/match").mock(
        return_value=httpx.Response(403, json=_INACCESSIBLE)
    )

    async with sm() as s:
        run = await enrichment_repo.create_run(s, provider_scope=["apollo"], params={})
        await s.commit()
        run_id = run.id

    await close_client()
    orch = EnrichmentOrchestrator(test_settings, sm)
    await orch.run(run_id, filters={})

    # Disjuntor: o Apollo é chamado só 1 vez (não 4), mesmo com 4 leads pendentes.
    assert apollo_route.call_count == 1

    async with sm() as s:
        run = await enrichment_repo.get_run(s, run_id)
        assert run.status == "completed"
        assert run.matched_count == 0
        events = await enrichment_repo.list_events(s, run_id)
        assert any(e.provider == "orchestrator" and e.event_type == "skipped" for e in events)

"""E2E: resultado positivo/negativo + motivo (enrichment_note) por lead."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.core.http_client import close_client
from app.repositories import enrichment_repo, lead_repo
from app.services.enrichment_orchestrator import EnrichmentOrchestrator

pytestmark = pytest.mark.e2e


async def _run(sm, settings, provider_scope):
    async with sm() as s:
        run = await enrichment_repo.create_run(s, provider_scope=provider_scope, params={})
        await s.commit()
        run_id = run.id
    await close_client()
    await EnrichmentOrchestrator(settings, sm).run(run_id, filters={})


@respx.mock
async def test_positivo_marca_campos(sessionmaker_fixture, test_settings):
    sm = sessionmaker_fixture
    async with sm() as s:
        await lead_repo.upsert_many(s, [{"phone_e164": "+5541900000001", "nome": "Ana"}])
        await s.commit()
    respx.post("https://apollo.test/v1/people/match").mock(
        return_value=httpx.Response(200, json={"person": {"email": "ana@x.com", "title": "Dev"}})
    )

    await _run(sm, test_settings, ["apollo"])

    async with sm() as s:
        lead = await lead_repo.get_by_phone(s, "+5541900000001")
        assert lead.enrichment_status == "enriched"  # positivo
        assert lead.email == "ana@x.com"
        assert "campos" in (lead.enrichment_note or "")
        assert "email" in (lead.enrichment_note or "")


@respx.mock
async def test_negativo_marca_motivo(sessionmaker_fixture, test_settings):
    sm = sessionmaker_fixture
    async with sm() as s:
        await lead_repo.upsert_many(s, [{"phone_e164": "+5541900000002", "nome": "Beto"}])
        await s.commit()
    respx.post("https://apollo.test/v1/people/match").mock(
        return_value=httpx.Response(200, json={"person": None})  # sem correspondência
    )

    await _run(sm, test_settings, ["apollo"])

    async with sm() as s:
        lead = await lead_repo.get_by_phone(s, "+5541900000002")
        assert lead.enrichment_status == "skipped"  # negativo
        assert "sem correspond" in (lead.enrichment_note or "").lower()

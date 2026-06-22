"""E2E do provider ``google_maps`` (Places + Geocoding) — serviço e orquestrador.

Cobre a estratégia combinada: (1) reverse-lookup por telefone com Place Details
e (2) fallback por geocoding do endereço existente; mais o disjuntor em
REQUEST_DENIED (chave/billing/API off).
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.config import Settings
from app.core.http_client import close_client
from app.core.rate_limiter import AsyncRateLimiter
from app.models.lead import Lead
from app.repositories import enrichment_repo, lead_repo
from app.services.enrichment_orchestrator import EnrichmentOrchestrator
from app.services.google_maps_service import GoogleMapsService

pytestmark = pytest.mark.e2e

_BASE = "https://maps.test/maps/api"

FIND_URL = r"https://maps\.test/maps/api/place/findplacefromtext/json.*"
DETAILS_URL = r"https://maps\.test/maps/api/place/details/json.*"
GEOCODE_URL = r"https://maps\.test/maps/api/geocode/json.*"

_DETAILS_COMPONENTS = [
    {"long_name": "123", "short_name": "123", "types": ["street_number"]},
    {"long_name": "Rua das Flores", "short_name": "Rua das Flores", "types": ["route"]},
    {"long_name": "Centro", "short_name": "Centro", "types": ["sublocality_level_1"]},
    {"long_name": "Curitiba", "short_name": "Curitiba", "types": ["administrative_area_level_2"]},
    {"long_name": "Paraná", "short_name": "PR", "types": ["administrative_area_level_1"]},
    {"long_name": "80010-000", "short_name": "80010-000", "types": ["postal_code"]},
]


def _settings() -> Settings:
    return Settings(
        google_maps_api_key="gmaps-test-key",
        google_maps_base_url=_BASE,
        google_maps_rate_limit=6000,
        http_max_retries=1,
    )


def _service() -> GoogleMapsService:
    return GoogleMapsService(_settings(), AsyncRateLimiter.from_rpm(6000))


@respx.mock
async def test_match_por_telefone_preenche_geo_e_endereco():
    respx.get(url__regex=FIND_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "OK",
                "candidates": [
                    {
                        "place_id": "PID1",
                        "name": "Padaria do João",
                        "geometry": {"location": {"lat": -25.43, "lng": -49.27}},
                    }
                ],
            },
        )
    )
    respx.get(url__regex=DETAILS_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "OK",
                "result": {
                    "name": "Padaria do João",
                    "geometry": {"location": {"lat": -25.43, "lng": -49.27}},
                    "address_components": _DETAILS_COMPONENTS,
                },
            },
        )
    )
    await close_client()

    lead = Lead(phone_e164="+5541999990000")  # sem endereço -> só o caminho do telefone
    result = await _service().enrich(lead)

    assert result.matched is True
    c = result.candidate
    assert c["numero"] == "123"
    assert c["endereco"] == "Rua das Flores"
    assert c["bairro"] == "Centro"
    assert c["cidade"] == "Curitiba"
    assert c["estado"] == "PR"  # short_name (UF)
    assert c["cep"] == "80010000"  # só dígitos
    assert float(c["latitude"]) == pytest.approx(-25.43)
    assert float(c["longitude"]) == pytest.approx(-49.27)
    assert c["observacoes"] == "Google Maps: Padaria do João"
    assert result.payload["source"] == "phone"


@respx.mock
async def test_fallback_geocoding_quando_telefone_nao_casa():
    respx.get(url__regex=FIND_URL).mock(
        return_value=httpx.Response(200, json={"status": "ZERO_RESULTS", "candidates": []})
    )
    respx.get(url__regex=GEOCODE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {
                        "address_components": _DETAILS_COMPONENTS,
                        "geometry": {"location": {"lat": -25.5, "lng": -49.3}},
                    }
                ],
            },
        )
    )
    await close_client()

    lead = Lead(phone_e164="+5541999990001", cidade="Curitiba", cep="80010000")
    result = await _service().enrich(lead)

    assert result.matched is True
    assert result.payload["source"] == "geocode"
    assert float(result.candidate["latitude"]) == pytest.approx(-25.5)
    assert result.candidate["estado"] == "PR"


@respx.mock
async def test_request_denied_vira_403_para_disjuntor():
    respx.get(url__regex=FIND_URL).mock(
        return_value=httpx.Response(
            200, json={"status": "REQUEST_DENIED", "error_message": "API key invalid"}
        )
    )
    await close_client()

    lead = Lead(phone_e164="+5541999990002")
    result = await _service().enrich(lead)

    assert result.matched is False
    assert result.http_status == 403  # orquestrador abre o disjuntor
    assert "REQUEST_DENIED" in result.error


@respx.mock
async def test_orquestrador_enriquece_com_google_maps(sessionmaker_fixture):
    sm = sessionmaker_fixture
    settings = _settings()

    async with sm() as s:
        await lead_repo.upsert_many(s, [{"phone_e164": "+5541999990003"}])
        await s.commit()

    respx.get(url__regex=FIND_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "OK",
                "candidates": [
                    {
                        "place_id": "PID2",
                        "name": "Mercado Central",
                        "geometry": {"location": {"lat": -25.4, "lng": -49.2}},
                    }
                ],
            },
        )
    )
    respx.get(url__regex=DETAILS_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "OK",
                "result": {
                    "name": "Mercado Central",
                    "geometry": {"location": {"lat": -25.4, "lng": -49.2}},
                    "address_components": _DETAILS_COMPONENTS,
                },
            },
        )
    )

    async with sm() as s:
        run = await enrichment_repo.create_run(s, provider_scope=["google_maps"], params={})
        await s.commit()
        run_id = run.id

    await close_client()
    await EnrichmentOrchestrator(settings, sm).run(run_id, filters={})

    async with sm() as s:
        run = await enrichment_repo.get_run(s, run_id)
        assert run.status == "completed"
        assert run.error_count == 0

        lead = await lead_repo.get_by_phone(s, "+5541999990003")
        assert lead.enrichment_status == "enriched"
        assert lead.cidade == "Curitiba"
        assert lead.estado == "PR"
        assert lead.google_maps_enriched_at is not None
        assert float(lead.latitude) == pytest.approx(-25.4)


@respx.mock
async def test_reprocessa_base_terminal_sem_rebaixar(sessionmaker_fixture):
    """Lead já 'enriched' (Apollo) e nunca tocado pelo Google é alvo de um run
    google-only — enriquece geo via geocoding e NÃO rebaixa o status."""
    sm = sessionmaker_fixture
    settings = _settings()

    async with sm() as s:
        await lead_repo.upsert_many(
            s, [{"phone_e164": "+5541999990004", "cidade": "Curitiba", "cep": "80010000"}]
        )
        lead = await lead_repo.get_by_phone(s, "+5541999990004")
        lead.enrichment_status = "enriched"  # já terminal (run anterior do Apollo)
        lead.enrichment_note = "match Apollo"
        await s.commit()

    respx.get(url__regex=FIND_URL).mock(
        return_value=httpx.Response(200, json={"status": "ZERO_RESULTS", "candidates": []})
    )
    respx.get(url__regex=GEOCODE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {
                        "address_components": _DETAILS_COMPONENTS,
                        "geometry": {"location": {"lat": -25.5, "lng": -49.3}},
                    }
                ],
            },
        )
    )

    async with sm() as s:
        run = await enrichment_repo.create_run(s, provider_scope=["google_maps"], params={})
        await s.commit()
        run_id = run.id

    await close_client()
    await EnrichmentOrchestrator(settings, sm).run(run_id, filters={})

    async with sm() as s:
        run = await enrichment_repo.get_run(s, run_id)
        assert run.status == "completed"
        assert run.processed_count == 1  # o lead terminal FOI selecionado

        lead = await lead_repo.get_by_phone(s, "+5541999990004")
        assert lead.enrichment_status == "enriched"  # não rebaixado
        assert lead.google_maps_enriched_at is not None
        assert float(lead.latitude) == pytest.approx(-25.5)


@respx.mock
async def test_no_match_carimba_timestamp_e_run_termina(sessionmaker_fixture):
    """Sem telefone casado e sem endereço, o Google não acha nada — mas carimba
    google_maps_enriched_at, então o lead sai do alvo e o run TERMINA (não laça)."""
    sm = sessionmaker_fixture
    settings = _settings()

    async with sm() as s:
        await lead_repo.upsert_many(s, [{"phone_e164": "+5541999990005"}])  # sem endereço
        await s.commit()

    respx.get(url__regex=FIND_URL).mock(
        return_value=httpx.Response(200, json={"status": "ZERO_RESULTS", "candidates": []})
    )

    async with sm() as s:
        run = await enrichment_repo.create_run(s, provider_scope=["google_maps"], params={})
        await s.commit()
        run_id = run.id

    await close_client()
    await EnrichmentOrchestrator(settings, sm).run(run_id, filters={})

    async with sm() as s:
        run = await enrichment_repo.get_run(s, run_id)
        assert run.status == "completed"
        assert run.error_count == 0

        lead = await lead_repo.get_by_phone(s, "+5541999990005")
        assert lead.google_maps_enriched_at is not None  # carimbado mesmo sem match
        assert lead.enrichment_status == "skipped"

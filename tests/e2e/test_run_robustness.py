"""E2E: robustez do run — status terminal em falha, heartbeat por lead,
cancelamento dentro do lote e download parcial (processed_only).

Cobre a correção do bug "tela travada em running": uma task que morre/crasha
DEVE deixar o run em status terminal (failed), nunca preso em "running".
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.core.http_client import close_client
from app.repositories import enrichment_repo, lead_repo
from app.services import export_service
from app.services.enrichment_orchestrator import EnrichmentOrchestrator

pytestmark = pytest.mark.e2e


@respx.mock
async def test_falha_marca_run_failed(sessionmaker_fixture, test_settings, monkeypatch):
    """Exceção não tratada no loop -> run termina em 'failed' (não fica 'running')."""
    sm = sessionmaker_fixture
    async with sm() as s:
        await lead_repo.upsert_many(s, [{"phone_e164": "+5541900000010", "nome": "Ana"}])
        await s.commit()
        run = await enrichment_repo.create_run(s, provider_scope=["apollo"], params={})
        await s.commit()
        run_id = run.id
    await close_client()

    orch = EnrichmentOrchestrator(test_settings, sm)

    async def boom(*_args, **_kwargs):
        raise RuntimeError("queda simulada no meio do run")

    # Estoura dentro do processamento do lote.
    monkeypatch.setattr(orch, "_process_lead", boom)

    with pytest.raises(RuntimeError):
        await orch.run(run_id, filters={})

    async with sm() as s:
        run = await enrichment_repo.get_run(s, run_id)
        assert run.status == "failed"  # <- nunca preso em "running"
        assert run.finished_at is not None
        events = await enrichment_repo.list_events(s, run_id)
        assert any(e.event_type == "run_failed" for e in events)


@respx.mock
async def test_heartbeat_e_parcial(sessionmaker_fixture, test_settings):
    """Cada lead bate heartbeat e fica disponível no download parcial (processed_only)."""
    sm = sessionmaker_fixture
    async with sm() as s:
        await lead_repo.upsert_many(
            s,
            [
                {"phone_e164": "+5541900000021", "nome": "Bia"},
                {"phone_e164": "+5541900000022", "nome": "Caio"},
            ],
        )
        await s.commit()
        run = await enrichment_repo.create_run(s, provider_scope=["apollo"], params={})
        await s.commit()
        run_id = run.id
    respx.post("https://apollo.test/v1/people/match").mock(
        return_value=httpx.Response(200, json={"person": {"email": "x@x.com", "title": "Dev"}})
    )
    await close_client()

    await EnrichmentOrchestrator(test_settings, sm).run(run_id, filters={})

    async with sm() as s:
        run = await enrichment_repo.get_run(s, run_id)
        assert run.status == "completed"
        assert run.checkpoint.get("heartbeat")  # prova de vida persistida

        # parcial: processed_only só traz quem saiu de "pending"
        rows = [
            lead async for lead in lead_repo.iter_export_rows(s, processed_only=True)
        ]
        assert len(rows) == 2
        assert all(r.enrichment_status != "pending" for r in rows)

        # o CSV parcial inclui cabeçalho + 2 linhas
        chunks = [c async for c in export_service.stream_csv(s, processed_only=True)]
        body = b"".join(chunks).decode("utf-8")
        assert "Status enriquecimento" in body
        assert body.count("enriched") == 2

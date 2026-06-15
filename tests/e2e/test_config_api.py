"""E2E: configuração de integrações (/config) — set/get/delete da chave Apollo.

Usa um runtime_config.json temporário (monkeypatch) para não tocar o cwd real.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import get_settings
from app.core import runtime_config
from app.db.session import get_db
from app.main import app
from app.repositories import enrichment_repo

pytestmark = pytest.mark.e2e


@pytest.fixture
def _tmp_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_config, "_PATH", tmp_path / "runtime_config.json")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def client(_tmp_runtime):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_apollo_key_lifecycle(client):
    # set
    r = await client.put("/config/integrations/apollo", json={"api_key": "secret-key-123456"})
    assert r.status_code == 200
    body = r.json()
    assert body["apollo_configured"] is True
    assert body["apollo_source"] == "runtime"
    assert body["apollo_masked"].endswith("3456")
    # nunca devolve o segredo em claro
    assert "secret" not in (body["apollo_masked"] or "")

    # get reflete o estado salvo
    assert (await client.get("/config/integrations")).json()["apollo_configured"] is True

    # delete volta para env/none (sem runtime)
    r3 = await client.delete("/config/integrations/apollo")
    assert r3.json()["apollo_source"] in ("env", "none")


async def test_set_key_propaga_para_get_settings(client):
    await client.put("/config/integrations/apollo", json={"api_key": "abcdef123456"})
    # o override de runtime tem precedência no get_settings (usado por API e CLI)
    assert get_settings().apollo_api_key == "abcdef123456"


async def test_key_curta_e_rejeitada(client):
    r = await client.put("/config/integrations/apollo", json={"api_key": "123"})
    assert r.status_code == 422  # min_length=8


async def test_apollo_usage_e_budget(sessionmaker_fixture, _tmp_runtime):
    sm = sessionmaker_fixture
    async with sm() as s:
        run = await enrichment_repo.create_run(s, provider_scope=["apollo"], params={})
        run.matched_count = 7  # ~7 créditos consumidos
        await s.commit()

    async def _ovr():
        async with sm() as s:
            yield s

    app.dependency_overrides[get_db] = _ovr
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            # sem budget definido
            u0 = (await c.get("/config/apollo-usage")).json()
            assert u0["consumed"] == 7 and u0["budget"] == 0 and u0["remaining"] is None
            # define budget -> remaining calculado
            r = await c.put("/config/integrations/apollo-budget", json={"budget": 100})
            assert r.json() == {"consumed": 7, "budget": 100, "remaining": 93}
    finally:
        app.dependency_overrides.clear()

"""Teste E2E: import (CSV cp1252-corrompido) -> enrich (Apollo+ViaCEP mockados) -> verifica.

Cobre: normalização de telefone, fill-only-empty entre providers, não-sobrescrita
de dados existentes, provenance, contadores do run, eventos e resume/idempotência.
"""

import httpx
import pytest
import respx

from app.core.http_client import close_client
from app.repositories import enrichment_repo, lead_repo
from app.services import import_service
from app.services.enrichment_orchestrator import EnrichmentOrchestrator

pytestmark = pytest.mark.e2e

APOLLO_PERSON = {
    "person": {
        "email": "apollo@found.com",
        "linkedin_url": "https://linkedin.com/in/x",
        "title": "Analista",
        "last_name": "Silva",
        "city": "Curitiba",
        "state": "PR",
    }
}
VIACEP_BODY = {
    "logradouro": "Praça da Sé",
    "bairro": "Sé",
    "localidade": "São Paulo",
    "uf": "SP",
}


@respx.mock
async def test_import_then_enrich(sessionmaker_fixture, test_settings, sample_csv_bytes):
    sm = sessionmaker_fixture

    # --- IMPORT ---
    async with sm() as s:
        result = await import_service.import_bytes(s, "sample_leads.csv", sample_csv_bytes)
        await s.commit()

    assert result.total == 3
    assert result.inserted == 2  # Regina, Carla
    assert len(result.rejected) == 1  # Eduardo (sem telefone)
    assert result.rejected[0].nome == "Eduardo"

    async with sm() as s:
        regina = await lead_repo.get_by_phone(s, "+5541991480001")
        carla = await lead_repo.get_by_phone(s, "+5541991480002")
        assert regina is not None and carla is not None
        # telefone normalizado para E.164
        assert regina.phone_e164 == "+5541991480001"
        # campos esparsos nulos após import
        assert regina.email is None
        assert regina.cep == "01001000"
        # genero/profissao mapeados apesar do cabeçalho corrompido
        assert regina.genero == "Feminino"
        assert carla.profissao == "Contador"
        # provenance do CSV
        assert carla.field_provenance.get("email") == "csv"

    # --- MOCKS ---
    respx.post("https://apollo.test/v1/people/match").mock(
        return_value=httpx.Response(200, json=APOLLO_PERSON)
    )
    respx.get(url__regex=r"https://viacep\.test/ws/\d{8}/json/").mock(
        return_value=httpx.Response(200, json=VIACEP_BODY)
    )

    # --- ENRICH ---
    await close_client()
    async with sm() as s:
        run = await enrichment_repo.create_run(
            s, provider_scope=["viacep", "apollo"], params={}
        )
        await s.commit()
        run_id = run.id

    orch = EnrichmentOrchestrator(test_settings, sm)
    await orch.run(run_id, filters={})

    # --- VERIFY ---
    async with sm() as s:
        regina = await lead_repo.get_by_phone(s, "+5541991480001")
        # apollo preencheu campos vazios
        assert regina.email == "apollo@found.com"
        assert regina.field_provenance["email"] == "apollo"
        assert regina.linkedin == "https://linkedin.com/in/x"
        assert regina.sobrenome == "Silva"
        # viacep rodou ANTES do apollo -> cidade vem do viacep, apollo NÃO sobrescreve
        assert regina.cidade == "São Paulo"
        assert regina.field_provenance["cidade"] == "viacep"
        assert regina.endereco == "Praça da Sé"
        assert regina.field_provenance["endereco"] == "viacep"
        assert regina.apollo_matched is True
        assert regina.enrichment_status == "enriched"

        carla = await lead_repo.get_by_phone(s, "+5541991480002")
        # dados já existentes NÃO são sobrescritos
        assert carla.email == "carla@existing.com"
        assert carla.field_provenance["email"] == "csv"
        assert carla.profissao == "Contador"
        # campo vazio preenchido pelo apollo
        assert carla.linkedin == "https://linkedin.com/in/x"
        assert carla.apollo_matched is True

        run = await enrichment_repo.get_run(s, run_id)
        assert run.status == "completed"
        assert run.processed_count == 2
        assert run.matched_count == 2
        assert run.error_count == 0
        events = await enrichment_repo.list_events(s, run_id)
        assert len(events) > 0

    # --- RESUME / IDEMPOTÊNCIA: segundo run não reprocessa ---
    async with sm() as s:
        run2 = await enrichment_repo.create_run(
            s, provider_scope=["viacep", "apollo"], params={}
        )
        await s.commit()
        run2_id = run2.id

    await orch.run(run2_id, filters={})

    async with sm() as s:
        run2 = await enrichment_repo.get_run(s, run2_id)
        assert run2.processed_count == 0  # nada pendente -> resume não duplica
        regina = await lead_repo.get_by_phone(s, "+5541991480001")
        assert regina.email == "apollo@found.com"  # inalterado

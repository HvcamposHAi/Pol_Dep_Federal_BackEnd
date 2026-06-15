"""Unit: lead_repo.stats — totais, completude média e pendentes Apollo."""

from __future__ import annotations

from datetime import date

from app.core.coverage import CORE_COMPLETENESS_FIELDS
from app.repositories import lead_repo

# Lead com TODOS os 9 campos do core set preenchidos.
_FULL = {
    "phone_e164": "+5541900000001",
    "nome_completo": "Ana Souza",
    "email": "ana@x.com",
    "profissao": "Dev",
    "cidade": "Curitiba",
    "cep": "80000000",
    "linkedin": "https://linkedin.com/in/ana",
    "instagram": "@ana",
    "sobrenome": "Souza",
    "data_nascimento": date(1990, 1, 1),
}
# Apenas 1 campo do core set (nome_completo).
_ONE = {"phone_e164": "+5541900000002", "nome_completo": "Bruno Dias"}
# Nenhum campo do core (só a chave natural).
_NONE = {"phone_e164": "+5541900000003"}


async def _seed(sm, rows):
    async with sm() as s:
        await lead_repo.upsert_many(s, rows)
        await s.commit()


async def test_stats_totais_e_completude(sessionmaker_fixture):
    sm = sessionmaker_fixture
    await _seed(sm, [_FULL, _ONE, _NONE])

    async with sm() as s:
        result = await lead_repo.stats(s)

    assert result["total_leads"] == 3
    # Nenhum tem apollo_matched=True -> todos pendentes.
    assert result["pendentes_apollo"] == 3
    # Média de campos preenchidos: (9 + 1 + 0)/3, dividido por 9, *100.
    n = len(CORE_COMPLETENESS_FIELDS)
    assert n == 9
    assert result["completude_media_pct"] == round((9 + 1 + 0) / 3 / n * 100, 1)


async def test_stats_base_vazia(sessionmaker_fixture):
    async with sessionmaker_fixture() as s:
        result = await lead_repo.stats(s)
    assert result == {"total_leads": 0, "completude_media_pct": 0.0, "pendentes_apollo": 0}


async def test_pendentes_conta_pending_ou_nao_matched(sessionmaker_fixture):
    sm = sessionmaker_fixture
    await _seed(sm, [_FULL])
    # Marca como enriquecido + apollo_matched -> deixa de ser pendente.
    async with sm() as s:
        lead = await lead_repo.get_by_phone(s, "+5541900000001")
        lead.enrichment_status = "enriched"
        lead.apollo_matched = True
        await s.commit()

    async with sm() as s:
        result = await lead_repo.stats(s)
    assert result["pendentes_apollo"] == 0

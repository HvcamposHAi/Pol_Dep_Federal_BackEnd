"""Unit: lead_repo.field_coverage — filled/missing/%, paridade de vazio e filtros."""

from __future__ import annotations

from app.repositories import lead_repo


async def _seed(sm, rows):
    async with sm() as s:
        await lead_repo.upsert_many(s, rows)
        await s.commit()


def _by_field(rows, field):
    return next(r for r in rows if r["field"] == field)


async def test_field_coverage_contagens_e_sources(sessionmaker_fixture):
    sm = sessionmaker_fixture
    await _seed(
        sm,
        [
            {"phone_e164": "+5541900000001", "email": "a@x.com", "cidade": "Curitiba"},
            {"phone_e164": "+5541900000002", "cidade": "Curitiba"},
            {"phone_e164": "+5541900000003"},
        ],
    )

    async with sm() as s:
        cov = await lead_repo.field_coverage(s)

    email = _by_field(cov, "email")
    assert email["filled"] == 1
    assert email["missing"] == 2
    assert email["coverage_pct"] == round(1 / 3 * 100, 1)
    assert email["sources"] == ["apollo"]

    cidade = _by_field(cov, "cidade")
    assert cidade["filled"] == 2
    # cidade pode vir de Apollo e ViaCEP.
    assert cidade["sources"] == ["apollo", "viacep"]

    # filled + missing == total para todo campo.
    for row in cov:
        assert row["filled"] + row["missing"] == 3


async def test_string_vazia_nao_conta_como_preenchido(sessionmaker_fixture):
    sm = sessionmaker_fixture
    # email com espaços = vazio (paridade com merge.is_empty).
    await _seed(sm, [{"phone_e164": "+5541900000009", "email": "   "}])

    async with sm() as s:
        cov = await lead_repo.field_coverage(s)
    assert _by_field(cov, "email")["filled"] == 0


async def test_field_coverage_respeita_filtros(sessionmaker_fixture):
    sm = sessionmaker_fixture
    await _seed(
        sm,
        [
            {"phone_e164": "+5541900000001", "email": "a@x.com", "estado": "PR"},
            {"phone_e164": "+5541900000002", "email": "b@x.com", "estado": "SP"},
        ],
    )

    async with sm() as s:
        cov = await lead_repo.field_coverage(s, estado="PR")
    email = _by_field(cov, "email")
    assert email["filled"] == 1
    assert email["missing"] == 0  # só 1 lead no filtro

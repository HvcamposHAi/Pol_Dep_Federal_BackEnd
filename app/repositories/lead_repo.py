"""Acesso a dados de ``leads`` (sem regra de negócio)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.coverage import (
    CORE_COMPLETENESS_FIELDS,
    COVERAGE_FIELDS,
    FIELD_SOURCES,
    NON_TEXT_FIELDS,
)
from app.core.merge import fill_only_empty, is_empty
from app.models.lead import Lead

# Colunas mapeáveis (exclui PK/timestamps/controle) — usadas no upsert e provenance
_CSV_PROVENANCE_SKIP = {"phone_e164", "raw_source"}


def _apply_filters(
    stmt,
    *,
    enrichment_status: str | None = None,
    apollo_matched: bool | None = None,
    cidade: str | None = None,
    estado: str | None = None,
    q: str | None = None,
    processed_only: bool = False,
):
    """Aplica o conjunto ÚNICO de filtros de leads (mesmo em list/stats/coverage/export).

    ``processed_only``: exporta só o que já foi tratado (status != "pending") —
    usado pelo download parcial do run.
    """
    if enrichment_status is not None:
        stmt = stmt.where(Lead.enrichment_status == enrichment_status)
    if processed_only:
        stmt = stmt.where(Lead.enrichment_status != "pending")
    if apollo_matched is not None:
        stmt = stmt.where(Lead.apollo_matched == apollo_matched)
    if cidade:
        stmt = stmt.where(Lead.cidade == cidade)
    if estado:
        stmt = stmt.where(Lead.estado == estado)
    if q:
        stmt = stmt.where(Lead.nome_completo.ilike(f"%{q}%"))
    return stmt


def _filled_expr(col_name: str) -> ColumnElement[int]:
    """Expressão 1/0 "campo preenchido", espelhando ``merge.is_empty`` (portável SQLite+PG)."""
    col = getattr(Lead, col_name)
    if col_name in NON_TEXT_FIELDS:
        return case((col.is_not(None), 1), else_=0)
    return case((and_(col.is_not(None), func.trim(col) != ""), 1), else_=0)


async def upsert_many(
    session: AsyncSession,
    rows: list[dict[str, Any]],
    provider: str = "csv",
) -> tuple[int, int]:
    """Upsert por ``phone_e164`` com regra fill-only-empty (não sobrescreve).

    Retorna (inserted, updated). Trata duplicatas dentro do próprio lote.
    """
    if not rows:
        return 0, 0

    phones = list({r["phone_e164"] for r in rows})
    existing: dict[str, Lead] = {
        lead.phone_e164: lead
        for lead in (
            await session.execute(select(Lead).where(Lead.phone_e164.in_(phones)))
        ).scalars()
    }

    inserted = updated = 0
    for r in rows:
        phone = r["phone_e164"]
        current = existing.get(phone)
        if current is None:
            lead = Lead(**r)
            lead.field_provenance = {
                k: provider
                for k, v in r.items()
                if k not in _CSV_PROVENANCE_SKIP and not is_empty(v)
            }
            session.add(lead)
            existing[phone] = lead
            inserted += 1
        else:
            current_dict = {col: getattr(current, col) for col in r}
            merge = fill_only_empty(current_dict, r, provider)
            if merge.patch:
                for col, value in merge.patch.items():
                    setattr(current, col, value)
                prov = dict(current.field_provenance or {})
                prov.update(merge.provenance)
                current.field_provenance = prov
                updated += 1

    await session.flush()
    return inserted, updated


async def get(session: AsyncSession, lead_id: uuid.UUID) -> Lead | None:
    return await session.get(Lead, lead_id)


async def get_by_phone(session: AsyncSession, phone_e164: str) -> Lead | None:
    res = await session.execute(select(Lead).where(Lead.phone_e164 == phone_e164))
    return res.scalar_one_or_none()


async def list_leads(
    session: AsyncSession,
    page: int = 1,
    size: int = 50,
    enrichment_status: str | None = None,
    apollo_matched: bool | None = None,
    cidade: str | None = None,
    estado: str | None = None,
    q: str | None = None,
) -> tuple[list[Lead], int]:
    filters = {
        "enrichment_status": enrichment_status,
        "apollo_matched": apollo_matched,
        "cidade": cidade,
        "estado": estado,
        "q": q,
    }
    base = _apply_filters(select(Lead), **filters)
    count_q = _apply_filters(select(func.count()).select_from(Lead), **filters)

    total = (await session.execute(count_q)).scalar_one()
    rows = (
        await session.execute(
            base.order_by(Lead.created_at.desc()).offset((page - 1) * size).limit(size)
        )
    ).scalars().all()
    return list(rows), total


def _target_predicate(providers: list[str] | None):
    """Predicado de "ainda há trabalho" para o run, conforme o escopo de providers.

    - Apollo no escopo: dirigido por ``enrichment_status == 'pending'`` (fluxo de
      créditos com rodadas por e-mail).
    - Sem Apollo: dirigido por "este provider ainda não tocou o lead"
      (``<provider>_enriched_at IS NULL``). Isso permite que uma fonte NOVA
      (ex.: Google Maps) enriqueça a base já terminal sem rechamar o Apollo.
    """
    provs = providers or []
    if "apollo" in provs:
        return Lead.enrichment_status == "pending"
    if "google_maps" in provs:
        return Lead.google_maps_enriched_at.is_(None)
    if "viacep" in provs:
        return Lead.viacep_enriched_at.is_(None)
    return Lead.enrichment_status == "pending"


async def select_targets(
    session: AsyncSession,
    *,
    with_email: bool | None,
    after_id: uuid.UUID | None,
    limit: int | None,
    cidade: str | None = None,
    estado: str | None = None,
    providers: list[str] | None = None,
) -> list[Lead]:
    """Seleciona leads-alvo para enriquecer, ordenados por id (resume determinístico).

    O conjunto-alvo depende do escopo (ver ``_target_predicate``). ``with_email``
    (True/False) só vale no fluxo do Apollo; None = sem filtro de e-mail.
    """
    stmt = select(Lead).where(_target_predicate(providers))
    if with_email is True:
        stmt = stmt.where(Lead.email.is_not(None))
    elif with_email is False:
        stmt = stmt.where(Lead.email.is_(None))
    if cidade:
        stmt = stmt.where(Lead.cidade == cidade)
    if estado:
        stmt = stmt.where(Lead.estado == estado)
    if after_id is not None:
        stmt = stmt.where(Lead.id > after_id)
    stmt = stmt.order_by(Lead.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def count_targets(
    session: AsyncSession,
    *,
    cidade: str | None = None,
    estado: str | None = None,
    providers: list[str] | None = None,
) -> int:
    stmt = select(func.count()).select_from(Lead).where(_target_predicate(providers))
    if cidade:
        stmt = stmt.where(Lead.cidade == cidade)
    if estado:
        stmt = stmt.where(Lead.estado == estado)
    return (await session.execute(stmt)).scalar_one()


async def patch_fields(
    session: AsyncSession,
    lead: Lead,
    patch: dict[str, Any],
    provenance: dict[str, str],
    *,
    provider: str | None,
    apollo_matched: bool | None = None,
    status: str | None = None,
    note: str | None = None,
) -> None:
    """Aplica patch (só colunas preenchidas) + provenance + flags no lead."""
    now = datetime.now(UTC)
    for col, value in patch.items():
        setattr(lead, col, value)
    if provenance:
        prov = dict(lead.field_provenance or {})
        prov.update(provenance)
        lead.field_provenance = prov
    if provider == "apollo":
        lead.apollo_enriched_at = now
        if apollo_matched is not None:
            lead.apollo_matched = apollo_matched
    elif provider == "viacep":
        lead.viacep_enriched_at = now
    elif provider == "google_maps":
        lead.google_maps_enriched_at = now
    if status is not None:
        lead.enrichment_status = status
    if note is not None:
        lead.enrichment_note = note
    await session.flush()


async def stats(session: AsyncSession) -> dict[str, Any]:
    """KPIs do dashboard: total, completude média (% sobre o core set) e pendentes Apollo."""
    total = (await session.execute(select(func.count()).select_from(Lead))).scalar_one()
    if not total:
        return {"total_leads": 0, "completude_media_pct": 0.0, "pendentes_apollo": 0}

    pendentes = (
        await session.execute(
            select(func.count())
            .select_from(Lead)
            .where(or_(Lead.enrichment_status == "pending", Lead.apollo_matched.is_(False)))
        )
    ).scalar_one()

    # Soma por linha de campos preenchidos sobre o core set, depois média entre linhas.
    row_sum: ColumnElement[int] | None = None
    for name in CORE_COMPLETENESS_FIELDS:
        expr = _filled_expr(name)
        row_sum = expr if row_sum is None else row_sum + expr
    avg_filled = (await session.execute(select(func.avg(row_sum)))).scalar_one()
    completude = (
        round(float(avg_filled) / len(CORE_COMPLETENESS_FIELDS) * 100, 1)
        if avg_filled is not None
        else 0.0
    )

    return {
        "total_leads": int(total),
        "completude_media_pct": completude,
        "pendentes_apollo": int(pendentes),
    }


async def field_coverage(session: AsyncSession, **filters: Any) -> list[dict[str, Any]]:
    """Cobertura por campo (filled/missing/%), com os mesmos filtros de ``list_leads``."""
    total = (
        await session.execute(_apply_filters(select(func.count()).select_from(Lead), **filters))
    ).scalar_one()

    agg_cols = [func.sum(_filled_expr(col)).label(col) for col, _label in COVERAGE_FIELDS]
    agg_stmt = _apply_filters(select(*agg_cols).select_from(Lead), **filters)
    row = (await session.execute(agg_stmt)).one()

    out: list[dict[str, Any]] = []
    for idx, (col, label) in enumerate(COVERAGE_FIELDS):
        filled = int(row[idx] or 0)
        pct = round(filled / total * 100, 1) if total else 0.0
        out.append(
            {
                "field": col,
                "label": label,
                "filled": filled,
                "missing": int(total) - filled,
                "coverage_pct": pct,
                "sources": FIELD_SOURCES.get(col, []),
            }
        )
    return out


async def iter_export_rows(session: AsyncSession, **filters: Any) -> AsyncIterator[Lead]:
    """Streaming de leads para exportação (não materializa toda a base em memória)."""
    stmt = _apply_filters(select(Lead), **filters).order_by(Lead.created_at.desc())
    result = await session.stream(stmt)
    async for lead in result.scalars():
        yield lead

"""Acesso a dados de ``leads`` (sem regra de negócio)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.merge import fill_only_empty, is_empty
from app.models.lead import Lead

# Colunas mapeáveis (exclui PK/timestamps/controle) — usadas no upsert e provenance
_CSV_PROVENANCE_SKIP = {"phone_e164", "raw_source"}


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
    conditions = []
    if enrichment_status is not None:
        conditions.append(Lead.enrichment_status == enrichment_status)
    if apollo_matched is not None:
        conditions.append(Lead.apollo_matched == apollo_matched)
    if cidade:
        conditions.append(Lead.cidade == cidade)
    if estado:
        conditions.append(Lead.estado == estado)
    if q:
        like = f"%{q}%"
        conditions.append(Lead.nome_completo.ilike(like))

    base = select(Lead)
    count_q = select(func.count()).select_from(Lead)
    for c in conditions:
        base = base.where(c)
        count_q = count_q.where(c)

    total = (await session.execute(count_q)).scalar_one()
    rows = (
        await session.execute(
            base.order_by(Lead.created_at.desc()).offset((page - 1) * size).limit(size)
        )
    ).scalars().all()
    return list(rows), total


async def select_targets(
    session: AsyncSession,
    *,
    with_email: bool | None,
    after_id: uuid.UUID | None,
    limit: int | None,
    cidade: str | None = None,
    estado: str | None = None,
) -> list[Lead]:
    """Seleciona leads pendentes para enriquecer, ordenados por id (resume determinístico).

    ``with_email``: True = só com e-mail (rodada 1); False = sem e-mail (rodada 2);
    None = todos pendentes.
    """
    stmt = select(Lead).where(Lead.enrichment_status == "pending")
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
) -> int:
    stmt = select(func.count()).select_from(Lead).where(Lead.enrichment_status == "pending")
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
    if status is not None:
        lead.enrichment_status = status
    await session.flush()

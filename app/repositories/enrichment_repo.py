"""Acesso a dados de ``enrichment_runs`` e ``enrichment_events``."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enrichment_event import EnrichmentEvent
from app.models.enrichment_run import EnrichmentRun


async def create_run(
    session: AsyncSession,
    *,
    provider_scope: list[str],
    params: dict[str, Any] | None = None,
) -> EnrichmentRun:
    run = EnrichmentRun(provider_scope=provider_scope, params=params, status="queued")
    session.add(run)
    await session.flush()
    return run


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> EnrichmentRun | None:
    return await session.get(EnrichmentRun, run_id)


async def list_runs(session: AsyncSession, limit: int = 50) -> list[EnrichmentRun]:
    res = await session.execute(
        select(EnrichmentRun).order_by(EnrichmentRun.created_at.desc()).limit(limit)
    )
    return list(res.scalars().all())


async def log_event(
    session: AsyncSession,
    *,
    run_id: uuid.UUID | None,
    lead_id: uuid.UUID | None,
    provider: str | None,
    level: str,
    event_type: str | None = None,
    message: str | None = None,
    fields_filled: list[str] | None = None,
    http_status: int | None = None,
    payload: dict | None = None,
) -> None:
    event = EnrichmentEvent(
        run_id=run_id,
        lead_id=lead_id,
        provider=provider,
        level=level,
        event_type=event_type,
        message=message,
        fields_filled=fields_filled,
        http_status=http_status,
        payload=payload,
    )
    session.add(event)


async def list_events(
    session: AsyncSession,
    run_id: uuid.UUID,
    level: str | None = None,
    limit: int = 200,
) -> list[EnrichmentEvent]:
    stmt = select(EnrichmentEvent).where(EnrichmentEvent.run_id == run_id)
    if level:
        stmt = stmt.where(EnrichmentEvent.level == level)
    stmt = stmt.order_by(EnrichmentEvent.id.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())

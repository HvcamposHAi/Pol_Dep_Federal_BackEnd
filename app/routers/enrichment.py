"""Endpoints de enriquecimento: criar run, status, eventos, cancelar.

O run pesado roda via CLI (``python -m app.cli enrich --run-id <id>``). A API
apenas cria a linha ``queued``. Para conveniência em dev, ``start_inline=true``
dispara o orquestrador em uma task asyncio no próprio processo.
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db, get_sessionmaker
from app.repositories import enrichment_repo
from app.schemas.common import Page
from app.schemas.enrichment import EventOut, RunCreate, RunOut, RunStatusOut
from app.services.enrichment_orchestrator import EnrichmentOrchestrator

router = APIRouter(prefix="/enrichment", tags=["enrichment"])


def _progress(run) -> float:
    if not run.total_targets:
        return 0.0
    return round(min(100.0, run.processed_count / run.total_targets * 100.0), 1)


@router.post("/runs", response_model=RunOut, status_code=202)
async def create_run(
    body: RunCreate,
    start_inline: bool = Query(False, description="dispara o run inline (dev)"),
    session: AsyncSession = Depends(get_db),
) -> RunOut:
    params = {
        "filters": body.filters.model_dump(),
        "dry_run": body.dry_run,
        "rate_limit": body.rate_limit,
    }
    run = await enrichment_repo.create_run(
        session, provider_scope=body.providers, params=params
    )
    await session.commit()

    if start_inline:
        settings = get_settings()
        if body.rate_limit:
            settings.apollo_rate_limit = body.rate_limit
        orchestrator = EnrichmentOrchestrator(settings, get_sessionmaker())
        asyncio.create_task(
            orchestrator.run(
                run.id, dry_run=body.dry_run, filters=body.filters.model_dump()
            )
        )

    return RunOut.model_validate(run)


@router.get("/runs", response_model=Page[RunOut])
async def list_runs(
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
) -> Page[RunOut]:
    runs = await enrichment_repo.list_runs(session, limit=limit)
    items = [RunOut.model_validate(r) for r in runs]
    return Page[RunOut](items=items, page=1, size=limit, total=len(items))


@router.get("/runs/{run_id}", response_model=RunStatusOut)
async def get_run(run_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> RunStatusOut:
    run = await enrichment_repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run não encontrado")
    out = RunStatusOut.model_validate(run)
    out.progress_pct = _progress(run)
    return out


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(run_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> RunOut:
    run = await enrichment_repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run não encontrado")
    if run.status in ("completed", "failed"):
        raise HTTPException(status_code=409, detail=f"run já está {run.status}")
    run.status = "canceled"
    await session.commit()
    return RunOut.model_validate(run)


@router.get("/runs/{run_id}/events", response_model=Page[EventOut])
async def list_events(
    run_id: uuid.UUID,
    level: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    session: AsyncSession = Depends(get_db),
) -> Page[EventOut]:
    events = await enrichment_repo.list_events(session, run_id, level=level, limit=limit)
    items = [EventOut.model_validate(e) for e in events]
    return Page[EventOut](items=items, page=1, size=limit, total=len(items))

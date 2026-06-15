"""Endpoints de enriquecimento: criar run, status, eventos, cancelar.

O run pesado roda via CLI (``python -m app.cli enrich --run-id <id>``). A API
apenas cria a linha ``queued``. Para conveniência em dev, ``start_inline=true``
dispara o orquestrador em uma task asyncio no próprio processo.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db, get_sessionmaker
from app.repositories import enrichment_repo
from app.schemas.common import Page
from app.schemas.enrichment import EventOut, RunCreate, RunOut, RunStatusOut
from app.services import export_service
from app.services.enrichment_orchestrator import EnrichmentOrchestrator

router = APIRouter(prefix="/enrichment", tags=["enrichment"])

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Sem heartbeat há mais que isto, um run "running" é considerado morto (processo
# encerrado por reload/crash) e marcado como ``failed`` — destrava a UI.
_RUN_STALE_AFTER_SECONDS = 120

# Mantém referência forte às tasks inline (evita coleta pelo GC enquanto rodam).
_inline_tasks: set[asyncio.Task] = set()


def _progress(run) -> float:
    if not run.total_targets:
        return 0.0
    return round(min(100.0, run.processed_count / run.total_targets * 100.0), 1)


def _heartbeat_age_seconds(run) -> float | None:
    """Idade (s) do último sinal de vida do run; None se nunca houve referência."""
    ts = (run.checkpoint or {}).get("heartbeat")
    ref: datetime | None = None
    if ts:
        try:
            ref = datetime.fromisoformat(ts)
        except (TypeError, ValueError):
            ref = None
    if ref is None:
        ref = run.started_at
    if ref is None:
        return None
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=UTC)
    return (datetime.now(UTC) - ref).total_seconds()


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
        task = asyncio.create_task(
            orchestrator.run(
                run.id, dry_run=body.dry_run, filters=body.filters.model_dump()
            )
        )
        # Sem manter referência, o GC pode coletar a task e o run morre "running".
        _inline_tasks.add(task)
        task.add_done_callback(_inline_tasks.discard)

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

    # Watchdog: um run "running" sem heartbeat recente teve o processo encerrado
    # (reload/crash). Marca como failed para a UI sair do estado travado.
    if run.status == "running":
        age = _heartbeat_age_seconds(run)
        if age is not None and age > _RUN_STALE_AFTER_SECONDS:
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            await enrichment_repo.log_event(
                session,
                run_id=run_id,
                lead_id=None,
                provider="orchestrator",
                level="error",
                event_type="run_stalled",
                message=(
                    f"Run sem progresso há {int(age)}s (processo encerrado?). "
                    "Marcado como failed. Retome pela CLI: "
                    f"python -m app.cli enrich --run-id {run_id}"
                ),
            )
            await session.commit()

    out = RunStatusOut.model_validate(run)
    out.progress_pct = _progress(run)
    return out


@router.get("/runs/{run_id}/export")
async def export_run(
    run_id: uuid.UUID,
    format: Literal["csv", "xlsx"] = Query("csv"),
    session: AsyncSession = Depends(get_db),
):
    """Baixa o PARCIAL do run a qualquer momento: leads já processados (não
    pendentes) dentro do escopo de filtros do run, com o estado atual do banco.
    Como o orquestrador faz commit por lead, reflete tudo o que já foi feito."""
    run = await enrichment_repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run não encontrado")
    run_filters = (run.params or {}).get("filters") or {}
    filters = {
        "cidade": run_filters.get("cidade"),
        "estado": run_filters.get("estado"),
        "processed_only": True,
    }
    suffix = "csv" if format == "csv" else "xlsx"
    disposition = f"attachment; filename=parcial_run_{run_id}.{suffix}"
    if format == "xlsx":
        content = await export_service.build_xlsx(session, **filters)
        return Response(
            content=content,
            media_type=_XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": disposition},
        )
    return StreamingResponse(
        export_service.stream_csv(session, **filters),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )


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

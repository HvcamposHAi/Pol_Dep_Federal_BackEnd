"""Endpoint de estatísticas do dashboard (GET /stats)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories import lead_repo
from app.schemas.stats import StatsOut

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=StatsOut)
async def get_stats(session: AsyncSession = Depends(get_db)) -> StatsOut:
    data = await lead_repo.stats(session)
    return StatsOut(**data)

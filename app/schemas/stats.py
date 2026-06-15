"""Schemas de estatísticas (dashboard KPIs e cobertura de campos)."""

from __future__ import annotations

from pydantic import BaseModel


class StatsOut(BaseModel):
    """KPIs do dashboard (GET /stats)."""

    total_leads: int
    completude_media_pct: float
    pendentes_apollo: int


class FieldCoverageOut(BaseModel):
    """Cobertura de um campo (GET /leads/field-coverage)."""

    field: str
    label: str
    filled: int
    missing: int
    coverage_pct: float
    sources: list[str]

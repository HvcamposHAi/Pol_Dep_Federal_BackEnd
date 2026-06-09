"""Schemas de enriquecimento (run + eventos)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RunFilters(BaseModel):
    """Filtros opcionais para selecionar leads do run."""

    limit: int | None = Field(default=None, ge=1)
    cidade: str | None = None
    estado: str | None = None
    only_missing_email: bool = False


class RunCreate(BaseModel):
    providers: list[str] = Field(default_factory=lambda: ["viacep", "apollo"])
    filters: RunFilters = Field(default_factory=RunFilters)
    dry_run: bool = False
    rate_limit: int | None = Field(default=None, ge=1, description="req/min Apollo (override)")


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    provider_scope: list[str]
    total_targets: int
    processed_count: int
    matched_count: int
    error_count: int
    current_round: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


class RunStatusOut(RunOut):
    progress_pct: float = 0.0


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    provider: str | None = None
    level: str
    event_type: str | None = None
    message: str | None = None
    fields_filled: list[str] | None = None
    http_status: int | None = None
    created_at: datetime | None = None

"""Model ORM ``enrichment_runs`` — run + checkpoint/resume."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.models.base import Base, JSONType, text_array


class EnrichmentRun(Base):
    __tablename__ = "enrichment_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="queued", server_default="queued"
    )
    provider_scope: Mapped[list[str]] = mapped_column(
        text_array(), nullable=False, default=lambda: ["viacep", "apollo"]
    )
    total_targets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_processed_lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid())
    current_round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    checkpoint: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    params: Mapped[dict | None] = mapped_column(JSONType)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

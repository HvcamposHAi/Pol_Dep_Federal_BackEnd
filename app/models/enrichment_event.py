"""Model ORM ``enrichment_events`` — log + erros."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.models.base import Base, JSONType, text_array


class EnrichmentEvent(Base):
    __tablename__ = "enrichment_events"

    # SQLite só auto-incrementa INTEGER PRIMARY KEY; no Postgres permanece bigint identity
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("enrichment_runs.id", ondelete="CASCADE")
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("leads.id", ondelete="SET NULL")
    )
    provider: Mapped[str | None] = mapped_column(String)
    level: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str | None] = mapped_column(String)
    message: Mapped[str | None] = mapped_column(Text)
    fields_filled: Mapped[list[str] | None] = mapped_column(text_array())
    http_status: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

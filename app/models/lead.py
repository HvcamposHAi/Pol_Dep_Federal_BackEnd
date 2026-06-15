"""Model ORM ``leads`` — espelha docs/schema.sql."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.models.base import Base, JSONType, text_array


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    phone_e164: Mapped[str] = mapped_column(Text, unique=True, nullable=False)

    nome_completo: Mapped[str | None] = mapped_column(Text)
    nome: Mapped[str | None] = mapped_column(Text)
    sobrenome: Mapped[str | None] = mapped_column(Text)
    nome_preferido: Mapped[str | None] = mapped_column(Text)
    telefone_bruto: Mapped[str | None] = mapped_column(Text)
    celular2: Mapped[str | None] = mapped_column(Text)
    telefone_fixo: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    documento: Mapped[str | None] = mapped_column(Text)
    data_nascimento: Mapped[date | None] = mapped_column(Date)
    genero: Mapped[str | None] = mapped_column(Text)
    cep: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str | None] = mapped_column(Text)
    cidade: Mapped[str | None] = mapped_column(Text)
    bairro: Mapped[str | None] = mapped_column(Text)
    regiao: Mapped[str | None] = mapped_column(Text)
    endereco: Mapped[str | None] = mapped_column(Text)
    numero: Mapped[str | None] = mapped_column(Text)
    complemento: Mapped[str | None] = mapped_column(Text)
    zona_eleitoral: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric)
    profissao: Mapped[str | None] = mapped_column(Text)
    profissao2: Mapped[str | None] = mapped_column(Text)
    cargos_autoridade: Mapped[str | None] = mapped_column(Text)
    cargo_autoridade_legado: Mapped[str | None] = mapped_column(Text)
    tipo_contato: Mapped[str | None] = mapped_column(Text)
    intencao_voto: Mapped[str | None] = mapped_column(Text)
    nivel_influencia: Mapped[str | None] = mapped_column(Text)
    potencial_mobilizacao: Mapped[str | None] = mapped_column(Text)
    votos_mobilizados: Mapped[int | None] = mapped_column(Integer)
    possivel_doador: Mapped[bool | None] = mapped_column(Boolean)
    estagio_relacionamento: Mapped[str | None] = mapped_column(Text)
    status_relacionamento: Mapped[str | None] = mapped_column(Text)
    nivel_engajamento: Mapped[str | None] = mapped_column(Text)
    score_relacionamento: Mapped[Decimal | None] = mapped_column(Numeric)
    canal_preferencial: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str] | None] = mapped_column(text_array())
    interesses: Mapped[list[str] | None] = mapped_column(text_array())
    lider_responsavel: Mapped[str | None] = mapped_column(Text)
    usuario_responsavel: Mapped[str | None] = mapped_column(Text)
    origem_primeiro_contato: Mapped[str | None] = mapped_column(Text)
    origem_ultimo_contato: Mapped[str | None] = mapped_column(Text)
    ultima_interacao: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    whatsapp_autorizado: Mapped[bool | None] = mapped_column(Boolean)
    superfa: Mapped[bool | None] = mapped_column(Boolean)
    observacoes: Mapped[str | None] = mapped_column(Text)
    instagram: Mapped[str | None] = mapped_column(Text)
    engajamento_instagram: Mapped[str | None] = mapped_column(Text)
    facebook: Mapped[str | None] = mapped_column(Text)
    twitter: Mapped[str | None] = mapped_column(Text)
    tiktok: Mapped[str | None] = mapped_column(Text)
    linkedin: Mapped[str | None] = mapped_column(Text)
    criado_em_origem: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    atualizado_em_origem: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # enriquecimento / auditoria
    apollo_matched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    apollo_enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    viacep_enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrichment_status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    # Motivo/resumo do tratamento (positivo: campos preenchidos; negativo: razão).
    enrichment_note: Mapped[str | None] = mapped_column(Text)
    field_provenance: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    raw_source: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

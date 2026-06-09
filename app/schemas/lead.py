"""Schemas de leads (saída da API + resultado do import)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class LeadOut(BaseModel):
    """Representação de um lead na API (espelha o model, campos opcionais)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    phone_e164: str
    nome_completo: str | None = None
    nome: str | None = None
    sobrenome: str | None = None
    nome_preferido: str | None = None
    telefone_bruto: str | None = None
    celular2: str | None = None
    telefone_fixo: str | None = None
    email: str | None = None
    documento: str | None = None
    data_nascimento: date | None = None
    genero: str | None = None
    cep: str | None = None
    estado: str | None = None
    cidade: str | None = None
    bairro: str | None = None
    regiao: str | None = None
    endereco: str | None = None
    numero: str | None = None
    complemento: str | None = None
    zona_eleitoral: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    profissao: str | None = None
    profissao2: str | None = None
    cargos_autoridade: str | None = None
    cargo_autoridade_legado: str | None = None
    tipo_contato: str | None = None
    intencao_voto: str | None = None
    nivel_influencia: str | None = None
    potencial_mobilizacao: str | None = None
    votos_mobilizados: int | None = None
    possivel_doador: bool | None = None
    estagio_relacionamento: str | None = None
    status_relacionamento: str | None = None
    nivel_engajamento: str | None = None
    score_relacionamento: Decimal | None = None
    canal_preferencial: str | None = None
    tags: list[str] | None = None
    interesses: list[str] | None = None
    lider_responsavel: str | None = None
    usuario_responsavel: str | None = None
    origem_primeiro_contato: str | None = None
    origem_ultimo_contato: str | None = None
    ultima_interacao: datetime | None = None
    whatsapp_autorizado: bool | None = None
    superfa: bool | None = None
    observacoes: str | None = None
    instagram: str | None = None
    engajamento_instagram: str | None = None
    facebook: str | None = None
    twitter: str | None = None
    tiktok: str | None = None
    linkedin: str | None = None
    criado_em_origem: datetime | None = None
    atualizado_em_origem: datetime | None = None
    apollo_matched: bool = False
    apollo_enriched_at: datetime | None = None
    viacep_enriched_at: datetime | None = None
    enrichment_status: str = "pending"
    field_provenance: dict = {}
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RejectedRow(BaseModel):
    linha: int
    motivo: str
    nome: str | None = None


class ImportResult(BaseModel):
    total: int
    inserted: int
    updated: int
    skipped: int
    rejected: list[RejectedRow] = []
    errors: list[str] = []

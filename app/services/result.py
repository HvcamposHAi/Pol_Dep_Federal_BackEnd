"""Resultado padronizado de um provider de enriquecimento (sem I/O de banco)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderResult:
    provider: str
    matched: bool = False
    candidate: dict[str, Any] = field(default_factory=dict)  # coluna do banco -> valor
    http_status: int | None = None
    error: str | None = None
    payload: dict | None = None  # trecho da resposta para log (SEM segredos)

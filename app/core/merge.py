"""Regra de merge "preenche só o que está vazio" (função pura, sem I/O).

Coração da garantia de integridade: o enriquecimento NUNCA sobrescreve um dado já
existente — apenas preenche colunas vazias. Usado por Apollo e ViaCEP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MergeResult:
    patch: dict[str, Any] = field(default_factory=dict)  # coluna -> novo valor
    fields_filled: list[str] = field(default_factory=list)  # colunas preenchidas
    provenance: dict[str, str] = field(default_factory=dict)  # coluna -> provider


def is_empty(value: Any) -> bool:
    """Considera vazio: ``None``, string vazia/whitespace, lista/dict vazios."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def fill_only_empty(
    current: dict[str, Any],
    incoming: dict[str, Any],
    provider: str,
) -> MergeResult:
    """Preenche em ``current`` apenas as colunas vazias com valores não-vazios de
    ``incoming``. Retorna o patch, as colunas preenchidas e a procedência.

    - Nunca sobrescreve valor já presente em ``current``.
    - Valor vazio em ``incoming`` é ignorado.
    - Função pura: não muta ``current`` nem ``incoming``.
    """
    result = MergeResult()
    for column, new_value in incoming.items():
        if is_empty(new_value):
            continue
        if not is_empty(current.get(column)):
            continue  # já preenchido -> preserva
        result.patch[column] = new_value
        result.fields_filled.append(column)
        result.provenance[column] = provider
    return result

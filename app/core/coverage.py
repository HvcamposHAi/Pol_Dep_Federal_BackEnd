"""Definições de completude e cobertura de campos (fonte única de verdade).

Usado por ``GET /stats`` e ``GET /leads/field-coverage``. A definição de
"completude" (``CORE_COMPLETENESS_FIELDS``) é espelhada no frontend em
``src/lib/leadFields.ts::COMPLETENESS_KEYS`` — manter as duas listas idênticas
(há teste de drift garantindo isso). Os labels reaproveitam ``COLUMN_DEFS``
(``column_mapping``) para não duplicar texto. ``FIELD_SOURCES`` é derivado dos
mapas dos provedores (advisory: quais provedores PODEM preencher o campo, não
proveniência por linha).
"""

from __future__ import annotations

from app.core.column_mapping import COLUMN_DEFS
from app.services.apollo_service import _FIELD_MAP as _APOLLO_MAP
from app.services.viacep_service import _FIELD_MAP as _VIACEP_MAP

# Coluna do banco -> label legível (espelha os cabeçalhos do CSV/import).
_LABELS: dict[str, str] = {column: header for header, column, _kind in COLUMN_DEFS}


def _label(column: str) -> str:
    return _LABELS.get(column, column)


# Campos que definem a "completude média" (idêntico ao front COMPLETENESS_KEYS).
CORE_COMPLETENESS_FIELDS: list[str] = [
    "nome_completo",
    "email",
    "profissao",
    "cidade",
    "cep",
    "linkedin",
    "instagram",
    "sobrenome",
    "data_nascimento",
]

# Campos reportados no diagnóstico de lacunas (7 do plano + extras do core).
_COVERAGE_COLUMNS: list[str] = [
    "email",
    "sobrenome",
    "profissao",
    "cidade",
    "cep",
    "linkedin",
    "instagram",
    "nome_completo",
    "data_nascimento",
]

# (coluna, label) ordenado.
COVERAGE_FIELDS: list[tuple[str, str]] = [(c, _label(c)) for c in _COVERAGE_COLUMNS]

# Colunas em que "preenchido" = NOT NULL apenas (sem trim — não são texto).
# Datas/numéricos não toleram ``trim()`` no Postgres.
NON_TEXT_FIELDS: frozenset[str] = frozenset({"data_nascimento", "latitude", "longitude"})


def _build_field_sources() -> dict[str, list[str]]:
    """Inverte os _FIELD_MAP de Apollo e ViaCEP: coluna -> [provedores]."""
    sources: dict[str, list[str]] = {}
    for col in _APOLLO_MAP.values():
        sources.setdefault(col, [])
        if "apollo" not in sources[col]:
            sources[col].append("apollo")
    for col in _VIACEP_MAP.values():
        sources.setdefault(col, [])
        if "viacep" not in sources[col]:
            sources[col].append("viacep")
    return sources


# Coluna -> provedores que podem preenchê-la (advisory).
FIELD_SOURCES: dict[str, list[str]] = _build_field_sources()

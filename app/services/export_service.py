"""Exportação de leads em CSV (;) ou XLSX, respeitando os filtros de listagem.

Layout de colunas = ``COLUMN_DEFS`` (mesma ordem/labels do import) — o arquivo
exportado pode ser reimportado sem corromper dados (round-trip). CSV é gerado em
streaming (não materializa a base); XLSX usa workbook write-only (memória limitada).
"""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.column_mapping import COLUMN_DEFS
from app.repositories import lead_repo

# (coluna no banco, cabeçalho) na ordem canônica do import.
EXPORT_COLUMNS: list[tuple[str, str]] = [(column, header) for header, column, _kind in COLUMN_DEFS]
# Colunas extras de enriquecimento (computadas), sempre ao final.
_EXTRA_HEADERS: list[str] = ["Resultado", "Status enriquecimento", "Motivo enriquecimento"]
_HEADERS: list[str] = [header for _col, header in EXPORT_COLUMNS] + _EXTRA_HEADERS

_POSITIVO = {"enriched"}
_NEGATIVO = {"skipped", "failed"}


def _resultado(status: str | None) -> str:
    if status in _POSITIVO:
        return "Positivo"
    if status in _NEGATIVO:
        return "Negativo"
    return ""  # pendente / não tratado


def _cell(value: Any) -> str:
    """Serializa um valor de célula de forma compatível com o import."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Sim" if value else "Não"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _row(lead: Any) -> list[str]:
    status = getattr(lead, "enrichment_status", None)
    base = [_cell(getattr(lead, col, None)) for col, _header in EXPORT_COLUMNS]
    base += [_resultado(status), _cell(status), _cell(getattr(lead, "enrichment_note", None))]
    return base


async def stream_csv(session: AsyncSession, **filters: Any) -> AsyncIterator[bytes]:
    """Gera o CSV (BOM UTF-8, separador ';') incrementalmente, linha a linha."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\n")

    writer.writerow(_HEADERS)
    yield "﻿".encode() + buf.getvalue().encode("utf-8")
    buf.seek(0)
    buf.truncate(0)

    async for lead in lead_repo.iter_export_rows(session, **filters):
        writer.writerow(_row(lead))
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate(0)


async def build_xlsx(session: AsyncSession, **filters: Any) -> bytes:
    """Monta um .xlsx em memória (workbook write-only, memória limitada)."""
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("contatos")
    ws.append(_HEADERS)
    async for lead in lead_repo.iter_export_rows(session, **filters):
        ws.append(_row(lead))
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()

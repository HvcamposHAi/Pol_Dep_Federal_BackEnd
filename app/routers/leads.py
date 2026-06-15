"""Endpoints de leads: importação, listagem e consulta."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories import lead_repo
from app.schemas.common import Page
from app.schemas.lead import ImportResult, LeadOut
from app.schemas.stats import FieldCoverageOut
from app.services import export_service, import_service

router = APIRouter(prefix="/leads", tags=["leads"])

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.post("/import", response_model=ImportResult)
async def import_leads(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
) -> ImportResult:
    content = await file.read()
    return await import_service.import_bytes(session, file.filename or "upload", content)


@router.get("", response_model=Page[LeadOut])
async def list_leads(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    enrichment_status: str | None = None,
    apollo_matched: bool | None = None,
    cidade: str | None = None,
    estado: str | None = None,
    q: str | None = None,
    session: AsyncSession = Depends(get_db),
) -> Page[LeadOut]:
    items, total = await lead_repo.list_leads(
        session,
        page=page,
        size=size,
        enrichment_status=enrichment_status,
        apollo_matched=apollo_matched,
        cidade=cidade,
        estado=estado,
        q=q,
    )
    return Page[LeadOut](
        items=[LeadOut.model_validate(i) for i in items], page=page, size=size, total=total
    )


@router.get("/field-coverage", response_model=list[FieldCoverageOut])
async def field_coverage(
    enrichment_status: str | None = None,
    apollo_matched: bool | None = None,
    cidade: str | None = None,
    estado: str | None = None,
    q: str | None = None,
    session: AsyncSession = Depends(get_db),
) -> list[FieldCoverageOut]:
    rows = await lead_repo.field_coverage(
        session,
        enrichment_status=enrichment_status,
        apollo_matched=apollo_matched,
        cidade=cidade,
        estado=estado,
        q=q,
    )
    return [FieldCoverageOut(**r) for r in rows]


@router.get("/export")
async def export_leads(
    format: Literal["csv", "xlsx"] = Query("csv"),
    enrichment_status: str | None = None,
    apollo_matched: bool | None = None,
    cidade: str | None = None,
    estado: str | None = None,
    q: str | None = None,
    session: AsyncSession = Depends(get_db),
):
    filters = {
        "enrichment_status": enrichment_status,
        "apollo_matched": apollo_matched,
        "cidade": cidade,
        "estado": estado,
        "q": q,
    }
    if format == "xlsx":
        content = await export_service.build_xlsx(session, **filters)
        return Response(
            content=content,
            media_type=_XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": "attachment; filename=contatos.xlsx"},
        )
    return StreamingResponse(
        export_service.stream_csv(session, **filters),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=contatos.csv"},
    )


@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead(lead_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> LeadOut:
    lead = await lead_repo.get(session, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead não encontrado")
    return LeadOut.model_validate(lead)


@router.get("/by-phone/{phone_e164}", response_model=LeadOut)
async def get_lead_by_phone(
    phone_e164: str, session: AsyncSession = Depends(get_db)
) -> LeadOut:
    lead = await lead_repo.get_by_phone(session, phone_e164)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead não encontrado")
    return LeadOut.model_validate(lead)

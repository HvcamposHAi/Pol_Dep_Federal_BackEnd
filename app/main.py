"""Aplicação FastAPI — factory + lifespan."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.core.http_client import close_client, init_client
from app.db.session import dispose_engine, get_engine
from app.routers import config, enrichment, health, leads, stats

# Frontend buildado (gerado por build_bundle). Vazio em dev (usa o Vite separado).
_STATIC = Path(__file__).resolve().parent.parent / "static"


async def _init_sqlite_schema() -> None:
    """Instalador local: cria as tabelas automaticamente quando o banco é SQLite."""
    settings = get_settings()
    if not settings.database_url.startswith("sqlite"):
        return  # Postgres/Supabase usa docs/schema.sql (não auto-criar em prod)
    # importa os models para registrar as tabelas no metadata
    from app.models import enrichment_event, enrichment_run, lead  # noqa: F401
    from app.models.base import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_client()  # cliente httpx compartilhado
    await _init_sqlite_schema()
    yield
    await close_client()
    await dispose_engine()


def _mount_frontend(app: FastAPI) -> None:
    """Serve o frontend buildado no mesmo servidor (instalador 1 processo/1 porta)."""
    if not (_STATIC / "index.html").exists():
        return
    assets = _STATIC / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        # As rotas de API foram registradas antes e têm prioridade; aqui cai o resto.
        candidate = _STATIC / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_STATIC / "index.html")  # fallback SPA (React Router)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Pol Dep Federal — Backend de Enriquecimento de Leads",
        version="0.1.0",
        lifespan=lifespan,
    )
    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    app.include_router(health.router)
    app.include_router(leads.router)
    app.include_router(enrichment.router)
    app.include_router(stats.router)
    app.include_router(config.router)
    _mount_frontend(app)  # por último: API tem prioridade, resto cai no SPA
    return app


app = create_app()

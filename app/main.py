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
    """Banco local (SQLite, padrão): cria as tabelas e adiciona colunas novas que
    ainda não existam — assim o ``dev.db`` se mantém em dia ao evoluir os models,
    sem migração manual. (Postgres é opcional e NÃO é auto-criado: usa docs/schema.sql.)"""
    settings = get_settings()
    if not settings.database_url.startswith("sqlite"):
        return
    # importa os models para registrar as tabelas no metadata
    from app.models import enrichment_event, enrichment_run, lead  # noqa: F401
    from app.models.base import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_sqlite_add_missing_columns)


def _sqlite_add_missing_columns(conn) -> None:
    """SQLite-only: adiciona (como NULLable) colunas presentes nos models mas
    ausentes em tabelas JÁ existentes — ``create_all`` não altera tabela criada.
    Evita o 500 'no such column' ao adicionar campos sem migração formal no local."""
    from sqlalchemy import inspect, text

    from app.models import enrichment_event, enrichment_run, lead  # noqa: F401
    from app.models.base import Base

    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # tabela nova: já criada por create_all
        present = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            col_type = column.type.compile(dialect=conn.dialect)
            conn.execute(
                text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}')
            )


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

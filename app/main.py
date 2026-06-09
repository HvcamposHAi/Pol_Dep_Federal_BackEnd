"""Aplicação FastAPI — factory + lifespan."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.http_client import close_client, init_client
from app.db.session import dispose_engine
from app.routers import enrichment, health, leads


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_client()  # cliente httpx compartilhado
    yield
    await close_client()
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Pol Dep Federal — Backend de Enriquecimento de Leads",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(leads.router)
    app.include_router(enrichment.router)
    return app


app = create_app()

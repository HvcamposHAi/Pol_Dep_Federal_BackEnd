"""Fixtures de teste: banco SQLite em memória + sessionmaker."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.models.base import Base

DATA_DIR = Path(__file__).parent / "data"


@pytest_asyncio.fixture
async def sessionmaker_fixture():
    """Engine SQLite em memória compartilhada (StaticPool) com as tabelas criadas."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    yield sm
    await engine.dispose()


@pytest.fixture
def test_settings() -> Settings:
    """Settings com endpoints fake e rate limit alto (testes rápidos)."""
    return Settings(
        apollo_api_key="test-key",
        apollo_base_url="https://apollo.test/v1",
        viacep_base_url="https://viacep.test/ws",
        apollo_rate_limit=6000,
        viacep_rate_limit=6000,
        http_max_retries=1,
    )


@pytest.fixture
def sample_csv_bytes() -> bytes:
    return (DATA_DIR / "sample_leads.csv").read_bytes()

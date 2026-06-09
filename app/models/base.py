"""Base declarativa do SQLAlchemy + tipos cross-dialect.

Os tipos abaixo rendem como Postgres no Supabase (JSONB, ARRAY, uuid) e caem para
equivalentes genéricos no SQLite — assim os MESMOS models rodam tanto contra o
Supabase quanto contra um banco de teste SQLite (E2E sem servidor).
"""

from sqlalchemy import JSON, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase

# JSONB no Postgres, JSON genérico no resto (ex.: sqlite)
JSONType = JSON().with_variant(JSONB(), "postgresql")


def text_array():
    """ARRAY(text) no Postgres; JSON (lista) no sqlite."""
    return ARRAY(Text()).with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    pass

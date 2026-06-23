"""Base declarativa do SQLAlchemy + tipos cross-dialect.

Os tipos abaixo caem para equivalentes genéricos no **SQLite** (banco padrão,
local) e rendem como Postgres (JSONB, ARRAY, uuid) quando ``DATABASE_URL`` aponta
para um Postgres — assim os MESMOS models rodam nos dois sem alteração.
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

"""Unit: auto-migração do SQLite local adiciona colunas novas a tabelas já criadas.

Reproduz o cenário que causou o 500 'no such column': um dev.db antigo, sem a
coluna nova do model. ``_sqlite_add_missing_columns`` deve adicioná-la sem erro.
"""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from app.main import _sqlite_add_missing_columns


def test_adiciona_colunas_faltantes(tmp_path):
    db = tmp_path / "antigo.db"
    engine = create_engine(f"sqlite:///{db}")
    # Tabela 'leads' "antiga": só o essencial, faltando muitas colunas do model.
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE leads (id TEXT PRIMARY KEY, phone_e164 TEXT NOT NULL)")
        )

    with engine.begin() as conn:
        _sqlite_add_missing_columns(conn)

    cols = {c["name"] for c in inspect(engine).get_columns("leads")}
    # a coluna que quebrou antes + outras do model agora presentes
    assert "google_maps_enriched_at" in cols
    assert "apollo_enriched_at" in cols
    assert "field_provenance" in cols
    assert "cidade" in cols
    engine.dispose()


def test_idempotente(tmp_path):
    """Rodar duas vezes não falha (colunas já presentes são ignoradas)."""
    db = tmp_path / "antigo2.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE leads (id TEXT PRIMARY KEY, phone_e164 TEXT NOT NULL)"))
    with engine.begin() as conn:
        _sqlite_add_missing_columns(conn)
    with engine.begin() as conn:
        _sqlite_add_missing_columns(conn)  # 2a vez: no-op, sem exceção
    engine.dispose()

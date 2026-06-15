"""Config de runtime definida pela UI (ex.: APOLLO_API_KEY), persistida em JSON.

Camada de override por cima do ``.env``: o que o operador salvar na tela de
Configurações fica aqui e tem precedência sobre o ``.env``. Mantém o segredo no
servidor (nunca no navegador). Arquivo no .gitignore — não versionar.
"""

from __future__ import annotations

import json
from pathlib import Path

# Relativo ao cwd do backend (mesma convenção do .env).
_PATH = Path("runtime_config.json")


def _read() -> dict:
    if not _PATH.exists():
        return {}
    try:
        return json.loads(_PATH.read_text(encoding="utf-8")) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write(data: dict) -> None:
    _PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_apollo_key() -> str | None:
    value = (_read().get("apollo_api_key") or "").strip()
    return value or None


def set_apollo_key(key: str) -> None:
    data = _read()
    data["apollo_api_key"] = key.strip()
    _write(data)


def clear_apollo_key() -> None:
    data = _read()
    data.pop("apollo_api_key", None)
    _write(data)


def get_apollo_budget() -> int:
    """Orçamento de créditos Apollo informado pelo operador (0 = não informado)."""
    try:
        return int(_read().get("apollo_credit_budget") or 0)
    except (TypeError, ValueError):
        return 0


def set_apollo_budget(budget: int) -> None:
    data = _read()
    data["apollo_credit_budget"] = max(0, int(budget))
    _write(data)

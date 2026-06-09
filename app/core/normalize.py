"""Normalização e limpeza de valores na importação.

Observações sobre a base real (verificadas no arquivo):
- O CSV é UTF-8 com BOM (decodificar com ``utf-8-sig``), NÃO cp1252.
- A própria base contém ~242 caracteres de substituição U+FFFD (``�``) já
  gravados na origem (acentos perdidos antes da geração do CSV). Esses valores
  são corrupção de dados preexistente — não há como recuperar o byte original.
  Por isso ``normalize_header`` também remove o ``�`` ao casar cabeçalhos.
- A coluna ``Telefone (E.164)`` traz só dígitos sem ``+55`` (ex.: 41991481195).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import phonenumbers
from dateutil import parser as date_parser

BOM = "﻿"
REPLACEMENT_CHAR = "�"  # "�"

_TRUE_TOKENS = {"sim", "s", "true", "1", "yes", "y", "verdadeiro"}
_FALSE_TOKENS = {"nao", "não", "n", "false", "0", "no", "falso"}


def strip_bom(s: str) -> str:
    return s.lstrip(BOM) if s else s


def normalize_header(header: str) -> str:
    """Normaliza um cabeçalho para casar com o mapa de colunas.

    Remove BOM, minúsculas e descarta TODO caractere que não seja ``[a-z0-9]`` —
    incluindo letras acentuadas E o caractere de substituição ``�``. Isso faz a
    forma limpa e a corrompida colapsarem na MESMA chave, pois a letra acentuada
    é removida em ambos os casos:

        normalize_header("Gênero")  -> "gnero"
        normalize_header("G�nero")  -> "gnero"   # mesmo resultado

    Assim um único mapa canônico (chaves vindas dos cabeçalhos limpos) casa tanto
    o CSV corrompido quanto um .xlsx com cabeçalhos limpos.
    """
    s = strip_bom(header or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def clean_value(v: object) -> str | None:
    """Trim básico; string vazia/whitespace vira ``None``."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def to_e164(raw: object, default_country: str = "BR") -> str | None:
    """Converte telefone para E.164 (ex.: '41991481195' -> '+5541991481195').

    Retorna ``None`` se vazio ou inválido (a linha deve ir para ``rejected``).
    """
    s = clean_value(raw)
    if not s:
        return None
    candidate = s if s.startswith("+") else s
    try:
        parsed = phonenumbers.parse(candidate, None if s.startswith("+") else default_country)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def clean_cep(raw: object) -> str | None:
    """Mantém só dígitos; exige 8 dígitos, senão ``None``."""
    s = clean_value(raw)
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    return digits if len(digits) == 8 else None


def to_bool_sim_nao(raw: object) -> bool | None:
    s = clean_value(raw)
    if s is None:
        return None
    low = s.lower()
    if low in _TRUE_TOKENS:
        return True
    if low in _FALSE_TOKENS:
        return False
    return None


def to_array(raw: object, sep: str = ",") -> list[str] | None:
    """Divide string em lista (ex.: 'a, b' -> ['a','b']). Vazio -> ``None``."""
    s = clean_value(raw)
    if not s:
        return None
    items = [part.strip() for part in s.split(sep)]
    items = [p for p in items if p]
    return items or None


def parse_int(raw: object) -> int | None:
    s = clean_value(raw)
    if not s:
        return None
    digits = re.sub(r"[^\d-]", "", s)
    try:
        return int(digits) if digits not in ("", "-") else None
    except ValueError:
        return None


def parse_numeric(raw: object) -> Decimal | None:
    """Aceita decimal com ponto ou vírgula (pt-BR)."""
    s = clean_value(raw)
    if not s:
        return None
    s = s.replace(" ", "")
    # Se tem vírgula e não ponto, vírgula é separador decimal
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def parse_date(raw: object) -> date | None:
    s = clean_value(raw)
    if not s:
        return None
    try:
        return date_parser.parse(s, dayfirst=True).date()
    except (ValueError, OverflowError):
        return None


def parse_datetime(raw: object) -> datetime | None:
    s = clean_value(raw)
    if not s:
        return None
    try:
        return date_parser.parse(s)
    except (ValueError, OverflowError):
        return None

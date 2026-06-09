"""Teste pontual: normalização de cabeçalhos e valores."""

from app.core.column_mapping import COLUMN_DEFS, NORMALIZED_TO_COLUMN, resolve_header
from app.core.normalize import (
    clean_cep,
    normalize_header,
    parse_int,
    to_array,
    to_bool_sim_nao,
    to_e164,
)

# "Profiss�o" e "G�nero" com o caractere de substituição U+FFFD da base real
CORRUPT_GENERO = "G�nero"
CORRUPT_PROFISSAO = "Profiss�o"


def test_header_clean_and_corrupt_collapse():
    # forma limpa e forma corrompida devem cair na MESMA chave
    assert normalize_header("Gênero") == normalize_header(CORRUPT_GENERO)
    assert normalize_header("Profissão") == normalize_header(CORRUPT_PROFISSAO)


def test_resolve_header_handles_corruption():
    assert resolve_header(CORRUPT_GENERO) == ("genero", "text")
    assert resolve_header(CORRUPT_PROFISSAO) == ("profissao", "text")
    assert resolve_header("Gênero") == ("genero", "text")


def test_resolve_header_with_bom_and_spaces():
    assert resolve_header("﻿  Nome Completo  ") == ("nome_completo", "text")


def test_mapping_covers_56_columns():
    assert len(COLUMN_DEFS) == 56
    assert len(NORMALIZED_TO_COLUMN) == 56  # sem colisões de chave


def test_to_e164_brazil():
    assert to_e164("41991481195") == "+5541991481195"
    assert to_e164("+5541991481195") == "+5541991481195"
    assert to_e164("") is None
    assert to_e164("123") is None


def test_clean_cep():
    assert clean_cep("01001-000") == "01001000"
    assert clean_cep("01001000") == "01001000"
    assert clean_cep("123") is None
    assert clean_cep("") is None


def test_to_bool_sim_nao():
    assert to_bool_sim_nao("Sim") is True
    assert to_bool_sim_nao("Não") is False
    assert to_bool_sim_nao("nao") is False
    assert to_bool_sim_nao("") is None
    assert to_bool_sim_nao("talvez") is None


def test_to_array():
    assert to_array("a, b ,c") == ["a", "b", "c"]
    assert to_array("") is None
    assert to_array("único") == ["único"]


def test_parse_int():
    assert parse_int("200") == 200
    assert parse_int("1.234") == 1234
    assert parse_int("") is None

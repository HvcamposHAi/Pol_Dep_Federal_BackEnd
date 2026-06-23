"""E2E: import devolve mensagem clara quando o arquivo não pode ser carregado
(cabeçalho/colunas não reconhecidos, sem coluna de telefone, ou arquivo vazio)."""

from __future__ import annotations

import pytest

from app.services import import_service

pytestmark = pytest.mark.e2e


async def test_cabecalho_sem_coluna_de_telefone(sessionmaker_fixture):
    sm = sessionmaker_fixture
    # CSV válido em ; mas SEM coluna de telefone reconhecível
    content = "Nome Completo;E-mail\nFulano;f@x.com\nBeltrano;b@x.com\n".encode("utf-8-sig")
    async with sm() as s:
        result = await import_service.import_bytes(s, "contatos.csv", content)

    assert result.inserted == 0 and result.updated == 0
    assert result.errors, "deveria reportar erro de estrutura"
    assert "coluna de telefone" in result.errors[0].lower()


async def test_nenhuma_coluna_reconhecida(sessionmaker_fixture):
    sm = sessionmaker_fixture
    # Cabeçalho totalmente desconhecido (ex.: arquivo errado / separador errado)
    content = "col_a;col_b;col_c\n1;2;3\n".encode("utf-8-sig")
    async with sm() as s:
        result = await import_service.import_bytes(s, "qualquer.csv", content)

    assert result.errors
    assert "nenhuma coluna reconhecida" in result.errors[0].lower()


async def test_arquivo_vazio(sessionmaker_fixture):
    sm = sessionmaker_fixture
    async with sm() as s:
        result = await import_service.import_bytes(s, "vazio.csv", b"")

    assert result.total == 0
    assert result.errors and "nenhuma linha" in result.errors[0].lower()


async def test_arquivo_valido_nao_dispara_erro(sessionmaker_fixture):
    sm = sessionmaker_fixture
    content = (
        "Nome Completo;Telefone (E.164)\nFulano;41991481195\n"
    ).encode("utf-8-sig")
    async with sm() as s:
        result = await import_service.import_bytes(s, "ok.csv", content)

    assert result.inserted == 1
    assert result.errors == []  # arquivo bom: sem mensagem de erro

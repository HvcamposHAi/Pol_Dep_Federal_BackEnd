"""Teste pontual: fill_only_empty (regra que protege a integridade dos dados)."""

from app.core.merge import fill_only_empty, is_empty


def test_fill_empty_columns():
    current = {"email": None, "linkedin": ""}
    incoming = {"email": "a@b.com", "linkedin": "https://l/x"}
    result = fill_only_empty(current, incoming, "apollo")
    assert result.patch == {"email": "a@b.com", "linkedin": "https://l/x"}
    assert set(result.fields_filled) == {"email", "linkedin"}
    assert result.provenance == {"email": "apollo", "linkedin": "apollo"}


def test_never_overwrites_existing():
    current = {"email": "original@x.com", "profissao": "Contador"}
    incoming = {"email": "novo@apollo.com", "profissao": "Engenheiro"}
    result = fill_only_empty(current, incoming, "apollo")
    assert result.patch == {}
    assert result.fields_filled == []


def test_whitespace_counts_as_empty():
    current = {"cidade": "   "}
    incoming = {"cidade": "Curitiba"}
    result = fill_only_empty(current, incoming, "viacep")
    assert result.patch == {"cidade": "Curitiba"}
    assert result.provenance["cidade"] == "viacep"


def test_ignores_empty_incoming():
    current = {"email": None}
    incoming = {"email": "", "linkedin": None}
    result = fill_only_empty(current, incoming, "apollo")
    assert result.patch == {}


def test_does_not_mutate_inputs():
    current = {"email": None}
    incoming = {"email": "a@b.com"}
    fill_only_empty(current, incoming, "apollo")
    assert current == {"email": None}
    assert incoming == {"email": "a@b.com"}


def test_is_empty_cases():
    assert is_empty(None)
    assert is_empty("")
    assert is_empty("   ")
    assert is_empty([])
    assert is_empty({})
    assert not is_empty("x")
    assert not is_empty(0)
    assert not is_empty(False)

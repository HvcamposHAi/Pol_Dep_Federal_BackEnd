"""Mapa único CSV/XLSX -> colunas do banco (única fonte de verdade).

As chaves são derivadas dos cabeçalhos LIMPOS via ``normalize_header``. Como a
normalização remove acentos e o caractere ``�``, os cabeçalhos corrompidos do
CSV real (ex.: ``"G�nero"``) casam automaticamente com a mesma chave
(``"gnero"``). Resiliente a reordenação de colunas (casa por nome, não posição).
"""

from __future__ import annotations

from app.core.normalize import normalize_header

# (cabeçalho limpo, coluna no banco, kind para coerção de valor)
# kind: text | int | numeric | bool | array | date | datetime | e164 | cep
COLUMN_DEFS: list[tuple[str, str, str]] = [
    ("Nome Completo", "nome_completo", "text"),
    ("Nome", "nome", "text"),
    ("Sobrenome", "sobrenome", "text"),
    ("Nome Preferido", "nome_preferido", "text"),
    ("Telefone (E.164)", "phone_e164", "e164"),  # chave natural
    ("Telefone (bruto)", "telefone_bruto", "text"),
    ("Celular 2", "celular2", "text"),
    ("Telefone Fixo", "telefone_fixo", "text"),
    ("E-mail", "email", "text"),
    ("Documento", "documento", "text"),
    ("Data de Nascimento", "data_nascimento", "date"),
    ("Gênero", "genero", "text"),
    ("CEP", "cep", "cep"),
    ("Estado", "estado", "text"),
    ("Cidade", "cidade", "text"),
    ("Bairro", "bairro", "text"),
    ("Região", "regiao", "text"),
    ("Endereço", "endereco", "text"),
    ("Número", "numero", "text"),
    ("Complemento", "complemento", "text"),
    ("Zona Eleitoral", "zona_eleitoral", "text"),
    ("Latitude", "latitude", "numeric"),
    ("Longitude", "longitude", "numeric"),
    ("Profissão", "profissao", "text"),
    ("Profissão 2", "profissao2", "text"),
    ("Cargos de Autoridade", "cargos_autoridade", "text"),
    ("Cargo de Autoridade (legado)", "cargo_autoridade_legado", "text"),
    ("Tipo de Contato", "tipo_contato", "text"),
    ("Intenção de Voto", "intencao_voto", "text"),
    ("Nível de Influência", "nivel_influencia", "text"),
    ("Potencial de Mobilização", "potencial_mobilizacao", "text"),
    ("Votos Mobilizados (potencial)", "votos_mobilizados", "int"),
    ("Possível Doador", "possivel_doador", "bool"),
    ("Estágio do Relacionamento", "estagio_relacionamento", "text"),
    ("Status do Relacionamento", "status_relacionamento", "text"),
    ("Nível de Engajamento", "nivel_engajamento", "text"),
    ("Score de Relacionamento", "score_relacionamento", "numeric"),
    ("Canal Preferencial", "canal_preferencial", "text"),
    ("Tags", "tags", "array"),
    ("Interesses", "interesses", "array"),
    ("Líder Responsável", "lider_responsavel", "text"),
    ("Usuário Responsável", "usuario_responsavel", "text"),
    ("Origem 1º Contato", "origem_primeiro_contato", "text"),
    ("Origem Último Contato", "origem_ultimo_contato", "text"),
    ("Última Interação", "ultima_interacao", "datetime"),
    ("WhatsApp Autorizado", "whatsapp_autorizado", "bool"),
    ("Superfã", "superfa", "bool"),
    ("Observações", "observacoes", "text"),
    ("Instagram", "instagram", "text"),
    ("Engajamento Instagram", "engajamento_instagram", "text"),
    ("Facebook", "facebook", "text"),
    ("Twitter", "twitter", "text"),
    ("TikTok", "tiktok", "text"),
    ("LinkedIn", "linkedin", "text"),
    ("Criado em", "criado_em_origem", "datetime"),
    ("Atualizado em", "atualizado_em_origem", "datetime"),
]

# Cabeçalho normalizado -> (coluna, kind)
NORMALIZED_TO_COLUMN: dict[str, tuple[str, str]] = {
    normalize_header(header): (column, kind) for header, column, kind in COLUMN_DEFS
}

# Coluna do banco que é a chave natural (telefone E.164)
PHONE_COLUMN = "phone_e164"

# Coluna de fallback para derivar o telefone quando a E.164 estiver vazia
PHONE_FALLBACK_COLUMN = "telefone_bruto"


def resolve_header(header: str) -> tuple[str, str] | None:
    """Retorna (coluna, kind) para um cabeçalho de entrada, ou ``None`` se desconhecido."""
    return NORMALIZED_TO_COLUMN.get(normalize_header(header))

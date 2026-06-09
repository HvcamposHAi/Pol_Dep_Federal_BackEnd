# Pol_Dep_Federal_BackEnd

Backend (FastAPI + Supabase/PostgreSQL) para **importação** e **enriquecimento** de
leads da campanha — Apollo.io (People Enrichment) + ViaCEP, com regra
*fill-only-empty* (nunca sobrescreve dado existente), rastreabilidade de origem
(`field_provenance`) e jobs retomáveis.

## Stack
- Python 3.11+ · FastAPI · SQLAlchemy 2 (async) + asyncpg
- Supabase (PostgreSQL) — conexão direta
- httpx + tenacity (retry/backoff) · openpyxl (xlsx) · phonenumbers (E.164)

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (Linux/Mac: source .venv/bin/activate)
pip install -e ".[dev]"
copy .env.example .env            # preencha DATABASE_URL e APOLLO_API_KEY
```

1. Rode o DDL de [docs/schema.sql](docs/schema.sql) no **SQL Editor do Supabase**
   (cria `leads`, `enrichment_runs`, `enrichment_events`).
2. Suba a API: `uvicorn app.main:app --reload` → `GET /health`.

## Uso

| Ação | Como |
|---|---|
| Importar leads | `POST /leads/import` (multipart, CSV `;` ou `.xlsx`) |
| Listar / consultar | `GET /leads`, `GET /leads/{id}`, `GET /leads/by-phone/{e164}` |
| Criar run | `POST /enrichment/runs` (cria `queued`) |
| Rodar/retomar o job | `python -m app.cli enrich --run-id <id>` (ou `--new`) |
| Status / eventos | `GET /enrichment/runs/{id}`, `.../events` |

O job pesado (~7.4k leads ≈ horas) roda pela **CLI**, não preso a um request.
O estado vive no banco → reiniciar retoma de onde parou.

> ⚠️ A importação espera o CSV em **UTF-8 com BOM**. A base de origem contém
> ~242 caracteres `�` já corrompidos na fonte (corrupção preexistente, não do import).

## Testes

```bash
pytest tests/unit -q      # rápidos, sem banco (merge + normalização)
pytest tests/e2e -q       # import->enrich->verifica (SQLite + HTTP mockado)
ruff check .
```

## Notas
- LGPD: a base legal para enriquecer dados pessoais de eleitores é
  responsabilidade da campanha.
- Nunca commite `.env` nem a base de leads (ver `.gitignore`).

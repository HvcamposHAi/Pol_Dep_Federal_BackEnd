-- ==========================================================================
-- schema.sql — DDL para executar MANUALMENTE no SQL Editor do Supabase.
-- O backend assume que estas tabelas já existem (não há Alembic).
-- Idempotente: pode rodar mais de uma vez sem erro.
-- ==========================================================================

-- Extensão para gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =========================================================
-- TABELA: leads  (chave natural = phone_e164; PK surrogate)
-- =========================================================
CREATE TABLE IF NOT EXISTS leads (
  id                         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_e164                 text NOT NULL UNIQUE,
  nome_completo              text,
  nome                       text,
  sobrenome                  text,
  nome_preferido             text,
  telefone_bruto             text,
  celular2                   text,
  telefone_fixo              text,
  email                      text,
  documento                  text,
  data_nascimento            date,
  genero                     text,
  cep                        text,
  estado                     text,
  cidade                     text,
  bairro                     text,
  regiao                     text,
  endereco                   text,
  numero                     text,
  complemento                text,
  zona_eleitoral             text,
  latitude                   numeric,
  longitude                  numeric,
  profissao                  text,
  profissao2                 text,
  cargos_autoridade          text,
  cargo_autoridade_legado    text,
  tipo_contato               text,
  intencao_voto              text,
  nivel_influencia           text,
  potencial_mobilizacao      text,
  votos_mobilizados          integer,
  possivel_doador            boolean,
  estagio_relacionamento     text,
  status_relacionamento      text,
  nivel_engajamento          text,
  score_relacionamento       numeric,
  canal_preferencial         text,
  tags                       text[],
  interesses                 text[],
  lider_responsavel          text,
  usuario_responsavel        text,
  origem_primeiro_contato    text,
  origem_ultimo_contato      text,
  ultima_interacao           timestamptz,
  whatsapp_autorizado        boolean,
  superfa                    boolean,
  observacoes                text,
  instagram                  text,
  engajamento_instagram      text,
  facebook                   text,
  twitter                    text,
  tiktok                     text,
  linkedin                   text,
  criado_em_origem           timestamptz,
  atualizado_em_origem       timestamptz,
  -- enriquecimento / auditoria
  apollo_matched             boolean NOT NULL DEFAULT false,
  apollo_enriched_at         timestamptz,
  viacep_enriched_at         timestamptz,
  google_maps_enriched_at    timestamptz,
  enrichment_status          text NOT NULL DEFAULT 'pending',
  enrichment_note            text,
  field_provenance           jsonb NOT NULL DEFAULT '{}'::jsonb,
  raw_source                 jsonb,
  created_at                 timestamptz NOT NULL DEFAULT now(),
  updated_at                 timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_leads_status        ON leads (enrichment_status);
CREATE INDEX IF NOT EXISTS idx_leads_apollo_match  ON leads (apollo_matched);
CREATE INDEX IF NOT EXISTS idx_leads_cep           ON leads (cep);
CREATE INDEX IF NOT EXISTS idx_leads_cidade_estado ON leads (cidade, estado);
CREATE INDEX IF NOT EXISTS idx_leads_pending       ON leads (id) WHERE enrichment_status = 'pending';

-- Migração idempotente p/ bancos já criados antes do provider Google Maps.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS google_maps_enriched_at timestamptz;

-- =========================================================
-- TABELA: enrichment_runs  (run + checkpoint/resume)
-- =========================================================
CREATE TABLE IF NOT EXISTS enrichment_runs (
  id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  status                  text NOT NULL DEFAULT 'queued',  -- queued/running/paused/completed/failed/canceled
  provider_scope          text[] NOT NULL DEFAULT ARRAY['viacep','apollo'],
  total_targets           integer NOT NULL DEFAULT 0,
  processed_count         integer NOT NULL DEFAULT 0,
  matched_count           integer NOT NULL DEFAULT 0,
  error_count             integer NOT NULL DEFAULT 0,
  last_processed_lead_id  uuid,
  current_round           integer NOT NULL DEFAULT 1,
  checkpoint              jsonb NOT NULL DEFAULT '{}'::jsonb,
  params                  jsonb,
  started_at              timestamptz,
  finished_at             timestamptz,
  created_at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_runs_status ON enrichment_runs (status);

-- =========================================================
-- TABELA: enrichment_events  (log + erros)
-- =========================================================
CREATE TABLE IF NOT EXISTS enrichment_events (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id        uuid REFERENCES enrichment_runs(id) ON DELETE CASCADE,
  lead_id       uuid REFERENCES leads(id) ON DELETE SET NULL,
  provider      text,            -- apollo/viacep/orchestrator
  level         text NOT NULL,   -- info/warn/error
  event_type    text,            -- matched/no_match/rate_limited/http_error/merged/skipped
  message       text,
  fields_filled text[],
  http_status   integer,
  payload       jsonb,           -- req/resp aparado, SEM segredos
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_run   ON enrichment_events (run_id);
CREATE INDEX IF NOT EXISTS idx_events_lead  ON enrichment_events (lead_id);
CREATE INDEX IF NOT EXISTS idx_events_level ON enrichment_events (level);

-- =========================================================
-- TRIGGER: mantém updated_at em leads
-- =========================================================
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_leads_updated ON leads;
CREATE TRIGGER trg_leads_updated BEFORE UPDATE ON leads
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

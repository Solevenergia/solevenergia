-- =============================================================
-- CONTALEV — Schema Supabase (migração de JSON para PostgreSQL)
-- =============================================================
-- Execute este script no Supabase Studio:
--   1. Entre em: https://supabase.com/dashboard
--   2. Selecione o projeto
--   3. Menu lateral → "SQL Editor"
--   4. "New query" → cole este arquivo inteiro → "Run"
-- =============================================================

-- -------------------------------------------------------------
-- TABELA: clientes
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clientes (
    uc                          TEXT PRIMARY KEY,
    nome                        TEXT NOT NULL,
    cpf                         TEXT DEFAULT '',
    uc_alternativa              TEXT DEFAULT '',
    telefone                    TEXT DEFAULT '',
    email                       TEXT DEFAULT '',
    endereco                    TEXT DEFAULT '',
    endereco_linha1             TEXT DEFAULT '',
    endereco_linha2             TEXT DEFAULT '',
    endereco_linha3             TEXT DEFAULT '',
    titular_fatura              TEXT DEFAULT '',
    desconto_pct                NUMERIC DEFAULT 0.2,
    data_adesao                 TEXT DEFAULT '',
    tarifa_sem                  NUMERIC DEFAULT 0,
    valor_cobranca_anterior     NUMERIC DEFAULT 0,
    venc_contalev_anterior      TEXT DEFAULT '',
    data_pagamento_anterior     TEXT DEFAULT '',
    economia_acumulada_anterior NUMERIC DEFAULT 0,
    codigo_barras               TEXT DEFAULT '',
    linha_digitavel             TEXT DEFAULT '',
    pix_payload                 TEXT DEFAULT '',
    usina_id                    TEXT,
    rateio_pct                  NUMERIC DEFAULT 0,
    saldo_kwh                   NUMERIC DEFAULT 0,
    apelido                     TEXT DEFAULT '',
    tipo_fornecimento           TEXT DEFAULT '',
    proxima_leitura             TEXT DEFAULT '',
    modo_bandeira               TEXT DEFAULT 'com_bandeira',
    kwh_creditado_real          NUMERIC DEFAULT 0,
    atualizado_em               TIMESTAMPTZ DEFAULT NOW()
);

-- Para bancos onde a tabela já existe, adiciona as colunas que faltam
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS endereco         TEXT DEFAULT '';
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS titular_fatura   TEXT DEFAULT '';
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS data_adesao      TEXT DEFAULT '';
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS uc_alternativa   TEXT DEFAULT '';
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS cpf              TEXT DEFAULT '';
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS telefone         TEXT DEFAULT '';
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS email            TEXT DEFAULT '';
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS apelido          TEXT DEFAULT '';
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS modo_bandeira    TEXT DEFAULT 'com_bandeira';
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS proxima_leitura  TEXT DEFAULT '';
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS tipo_fornecimento TEXT DEFAULT '';
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS kwh_creditado_real NUMERIC DEFAULT 0;
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS atualizado_em    TIMESTAMPTZ DEFAULT NOW();

-- Trigger para atualizar "atualizado_em" automaticamente
CREATE OR REPLACE FUNCTION _set_atualizado_em()
RETURNS TRIGGER AS $$
BEGIN
    NEW.atualizado_em = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_clientes_atualizado_em ON clientes;
CREATE TRIGGER trg_clientes_atualizado_em
    BEFORE UPDATE ON clientes
    FOR EACH ROW EXECUTE FUNCTION _set_atualizado_em();

-- Índices úteis
CREATE INDEX IF NOT EXISTS idx_clientes_uc_alt  ON clientes (uc_alternativa);
CREATE INDEX IF NOT EXISTS idx_clientes_usina   ON clientes (usina_id);
CREATE INDEX IF NOT EXISTS idx_clientes_nome    ON clientes (nome);

-- =============================================================
-- CONFIRMAÇÃO
-- =============================================================
-- Após rodar, verifique em "Table Editor" se a tabela 'clientes'
-- tem todas as colunas acima. Depois, me avise aqui para eu
-- continuar a migração do código.
-- =============================================================

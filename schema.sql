-- ================================================================
--  CONTALEV — Schema Supabase (PostgreSQL)
--  Execute este script no SQL Editor do Supabase
-- ================================================================

-- ── USINAS ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS usinas (
    uid                     TEXT PRIMARY KEY,
    nome                    TEXT NOT NULL,
    endereco                TEXT DEFAULT '',
    cep                     TEXT DEFAULT '',
    cidade_uf               TEXT DEFAULT '',
    potencia_kwp            REAL DEFAULT 0,
    modulos_tipo            TEXT DEFAULT '',
    modulos_qtd             INTEGER DEFAULT 0,
    inversor                TEXT DEFAULT '',
    estrutura               TEXT DEFAULT '',
    uc_geradora             TEXT DEFAULT '',
    titular_uc              TEXT DEFAULT '',
    cpf_titular             TEXT DEFAULT '',
    data_comissionamento    TEXT DEFAULT '',
    garantia_modulos        TEXT DEFAULT '',
    garantia_inversor       TEXT DEFAULT '',
    geracao_media_mensal    REAL DEFAULT 0,
    geracao_prevista_diaria REAL DEFAULT 0,
    observacoes             TEXT DEFAULT '',
    investidor_nome         TEXT DEFAULT '',
    investidor_cpf_cnpj     TEXT DEFAULT '',
    investidor_email        TEXT DEFAULT '',
    investidor_telefone     TEXT DEFAULT '',
    investidor_banco        TEXT DEFAULT '',
    investidor_agencia      TEXT DEFAULT '',
    investidor_conta        TEXT DEFAULT '',
    investidor_pix          TEXT DEFAULT '',
    investidor_desagio_pct  REAL DEFAULT 0,
    investidor_dia_pagamento TEXT DEFAULT '',
    investidor_valor_minimo REAL DEFAULT 0,
    proxima_leitura         TEXT DEFAULT '',
    documento_titular_pdf   TEXT DEFAULT '',
    saldo_kwh               REAL DEFAULT 0,
    atualizado_em           TIMESTAMPTZ DEFAULT NOW()
);

-- ── CLIENTES ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS clientes (
    uc                          TEXT PRIMARY KEY,
    nome                        TEXT NOT NULL,
    endereco_linha1             TEXT DEFAULT '',
    endereco_linha2             TEXT DEFAULT '',
    endereco_linha3             TEXT DEFAULT '',
    desconto_pct                REAL DEFAULT 0.2,
    tarifa_sem                  REAL DEFAULT 0,
    valor_cobranca_anterior     REAL DEFAULT 0,
    venc_contalev_anterior      TEXT DEFAULT '',
    data_pagamento_anterior     TEXT DEFAULT '',
    economia_acumulada_anterior REAL DEFAULT 0,
    codigo_barras               TEXT DEFAULT '',
    linha_digitavel             TEXT DEFAULT '',
    pix_payload                 TEXT DEFAULT '',
    usina_id                    TEXT REFERENCES usinas(uid) ON DELETE SET NULL,
    rateio_pct                  REAL DEFAULT 0,
    saldo_kwh                   REAL DEFAULT 0,
    cpf                         TEXT DEFAULT '',
    telefone                    TEXT DEFAULT '',
    email                       TEXT DEFAULT '',
    apelido                     TEXT DEFAULT '',
    tipo_fornecimento           TEXT DEFAULT '',
    proxima_leitura             TEXT DEFAULT '',
    modo_bandeira               TEXT DEFAULT 'com_bandeira',
    kwh_creditado_real          REAL DEFAULT 0,
    atualizado_em               TIMESTAMPTZ DEFAULT NOW()
);

-- ── HISTORICO DE COBRANÇAS ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS historico (
    id                  TEXT PRIMARY KEY,
    data                TEXT DEFAULT '',
    uc                  TEXT DEFAULT '',
    nome                TEXT DEFAULT '',
    mes_referencia      TEXT DEFAULT '',
    total_sem           REAL DEFAULT 0,
    total_com           REAL DEFAULT 0,
    economia_mes        REAL DEFAULT 0,
    economia_acum       REAL DEFAULT 0,
    vencimento          TEXT DEFAULT '',
    consumo_kwh         REAL DEFAULT 0,
    compensado_kwh      REAL DEFAULT 0,
    pdf                 TEXT DEFAULT '',
    pdf_url             TEXT DEFAULT '',         -- Storage path da cobranca CONTALEV
    pdf_equatorial      TEXT DEFAULT '',         -- nome do arquivo da fatura Equatorial
    pdf_equatorial_url  TEXT DEFAULT '',         -- Storage path da fatura Equatorial
    status              TEXT DEFAULT 'Aguardando pagamento',
    data_leitura_atual  TEXT DEFAULT '',
    atualizado_em       TIMESTAMPTZ DEFAULT NOW()
);

-- ── GERAÇÃO MENSAL (fatura da usina) ───────────────────────────
CREATE TABLE IF NOT EXISTS geracao_mensal (
    usina_uid               TEXT NOT NULL REFERENCES usinas(uid) ON DELETE CASCADE,
    mes_referencia          TEXT NOT NULL,
    kwh_gerado              REAL DEFAULT 0,
    data_leitura_anterior   TEXT DEFAULT '',
    data_leitura_atual      TEXT DEFAULT '',
    n_dias                  INTEGER DEFAULT 0,
    saldo_kwh               REAL DEFAULT 0,
    excedente_kwh           REAL DEFAULT 0,
    data_registro           TEXT DEFAULT '',
    origem                  TEXT DEFAULT '',
    fatura_pdf              TEXT DEFAULT '',
    atualizado_em           TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (usina_uid, mes_referencia)
);

-- ── GERAÇÃO DIÁRIA ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS geracao_diaria (
    id          SERIAL PRIMARY KEY,
    usina_uid   TEXT NOT NULL REFERENCES usinas(uid) ON DELETE CASCADE,
    data        TEXT NOT NULL,
    kwh         REAL DEFAULT 0,
    obs         TEXT DEFAULT '',
    UNIQUE (usina_uid, data)
);

-- ── TARIFAS MENSAIS ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tarifas (
    mes_referencia      TEXT PRIMARY KEY,
    tarifa_sem          REAL DEFAULT 0,
    bandeira_amarela    REAL DEFAULT 0,
    bandeira_vermelha   REAL DEFAULT 0,
    fio_b               REAL DEFAULT 0,
    observacao          TEXT DEFAULT '',
    atualizado_em       TIMESTAMPTZ DEFAULT NOW()
);

-- ── HISTÓRICO DO INVESTIDOR ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS investidor_historico (
    id                  SERIAL PRIMARY KEY,
    uid                 TEXT DEFAULT '',
    usina_nome          TEXT DEFAULT '',
    investidor_nome     TEXT DEFAULT '',
    investidor_cpf_cnpj TEXT DEFAULT '',
    investidor_banco    TEXT DEFAULT '',
    investidor_agencia  TEXT DEFAULT '',
    investidor_conta    TEXT DEFAULT '',
    investidor_pix      TEXT DEFAULT '',
    mes_referencia      TEXT DEFAULT '',
    kwh_gerado          REAL DEFAULT 0,
    tarifa_equatorial   REAL DEFAULT 0,
    desagio_pct         REAL DEFAULT 0,
    valor_bruto         REAL DEFAULT 0,
    valor_desagio       REAL DEFAULT 0,
    valor_com_desagio   REAL DEFAULT 0,
    fio_b               REAL DEFAULT 0,
    valor_minimo        REAL DEFAULT 0,
    valor_liquido       REAL DEFAULT 0,
    dia_pagamento       TEXT DEFAULT '',
    data_geracao        TEXT DEFAULT '',
    uc_geradora         TEXT DEFAULT '',
    pdf                 TEXT DEFAULT '',
    atualizado_em       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (uid, mes_referencia)
);

-- ── ÍNDICES PARA CONSULTAS COMUNS ───────────────────────────────
CREATE INDEX IF NOT EXISTS idx_clientes_usina ON clientes(usina_id);
CREATE INDEX IF NOT EXISTS idx_historico_uc ON historico(uc);
CREATE INDEX IF NOT EXISTS idx_historico_mes ON historico(mes_referencia);
CREATE INDEX IF NOT EXISTS idx_geracao_mensal_usina ON geracao_mensal(usina_uid);

-- ── ROW LEVEL SECURITY (opcional, habilitar depois) ─────────────
-- ALTER TABLE clientes ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE usinas ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE historico ENABLE ROW LEVEL SECURITY;

-- ── FUNÇÃO AUXILIAR: atualizar timestamp automaticamente ────────
CREATE OR REPLACE FUNCTION atualizar_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.atualizado_em = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers de atualização automática
DO $$ BEGIN
    CREATE TRIGGER trg_usinas_updated BEFORE UPDATE ON usinas
        FOR EACH ROW EXECUTE FUNCTION atualizar_timestamp();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_clientes_updated BEFORE UPDATE ON clientes
        FOR EACH ROW EXECUTE FUNCTION atualizar_timestamp();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_historico_updated BEFORE UPDATE ON historico
        FOR EACH ROW EXECUTE FUNCTION atualizar_timestamp();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_tarifas_updated BEFORE UPDATE ON tarifas
        FOR EACH ROW EXECUTE FUNCTION atualizar_timestamp();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

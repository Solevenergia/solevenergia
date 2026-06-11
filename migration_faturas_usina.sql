-- ============================================================
--  tb_faturas_usina — controle dos boletos das usinas
--  (fatura Equatorial da UC geradora que a SoLev paga e
--   desconta do proprietário). 1 registro por usina/mês.
--  Rodar no Supabase SQL Editor.
-- ============================================================
CREATE TABLE IF NOT EXISTS tb_faturas_usina (
    id_fatura_usina   BIGSERIAL PRIMARY KEY,
    id_usina          BIGINT NOT NULL REFERENCES tb_usinas(id_usina) ON DELETE CASCADE,

    mes_referencia    TEXT   NOT NULL,            -- 'M/AAAA' (igual geracao_mensal)
    ano_referencia    INT,
    mes_num           INT,

    qtd_geracao_kwh   NUMERIC DEFAULT 0,          -- geração do ciclo (da extração)
    vlr_fatura        NUMERIC,                    -- valor do boleto que a SoLev paga
    dt_vencimento     DATE,
    dt_leitura        DATE,                       -- leitura da fatura (opcional)

    cod_barras        TEXT,                       -- linha digitável / código de barras
    pix_copia_cola    TEXT,                       -- PIX copia-e-cola do boleto

    status_pgto       TEXT NOT NULL DEFAULT 'pendente',  -- pendente | pago | cancelado
    dt_pagamento      DATE,                       -- quando a SoLev pagou

    desc_obs          TEXT,
    pdf_path          TEXT,                       -- caminho local do PDF
    pdf_url           TEXT,                       -- URL (CDN), se houver

    criado_em         TIMESTAMPTZ DEFAULT now(),
    atualizado_em     TIMESTAMPTZ DEFAULT now(),

    UNIQUE (id_usina, mes_referencia)
);

CREATE INDEX IF NOT EXISTS idx_faturas_usina_venc   ON tb_faturas_usina (dt_vencimento);
CREATE INDEX IF NOT EXISTS idx_faturas_usina_status ON tb_faturas_usina (status_pgto);
CREATE INDEX IF NOT EXISTS idx_faturas_usina_usina  ON tb_faturas_usina (id_usina);

-- atualiza atualizado_em em cada UPDATE
CREATE OR REPLACE FUNCTION _touch_faturas_usina() RETURNS trigger AS $$
BEGIN
    NEW.atualizado_em = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_touch_faturas_usina ON tb_faturas_usina;
CREATE TRIGGER trg_touch_faturas_usina
    BEFORE UPDATE ON tb_faturas_usina
    FOR EACH ROW EXECUTE FUNCTION _touch_faturas_usina();

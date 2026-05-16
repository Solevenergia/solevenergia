-- =============================================================
-- CONTALEV — Migracao 001: saldo conferido em tb_cliente_usina
-- =============================================================
-- Adiciona campos para controle do saldo conferido manualmente
-- pelo usuario, separando do saldo bruto que veio da Equatorial.
--
-- Como rodar:
--   1. Supabase Studio → SQL Editor → New Query
--   2. Cole este script e clique "Run"
--   3. Confirme em Table Editor que tb_cliente_usina tem as
--      novas colunas: dt_saldo_conferido, desc_saldo_obs
-- =============================================================

ALTER TABLE tb_cliente_usina
    ADD COLUMN IF NOT EXISTS dt_saldo_conferido DATE;

ALTER TABLE tb_cliente_usina
    ADD COLUMN IF NOT EXISTS desc_saldo_obs TEXT DEFAULT '';

-- Comentarios para documentar o uso das colunas
COMMENT ON COLUMN tb_cliente_usina.qtd_saldo_kwh IS
    'Saldo conferido pelo usuario (kWh). Pode divergir do saldo na fatura da Equatorial.';

COMMENT ON COLUMN tb_cliente_usina.dt_saldo_conferido IS
    'Data da ultima conferencia do saldo pelo usuario.';

COMMENT ON COLUMN tb_cliente_usina.desc_saldo_obs IS
    'Observacao livre sobre a ultima conferencia (ex: "conferido com fatura X").';

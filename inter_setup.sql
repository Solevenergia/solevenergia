-- inter_setup.sql
-- Execute este script no Supabase SQL Editor UMA VEZ para adicionar as colunas
-- de integração com o Banco Inter na tabela tb_faturas.
--
-- Acesse: painel Supabase → SQL Editor → cole e execute.

ALTER TABLE tb_faturas
  ADD COLUMN IF NOT EXISTS inter_nosso_numero TEXT,
  ADD COLUMN IF NOT EXISTS inter_seu_numero   TEXT,
  ADD COLUMN IF NOT EXISTS inter_linha_dig    TEXT,
  ADD COLUMN IF NOT EXISTS inter_pix_copia    TEXT,
  ADD COLUMN IF NOT EXISTS inter_status       TEXT,
  ADD COLUMN IF NOT EXISTS inter_dt_emissao   DATE;

-- Índice único para lookup no webhook (nossoNumero → id_fatura em O(1))
CREATE UNIQUE INDEX IF NOT EXISTS idx_faturas_inter_nosso_numero
  ON tb_faturas (inter_nosso_numero)
  WHERE inter_nosso_numero IS NOT NULL;

-- Confirma
SELECT column_name, data_type
  FROM information_schema.columns
 WHERE table_name = 'tb_faturas'
   AND column_name LIKE 'inter_%'
 ORDER BY column_name;

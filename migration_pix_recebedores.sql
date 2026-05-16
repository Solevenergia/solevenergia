-- =================================================================
-- Migration: Sistema Multi-Pix com histórico de vínculos
-- Execute no Supabase SQL Editor (Dashboard > SQL Editor)
-- =================================================================

-- 1. Campos para exibição no QR Code PIX (nome e cidade têm limite de
--    caracteres no padrão BRCode: nome ≤ 25, cidade ≤ 15)
ALTER TABLE tb_investidores
  ADD COLUMN IF NOT EXISTS desc_nome_pix   VARCHAR(25),
  ADD COLUMN IF NOT EXISTS desc_cidade_pix VARCHAR(15);

-- 2. Histórico de vínculos: quando o vínculo começou e quando terminou
ALTER TABLE tb_cliente_usina
  ADD COLUMN IF NOT EXISTS dt_inicio DATE DEFAULT CURRENT_DATE,
  ADD COLUMN IF NOT EXISTS dt_fim    DATE;          -- NULL = vínculo ativo

-- 3. Novo PK serial para permitir múltiplos períodos da mesma dupla
--    (cliente pode sair de uma usina e voltar depois)
ALTER TABLE tb_cliente_usina
  ADD COLUMN IF NOT EXISTS id BIGSERIAL;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'tb_cliente_usina_pkey'
      AND conrelid = 'tb_cliente_usina'::regclass
  ) THEN
    ALTER TABLE tb_cliente_usina DROP CONSTRAINT tb_cliente_usina_pkey;
  END IF;
END $$;

ALTER TABLE tb_cliente_usina ADD PRIMARY KEY (id);

-- 4. Permite endereços de usinas sem cliente vinculado
ALTER TABLE tb_enderecos ALTER COLUMN id_cliente DROP NOT NULL;

-- 6. Informações do dono da usina e documentos anexos
ALTER TABLE tb_usinas
  ADD COLUMN IF NOT EXISTS desc_dono_nome          TEXT,
  ADD COLUMN IF NOT EXISTS desc_dono_cpf_cnpj      TEXT,
  ADD COLUMN IF NOT EXISTS desc_dono_telefone      TEXT,
  ADD COLUMN IF NOT EXISTS desc_dono_email         TEXT,
  ADD COLUMN IF NOT EXISTS dt_dono_nascimento      TEXT,
  ADD COLUMN IF NOT EXISTS dt_nascimento_titular   TEXT,
  ADD COLUMN IF NOT EXISTS path_doc_cnh_rg         TEXT,
  ADD COLUMN IF NOT EXISTS path_doc_procuracao     TEXT,
  ADD COLUMN IF NOT EXISTS path_doc_cnh_rg_proc    TEXT;

-- 5. Índices de performance
CREATE INDEX IF NOT EXISTS idx_cli_usina_cliente
  ON tb_cliente_usina(id_cliente);

CREATE INDEX IF NOT EXISTS idx_cli_usina_usina
  ON tb_cliente_usina(id_usina);

CREATE INDEX IF NOT EXISTS idx_cli_usina_ativo
  ON tb_cliente_usina(id_cliente)
  WHERE dt_fim IS NULL;

-- Inativar usina (igual ao STATUS de tb_clientes)
-- Rodar no SQL Editor do Supabase (projeto SOLEV v2)
-- Linhas existentes ganham true (ativa) automaticamente.

ALTER TABLE tb_usinas
    ADD COLUMN IF NOT EXISTS "STATUS" boolean NOT NULL DEFAULT true;

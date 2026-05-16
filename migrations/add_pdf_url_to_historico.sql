-- Migration: adiciona colunas de PDF/Storage na tabela historico
-- Execute no Supabase SQL Editor: https://supabase.com/dashboard/project/akmeitjtxpoxrpdxplgc/sql
-- Data: 2026-05-03

-- URL da cobranca CONTALEV no Supabase Storage
ALTER TABLE historico ADD COLUMN IF NOT EXISTS pdf_url TEXT DEFAULT '';

-- Fatura Equatorial (nome do arquivo + URL no Storage)
ALTER TABLE historico ADD COLUMN IF NOT EXISTS pdf_equatorial TEXT DEFAULT '';
ALTER TABLE historico ADD COLUMN IF NOT EXISTS pdf_equatorial_url TEXT DEFAULT '';

-- Verifica resultado
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'historico'
  AND column_name IN ('pdf_url', 'pdf_equatorial', 'pdf_equatorial_url')
ORDER BY column_name;

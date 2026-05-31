-- ============================================================
-- MIGRAÇÃO: Unificar tb_donos → tb_investidores
-- Executar no Supabase SQL Editor:
-- https://app.supabase.com/project/bwljfybvyepbcalmmcfi/sql
--
-- ATENÇÃO: Execute os passos UM A UM e verifique o resultado
-- de cada um antes de continuar.
-- ============================================================


-- ── PASSO 1: Visualizar o que será migrado ──────────────────
-- Rode primeiro só isso para conferir os dados:
SELECT
    d.id_dono,
    d.desc_nome,
    d.desc_cpf_cnpj,
    d.desc_telefone,
    d.desc_email,
    d.dt_nascimento,
    CASE
        WHEN i.id_investidor IS NOT NULL THEN 'JÁ EXISTE em tb_investidores (ID ' || i.id_investidor || ')'
        ELSE 'SERÁ INSERIDO'
    END AS situacao
FROM tb_donos d
LEFT JOIN tb_investidores i ON i.desc_cpf_cnpj = d.desc_cpf_cnpj
    AND d.desc_cpf_cnpj IS NOT NULL AND d.desc_cpf_cnpj <> ''
ORDER BY d.id_dono;


-- ── PASSO 2: Migrar donos que ainda não existem ─────────────
-- Insere em tb_investidores os donos que não têm CPF/CNPJ
-- correspondente lá ainda:
INSERT INTO tb_investidores (desc_nome, desc_cpf_cnpj, desc_telefone, desc_email)
SELECT DISTINCT ON (d.desc_cpf_cnpj)
    d.desc_nome,
    d.desc_cpf_cnpj,
    d.desc_telefone,
    d.desc_email
FROM tb_donos d
WHERE NOT EXISTS (
    SELECT 1 FROM tb_investidores i
    WHERE i.desc_cpf_cnpj = d.desc_cpf_cnpj
      AND d.desc_cpf_cnpj IS NOT NULL
      AND d.desc_cpf_cnpj <> ''
)
RETURNING id_investidor, desc_nome, desc_cpf_cnpj;


-- ── PASSO 3: Ver o mapeamento dono → investidor ─────────────
-- Confira antes de atualizar as usinas:
SELECT
    u.id_usina,
    u.desc_nome AS usina,
    u.id_dono,
    d.desc_nome AS dono_nome,
    i.id_investidor,
    i.desc_nome AS investidor_nome
FROM tb_usinas u
JOIN tb_donos d ON d.id_dono = u.id_dono
JOIN tb_investidores i ON i.desc_cpf_cnpj = d.desc_cpf_cnpj
WHERE u.id_dono IS NOT NULL
ORDER BY u.id_usina;


-- ── PASSO 4: Atualizar id_investidor nas usinas ─────────────
-- Para cada usina que tem id_dono mas não tem id_investidor,
-- preenche id_investidor com o registro migrado:
UPDATE tb_usinas u
SET id_investidor = i.id_investidor
FROM tb_donos d
JOIN tb_investidores i
  ON i.desc_cpf_cnpj = d.desc_cpf_cnpj
WHERE u.id_dono = d.id_dono
  AND u.id_investidor IS NULL
  AND d.desc_cpf_cnpj IS NOT NULL
  AND d.desc_cpf_cnpj <> '';

-- Verificar resultado:
SELECT id_usina, desc_nome, id_investidor, id_dono
FROM tb_usinas
WHERE id_dono IS NOT NULL
ORDER BY id_usina;


-- ── PASSO 5: Remover coluna id_dono de tb_usinas ────────────
ALTER TABLE tb_usinas DROP COLUMN IF EXISTS id_dono;


-- ── PASSO 6: Remover tabela tb_donos ────────────────────────
DROP TABLE IF EXISTS tb_donos;


-- ── PASSO 7: Confirmar resultado final ──────────────────────
SELECT
    u.id_usina,
    u.desc_nome AS usina,
    i.id_investidor,
    i.desc_nome AS proprietario,
    i.desc_pix,
    i.pct_desagio
FROM tb_usinas u
LEFT JOIN tb_investidores i ON i.id_investidor = u.id_investidor
ORDER BY u.id_usina;

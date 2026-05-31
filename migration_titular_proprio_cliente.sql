-- migration_titular_proprio_cliente.sql
-- Adiciona campos em tb_clientes para clientes cujo titular da UC é diferente
-- do titular da usina vinculada (ex.: cliente independente recebendo créditos
-- via rateio Equatorial, mas mantém sua própria titularidade da UC).
--
-- Executar no Supabase SQL Editor:
--   1. Abre https://supabase.com/dashboard/project/<projeto>/sql
--   2. Cola este arquivo
--   3. Clica "Run"

ALTER TABLE tb_clientes
  ADD COLUMN IF NOT EXISTS desc_nome_titular_fatura  VARCHAR(200),
  ADD COLUMN IF NOT EXISTS desc_cpf_titular_fatura   VARCHAR(20),
  ADD COLUMN IF NOT EXISTS dt_nascimento_titular_fatura DATE,
  ADD COLUMN IF NOT EXISTS flg_titularidade_propria  BOOLEAN DEFAULT false;

COMMENT ON COLUMN tb_clientes.desc_nome_titular_fatura IS
  'Nome do titular da UC consumidora (se diferente do titular da usina vinculada).';

COMMENT ON COLUMN tb_clientes.desc_cpf_titular_fatura IS
  'CPF/CNPJ do titular da UC. Quando preenchido + flg_titularidade_propria, usado no login Equatorial.';

COMMENT ON COLUMN tb_clientes.dt_nascimento_titular_fatura IS
  'Data de nascimento do titular da UC. Usada para login no portal Equatorial.';

COMMENT ON COLUMN tb_clientes.flg_titularidade_propria IS
  'Quando TRUE, sistema usa desc_cpf_titular_fatura + dt_nascimento_titular_fatura como credenciais Equatorial em vez do titular da usina vinculada.';

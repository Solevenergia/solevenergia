-- SoLev Energia — UNIQUE em tb_enderecos.id_cliente
-- Necessario pro upsert do importar_planilha.py funcionar
-- (1 endereco por cliente — eh o caso no SoLev)

-- Remove duplicatas se houver, mantendo o id mais recente por cliente
DELETE FROM tb_enderecos a
USING tb_enderecos b
WHERE a.id_cliente = b.id_cliente
  AND a.id_endereco < b.id_endereco;

-- Adiciona UNIQUE
ALTER TABLE tb_enderecos
  ADD CONSTRAINT tb_enderecos_id_cliente_key UNIQUE (id_cliente);

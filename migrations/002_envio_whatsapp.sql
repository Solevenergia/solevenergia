-- ============================================================
-- Controle de envio da mensagem de cobrança por WhatsApp
-- Rodar no Supabase: SQL Editor > New query > colar > Run
-- ============================================================
-- dt_envio_whatsapp   : último envio (NULL = nunca enviada)
-- envio_whatsapp_por  : usuário logado que enviou (admin, julio…)
-- qtd_envios_whatsapp : total de aberturas do WhatsApp (reenvio conta)

alter table tb_faturas add column if not exists dt_envio_whatsapp   timestamptz;
alter table tb_faturas add column if not exists envio_whatsapp_por  text;
alter table tb_faturas add column if not exists qtd_envios_whatsapp integer not null default 0;

comment on column tb_faturas.dt_envio_whatsapp   is 'Último envio da cobrança por WhatsApp (clique no botão ou marcação manual)';
comment on column tb_faturas.envio_whatsapp_por  is 'Usuário logado que fez o último envio';
comment on column tb_faturas.qtd_envios_whatsapp is 'Total de aberturas do WhatsApp para esta fatura (reenvios contam)';

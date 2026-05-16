# SoLev Energia

Sistema de gestao de cobrancas e rateio de energia solar.
Fork do CONTALEV v1, adaptado para a operacao da SoLev Energia.

## Stack
- Python 3.11+ / Flask
- Supabase (PostgreSQL + Storage)
- Bootstrap 5

## Rodar localmente

```bash
pip install -r requirements.txt
python app.py
```

Acessa: http://localhost:5000

## Estrutura
- `app.py` — entry point Flask
- `db.py` — camada de acesso ao Supabase
- `routes/` — rotas Flask por modulo
- `templates/` — Jinja2 HTML
- `static/` — assets web
- `migrations/` — scripts SQL evolutivos

## Credenciais (nao commitar)
- `supabase_config.json` — chaves Supabase
- `.env` — segredos locais

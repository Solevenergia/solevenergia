"""
Atualiza a fatura do Antonio (id=6, 05/2026) com os dados SCEE extraídos
do PDF da Equatorial.

PASSO 1 — Execute este SQL no Supabase SQL Editor:
────────────────────────────────────────────────────────────────────────────
ALTER TABLE tb_faturas
  ADD COLUMN IF NOT EXISTS desc_ciclo_geracao      TEXT,
  ADD COLUMN IF NOT EXISTS cod_uc_usina            TEXT,
  ADD COLUMN IF NOT EXISTS pct_rateio_scee         NUMERIC(8,4),
  ADD COLUMN IF NOT EXISTS qtd_geracao_usina_kwh   NUMERIC(12,2),
  ADD COLUMN IF NOT EXISTS qtd_excedente_kwh       NUMERIC(12,2),
  ADD COLUMN IF NOT EXISTS qtd_credito_kwh         NUMERIC(12,2),
  ADD COLUMN IF NOT EXISTS qtd_saldo_exp_30d_kwh   NUMERIC(12,2),
  ADD COLUMN IF NOT EXISTS qtd_saldo_exp_60d_kwh   NUMERIC(12,2);
────────────────────────────────────────────────────────────────────────────

PASSO 2 — Execute este script:
    python scripts/atualizar_scee_antonio.py
"""
import sys, os
# Garante UTF-8 no stdout (Windows cp1252 nao suporta simbolos especiais)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from extrair_equatorial import extrair_equatorial
from db import _db

# ── Configuração ────────────────────────────────────────────────────────────
ID_FATURA       = 6
PDF_EQUATORIAL  = "uploads/052026-EQUATORIAL-000102059901249.pdf"
# ────────────────────────────────────────────────────────────────────────────

print("=" * 60)
print(" Atualização SCEE — Fatura #6 / Antonio de Paula Oliveira")
print("=" * 60)

# 1) Extrai dados SCEE do PDF
print(f"\n1. Extraindo dados de: {PDF_EQUATORIAL}")
if not os.path.exists(PDF_EQUATORIAL):
    print(f"   ERRO: PDF não encontrado em {PDF_EQUATORIAL}")
    sys.exit(1)

dados = extrair_equatorial(PDF_EQUATORIAL)

excedente = dados.get("excedente_recebido_kwh", 0) or 0
pct       = dados.get("scee_pct_rateio", 0) or 0
credito   = dados.get("credito_recebido_kwh", 0) or 0
saldo     = dados.get("saldo_kwh", 0) or 0
s30       = dados.get("saldo_expirar_30d_kwh", 0) or 0
s60       = dados.get("saldo_expirar_60d_kwh", 0) or 0
ciclo     = dados.get("ciclo_geracao_mes") or dados.get("scee_ciclo_mes", "")
uc_usina  = dados.get("scee_uc_geradora", "")

# Geração estimada da usina (excedente ÷ % rateio)
geracao_usina = round(excedente / (pct / 100), 2) if pct > 0 else 0

print(f"\n   Ciclo de geração:          {ciclo}")
print(f"   UC da usina geradora:      {uc_usina}")
print(f"   % Rateio desta UC:         {pct:.4f}%")
print(f"   Excedente recebido:        {excedente:,.2f} kWh")
print(f"   Crédito compensado:        {credito:,.2f} kWh")
print(f"   Saldo disponível:          {saldo:,.2f} kWh")
print(f"   Saldo expira 30d:          {s30:,.2f} kWh")
print(f"   Saldo expira 60d:          {s60:,.2f} kWh")
print(f"   Geração estimada da usina: {geracao_usina:,.2f} kWh  (= {excedente} ÷ {pct/100})")

# 2) Verifica colunas no banco
print("\n2. Verificando colunas SCEE no banco...")
db = _db()
try:
    rows = db.select("tb_faturas", filtros={"id_fatura": ID_FATURA})
    if not rows:
        print(f"   ERRO: fatura id={ID_FATURA} não encontrada.")
        sys.exit(1)
    fatura = rows[0]
    if "desc_ciclo_geracao" not in fatura:
        print("\n   ⚠️  COLUNAS SCEE AINDA NÃO EXISTEM NO BANCO.")
        print("   Execute o SQL do PASSO 1 no Supabase SQL Editor e rode este script novamente.\n")
        sys.exit(1)
    print("   ✓ Colunas SCEE encontradas.")
except Exception as e:
    print(f"   Erro ao acessar banco: {e}")
    sys.exit(1)

# 3) Atualiza o registro
print(f"\n3. Atualizando fatura id={ID_FATURA}...")
update_data = {
    "desc_ciclo_geracao":   ciclo,
    "cod_uc_usina":         uc_usina,
    "pct_rateio_scee":      round(pct, 4),
    "qtd_geracao_usina_kwh":geracao_usina,
    "qtd_excedente_kwh":    round(excedente, 2),
    "qtd_credito_kwh":      round(credito, 2),
    "qtd_saldo_exp_30d_kwh":round(s30, 2),
    "qtd_saldo_exp_60d_kwh":round(s60, 2),
}

try:
    db.patch("tb_faturas", {"id_fatura": ID_FATURA}, update_data)
    print("   ✓ Fatura atualizada com sucesso!\n")
    print("   Campos gravados:")
    for k, v in update_data.items():
        print(f"     {k}: {v}")
except Exception as e:
    print(f"   ERRO ao atualizar: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print(" Concluído.")
print("=" * 60)

"""Backup local do Supabase SOLEV.

Exporta as tabelas de negócio para um JSON datado em backups/.
Mantém os últimos RETENCAO backups (apaga os mais antigos).

Uso:
    python backup_supabase.py

Agendado diariamente via Agendador de Tarefas do Windows.
Restaurar: ver restaurar_backup.py (gerado junto) ou importar o JSON manualmente.
"""
import os, sys, json
from datetime import datetime

# Garante que roda a partir da pasta do projeto (acha supabase_config.json)
_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(_DIR)
sys.path.insert(0, _DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from db import _db

# Tabelas de negócio (todas as que aparecem no código)
TABELAS = [
    "tb_clientes", "tb_enderecos", "tb_cliente_usina", "tb_usinas",
    "tb_investidores", "tb_titulares", "tb_rateios_mensais",
    "tb_simulacoes", "tb_faturas", "tb_historico_consumo",
    "tb_documentos_cliente",
]
RETENCAO = 30  # mantém os últimos N backups


def main():
    db = _db()
    dump, resumo, total = {}, [], 0
    for t in TABELAS:
        try:
            rows = db.select(t)
            dump[t] = rows
            total += len(rows)
            resumo.append(f"  {t:24s}: {len(rows)}")
        except Exception as e:
            dump[t] = {"_erro": str(e)}
            resumo.append(f"  {t:24s}: ERRO ({str(e)[:50]})")

    os.makedirs("backups", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = os.path.join("backups", f"solev_backup_{ts}.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump({"_gerado_em": datetime.now().isoformat(), "tabelas": dump},
                  f, ensure_ascii=False, indent=1)

    print(f"[{ts}] Backup salvo: {caminho}  ({total} registros)")
    for r in resumo:
        print(r)

    # Retenção: remove backups além dos últimos RETENCAO
    arquivos = sorted(f for f in os.listdir("backups")
                      if f.startswith("solev_backup_") and f.endswith(".json"))
    for antigo in arquivos[:-RETENCAO]:
        try:
            os.remove(os.path.join("backups", antigo))
            print(f"  (removido antigo: {antigo})")
        except Exception:
            pass


if __name__ == "__main__":
    main()

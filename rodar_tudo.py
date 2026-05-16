"""
rodar_tudo.py — CONTALEV
Executa o pipeline completo para todos os clientes:
  1. Baixa fatura da Equatorial GO (Playwright)
  2. Extrai dados do PDF
  3. Gera cobranca CONTALEV
  4. Envia WhatsApp com PDF

Uso:
  python rodar_tudo.py                    # mes atual, todos os clientes
  python rodar_tudo.py --mes 04/2026      # mes especifico
  python rodar_tudo.py --uc 3011234567    # um cliente
  python rodar_tudo.py --so-gerar         # sem download, sem WA
  python rodar_tudo.py --sem-whatsapp     # download + gera, sem WA
  python rodar_tudo.py --headless         # browser invisivel
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime


def mes_atual():
    return datetime.now().strftime("%m/%Y")


def rodar_etapa(descricao: str, comando: list) -> bool:
    print(f"\n{'▶'*3} {descricao}")
    print(f"   {' '.join(comando)}")
    resultado = subprocess.run(comando, capture_output=False)
    ok = resultado.returncode == 0
    print(f"   {'✅ OK' if ok else '❌ FALHOU'}")
    return ok


def main():
    parser = argparse.ArgumentParser(description="CONTALEV — Pipeline completo")
    parser.add_argument("--uc",            type=str,             help="UC especifica")
    parser.add_argument("--mes",           type=str, default=None)
    parser.add_argument("--headless",      action="store_true")
    parser.add_argument("--sem-whatsapp",  action="store_true")
    parser.add_argument("--so-gerar",      action="store_true",  help="So gera cobrancas (sem download e sem WA)")
    parser.add_argument("--forcar",        action="store_true",  help="Re-baixa mesmo se fatura ja existir")
    args = parser.parse_args()

    mes = args.mes or mes_atual()

    print(f"\n{'═'*60}")
    print(f"  CONTALEV — Pipeline Mensal")
    print(f"  Mes: {mes}  |  {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'═'*60}")

    alvo = ["--uc", args.uc] if args.uc else ["--todos"]

    # ── Etapa 1: Download das faturas ─────────────────────────────────────────
    if not args.so_gerar:
        cmd_download = (
            ["python", "baixar_equatorial.py"]
            + alvo
            + ["--mes", mes]
            + (["--headless"] if args.headless else [])
            + (["--forcar"]   if args.forcar   else [])
        )
        ok = rodar_etapa("ETAPA 1 — Download faturas Equatorial GO", cmd_download)
        if not ok:
            print("\n⚠️  Download teve falhas. Continuando com as faturas disponiveis...")

    # ── Etapa 2 + 3: Gera cobrancas ───────────────────────────────────────────
    cmd_gerar = (
        ["python", "pipeline_contalev.py"]
        + alvo
        + ["--sem-whatsapp"]
    )
    ok = rodar_etapa("ETAPA 2/3 — Extracao + Geracao de cobrancas CONTALEV", cmd_gerar)
    if not ok:
        print("\n❌ Falha critica na geracao de cobrancas. Abortando.")
        sys.exit(1)

    # ── Etapa 4: Envio WhatsApp ────────────────────────────────────────────────
    if not args.sem_whatsapp and not args.so_gerar:
        cmd_wa = (
            ["python", "pipeline_contalev.py"]
            + alvo
        )
        rodar_etapa("ETAPA 4 — Envio via WhatsApp", cmd_wa)

    print(f"\n{'═'*60}")
    print(f"  Pipeline concluido — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'═'*60}\n")


if __name__ == "__main__":
    main()

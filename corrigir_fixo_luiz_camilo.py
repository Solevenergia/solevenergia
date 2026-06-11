"""
corrigir_fixo_luiz_camilo.py
Pós-incidente 03/06: recria os vínculos FIXO do Luiz Camilo de Oliveira nas
usinas USJoseOliveira88/93 (ids novos), fechando os vínculos residuais errados.

Config (travada no Distribuir Clientes):
  UC 000148948401217 → USJoseOliveira88 (UC ...88)  90%
  UC 000358864801258 → USJoseOliveira88 (UC ...88)  10%
                     → USJoseOliveira93 (UC ...93) 100%

Idempotente. Resolve clientes por cod_uc e usinas por uc_geradora.
Execute: python corrigir_fixo_luiz_camilo.py
"""
import sys, io
from datetime import date
sys.path.insert(0, r"C:\Rede\SOLEV")
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass
from db import _db

HOJE = date.today().isoformat()

# UC geradora -> pct, por cod_uc do cliente
PLANO = [
    {"cod_uc_cliente": "000148948401217", "uc_geradora": "000395413701288", "pct": 90},   # us88
    {"cod_uc_cliente": "000358864801258", "uc_geradora": "000395413701288", "pct": 10},   # us88
    {"cod_uc_cliente": "000358864801258", "uc_geradora": "000432204401293", "pct": 100},  # us93
]


def _resolve_cliente(db, cod_uc):
    r = db.select("tb_clientes", filtros={"cod_uc": cod_uc}, columns="id_cliente,desc_nome,cod_uc")
    return r[0] if r else None


def _resolve_usina(db, uc_geradora):
    r = db.select("tb_usinas", raw_params={"cod_uc_geradora": f"eq.{uc_geradora}"},
                  columns="id_usina,desc_nome,cod_uc_geradora")
    return r[0] if r else None


def main():
    db = _db()
    print("\n" + "="*64)
    print("  Correção FIXO — Luiz Camilo de Oliveira")
    print("="*64 + "\n")

    # Resolve clientes e usinas
    ids_clientes = set()
    plano_res = []
    for p in PLANO:
        cli = _resolve_cliente(db, p["cod_uc_cliente"])
        usi = _resolve_usina(db, p["uc_geradora"])
        if not cli:
            print(f"  ❌ Cliente UC {p['cod_uc_cliente']} não encontrado"); return
        if not usi:
            print(f"  ❌ Usina UC geradora {p['uc_geradora']} não encontrada"); return
        ids_clientes.add(cli["id_cliente"])
        plano_res.append((cli, usi, p["pct"]))
        print(f"  • {cli['desc_nome']} (id={cli['id_cliente']}, UC {p['cod_uc_cliente']}) "
              f"→ {usi['desc_nome']} (id={usi['id_usina']})  {p['pct']}%")

    # 1) Fecha vínculos ATIVOS não-FIXO desses clientes (resíduo do incidente)
    print("\n  Fechando vínculos residuais (ativos, não-FIXO)...")
    fechados = 0
    for id_c in ids_clientes:
        ativos = db.select("tb_cliente_usina",
            raw_params={"id_cliente": f"eq.{id_c}", "dt_fim": "is.null"},
            columns="id,id_usina,pct_rateio,desc_saldo_obs")
        for v in ativos:
            if (v.get("desc_saldo_obs") or "").upper() == "FIXO":
                continue  # já é FIXO, não mexe
            db.patch("tb_cliente_usina", {"id": v["id"]}, {"dt_fim": HOJE})
            fechados += 1
            print(f"     fechado: cliente={id_c} usina={v.get('id_usina')} pct={v.get('pct_rateio')}")
    if not fechados:
        print("     (nenhum resíduo a fechar)")

    # 2) Cria os vínculos FIXO corretos (idempotente)
    print("\n  Criando vínculos FIXO...")
    for cli, usi, pct in plano_res:
        ja = db.select("tb_cliente_usina",
            raw_params={"id_cliente": f"eq.{cli['id_cliente']}", "id_usina": f"eq.{usi['id_usina']}",
                        "dt_fim": "is.null", "desc_saldo_obs": "eq.FIXO"})
        if ja:
            print(f"     ⏭️  já existe FIXO: {cli['desc_nome']} → {usi['desc_nome']} ({pct}%)")
            continue
        db.upsert("tb_cliente_usina", {
            "id_cliente":     cli["id_cliente"],
            "id_usina":       usi["id_usina"],
            "pct_rateio":     pct,
            "dt_inicio":      HOJE,
            "desc_saldo_obs": "FIXO",
        })
        print(f"     ✅ FIXO: {cli['desc_nome']} → {usi['desc_nome']} ({pct}%)")

    print("\n" + "="*64)
    print("  Concluído. Vínculos FIXO travados — não serão tocados pelo")
    print("  algoritmo de distribuição.")
    print("="*64 + "\n")


if __name__ == "__main__":
    main()

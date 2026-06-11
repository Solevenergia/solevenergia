"""
cadastrar_luiz_camilo.py

⚠️ OBSOLETO — os ids de usina aqui (22/23) são PRÉ-incidente 03/06 e não
   existem mais. Para (re)criar os vínculos FIXO do Luiz Camilo use:
       python corrigir_fixo_luiz_camilo.py
   (resolve clientes/usinas por UC, robusto a mudança de id, e fecha resíduos).

Registra os 2 clientes (UCs) do Luiz Camilo de Oliveira e cria os vínculos
FIXOS com as usinas USJoseOliveira93 e USJoseOliveira88.

Vínculos:
  UC 000358864801258 → USJoseOliveira93 (id=22) 100%
                     → USJoseOliveira88 (id=23)  10%
  UC 000148948401217 → USJoseOliveira88 (id=23)  90%

Execute UMA única vez: python cadastrar_luiz_camilo.py
"""
import sys, io
from datetime import date

sys.path.insert(0, r"C:\Rede\SOLEV")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from db import _db

HOJE = date.today().isoformat()

# ─── DADOS DOS CLIENTES ────────────────────────────────────────────────────────
# Preencha os campos opcionais antes de executar (deixe None se não souber)
CLIENTES = [
    {
        "cod_uc":                "000358864801258",
        "desc_nome":             "LUIZ CAMILO DE OLIVEIRA",
        "desc_apelido":          None,          # ex: "LUIZCAMILO1"
        "desc_cpf":              None,          # ex: "123.456.789-00"
        "desc_telefone":         None,          # ex: "(62) 99999-9999"
        "desc_email":            None,
        "desc_titular_fatura":   "JOSE OLIVEIRA",
        "pct_desconto":          0.20,
        "tp_bandeira":           "com_bandeira",
        "tp_fornecimento":       "MONOFASICO",
        "proxima_leitura":       "2026-06-08",  # dia 8 = USJoseOliveira93
        "qtd_consumo_medio_kwh": 17262.0,       # 16100 (93/100%) + 1162 (88/10%)
        "STATUS":                True,
    },
    {
        "cod_uc":                "000148948401217",
        "desc_nome":             "LUIZ CAMILO DE OLIVEIRA",
        "desc_apelido":          None,          # ex: "LUIZCAMILO2"
        "desc_cpf":              None,
        "desc_telefone":         None,
        "desc_email":            None,
        "desc_titular_fatura":   "JOSE OLIVEIRA",
        "pct_desconto":          0.20,
        "tp_bandeira":           "com_bandeira",
        "tp_fornecimento":       "MONOFASICO",
        "proxima_leitura":       "2026-06-10",  # dia 10 = USJoseOliveira88
        "qtd_consumo_medio_kwh": 10456.0,       # 11618 (88/90%)
        "STATUS":                True,
    },
]

# ─── VÍNCULOS FIXOS ────────────────────────────────────────────────────────────
# (id_cliente será resolvido após o INSERT dos clientes)
VINCULOS = [
    # UC 000358864801258
    {"cod_uc": "000358864801258", "id_usina": 22, "pct_rateio": 100},  # USJoseOliveira93 100%
    {"cod_uc": "000358864801258", "id_usina": 23, "pct_rateio": 10},   # USJoseOliveira88  10%
    # UC 000148948401217
    {"cod_uc": "000148948401217", "id_usina": 23, "pct_rateio": 90},   # USJoseOliveira88  90%
]


def main():
    db = _db()

    print(f"\n{'='*60}")
    print("  Cadastro Luiz Camilo de Oliveira")
    print(f"{'='*60}\n")

    # ─── 1) Registra os clientes ───────────────────────────────────
    uc_para_id: dict[str, int] = {}

    for dados in CLIENTES:
        cod_uc = dados["cod_uc"]

        # Verifica se já existe
        existentes = db.select("tb_clientes", filtros={"cod_uc": cod_uc})
        if existentes:
            id_cliente = existentes[0]["id_cliente"]
            print(f"  ⏭️  UC {cod_uc} já existe → id_cliente={id_cliente}")
            uc_para_id[cod_uc] = id_cliente
            continue

        # Monta o payload (sem campos None)
        row = {k: v for k, v in dados.items() if v is not None}
        if "desc_cpf" in row:
            import re
            row["desc_cpf"] = re.sub(r'[.\-/]', '', row["desc_cpf"])

        resultado = db.upsert_returning("tb_clientes", row, on_conflict="cod_uc")
        id_cliente = resultado.get("id_cliente")
        if id_cliente:
            uc_para_id[cod_uc] = id_cliente
            print(f"  ✅ UC {cod_uc} → id_cliente={id_cliente}  ({dados['desc_nome']})")
        else:
            print(f"  ❌ Falha ao inserir UC {cod_uc}: {resultado}")
            return

    # ─── 2) Cria vínculos FIXO ────────────────────────────────────
    print()
    for v in VINCULOS:
        cod_uc = v["cod_uc"]
        id_cliente = uc_para_id.get(cod_uc)
        if not id_cliente:
            print(f"  ❌ id_cliente não encontrado para UC {cod_uc}")
            continue

        id_usina  = v["id_usina"]
        pct       = v["pct_rateio"]

        # Verifica se já existe vínculo ativo FIXO para essa (cliente, usina)
        existentes = db.select("tb_cliente_usina",
            raw_params={
                "id_cliente":   f"eq.{id_cliente}",
                "id_usina":     f"eq.{id_usina}",
                "dt_fim":       "is.null",
                "desc_saldo_obs": "eq.FIXO",
            })
        if existentes:
            print(f"  ⏭️  Vínculo FIXO já existe: id_cliente={id_cliente} → id_usina={id_usina} ({pct}%)")
            continue

        row = {
            "id_cliente":    id_cliente,
            "id_usina":      id_usina,
            "pct_rateio":    pct,
            "dt_inicio":     HOJE,
            "desc_saldo_obs": "FIXO",
        }
        db.upsert("tb_cliente_usina", row)
        print(f"  ✅ Vínculo FIXO: id_cliente={id_cliente} (UC {cod_uc}) → id_usina={id_usina} ({pct}%)")

    print(f"\n{'='*60}")
    print("  Concluído. Vínculos marcados como FIXO não serão")
    print("  sobrescritos pelo algoritmo de distribuição automática.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

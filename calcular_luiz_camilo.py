"""
calcular_luiz_camilo.py
Aplica a fórmula especial dos vínculos FIXO do Luiz Camilo.

Fórmula:
  cobranca_total = SUM por vínculo de:
    pct_rateio × usina_geracao_ciclo × (tarifa_usina × (1 - desconto) - tarifa_fio_b)

Onde:
  • pct_rateio          → do vínculo FIXO em tb_cliente_usina
  • usina_geracao_ciclo → geracao_ciclo_kwh do PDF Equatorial DA USINA, no ciclo aplicado
  • tarifa_usina        → tarifa_convencional do PDF Equatorial DA USINA, mesmo ciclo
  • tarifa_fio_b        → tarifa_nao_comp do PDF Equatorial DO CONSUMIDOR (Luiz)
  • desconto            → pct_desconto do cliente em tb_clientes

O ciclo aplicado é lido do `ciclo_geracao_mes` do PDF do consumidor.
"""
import sys, io
sys.path.insert(0, r"C:\Rede\SOLEV")
sys.path.insert(0, r"C:\Rede\SOLEV\scripts")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from extrair_equatorial import extrair_equatorial

# ─── PDFs disponíveis ─────────────────────────────────────────────────────────
PDF_CONSUMIDOR = {
    263: r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\LuizOliveira17-0001.489.484012-17\202604-EquatorialLuizOliveria17.pdf",
    264: r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\LuizOliveira58-0003.588.648.012-58\202604-EquatorialLuizOliveria58.pdf",
}

# PDFs de usinas indexados por (id_usina, "MM/YYYY")
PDF_USINA = {
    (23, "03/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USjoseOliveira88-0003.954.137.012-88\202603-EquatorialUCJoseOliveira88.pdf",
    (23, "04/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USjoseOliveira88-0003.954.137.012-88\202604-EquatorialUCJoseOliveira88.pdf",
    (23, "05/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USjoseOliveira88-0003.954.137.012-88\202605-EquatorialUCJoseOliveira88.pdf",
    (22, "03/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USJoseOliveira93-0004.322.044.012-93\202603-EquatorialUCJoseOliveira93.pdf",
    (22, "04/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USJoseOliveira93-0004.322.044.012-93\202604-EquatorialUCJoseOliveira93.pdf",
}

# Nomes (apenas para display)
NOME_USINA = {22: "USJoseOliveira93", 23: "USJoseOliveira88"}


def _norm_mes(s: str) -> str:
    """Normaliza '4/2026' → '04/2026'."""
    if not s or "/" not in s:
        return s
    m, a = s.split("/")
    return f"{int(m):02d}/{a}"


def calcular_cobranca_fixo(id_cliente: int):
    """Calcula a cobrança SOLEV pelo modelo FIXO (Luiz Camilo)."""
    from db import _db
    db = _db()

    # 1) Dados do cliente
    rows = db.select("tb_clientes", filtros={"id_cliente": id_cliente})
    if not rows:
        print(f"[{id_cliente}] cliente nao encontrado")
        return
    cli = rows[0]
    nome     = cli.get("desc_nome", "?")
    uc       = cli.get("cod_uc", "?")
    desconto = float(cli.get("pct_desconto") or 0)

    # 2) Vínculos FIXO ativos
    vincs = db.select("tb_cliente_usina",
        raw_params={
            "id_cliente":     f"eq.{id_cliente}",
            "dt_fim":         "is.null",
            "desc_saldo_obs": "eq.FIXO",
        })
    if not vincs:
        print(f"[{id_cliente}] {nome} - sem vinculos FIXO")
        return

    # 3) PDF do consumidor → fio_b + ciclo aplicado
    pdf_cons = PDF_CONSUMIDOR.get(id_cliente)
    if not pdf_cons:
        print(f"[{id_cliente}] PDF do consumidor nao mapeado")
        return
    cons = extrair_equatorial(pdf_cons, verbose=False)
    tarifa_fio_b = float(cons.get("tarifa_nao_comp", 0) or 0)
    ciclo_aplicado = _norm_mes(cons.get("ciclo_geracao_mes", ""))
    mes_ref = _norm_mes(cons.get("mes_referencia", ""))

    print()
    print("=" * 70)
    print(f"  CLIENTE {id_cliente} - {nome}")
    print(f"  UC consumidora : {uc}")
    print(f"  Mes referencia : {mes_ref}    Ciclo aplicado: {ciclo_aplicado}")
    print(f"  Desconto       : {desconto*100:.1f}%")
    print(f"  Tarifa fio B   : R$ {tarifa_fio_b:.6f} (tarifa_nao_comp do PDF consumidor)")
    print("=" * 70)

    total_cobranca = 0.0
    total_geracao  = 0.0
    total_sem      = 0.0
    detalhamento = []

    # 4) Loop por vínculo FIXO
    for v in vincs:
        id_usina = v.get("id_usina")
        pct      = float(v.get("pct_rateio") or 0) / 100.0
        nome_us  = NOME_USINA.get(id_usina, f"usina_{id_usina}")

        pdf_us = PDF_USINA.get((id_usina, ciclo_aplicado))
        if not pdf_us:
            print(f"  X PDF da {nome_us} no ciclo {ciclo_aplicado} nao encontrado")
            continue

        usina = extrair_equatorial(pdf_us, verbose=False)
        ger_total  = float(usina.get("geracao_ciclo_kwh", 0) or 0)
        tarifa_us  = float(usina.get("tarifa_convencional", 0) or 0)

        ger_aplicada = pct * ger_total
        # Fórmula: contribuicao = ger_aplicada × (tarifa_usina × (1-desconto) - tarifa_fio_b)
        valor_com_solev   = ger_aplicada * (tarifa_us * (1 - desconto) - tarifa_fio_b)
        valor_sem_solev   = ger_aplicada * tarifa_us
        economia          = valor_sem_solev - valor_com_solev

        detalhamento.append({
            "usina": nome_us,
            "id_usina": id_usina,
            "pct": pct * 100,
            "ger_total": ger_total,
            "ger_aplicada": ger_aplicada,
            "tarifa_us": tarifa_us,
            "valor_sem": valor_sem_solev,
            "valor_com": valor_com_solev,
            "economia": economia,
        })

        total_cobranca += valor_com_solev
        total_geracao  += ger_aplicada
        total_sem      += valor_sem_solev

        print()
        print(f"  Vinculo {nome_us} (id {id_usina})")
        print(f"    pct rateio        : {pct*100:.1f}%")
        print(f"    geracao usina     : {ger_total:>12,.2f} kWh (ciclo {ciclo_aplicado})")
        print(f"    geracao aplicada  : {ger_aplicada:>12,.2f} kWh ({pct*100:.0f}% x {ger_total:,.2f})")
        print(f"    tarifa usina      : R$ {tarifa_us:.6f}/kWh")
        print(f"    fator             : (R$ {tarifa_us:.6f} x (1-{desconto:.0%}) - R$ {tarifa_fio_b:.6f})")
        print(f"                       = (R$ {tarifa_us*(1-desconto):.6f} - R$ {tarifa_fio_b:.6f})")
        print(f"                       = R$ {tarifa_us*(1-desconto)-tarifa_fio_b:.6f}")
        print(f"    SEM SOLEV         : {ger_aplicada:,.2f} x R$ {tarifa_us:.6f} = R$ {valor_sem_solev:,.2f}")
        print(f"    COM SOLEV         : {ger_aplicada:,.2f} x R$ {tarifa_us*(1-desconto)-tarifa_fio_b:.6f} = R$ {valor_com_solev:,.2f}")
        print(f"    Economia          : R$ {economia:,.2f}")

    print()
    print("-" * 70)
    print(f"  TOTAIS CONSOLIDADOS")
    print(f"    geracao aplicada total : {total_geracao:>12,.2f} kWh")
    print(f"    SEM SOLEV (referencia) : R$ {total_sem:>12,.2f}")
    print(f"    COBRANCA SOLEV         : R$ {total_cobranca:>12,.2f}")
    print(f"    Economia total         : R$ {total_sem - total_cobranca:>12,.2f}")
    print("-" * 70)

    return {
        "id_cliente": id_cliente,
        "nome": nome,
        "uc": uc,
        "mes_ref": mes_ref,
        "ciclo": ciclo_aplicado,
        "desconto": desconto,
        "tarifa_fio_b": tarifa_fio_b,
        "vinculos": detalhamento,
        "total_geracao": total_geracao,
        "total_sem": total_sem,
        "total_com": total_cobranca,
    }


def main():
    print(f"\n{'#'*70}")
    print(f"  CALCULO FIXO - LUIZ CAMILO DE OLIVEIRA")
    print(f"  Modelo: cobranca = gerac_aplicada x (tarifa_usina x (1-desc) - fio_b)")
    print(f"{'#'*70}")

    for id_cli in [263, 264]:
        calcular_cobranca_fixo(id_cli)


if __name__ == "__main__":
    main()

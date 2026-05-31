"""
gerar_cobranças_luiz_camilo_fixo.py
Gera cobranças SOLEV para o Luiz Camilo aplicando a fórmula FIXO:

  cobranca = SUM por vínculo de:
    pct_rateio × geracao_usina_ciclo × (tarifa_usina × (1-desconto) - tarifa_fio_b)

Onde:
  • geracao_usina_ciclo → geracao_ciclo_kwh do PDF Equatorial DA USINA
  • tarifa_usina        → tarifa_convencional do PDF Equatorial DA USINA
  • tarifa_fio_b        → tarifa_nao_comp do PDF Equatorial DO CONSUMIDOR
  • desconto            → pct_desconto do cliente

Implementação: usa montar_dados/gerar_cobranca do fluxo padrão, mas:
  - override de consumo_kwh / consumo_compensado / consumo_nao_comp com geracao_aplicada
  - tarifa_sem = média ponderada das tarifas das usinas (geração-peso)
  - injeta fio_b_deducao para abater do total_com sem mexer no total_sem
"""
import os, sys, io, shutil
sys.path.insert(0, r"C:\Rede\SOLEV")
sys.path.insert(0, r"C:\Rede\SOLEV\scripts")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from extrair_equatorial import extrair_equatorial
from gerar_cobranca_auto import montar_dados, gerar_qrcode_pix
from contalev_cobranca_v2_padrao import gerar_cobranca
from db import (
    _db, carregar_clientes, storage_upload_pdf,
    tb_get_cliente_por_uc, tb_get_usinas_do_cliente, tb_get_pix_da_usina,
    _resolver_id_cliente_por_uc, tb_reservar_id_fatura,
)

# ─── CONFIG ────────────────────────────────────────────────────────────────────
PDF_CONSUMIDOR = {
    263: r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\LuizOliveira17-0001.489.484012-17\202604-EquatorialLuizOliveria17.pdf",
    264: r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\LuizOliveira58-0003.588.648.012-58\202604-EquatorialLuizOliveria58.pdf",
}

PDF_USINA = {
    (23, "03/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USjoseOliveira88-0003.954.137.012-88\202603-EquatorialUCJoseOliveira88.pdf",
    (23, "04/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USjoseOliveira88-0003.954.137.012-88\202604-EquatorialUCJoseOliveira88.pdf",
    (23, "05/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USjoseOliveira88-0003.954.137.012-88\202605-EquatorialUCJoseOliveira88.pdf",
    (22, "03/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USJoseOliveira93-0004.322.044.012-93\202603-EquatorialUCJoseOliveira93.pdf",
    (22, "04/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USJoseOliveira93-0004.322.044.012-93\202604-EquatorialUCJoseOliveira93.pdf",
}

NOME_USINA_FOLDER = {22: "USJoseOliveira93", 23: "USJoseOliveira88"}

# (id_cliente → nome_camel para nome do arquivo)
NOME_CAMEL = {
    263: "LuizCamiloOliveira17",
    264: "LuizCamiloOliveira58",
}


def _norm_mes(s: str) -> str:
    if not s or "/" not in s:
        return s
    m, a = s.split("/")
    return f"{int(m):02d}/{a}"


def gerar_cobranca_fixo(id_cliente: int) -> bool:
    db = _db()

    # 1) Cliente
    cli_rows = db.select("tb_clientes", filtros={"id_cliente": id_cliente})
    if not cli_rows:
        print(f"  X cliente {id_cliente} nao encontrado")
        return False
    cli_db = cli_rows[0]
    uc       = cli_db.get("cod_uc")
    nome     = cli_db.get("desc_nome", "?")
    desconto = float(cli_db.get("pct_desconto") or 0)

    # 2) Vinculos FIXO
    vincs = db.select("tb_cliente_usina",
        raw_params={
            "id_cliente":     f"eq.{id_cliente}",
            "dt_fim":         "is.null",
            "desc_saldo_obs": "eq.FIXO",
        })
    if not vincs:
        print(f"  X cliente {id_cliente} sem vinculos FIXO")
        return False

    # 3) PDF consumidor → tarifa fio B + ciclo aplicado + dados padrao
    pdf_cons = PDF_CONSUMIDOR.get(id_cliente)
    if not pdf_cons or not os.path.exists(pdf_cons):
        print(f"  X PDF consumidor nao encontrado: {pdf_cons}")
        return False
    equatorial = extrair_equatorial(pdf_cons, verbose=False)
    tarifa_fio_b   = float(equatorial.get("tarifa_nao_comp", 0) or 0)
    ciclo_aplicado = _norm_mes(equatorial.get("ciclo_geracao_mes", ""))

    # 4) Calcula gerac aplicada por usina (e tarifa ponderada das usinas)
    total_ger      = 0.0
    peso_tarifa    = 0.0   # SUM(ger_aplic × tarifa_usina)
    breakdown = []
    for v in vincs:
        id_usina = v.get("id_usina")
        pct      = float(v.get("pct_rateio") or 0) / 100.0
        pdf_us   = PDF_USINA.get((id_usina, ciclo_aplicado))
        if not pdf_us:
            print(f"  X PDF da usina id={id_usina} no ciclo {ciclo_aplicado} nao mapeado")
            return False
        usina = extrair_equatorial(pdf_us, verbose=False)
        ger_us_total = float(usina.get("geracao_ciclo_kwh", 0) or 0)
        tarifa_us    = float(usina.get("tarifa_convencional", 0) or 0)
        ger_aplicada = pct * ger_us_total
        total_ger    += ger_aplicada
        peso_tarifa  += ger_aplicada * tarifa_us
        breakdown.append({
            "id_usina": id_usina, "pct": pct*100, "ger_us": ger_us_total,
            "ger_aplic": ger_aplicada, "tarifa_us": tarifa_us
        })

    if total_ger <= 0:
        print(f"  X geracao total = 0 para cliente {id_cliente}")
        return False

    tarifa_sem_ponderada = peso_tarifa / total_ger
    fio_b_deducao = total_ger * tarifa_fio_b

    print(f"\n{'='*70}")
    print(f"  CLIENTE {id_cliente} - {nome}  UC {uc}")
    print(f"  Ciclo {ciclo_aplicado}  desconto {desconto*100:.0f}%  fio_b {tarifa_fio_b:.6f}")
    print(f"  Geracao aplicada total: {total_ger:.2f} kWh  |  tarifa media: R$ {tarifa_sem_ponderada:.6f}")
    for b in breakdown:
        print(f"    usina {b['id_usina']} {b['pct']:.0f}% × {b['ger_us']:.2f} = {b['ger_aplic']:.2f} kWh @ R$ {b['tarifa_us']:.6f}")
    print(f"  Deducao fio B: {total_ger:.2f} × {tarifa_fio_b:.6f} = R$ {fio_b_deducao:.2f}")
    print(f"{'='*70}\n")

    # 5) OVERRIDES no equatorial para que montar_dados produza valores corretos
    equatorial["consumo_kwh"]         = round(total_ger, 2)
    equatorial["compensado_kwh"]      = round(total_ger, 2)
    equatorial["consumo_compensado"]  = round(total_ger, 2)
    equatorial["nao_comp_kwh"]        = 0.0
    equatorial["consumo_nao_comp"]    = 0.0
    equatorial["consumo_nao_comp_kwh"] = 0.0
    equatorial["valor_parc_injet"]    = 0.0   # ja deduzido em fio_b_deducao

    # 6) Carrega cliente no formato legado
    clientes_legado = carregar_clientes()
    cliente = clientes_legado.get(uc)
    if not cliente:
        for k, v in clientes_legado.items():
            if k.lstrip("0") == str(uc).lstrip("0"):
                cliente = v
                uc = k
                break
    if not cliente:
        print(f"  X cliente UC {uc} nao encontrado em carregar_clientes()")
        return False

    # 7) Monta dados; passa tarifa_override = tarifa ponderada das usinas
    dados = montar_dados(equatorial, cliente, uc, pdf_cons, tarifa_override=tarifa_sem_ponderada)
    dados["fio_b_deducao"] = fio_b_deducao

    # 8) PIX (se usina tiver)
    try:
        _vinc_db = tb_get_usinas_do_cliente(id_cliente)
        if _vinc_db:
            _rec = tb_get_pix_da_usina(_vinc_db[0]["id_usina"])
            if _rec and _rec.get("desc_pix"):
                # gera QR com total estimado (será recalculado se for off, mas só pra visual)
                total_estimado = total_ger * (tarifa_sem_ponderada * (1-desconto) - tarifa_fio_b)
                qr = gerar_qrcode_pix(
                    total_estimado,
                    chave_pix=_rec.get("desc_pix"),
                    nome_recebedor=_rec.get("desc_nome_pix") or _rec.get("desc_nome"),
                    cidade=_rec.get("desc_cidade_pix"),
                )
                if qr:
                    dados["pix_qr_path"] = qr
    except Exception as e:
        print(f"  ⚠️ PIX: {e}")

    # 9) id_fatura
    try:
        _id_cli_b = _resolver_id_cliente_por_uc(uc)
        if _id_cli_b:
            dados["id_cliente"] = _id_cli_b
            import re as _re
            _mm = _re.match(r"^(\d{1,2})/(\d{4})$", str(equatorial.get("mes_referencia") or "").strip())
            if _mm:
                dados["id_fatura"] = tb_reservar_id_fatura(_id_cli_b, int(_mm.group(2)), int(_mm.group(1)))
    except Exception as e:
        print(f"  ⚠️ id_fatura: {e}")

    # 10) Gera PDF (gerar_cobranca chama calcular() internamente)
    gerar_cobranca(dados)

    arquivo_gerado = dados.get("output_path", "")
    if not arquivo_gerado or not os.path.exists(arquivo_gerado):
        print(f"  X arquivo nao encontrado: {arquivo_gerado}")
        return False

    # 11) Move para pasta do cliente
    pasta_cli = os.path.dirname(pdf_cons)
    nome_camel = NOME_CAMEL[id_cliente]
    yyyymm = equatorial.get("mes_referencia", "04/2026")
    m, a = yyyymm.split("/")
    yyyymm_str = f"{a}{int(m):02d}"
    nome_arq = f"{yyyymm_str}-SoLev{nome_camel}.pdf"
    destino = os.path.join(pasta_cli, nome_arq)
    shutil.move(arquivo_gerado, destino)
    print(f"  OK PDF salvo: {destino}")

    # 12) Upload Storage (sobrescreve o errado)
    try:
        path_storage = storage_upload_pdf(destino, nome_arq, bucket="faturas")
        print(f"  OK Storage: {path_storage}")
    except Exception as e:
        print(f"  ⚠️ Storage: {e}")

    return True


def main():
    print(f"\n{'#'*70}")
    print(f"  GERACAO COBRANCAS FIXO - LUIZ CAMILO DE OLIVEIRA")
    print(f"{'#'*70}")
    ok = falha = 0
    for id_cli in [263, 264]:
        try:
            if gerar_cobranca_fixo(id_cli):
                ok += 1
            else:
                falha += 1
        except Exception as e:
            import traceback
            traceback.print_exc()
            falha += 1
    print(f"\n{'='*70}")
    print(f"  Geradas: {ok}  Falhas: {falha}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()

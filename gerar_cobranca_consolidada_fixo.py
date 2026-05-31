"""
gerar_cobranca_consolidada_fixo.py
Gera UMA cobrança SOLEV consolidada para vários clientes FIXO do mesmo titular.
PDF único com:
  - Lista de UCs com geração comprada por UC
  - Total agregado
  - 1 QR code PIX + 1 código de barras pelo valor total

Uso (Luiz Camilo):
  python gerar_cobranca_consolidada_fixo.py
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
    tb_get_usinas_do_cliente, tb_get_pix_da_usina,
    _resolver_id_cliente_por_uc, tb_reservar_id_fatura,
)
from utils import _fmt_uc15

# Mesma config dos PDFs do script gerar_cobranças_luiz_camilo_fixo.py
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

# (nome consolidado camel + ordem de UCs para o Luiz)
CASO_LUIZ = {
    "id_clientes":   [263, 264],
    "nome_camel":    "LuizCamiloOliveira",
    "pasta_destino": r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\LuizOliveira-Consolidada",
}


def _norm_mes(s):
    if not s or "/" not in s: return s
    m, a = s.split("/")
    return f"{int(m):02d}/{a}"


def _fmt_kwh(v): return f"{v:,.2f} kWh".replace(",", "X").replace(".", ",").replace("X", ".")


def calcular_consolidada(id_clientes):
    """Calcula valores FIXO agregados de vários clientes do mesmo titular.
    Retorna dict com totais e detalhamento por UC.
    """
    db = _db()

    detalhamento_uc = []           # uma entrada por UC (cliente)
    total_ger = 0.0
    total_fio_b_deducao = 0.0
    peso_tarifa = 0.0
    consumer_ref = None            # PDF do consumidor usado para data, fio_b, etc.
    cli_ref = None                 # primeiro cliente (usado para nome/cpf)

    for id_cli in id_clientes:
        cli_rows = db.select("tb_clientes", filtros={"id_cliente": id_cli})
        if not cli_rows:
            raise RuntimeError(f"cliente {id_cli} nao encontrado")
        cli_db = cli_rows[0]
        if cli_ref is None:
            cli_ref = cli_db

        desconto = float(cli_db.get("pct_desconto") or 0)

        vincs = db.select("tb_cliente_usina",
            raw_params={
                "id_cliente":     f"eq.{id_cli}",
                "dt_fim":         "is.null",
                "desc_saldo_obs": "eq.FIXO",
            })
        if not vincs:
            raise RuntimeError(f"cliente {id_cli} sem vinculos FIXO")

        # PDF consumidor (usado para tarifa_fio_b + ciclo)
        pdf_cons = PDF_CONSUMIDOR.get(id_cli)
        if not pdf_cons or not os.path.exists(pdf_cons):
            raise RuntimeError(f"PDF consumidor cli {id_cli} nao encontrado")
        cons = extrair_equatorial(pdf_cons, verbose=False)
        if consumer_ref is None:
            consumer_ref = cons      # primeiro consumidor usado para datas/vencimento

        tarifa_fio_b = float(cons.get("tarifa_nao_comp", 0) or 0)
        ciclo        = _norm_mes(cons.get("ciclo_geracao_mes", ""))

        ger_cli = 0.0
        valor_com_cli = 0.0
        valor_sem_cli = 0.0
        breakdown_vinculos = []

        for v in vincs:
            id_usina = v.get("id_usina")
            pct      = float(v.get("pct_rateio") or 0) / 100.0
            pdf_us = PDF_USINA.get((id_usina, ciclo))
            if not pdf_us:
                raise RuntimeError(f"PDF da usina {id_usina} ciclo {ciclo} nao mapeado")
            usina = extrair_equatorial(pdf_us, verbose=False)
            ger_us_total = float(usina.get("geracao_ciclo_kwh", 0) or 0)
            tarifa_us    = float(usina.get("tarifa_convencional", 0) or 0)
            ger_aplic    = pct * ger_us_total
            valor_sem    = ger_aplic * tarifa_us
            valor_com    = ger_aplic * (tarifa_us * (1 - desconto) - tarifa_fio_b)

            ger_cli       += ger_aplic
            valor_sem_cli += valor_sem
            valor_com_cli += valor_com
            peso_tarifa   += ger_aplic * tarifa_us
            total_fio_b_deducao += ger_aplic * tarifa_fio_b

            breakdown_vinculos.append({
                "id_usina": id_usina, "pct": pct*100, "ger_us": ger_us_total,
                "ger_aplic": ger_aplic, "tarifa_us": tarifa_us,
            })

        total_ger += ger_cli
        uc_raw = cli_db.get("cod_uc")
        detalhamento_uc.append({
            "id_cliente": id_cli,
            "label":      _fmt_uc15(uc_raw),   # ex.: "0001.489.484.012-17"
            "uc":         uc_raw,
            "ger_aplic":  ger_cli,
            "valor_sem":  valor_sem_cli,
            "valor_com":  valor_com_cli,
            "vinculos":   breakdown_vinculos,
        })

    if total_ger <= 0:
        raise RuntimeError("geracao total = 0")

    tarifa_sem_pond = peso_tarifa / total_ger
    total_sem = sum(d["valor_sem"] for d in detalhamento_uc)
    total_com = sum(d["valor_com"] for d in detalhamento_uc)

    return {
        "cli_ref":       cli_ref,
        "consumer_ref":  consumer_ref,
        "detalhamento":  detalhamento_uc,
        "total_ger":     total_ger,
        "tarifa_sem":    tarifa_sem_pond,
        "fio_b_deducao": total_fio_b_deducao,
        "total_sem":     total_sem,
        "total_com":     total_com,
    }


def gerar_pdf_consolidada(caso):
    """Gera o PDF consolidado para o caso (Luiz Camilo)."""
    db = _db()
    calc = calcular_consolidada(caso["id_clientes"])

    cli_ref     = calc["cli_ref"]
    consumer    = calc["consumer_ref"]
    total_ger   = calc["total_ger"]
    tarifa_sem  = calc["tarifa_sem"]
    fio_b_ded   = calc["fio_b_deducao"]
    total_sem   = calc["total_sem"]
    total_com   = calc["total_com"]
    detalhe     = calc["detalhamento"]

    print(f"\n{'='*70}")
    print(f"  CONSOLIDADA - {cli_ref.get('desc_nome')}")
    print(f"  Mes referencia: {consumer.get('mes_referencia')}")
    print(f"  Tarifa media usina: R$ {tarifa_sem:.6f}")
    for d in detalhe:
        print(f"    {d['label']:<8} ger={d['ger_aplic']:>10,.2f} kWh   sem=R$ {d['valor_sem']:>10,.2f}   com=R$ {d['valor_com']:>10,.2f}")
    print(f"  TOTAL geracao: {total_ger:>10,.2f} kWh")
    print(f"  TOTAL SEM:     R$ {total_sem:>10,.2f}")
    print(f"  Fio B abs:     R$ {fio_b_ded:>10,.2f}")
    print(f"  TOTAL COM:     R$ {total_com:>10,.2f}")
    print(f"{'='*70}\n")

    # Equatorial base = primeiro consumer (datas/leitura/vencimento)
    equatorial = dict(consumer)  # shallow copy
    equatorial["consumo_kwh"]         = round(total_ger, 2)
    equatorial["compensado_kwh"]      = round(total_ger, 2)
    equatorial["consumo_compensado"]  = round(total_ger, 2)
    equatorial["nao_comp_kwh"]        = 0.0
    equatorial["consumo_nao_comp"]    = 0.0
    equatorial["consumo_nao_comp_kwh"] = 0.0
    equatorial["valor_parc_injet"]    = 0.0
    equatorial["total_fatura"]        = 0.0

    # Cliente legado (formato com 'nome', 'cpf', 'endereco', etc.)
    clientes_legado = carregar_clientes()
    uc_ref = cli_ref.get("cod_uc")
    cliente = clientes_legado.get(uc_ref)
    if not cliente:
        for k, v in clientes_legado.items():
            if k.lstrip("0") == str(uc_ref).lstrip("0"):
                cliente = v
                break
    if not cliente:
        raise RuntimeError(f"cliente UC {uc_ref} nao encontrado")

    # Monta dados base
    dados = montar_dados(equatorial, cliente, uc_ref, PDF_CONSUMIDOR[caso["id_clientes"][0]],
                         tarifa_override=tarifa_sem)
    dados["fio_b_deducao"] = fio_b_ded

    # Economia anterior = soma da economia das faturas dos MESES ANTERIORES
    # de TODOS os clientes consolidados (exclui o mês atual para evitar
    # dupla contagem do próprio mês quando regerar o PDF).
    mes_ref = consumer.get("mes_referencia", "")
    mes_at, ano_at = mes_ref.split("/")
    mes_at, ano_at = int(mes_at), int(ano_at)
    prior_eco = 0.0
    for id_cli in caso["id_clientes"]:
        faturas_anteriores = db.select("tb_faturas",
            raw_params={"id_cliente": f"eq.{id_cli}", "status": "neq.cancelado"})
        for f in faturas_anteriores:
            f_mes = int(f.get("mes_referencia") or 0)
            f_ano = int(f.get("ano_referencia") or 0)
            if (f_ano, f_mes) < (ano_at, mes_at):
                prior_eco += float(f.get("vlr_economia_mes") or 0)
    dados["economia_acumulada_anterior"] = round(prior_eco, 2)
    print(f"  Economia anterior (meses < {mes_at:02d}/{ano_at}): R$ {prior_eco:,.2f}")

    # Lista de UCs para o template (linhas agregadas)
    dados["consumo_por_uc"] = [
        {
            "label":     d["label"],
            "uc":        d["uc"],
            "ger_fmt":   _fmt_kwh(d["ger_aplic"]),
            "valor_sem_fmt": f"R$ {d['valor_sem']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "valor_com_fmt": f"R$ {d['valor_com']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        }
        for d in detalhe
    ]

    # Forca UC exibida = lista de UCs
    ucs_str = " + ".join(d["uc"] for d in detalhe if d.get("uc"))
    dados["unidade_consumidora"] = ucs_str

    # PIX (usa o recebedor da primeira usina do primeiro cliente)
    try:
        primeiro_cli = caso["id_clientes"][0]
        _vinc_db = tb_get_usinas_do_cliente(primeiro_cli)
        if _vinc_db:
            _rec = tb_get_pix_da_usina(_vinc_db[0]["id_usina"])
            if _rec and _rec.get("desc_pix"):
                qr = gerar_qrcode_pix(
                    total_com,
                    chave_pix=_rec.get("desc_pix"),
                    nome_recebedor=_rec.get("desc_nome_pix") or _rec.get("desc_nome"),
                    cidade=_rec.get("desc_cidade_pix"),
                )
                if qr:
                    dados["pix_qr_path"] = qr
    except Exception as e:
        print(f"  ⚠️ PIX: {e}")

    # id_cliente para nome do arquivo (usa o primeiro)
    dados["id_cliente"] = caso["id_clientes"][0]

    # Gera PDF
    gerar_cobranca(dados)

    arquivo_gerado = dados.get("output_path", "")
    if not arquivo_gerado or not os.path.exists(arquivo_gerado):
        raise RuntimeError(f"arquivo nao encontrado: {arquivo_gerado}")

    # Move para pasta consolidada
    pasta_destino = caso["pasta_destino"]
    os.makedirs(pasta_destino, exist_ok=True)
    mes_ref = consumer.get("mes_referencia", "04/2026")
    m, a = mes_ref.split("/")
    yyyymm = f"{a}{int(m):02d}"
    nome_arq = f"{yyyymm}-SoLev{caso['nome_camel']}-Consolidada.pdf"
    destino = os.path.join(pasta_destino, nome_arq)
    shutil.move(arquivo_gerado, destino)
    print(f"  OK PDF consolidado: {destino}")

    # Upload Storage
    try:
        path_s = storage_upload_pdf(destino, nome_arq, bucket="faturas")
        print(f"  OK Storage: {path_s}")
    except Exception as e:
        print(f"  ⚠️ Storage: {e}")

    return destino


def main():
    print(f"\n{'#'*70}")
    print(f"  COBRANCA CONSOLIDADA FIXO")
    print(f"{'#'*70}")
    pdf = gerar_pdf_consolidada(CASO_LUIZ)
    print(f"\nArquivo: {pdf}\n")


if __name__ == "__main__":
    main()

"""
Blueprint: Investidor
Rotas: /investidor, /investidor/gerar/<uid>
Helper: _gerar_pdf_investidor
"""
import os
import unicodedata
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash

from extrair_equatorial import extrair_equatorial
from contalev_cobranca_v2_padrao import _fmt_brl
from db import carregar_usinas, carregar_investidor_hist, salvar_investidor_hist

bp = Blueprint('investidor', __name__)

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_FOLDER = os.path.join(_PROJECT_DIR, "uploads")


@bp.route("/investidor")
def investidor_lista():
    from db import tb_carregar_usinas, tb_get_investidor
    usinas = carregar_usinas()
    # Inclui usinas do sistema novo que nao estao no legado
    for u in tb_carregar_usinas():
        uid_novo = str(u["id_usina"])
        if uid_novo not in usinas:
            inv = tb_get_investidor(u.get("id_investidor")) if u.get("id_investidor") else {}
            usinas[uid_novo] = {
                "nome":                    u.get("desc_nome", uid_novo),
                "investidor_nome":         inv.get("desc_nome", ""),
                "investidor_desagio_pct":  (inv.get("pct_desagio", 0) or 0),
                "investidor_valor_minimo": (inv.get("vlr_minimo", 0) or 0),
                "_from_tb": True,
            }
    hist = carregar_investidor_hist()
    return render_template("investidor.html", usinas=usinas, historico=hist[:10], fmt=_fmt_brl)


@bp.route("/investidor/gerar/<uid>", methods=["GET", "POST"])
def investidor_gerar(uid):
    from db import tb_get_usina, tb_get_investidor
    usinas = carregar_usinas()
    if uid not in usinas:
        try:
            usina_tb = tb_get_usina(int(uid))
            if usina_tb:
                inv_tb = tb_get_investidor(usina_tb.get("id_investidor")) if usina_tb.get("id_investidor") else {}
                usinas[uid] = {
                    "nome":                   usina_tb.get("desc_nome", uid),
                    "uc_geradora":            usina_tb.get("cod_uc_geradora", ""),
                    "titular_uc":             usina_tb.get("desc_titular_uc", ""),
                    "cpf_titular":            usina_tb.get("desc_cpf_titular", ""),
                    "investidor_nome":        inv_tb.get("desc_nome", ""),
                    "investidor_desagio_pct": (inv_tb.get("pct_desagio", 0) or 0),
                    "investidor_valor_minimo":(inv_tb.get("vlr_minimo", 0) or 0),
                    "investidor_dia_pgto":    (inv_tb.get("qtd_dia_pagamento", 0) or 0),
                }
        except (ValueError, TypeError):
            pass
    if uid not in usinas:
        flash("Usina nao encontrada!", "danger")
        return redirect(url_for(".investidor_lista"))
    usina = usinas[uid]

    if request.method == "POST":
        if "pdf" not in request.files or request.files["pdf"].filename == "":
            flash("Selecione o PDF da fatura da UC geradora!", "danger")
            return redirect(url_for(".investidor_gerar", uid=uid))

        pdf = request.files["pdf"]
        pdf_path = os.path.join(UPLOAD_FOLDER, pdf.filename)
        pdf.save(pdf_path)

        try:
            equatorial = extrair_equatorial(pdf_path, verbose=False)
        except Exception as e:
            flash(f"Erro ao extrair: {e}", "danger")
            return redirect(url_for(".investidor_gerar", uid=uid))

        kwh_gerado = float(request.form.get("kwh_gerado", "0").replace(",", ".") or "0")
        if kwh_gerado == 0:
            kwh_gerado = equatorial.get("consumo_kwh", 0) or 0

        tarifa_equatorial = float(request.form.get("tarifa_equatorial", "0").replace(",", ".") or "0")
        if tarifa_equatorial == 0:
            tarifa_equatorial = usina.get("investidor_desagio_pct", 0) or 0

        fio_b = float(request.form.get("fio_b", "0").replace(",", ".") or "0")
        valor_minimo = float(request.form.get("valor_minimo", "0").replace(",", ".") or "0")
        if valor_minimo == 0:
            valor_minimo = usina.get("investidor_valor_minimo", 0) or 0

        desagio = usina.get("investidor_desagio_pct", 0) or 0
        if desagio > 1:
            desagio = desagio / 100

        mes_ref = equatorial.get("mes_referencia", request.form.get("mes_referencia", ""))

        valor_bruto = kwh_gerado * tarifa_equatorial
        valor_desagio = valor_bruto * desagio
        valor_com_desagio = valor_bruto - valor_desagio
        valor_liquido = valor_com_desagio - fio_b - valor_minimo

        resultado = {
            "uid": uid,
            "usina_nome": usina.get("nome", uid),
            "investidor_nome": usina.get("investidor_nome", ""),
            "investidor_cpf_cnpj": usina.get("investidor_cpf_cnpj", ""),
            "investidor_banco": usina.get("investidor_banco", ""),
            "investidor_agencia": usina.get("investidor_agencia", ""),
            "investidor_conta": usina.get("investidor_conta", ""),
            "investidor_pix": usina.get("investidor_pix", ""),
            "mes_referencia": mes_ref,
            "kwh_gerado": kwh_gerado,
            "tarifa_equatorial": tarifa_equatorial,
            "desagio_pct": desagio * 100 if desagio < 1 else desagio,
            "valor_bruto": round(valor_bruto, 2),
            "valor_desagio": round(valor_desagio, 2),
            "valor_com_desagio": round(valor_com_desagio, 2),
            "fio_b": round(fio_b, 2),
            "valor_minimo": round(valor_minimo, 2),
            "valor_liquido": round(valor_liquido, 2),
            "dia_pagamento": usina.get("investidor_dia_pagamento", ""),
            "data_geracao": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "uc_geradora": usina.get("uc_geradora", ""),
        }

        pdf_out = _gerar_pdf_investidor(resultado)
        resultado["pdf"] = os.path.basename(pdf_out)

        hist = carregar_investidor_hist()
        hist.insert(0, resultado)
        salvar_investidor_hist(hist)

        flash(f"Demonstrativo gerado! {usina.get('investidor_nome', '')} - Liquido: {_fmt_brl(valor_liquido)}", "success")
        return render_template("investidor_resultado.html", r=resultado, fmt=_fmt_brl)

    return render_template("investidor_gerar.html", usina=usina, uid=uid, fmt=_fmt_brl)


def _gerar_pdf_investidor(r):
    """Gera PDF do demonstrativo de pagamento ao investidor."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as cv
    from reportlab.lib.colors import HexColor

    dark_blue = HexColor("#1a2a4a")
    orange = HexColor("#f5a623")
    white = HexColor("#ffffff")
    gray = HexColor("#f5f5f5")
    W, H = A4

    nome_arq = unicodedata.normalize('NFKD', r["investidor_nome"]).encode('ascii', 'ignore').decode('ascii')
    nome_arq = "".join(w.capitalize() for w in nome_arq.split())
    mes = r["mes_referencia"].replace("/", "")
    output = os.path.join(_PROJECT_DIR, f"{mes}-CONTALEV{nome_arq}.pdf")

    c = cv.Canvas(output, pagesize=A4)
    c.setTitle(f"Demonstrativo Investidor - {r['investidor_nome']}")

    # Header
    c.setFillColor(dark_blue)
    c.rect(0, H - 60, W, 60, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(25, H - 25, "CONTALEV")
    c.setFillColor(orange)
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(W - 25, H - 22, "DEMONSTRATIVO DE PAGAMENTO")
    c.setFillColor(HexColor("#cccccc"))
    c.setFont("Helvetica", 8)
    c.drawRightString(W - 25, H - 38, f"Ref.: {r['mes_referencia']}  |  Gerado em: {r['data_geracao']}")
    c.drawString(25, H - 38, "O sol gera. A CONTALEV reduz.")

    y = H - 85

    # Investidor
    c.setFillColor(dark_blue)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(25, y, "INVESTIDOR")
    y -= 4
    c.setStrokeColor(orange); c.setLineWidth(1.5)
    c.line(25, y, W - 25, y)
    y -= 16
    items_inv = [
        ("Nome:", r["investidor_nome"]),
        ("CPF/CNPJ:", r["investidor_cpf_cnpj"]),
        ("Usina:", f"{r['usina_nome']}  |  UC Geradora: {r['uc_geradora']}"),
    ]
    for label, val in items_inv:
        c.setFont("Helvetica-Bold", 9); c.setFillColor(dark_blue)
        c.drawString(30, y, label)
        c.setFont("Helvetica", 9); c.setFillColor(HexColor("#333333"))
        c.drawString(100, y, val)
        y -= 14

    y -= 10

    # Memoria de calculo
    c.setFillColor(dark_blue)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(25, y, "MEMORIA DE CALCULO")
    y -= 4
    c.setStrokeColor(orange); c.line(25, y, W - 25, y)
    y -= 20

    def _row(label, valor_str, destaque=False, subtotal=False):
        nonlocal y
        if subtotal:
            c.setFillColor(gray)
            c.rect(25, y - 4, W - 50, 18, fill=1, stroke=0)
        c.setFillColor(dark_blue if destaque else HexColor("#333333"))
        c.setFont("Helvetica-Bold" if destaque or subtotal else "Helvetica", 9)
        c.drawString(35, y, label)
        c.drawRightString(W - 35, y, valor_str)
        y -= 20

    _row("Energia Gerada", f"{r['kwh_gerado']:,.2f} kWh".replace(",", "X").replace(".", ",").replace("X", "."))
    _row("Tarifa Equatorial (R$/kWh)", f"R$ {r['tarifa_equatorial']:.6f}".replace(".", ","))
    _row("Valor Bruto da Energia", _fmt_brl(r["valor_bruto"]), subtotal=True)

    y -= 5
    c.setStrokeColor(HexColor("#e0e0e0")); c.setLineWidth(0.5)
    c.line(35, y + 10, W - 35, y + 10)

    _row(f"(-) Desagio ({r['desagio_pct']:.0f}%)", f"- {_fmt_brl(r['valor_desagio'])}")
    _row("Valor com Desagio", _fmt_brl(r["valor_com_desagio"]), subtotal=True)

    y -= 5
    c.line(35, y + 10, W - 35, y + 10)

    _row("(-) Fio B (Transmissao)", f"- {_fmt_brl(r['fio_b'])}")
    _row("(-) Valor Minimo da Fatura", f"- {_fmt_brl(r['valor_minimo'])}")

    y -= 8

    # TOTAL
    total_h = 40
    c.setFillColor(dark_blue)
    c.roundRect(25, y - total_h + 15, W - 50, total_h, 5, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica", 9)
    c.drawString(35, y - 5, "VALOR LIQUIDO A PAGAR AO INVESTIDOR")
    c.setFillColor(orange)
    c.setFont("Helvetica-Bold", 22)
    c.drawRightString(W - 35, y - 10, _fmt_brl(r["valor_liquido"]))

    y -= total_h + 20

    # Dados bancarios
    c.setFillColor(dark_blue)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(25, y, "DADOS PARA PAGAMENTO")
    y -= 4
    c.setStrokeColor(orange); c.setLineWidth(1.5); c.line(25, y, W - 25, y)
    y -= 18

    dados_bank = [
        ("Banco:", r.get("investidor_banco", "")),
        ("Agencia:", r.get("investidor_agencia", "")),
        ("Conta:", r.get("investidor_conta", "")),
        ("Chave PIX:", r.get("investidor_pix", "")),
        ("Dia de Pagamento:", r.get("dia_pagamento", "")),
    ]
    for label, val in dados_bank:
        if val:
            c.setFont("Helvetica-Bold", 9); c.setFillColor(dark_blue)
            c.drawString(30, y, label)
            c.setFont("Helvetica", 9); c.setFillColor(HexColor("#333333"))
            c.drawString(120, y, val)
            y -= 14

    # Rodape
    c.setFillColor(dark_blue)
    c.rect(0, 0, W, 30, fill=1, stroke=0)
    c.setFillColor(HexColor("#aaaaaa"))
    c.setFont("Helvetica", 6)
    c.drawString(25, 12, "CONTALEV SERVICOS E LOCACOES LTDA  |  CNPJ: 39.955.084/0001-52  |  contatocontalev@gmail.com")

    c.save()
    return output

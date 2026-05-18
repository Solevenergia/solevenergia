"""
=============================================================
  SOLEV — TEMPLATE PADRAO DE COBRANCA (v2 - COM FORMULAS)
=============================================================
  FORMULAS AUTOMATICAS:
    • num_dias       = data_leitura - anterior_leitura
    • venc_contalev  = venc_equatorial - 3 dias
    • mes_ano_fatura = mes_referencia → "Marco / 2026"
    • output_path    = Cobranca_{NomeCliente}.pdf
    • subtotal_sem   = consumo_kwh × tarifa_sem
    • total_sem      = subtotal_sem + iluminacao + multa + juros
    • tarifa_com     = tarifa_sem × (1 - desconto_pct)
    • subtotal_com   = (compensado × tarifa_com) + (nao_comp × tarifa_sem)
    • multa_com      = valor_cobranca_anterior × 2%    [se atraso]
    • juros_com      = valor_cobranca_anterior × 0,1627%/dia × dias_atraso
    • total_com      = subtotal_com + iluminacao + multa_com + juros_com
    • economia_mes   = total_sem - total_com
    • economia_acum  = economia_anterior + economia_mes
=============================================================
"""

DADOS = {
    "nome":               "SERGIO ALFREDO TALONE",
    "cpf":                "777.539.411-01",
    "endereco_linha1":    "AVENIDA LONDRES, Q.126,"
    "endereco_linha2"     "JARDIM EUROPA",
    "endereco_linha3":    "CEP 74.330-260, GOIANIA/GO",
    "unidade_consumidora":"16396078",
    "tipo_fornecimento":  "Trifasico",
    "mes_referencia":     "03/2026",
    "anterior_leitura":   "11/02/2026",
    "data_leitura":       "12/03/2026",
    "proxima_leitura":    "13/04/2026",
    "venc_equatorial":    "01/04/2026",
    "consumo_kwh":        679.00,
    "tarifa_sem":         1.135823,
    "desconto_pct":       0.20,
    "consumo_compensado": 451.45,
    "consumo_nao_comp":   227.55,
    "iluminacao_publica": 25.58,
    "multa":              0.00,
    "juros":              0.00,
    "correcao_ipca":      0.00,
    "economia_acumulada_anterior": 0.00,
    # ── Dados do mes anterior (para calculo de multa/juros COM) ──
    "valor_cobranca_anterior":  0.00,       # valor total COM SOLEV do mes anterior
    "venc_contalev_anterior":   "",          # vencimento da cobranca anterior, ex: "28/02/2026"
    "data_pagamento_anterior":  "",          # data que o cliente pagou, ex: "05/03/2026" (vazio = em dia)
    "codigo_barras":      "CODIGO DE BARRA EM DESENVOLVIMENTO",
    "linha_digitavel":    "XXXX.XXXX  XXXXX.XXXXX  XXXXX.XXXXX  X  XXXXXXXXXXXXXX",
    "pix_payload":        "00020126710014BR.GOV.BCB.PIX0129daniloevangelista@hotmail.com0216SOLEV-MAR20265204000053039865406694.255802BR5925Danilo Evangelista de Sou6009SAO PAULO62140510ISFfe2uLzk6304EC1F",
    "equatorial_pdf":     "/home/claude/032026-FATURAEQUATORIAL.pdf",
}


def _fmt_brl(valor):
    if valor == 0:
        return "R$ 0,00"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def _fmt_kwh(valor):
    return f"{valor:,.2f} kWh".replace(",", "X").replace(".", ",").replace("X", ".")

def _fmt_tarifa(valor):
    return f"R$ {valor:.6f}".replace(".", ",")

def _fmt_pct(valor):
    return f"{int(valor * 100)}%"

def _fmt_cpf(cpf):
    import re as _re
    if not cpf: return ""
    d = _re.sub(r'\D', '', str(cpf))
    if len(d) == 11: return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    if len(d) == 14: return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return cpf

def calcular(d):
    out = dict(d)

    # ── Formulas de datas ──────────────────────────────────
    from datetime import datetime, timedelta
    _dfmt = "%d/%m/%Y"

    # Datas podem estar vazias no modo manual
    _dl = d.get("data_leitura", "").strip()
    _al = d.get("anterior_leitura", "").strip()
    _ve = d.get("venc_equatorial", "").strip()

    if _dl and _al:
        dt_leitura  = datetime.strptime(_dl, _dfmt)
        dt_anterior = datetime.strptime(_al, _dfmt)
        num_dias    = (dt_leitura - dt_anterior).days
    else:
        num_dias = int(d.get("n_dias", 0) or 0)

    # Vencimento SOLEV: usa o informado diretamente, ou calcula a partir do Equatorial
    venc_contalev = d.get("vencimento_contalev", "").strip()
    if not venc_contalev and _ve:
        dt_venc_eq    = datetime.strptime(_ve, _dfmt)
        venc_contalev = (dt_venc_eq - timedelta(days=3)).strftime(_dfmt)

    out["num_dias"]       = str(num_dias)
    out["venc_contalev"]  = venc_contalev

    # ── mes_ano_fatura a partir de mes_referencia ──────────
    _meses = {1:"Janeiro",2:"Fevereiro",3:"Marco",4:"Abril",5:"Maio",6:"Junho",
              7:"Julho",8:"Agosto",9:"Setembro",10:"Outubro",11:"Novembro",12:"Dezembro"}
    mes_num, ano = d["mes_referencia"].split("/")
    mes_ano_fatura = f"{_meses[int(mes_num)]} / {ano}"
    out["mes_ano_fatura"] = mes_ano_fatura

    if _dl and _al:
        print(f"📅 Leitura anterior: {_al} → Leitura atual: {_dl} = {num_dias} dias")
    if _ve:
        print(f"📅 Venc. Equatorial: {_ve} → Venc. SOLEV: {venc_contalev}")
    print(f"📅 Mes referencia: {d['mes_referencia']} → {mes_ano_fatura}")

    consumo       = d["consumo_kwh"]
    tarifa_sem    = d["tarifa_sem"]
    desconto      = d["desconto_pct"]
    comp          = d["consumo_compensado"]
    nao_comp      = d["consumo_nao_comp"]
    ilum          = d["iluminacao_publica"]
    multa         = d["multa"]         # multa Equatorial (SEM)
    juros         = d["juros"]         # juros Equatorial (SEM)
    ipca          = float(d.get("correcao_ipca", 0) or 0)
    eco_anterior  = d["economia_acumulada_anterior"]

    # ── BANDEIRAS ──────────────────────────────────────────
    # Valor R$ que a Equatorial cobrou (extraido da linha ADC BANDEIRA do PDF).
    # Pela SCEE, a Equatorial cobra a bandeira apenas sobre o consumo NAO
    # compensado pela geracao solar (energia injetada nao paga bandeira).
    adc_band_amar_eq = float(d.get("adc_bandeira_amarela",  0) or 0)
    adc_band_verm_eq = float(d.get("adc_bandeira_vermelha", 0) or 0)

    # Tarifa R$/kWh da bandeira (vem do tb_tarifas via resolver_bandeiras)
    tarifa_band_amar = float(d.get("bandeira_tarifa_amar", 0) or 0)
    tarifa_band_verm = float(d.get("bandeira_tarifa_verm", 0) or 0)

    # CENARIO "SEM SOLEV": sem o sistema da SOLEV, o cliente nao teria
    # SCEE — a Equatorial cobraria bandeira sobre TODO o consumo (481 kWh,
    # nao so os 30 nao compensados). E o que se usa para calcular economia.
    band_amar_sem_contalev = consumo * tarifa_band_amar if tarifa_band_amar > 0 else 0.0
    band_verm_sem_contalev = consumo * tarifa_band_verm if tarifa_band_verm > 0 else 0.0

    # CENARIO "COM SOLEV": cliente paga ADC Equatorial (passa direto) +
    # eventual bandeira SOLEV sobre energia compensada (so para sem_bandeira).
    modo_band = (d.get("modo_bandeira") or "com_bandeira").strip().lower()
    cobra_band_contalev = modo_band != "com_bandeira"

    if cobra_band_contalev:
        # SOLEV cobra sobre energia compensada, com o mesmo desconto
        band_amar_contalev = comp * tarifa_band_amar * (1 - desconto) if tarifa_band_amar > 0 else 0.0
        band_verm_contalev = comp * tarifa_band_verm * (1 - desconto) if tarifa_band_verm > 0 else 0.0
    else:
        band_amar_contalev = band_verm_contalev = 0.0

    # ── FORMULAS SEM SOLEV ──────────────────────────────
    subtotal_sem  = consumo * tarifa_sem
    # Bandeira sem SOLEV = sobre TODA a conta (consumo total * tarifa)
    total_sem     = (subtotal_sem + ilum + multa + juros + ipca
                     + band_amar_sem_contalev + band_verm_sem_contalev)

    # ── FORMULAS COM SOLEV ──────────────────────────────
    tarifa_com    = tarifa_sem * (1 - desconto)
    subtotal_com  = (comp * tarifa_com) + (nao_comp * tarifa_sem)

    # ── Multa e juros SOLEV (atraso no pagamento do mes anterior) ─
    multa_com = 0.0
    juros_com = 0.0

    # Prioridade 1: override manual (usado na primeira cobranca de transicao)
    _multa_ov = d.get("multa_com_override", 0.0) or 0.0
    _juros_ov = d.get("juros_com_override", 0.0) or 0.0
    if _multa_ov > 0 or _juros_ov > 0:
        multa_com = float(_multa_ov)
        juros_com = float(_juros_ov)
        if multa_com > 0 or juros_com > 0:
            print(f"⚠️  Multa/Juros COM (manual): Multa = {_fmt_brl(multa_com)}, Juros = {_fmt_brl(juros_com)}")
    else:
        # Prioridade 2: calculo automatico a partir do mes anterior
        valor_ant = d.get("valor_cobranca_anterior", 0.0)
        venc_ant  = d.get("venc_contalev_anterior", "").strip()
        pgto_ant  = d.get("data_pagamento_anterior", "").strip()

        if valor_ant > 0 and venc_ant and pgto_ant:
            dt_venc_ant = datetime.strptime(venc_ant, _dfmt)
            dt_pgto_ant = datetime.strptime(pgto_ant, _dfmt)
            dias_atraso = (dt_pgto_ant - dt_venc_ant).days
            if dias_atraso > 0:
                multa_com = valor_ant * 0.02                            # 2% sobre valor anterior
                juros_com = valor_ant * 0.001627 * dias_atraso          # 0,1627% ao dia
                print(f"⚠️  ATRASO MES ANTERIOR: {dias_atraso} dias (pagou {pgto_ant}, vencia {venc_ant})")
                print(f"⚠️  Base: cobranca anterior = {_fmt_brl(valor_ant)}")
                print(f"⚠️  Multa SOLEV: 2% de {_fmt_brl(valor_ant)} = {_fmt_brl(multa_com)}")
                print(f"⚠️  Juros SOLEV: 0,1627%/dia × {dias_atraso} dias de {_fmt_brl(valor_ant)} = {_fmt_brl(juros_com)}")

    difci           = float(d.get("difci",           0) or 0)
    ecnisenta       = float(d.get("ecnisenta",       0) or 0)
    ajuste_valor    = float(d.get("ajuste_valor",    0) or 0)
    compensacao_dic = float(d.get("compensacao_dic", 0) or 0)  # negativo = credito da distribuidora

    # Compensacao DIC e Ajuste afetam ambos (SEM e COM)
    total_sem = total_sem + compensacao_dic + ajuste_valor
    # multa/juros/IPCA Equatorial entram no COM tambem (SOLEV repassa o custo ao cliente)
    # Bandeira no COM = ADC Equatorial (passa direto) + SOLEV com desconto (so se nao for com_bandeira)
    total_com = (subtotal_com + ilum + multa + juros + ipca
                 + multa_com + juros_com + difci + ecnisenta + ajuste_valor
                 + compensacao_dic
                 + adc_band_amar_eq + adc_band_verm_eq
                 + band_amar_contalev + band_verm_contalev)

    # ── ECONOMIA ───────────────────────────────────────────
    economia_mes  = total_sem - total_com
    economia_acum = max(0.0, eco_anterior + economia_mes)

    print("┌─────────────────────────────────────────────────┐")
    print("│           CALCULOS AUTOMATICOS                  │")
    print("├─────────────────────────────────────────────────┤")
    print(f"│ SEM SOLEV:                                      │")
    print(f"│   Consumo: {consumo:.2f} kWh × R$ {tarifa_sem:.6f}")
    print(f"│   Subtotal: {_fmt_brl(subtotal_sem)}")
    print(f"│   + Ilum: {_fmt_brl(ilum)} + Multa: {_fmt_brl(multa)} + Juros: {_fmt_brl(juros)}" + (f" + IPCA: {_fmt_brl(ipca)}" if ipca else ""))
    print(f"│   TOTAL SEM: {_fmt_brl(total_sem)}")
    print(f"│                                                 │")
    print(f"│ COM SOLEV:                                      │")
    print(f"│   Tarifa: R$ {tarifa_sem:.6f} × (1 - {desconto:.0%}) = R$ {tarifa_com:.6f}")
    print(f"│   Compensado: {comp:.2f} × R$ {tarifa_com:.6f} = {_fmt_brl(comp * tarifa_com)}")
    print(f"│   Nao Comp:   {nao_comp:.2f} × R$ {tarifa_sem:.6f} = {_fmt_brl(nao_comp * tarifa_sem)}")
    print(f"│   Subtotal: {_fmt_brl(subtotal_com)}")
    print(f"│   + Ilum: {_fmt_brl(ilum)} + Multa: {_fmt_brl(multa_com)} + Juros: {_fmt_brl(juros_com)}")
    if compensacao_dic != 0:
        print(f"│   + Compensacao DIC: {_fmt_brl(compensacao_dic)}")
    if ajuste_valor != 0:
        print(f"│   + Ajuste: {_fmt_brl(ajuste_valor)}")
    print(f"│   TOTAL COM: {_fmt_brl(total_com)}")
    print(f"│                                                 │")
    print(f"│ ECONOMIA:                                       │")
    print(f"│   Este mes: {_fmt_brl(total_sem)} - {_fmt_brl(total_com)} = {_fmt_brl(economia_mes)}")
    print(f"│   Anterior: {_fmt_brl(eco_anterior)}")
    print(f"│   Acumulada: {_fmt_brl(economia_acum)}")
    print("└─────────────────────────────────────────────────┘")

    out["cpf_fmt"]           = _fmt_cpf(d.get("cpf", ""))
    out["consumo_kwh_fmt"]   = _fmt_kwh(consumo)
    out["tarifa_sem_fmt"]    = _fmt_tarifa(tarifa_sem)
    out["subtotal_sem_fmt"]  = _fmt_brl(subtotal_sem)
    out["total_sem_fmt"]     = _fmt_brl(total_sem)
    out["consumo_comp_fmt"]  = _fmt_kwh(comp)
    out["consumo_ncomp_fmt"] = _fmt_kwh(nao_comp)
    out["tarifa_com_fmt"]    = _fmt_tarifa(tarifa_com)
    out["desconto_pct_fmt"]  = _fmt_pct(desconto)
    out["subtotal_com_fmt"]  = _fmt_brl(subtotal_com)
    out["total_com_fmt"]     = _fmt_brl(total_com)
    out["ilum_fmt"]          = _fmt_brl(ilum)
    out["multa_fmt"]         = _fmt_brl(multa)          # Equatorial (SEM)
    out["juros_fmt"]         = _fmt_brl(juros)          # Equatorial (SEM)
    out["ipca_fmt"]          = _fmt_brl(ipca) if ipca > 0 else ""
    out["_ipca"]             = ipca
    out["multa_com_fmt"]     = _fmt_brl(multa_com)
    out["juros_com_fmt"]     = _fmt_brl(juros_com)
    out["_multa_com"]        = multa_com   # numerico para verificar se ha atraso SOLEV
    out["_juros_com"]        = juros_com
    out["difci"]                  = difci
    out["ecnisenta"]              = ecnisenta
    out["difci_fmt"]              = _fmt_brl(difci)
    out["ecnisenta_fmt"]          = _fmt_brl(ecnisenta)
    out["ajuste_valor"]           = ajuste_valor
    out["ajuste_valor_fmt"]       = _fmt_brl(abs(ajuste_valor)) if ajuste_valor else ""
    out["compensacao_dic"]        = compensacao_dic
    out["compensacao_dic_fmt"]    = _fmt_brl(abs(compensacao_dic)) if compensacao_dic else ""
    out["economia_mes_fmt"]  = _fmt_brl(economia_mes)
    out["economia_acum_fmt"] = _fmt_brl(economia_acum)
    out["_subtotal_sem"] = subtotal_sem
    out["_total_sem"]    = total_sem
    out["_tarifa_com"]   = tarifa_com
    out["_subtotal_com"] = subtotal_com
    out["_total_com"]    = total_com
    out["_economia_mes"] = economia_mes
    out["_economia_acum"]= economia_acum
    # Bandeiras — para persistencia em tb_faturas e exibicao na fatura
    out["_band_amar_equatorial"] = adc_band_amar_eq
    out["_band_verm_equatorial"] = adc_band_verm_eq
    out["_band_amar_contalev"]   = band_amar_contalev
    out["_band_verm_contalev"]   = band_verm_contalev
    # Valor cobrado COM SOLEV (equatorial + solev por cor)
    out["_band_amar_total_com"] = adc_band_amar_eq + band_amar_contalev
    out["_band_verm_total_com"] = adc_band_verm_eq + band_verm_contalev
    # Valor que seria pago SEM SOLEV (sobre todo o consumo — para economia)
    out["_band_amar_total_sem"] = band_amar_sem_contalev
    out["_band_verm_total_sem"] = band_verm_sem_contalev
    out["band_amar_total_com_fmt"] = _fmt_brl(out["_band_amar_total_com"]) if out["_band_amar_total_com"] > 0 else ""
    out["band_verm_total_com_fmt"] = _fmt_brl(out["_band_verm_total_com"]) if out["_band_verm_total_com"] > 0 else ""
    out["band_amar_total_sem_fmt"] = _fmt_brl(out["_band_amar_total_sem"]) if out["_band_amar_total_sem"] > 0 else ""
    out["band_verm_total_sem_fmt"] = _fmt_brl(out["_band_verm_total_sem"]) if out["_band_verm_total_sem"] > 0 else ""
    return out


from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128
from reportlab.graphics.shapes import Drawing
import io
import base64
import os
import tempfile

_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── Compat: app.py chama _preparar_logos() na inicializacao ──────────────────
def _preparar_logos():
    pass


# ─── Geracao de barcode PNG em base64 ─────────────────────────────────────────
def _gerar_barcode_b64(codigo_barras: str) -> str:
    digits = "".join(c for c in (codigo_barras or "") if c.isdigit())
    if len(digits) < 10:
        return ""
    try:
        BAR_H = 40
        bc = code128.Code128(digits, barHeight=BAR_H, barWidth=0.9, humanReadable=False)
        d = Drawing(bc.width, BAR_H)
        d.add(bc)
        buf = io.BytesIO()
        renderPM.drawToFile(d, buf, fmt="PNG")
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()
    except Exception:
        return ""


# ─── Geracao de QR Code PIX em base64 ─────────────────────────────────────────
def _gerar_qr_b64(pix_qr_path: str, pix_payload: str) -> str:
    if pix_qr_path and os.path.exists(pix_qr_path):
        with open(pix_qr_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    if pix_payload and len(pix_payload) >= 20:
        try:
            import qrcode as _qr
            qr_obj = _qr.QRCode(box_size=8, border=1)
            qr_obj.add_data(pix_payload)
            qr_obj.make(fit=True)
            img = qr_obj.make_image(fill_color="#0E1B2E", back_color="#FFFFFF")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()
        except Exception:
            pass
    return ""


# ─── Playwright HTML → PDF ────────────────────────────────────────────────────
def _html_para_pdf(html_str: str) -> bytes:
    with tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", encoding="utf-8", delete=False
    ) as f:
        f.write(html_str)
        tmp_path = f.name
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto("file:///" + tmp_path.replace("\\", "/"))
            page.wait_for_load_state("networkidle", timeout=20000)
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "0mm", "right": "0mm",
                        "bottom": "0mm", "left": "0mm"},
                prefer_css_page_size=True,
            )
            browser.close()
        return pdf_bytes
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ─── Registro de fonte decorativa para o rodape ──────────────────────────────
def _registrar_fonte_rodape():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os
    _base = r"C:\Windows\Fonts"
    _map = {
        "Georgia":           os.path.join(_base, "georgia.ttf"),
        "Georgia-Italic":    os.path.join(_base, "georgiai.ttf"),
        "Georgia-Bold":      os.path.join(_base, "georgiab.ttf"),
    }
    try:
        registered = pdfmetrics.getRegisteredFontNames()
        for name, path in _map.items():
            if name not in registered and os.path.exists(path):
                pdfmetrics.registerFont(TTFont(name, path))
        return "Georgia" in pdfmetrics.getRegisteredFontNames()
    except Exception:
        return False


# ─── Overlay ReportLab para a pagina da Equatorial ───────────────────────────
def _criar_overlay_pdf(page_w: float = None, page_h: float = None) -> bytes:
    INK    = HexColor("#0E1B2E")
    ACCENT = HexColor("#E8732A")
    PAPER  = HexColor("#F2E8D4")
    WHITE  = HexColor("#FFFFFF")
    MUTED  = HexColor("#888888")

    _geo = _registrar_fonte_rodape()
    F_TITLE = "Helvetica-Bold"
    F_SUB   = "Georgia"        if _geo else "Times-Roman"
    F_VERSE = "Georgia-Italic" if _geo else "Times-Italic"

    buf = io.BytesIO()
    _ps = (page_w, page_h) if (page_w and page_h) else A4
    c = canvas.Canvas(buf, pagesize=_ps)
    W, H = _ps

    # ── Faixa superior: wordmark + label direita ──────────────────────────────
    STRIP_H = 10 * mm
    c.setFillColor(INK)
    c.rect(0, H - STRIP_H, W, STRIP_H, fill=1, stroke=0)

    MID_Y = H - STRIP_H / 2
    SX    = 12 * mm
    FS_WM = 12

    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", FS_WM)
    s_w = c.stringWidth("s", "Helvetica-Bold", FS_WM)
    c.drawString(SX, MID_Y - FS_WM * 0.35, "s")

    o_cx = SX + s_w + FS_WM * 0.25
    o_cy = MID_Y - FS_WM * 0.05
    OR   = FS_WM * 0.42
    IR   = OR * 0.58
    c.setFillColor(WHITE);  c.circle(o_cx, o_cy, OR, fill=1, stroke=0)
    c.setFillColor(ACCENT); c.circle(o_cx, o_cy, IR, fill=1, stroke=0)

    lx = o_cx + OR + FS_WM * 0.08
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", FS_WM)
    l_w = c.stringWidth("l", "Helvetica-Bold", FS_WM)
    c.drawString(lx, MID_Y - FS_WM * 0.35, "l")
    c.setFont("Helvetica", FS_WM)
    c.drawString(lx + l_w, MID_Y - FS_WM * 0.35, "ev")

    c.setFillColor(ACCENT)
    c.setFont("Helvetica", 7)
    right_txt = "FATURA  EQUATORIAL  GO    ·    ANEXO"
    rw = c.stringWidth(right_txt, "Helvetica", 7)
    c.drawString(W - 12 * mm - rw, MID_Y - 2.5, right_txt)

    # ── Area inferior ─────────────────────────────────────────────────────────
    COVER_H = 115 * mm
    c.setFillColor(PAPER)
    c.rect(0, 0, W, COVER_H, fill=1, stroke=0)
    c.setFillColor(ACCENT)
    c.rect(0, COVER_H, W, 1.5 * mm, fill=1, stroke=0)

    # ── Simbolo SoLev + bloco "Obrigado" (grupo centralizado) ────────────────
    SYM_R  = 15 * mm
    GAP    = 9 * mm
    SYM_CY = COVER_H - 30 * mm

    OBR_TXT = "Obrigado pela sua confiança!"
    OBR_FS  = 22
    SUB1    = "É um prazer cuidar da sua energia e da sua economia."
    SUB2    = "Que o sol continue iluminando os seus dias."
    SUB_FS  = 11.5

    c.setFont(F_TITLE, OBR_FS)
    obr_w  = c.stringWidth(OBR_TXT, F_TITLE, OBR_FS)
    c.setFont(F_SUB, SUB_FS)
    sub1_w = c.stringWidth(SUB1, F_SUB, SUB_FS)
    sub2_w = c.stringWidth(SUB2, F_SUB, SUB_FS)
    TEXT_W  = max(obr_w, sub1_w, sub2_w)

    GROUP_W   = 2 * SYM_R + GAP + TEXT_W
    GROUP_X   = (W - GROUP_W) / 2
    SYM_CX    = GROUP_X + SYM_R
    TEXT_LEFT = GROUP_X + 2 * SYM_R + GAP

    c.setFillColor(INK);    c.circle(SYM_CX, SYM_CY, SYM_R, fill=1, stroke=0)
    c.setFillColor(ACCENT); c.circle(SYM_CX, SYM_CY, SYM_R * 0.58, fill=1, stroke=0)

    c.setFillColor(INK)
    c.setFont(F_TITLE, OBR_FS)
    c.drawString(TEXT_LEFT, SYM_CY + 6 * mm, OBR_TXT)
    c.setFont(F_SUB, SUB_FS)
    c.drawString(TEXT_LEFT, SYM_CY - 2 * mm, SUB1)
    c.drawString(TEXT_LEFT, SYM_CY - 9 * mm, SUB2)

    # ── Separador e versiculo ─────────────────────────────────────────────────
    CX    = W / 2
    SEP_Y = COVER_H - 62 * mm
    c.setStrokeColor(ACCENT)
    c.setLineWidth(0.4 * mm)
    c.line(20 * mm, SEP_Y, W - 20 * mm, SEP_Y)

    V1 = "\"O amor é paciente, o amor é bondoso."
    V2 = "Não inveja, não se vangloria, não se orgulha."
    V3 = "Não maltrata, não procura seus interesses,"
    V4 = "não se ira facilmente, não guarda rancor.\""
    REF = "1 Coríntios 13:4-7"
    FS_V = 10.5
    LH   = 6.5 * mm

    c.setFillColor(ACCENT)
    c.setFont(F_VERSE, FS_V)
    c.drawCentredString(CX, SEP_Y - 9 * mm,        V1)
    c.drawCentredString(CX, SEP_Y - 9 * mm - LH,   V2)
    c.drawCentredString(CX, SEP_Y - 9 * mm - 2*LH, V3)
    c.drawCentredString(CX, SEP_Y - 9 * mm - 3*LH, V4)

    c.setFillColor(MUTED)
    c.setFont(F_VERSE, 9)
    c.drawCentredString(CX, SEP_Y - 9 * mm - 4*LH - 3*mm, REF)

    c.save()
    buf.seek(0)
    return buf.getvalue()


# ─── Listas de linhas extras (bandeiras, IPCA, etc.) ─────────────────────────
def _extras_sem(d: dict) -> list:
    extras = []
    if d.get("_ipca", 0) > 0:
        extras.append({"label": "Correcao IPCA", "valor": d["ipca_fmt"]})
    if d.get("_band_amar_total_sem", 0) > 0:
        extras.append({"label": "Bandeira Amarela",
                       "valor": d.get("band_amar_total_sem_fmt", "")})
    if d.get("_band_verm_total_sem", 0) > 0:
        extras.append({"label": "Bandeira Vermelha",
                       "valor": d.get("band_verm_total_sem_fmt", "")})
    av = d.get("ajuste_valor", 0)
    if av > 0:
        extras.append({"label": "Acrescimo", "valor": d["ajuste_valor_fmt"]})
    elif av < 0:
        extras.append({"label": "Desconto", "valor": "- " + d["ajuste_valor_fmt"]})
    if d.get("compensacao_dic", 0) != 0:
        extras.append({"label": "Comp. DIC Mensal",
                       "valor": "- " + d.get("compensacao_dic_fmt", "")})
    return extras


def _extras_com(d: dict) -> list:
    extras = []
    if d.get("_ipca", 0) > 0:
        extras.append({"label": "Correcao IPCA", "valor": d["ipca_fmt"]})
    if d.get("_band_amar_total_com", 0) > 0:
        extras.append({"label": "Bandeira Amarela",
                       "valor": d.get("band_amar_total_com_fmt", "")})
    if d.get("_band_verm_total_com", 0) > 0:
        extras.append({"label": "Bandeira Vermelha",
                       "valor": d.get("band_verm_total_com_fmt", "")})
    if d.get("_multa_com", 0) > 0:
        extras.append({"label": "Multa SOLEV", "valor": d["multa_com_fmt"]})
    if d.get("_juros_com", 0) > 0:
        extras.append({"label": "Juros SOLEV", "valor": d["juros_com_fmt"]})
    if d.get("difci", 0) > 0:
        extras.append({"label": "DIFCI", "valor": d["difci_fmt"]})
    if d.get("ecnisenta", 0) > 0:
        extras.append({"label": "ECNISENTA", "valor": d["ecnisenta_fmt"]})
    av = d.get("ajuste_valor", 0)
    if av > 0:
        extras.append({"label": "Acrescimo", "valor": d["ajuste_valor_fmt"]})
    elif av < 0:
        extras.append({"label": "Desconto", "valor": "- " + d["ajuste_valor_fmt"]})
    if d.get("compensacao_dic", 0) != 0:
        extras.append({"label": "Comp. DIC Mensal",
                       "valor": "- " + d.get("compensacao_dic_fmt", "")})
    return extras


# ─── Monta contexto para o template Jinja2 ────────────────────────────────────
def _dict_para_contexto(d: dict, qr_b64: str, bar_b64: str) -> dict:
    _meses = ["", "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
              "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    try:
        mes_num = int(str(d.get("mes_referencia", "01/2026")).split("/")[0])
        mes_nome = _meses[mes_num] if 1 <= mes_num <= 12 else ""
    except Exception:
        mes_nome = ""

    end = d.get("endereco", "")
    if not end:
        parts = [d.get("endereco_linha1", ""), d.get("endereco_linha2", ""),
                 d.get("endereco_linha3", "")]
        end = "\n".join(p for p in parts if p)

    pct_int = int(round(float(d.get("desconto_pct", 0)) * 100))
    eco_mes = d.get("economia_mes_fmt", "R$ 0,00").replace("R$ ", "")

    return {
        "mes_ref":    d.get("mes_ano_fatura", ""),
        "mes_nome":   mes_nome,
        "vencimento": d.get("venc_contalev", ""),
        "id_fatura":  d.get("id_fatura", ""),
        "cliente": {
            "nome":     d.get("nome", ""),
            "cpf":      d.get("cpf_fmt", "") or d.get("cpf", ""),
            "endereco": end,
            "cep":      d.get("cep", ""),
        },
        "uc":          d.get("unidade_consumidora", ""),
        "fornecimento": d.get("tipo_fornecimento", ""),
        "leitura": {
            "mes_ref":  d.get("mes_referencia", ""),
            "anterior": d.get("anterior_leitura", ""),
            "atual":    d.get("data_leitura", ""),
            "proxima":  d.get("proxima_leitura", ""),
            "dias":     d.get("num_dias", ""),
        },
        "sem_solev": {
            "consumo": d.get("consumo_kwh_fmt", ""),
            "tarifa":  d.get("tarifa_sem_fmt", ""),
            "energia": d.get("subtotal_sem_fmt", ""),
            "ilum":    d.get("ilum_fmt", ""),
            "multa":   d.get("multa_fmt", ""),
            "juros":   d.get("juros_fmt", ""),
            "total":   d.get("total_sem_fmt", ""),
        },
        "com_solev": {
            "consumo_comp":     d.get("consumo_comp_fmt", ""),
            "consumo_nao_comp": d.get("consumo_ncomp_fmt", ""),
            "tarifa_desc":      d.get("tarifa_com_fmt", ""),
            "desconto_pct":     pct_int,
            "energia":          d.get("subtotal_com_fmt", ""),
            "ilum":             d.get("ilum_fmt", ""),
            "multa":            d.get("multa_fmt", ""),
            "juros":            d.get("juros_fmt", ""),
            "total":            d.get("total_com_fmt", ""),
        },
        "economia_mes":       eco_mes,
        "economia_acumulada": d.get("economia_acum_fmt", ""),
        "boleto": {
            "linha_digitavel": d.get("linha_digitavel", ""),
            "valor":           d.get("total_com_fmt", ""),
            "barcode_b64":     bar_b64,
        },
        "pix": {
            "qr_b64":        qr_b64,
            "chave_display": d.get("pix_chave_display", ""),
            "banco":         "Banco Inter",
        },
        "extras_sem": _extras_sem(d),
        "extras_com":  _extras_com(d),
    }




def _pagina1(d: dict, path: str):
    from jinja2 import Environment, FileSystemLoader
    qr_b64  = _gerar_qr_b64(d.get("pix_qr_path", ""), d.get("pix_payload", ""))
    bar_b64 = _gerar_barcode_b64(d.get("codigo_barras", ""))
    fatura  = _dict_para_contexto(d, qr_b64, bar_b64)
    env = Environment(
        loader=FileSystemLoader(os.path.join(_DIR, "templates")),
        autoescape=False,
    )
    html = env.get_template("fatura/cobranca.html").render(fatura=fatura)
    pdf  = _html_para_pdf(html)
    with open(path, "wb") as f:
        f.write(pdf)


def _pagina2(d: dict, path: str):
    eq = d.get("equatorial_pdf", "")
    if not eq or not os.path.exists(eq):
        return
    from pypdf import PdfReader, PdfWriter
    eq_reader  = PdfReader(eq)
    eq_page    = eq_reader.pages[0]
    pw = float(eq_page.mediabox.width)
    ph = float(eq_page.mediabox.height)
    overlay_bytes = _criar_overlay_pdf(pw, ph)
    overlay_page  = PdfReader(io.BytesIO(overlay_bytes)).pages[0]
    eq_page.merge_page(overlay_page)
    writer = PdfWriter()
    writer.add_page(eq_page)
    with open(path, "wb") as f:
        writer.write(f)


def _nome_para_arquivo(nome):
    """Converte nome do cliente para nome de arquivo: usa apenas primeiro+ultimo
    em CamelCase, sem acentos. Ex: 'SERGIO ALFREDO TALONE' → 'SergioTalone'.
    Ver skill file-naming/ para o padrao completo."""
    import unicodedata
    nome_limpo = unicodedata.normalize('NFKD', nome).encode('ascii', 'ignore').decode('ascii')
    partes = nome_limpo.strip().split()
    if len(partes) > 2:
        partes = [partes[0], partes[-1]]
    return "".join(word.capitalize() for word in partes)


def _mes_para_yyyymm(mes_ref):
    """Converte 'MM/AAAA' para 'AAAAMM'. Tolera 'M/AAAA' (sem zero a esquerda).
    Ex: '04/2026' → '202604', '4/2026' → '202604'."""
    s = (mes_ref or "").strip().replace("/", "")
    if len(s) == 5:  # MAAAA → ano comeca no indice 1
        return s[1:] + s[0].zfill(2)
    if len(s) == 6:  # MMAAAA → MMAAAA → AAAAMM
        return s[2:] + s[:2]
    return s


def gerar_cobranca(d):
    _preparar_logos()
    # Nome do arquivo: padrao novo (YYYYMM)_SoLev_PrimeiroUltimo_idCliente.pdf
    # Ver skill file-naming/SKILL.md para detalhes
    nome_arq = _nome_para_arquivo(d["nome"])
    yyyymm = _mes_para_yyyymm(d.get("mes_referencia", "01/2026"))
    id_cliente = d.get("id_cliente")
    if id_cliente:
        # Padrao novo (preferido)
        d["output_path"] = os.path.join(
            _DIR, f"{yyyymm}_SoLev_{nome_arq}_{int(id_cliente)}.pdf"
        )
    else:
        # Fallback: padrao legado com sufixo de UC (compatibilidade)
        uc_suffix = ""
        if "unidade_consumidora" in d and d["unidade_consumidora"]:
            uc = str(d["unidade_consumidora"]).strip().replace(".", "").replace("-", "")
            uc_suffix = f"-{uc[-4:]}" if len(uc) >= 4 else f"-{uc}"
        d["output_path"] = os.path.join(
            _DIR, f"{yyyymm}-SoLev{nome_arq}{uc_suffix}.pdf"
        )
    dados = calcular(d)
    base = dados["output_path"].replace(".pdf", "")
    p1 = base + "_p1_tmp.pdf"; p2 = base + "_p2_tmp.pdf"; pm = base + "_merge_tmp.pdf"
    os.makedirs(os.path.dirname(dados["output_path"]) or ".", exist_ok=True)
    print("\nGerando pagina 1 (cobranca SOLEV)...")
    _pagina1(dados, p1)
    eq = dados.get("equatorial_pdf", "")
    if eq and os.path.exists(eq):
        print("Gerando pagina 2 (fatura Equatorial modificada)...")
        _pagina2(dados, p2)
        # Mescla paginas usando pypdf (Python puro, sem qpdf externo)
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()
        for src_pdf in [p1, p2]:
            reader = PdfReader(src_pdf)
            writer.add_page(reader.pages[0])
        with open(dados["output_path"], "wb") as f_out:
            writer.write(f_out)
        os.remove(p1); os.remove(p2)
    else:
        print("(Fatura Equatorial nao informada — apenas pag. 1)")
        # Apenas renomeia/copia a pagina 1
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(p1)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])
        with open(dados["output_path"], "wb") as f_out:
            writer.write(f_out)
        os.remove(p1)
    print(f"\n✅ Cobranca gerada: {dados['output_path']}")


if __name__ == "__main__":
    gerar_cobranca(DADOS)

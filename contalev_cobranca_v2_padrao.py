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
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.graphics.barcode import code128
from reportlab.graphics.barcode import qr
from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Drawing
import reportlab.graphics.shapes as shapes
from PIL import Image
import numpy as np
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_JPEG = os.path.join(_DIR, "LOGO_SOLEV.jpeg")
LOGO_COLOR = os.path.join(_DIR, "logo_transparent.png")
LOGO_WHITE = os.path.join(_DIR, "logo_white_v_colored.png")


def _preparar_logos():
    if os.path.exists(LOGO_COLOR) and os.path.exists(LOGO_WHITE):
        return
    if not os.path.exists(LOGO_JPEG):
        raise FileNotFoundError(f"Logo nao encontrada: {LOGO_JPEG}")
    img = Image.open(LOGO_JPEG).convert('RGBA')
    arr = np.array(img)
    r, g, b, a = arr[:,:,0], arr[:,:,1], arr[:,:,2], arr[:,:,3]
    white_mask = (r > 235) & (g > 235) & (b > 235)
    arr[white_mask, 3] = 0
    near_white = (r > 210) & (g > 210) & (b > 210) & ~white_mask
    avg = (r[near_white].astype(int) + g[near_white].astype(int) + b[near_white].astype(int)) // 3
    arr[near_white, 3] = (255 - (avg - 210) * 255 // 45).clip(0, 255).astype(np.uint8)
    transparent = Image.fromarray(arr)
    bbox = transparent.getbbox()
    if bbox: transparent = transparent.crop(bbox)
    transparent.save(LOGO_COLOR)
    arr2 = np.array(transparent.copy(), dtype=np.float64)
    r2, g2, b2, a2 = arr2[:,:,0], arr2[:,:,1], arr2[:,:,2], arr2[:,:,3]
    brightness = (r2 + g2 + b2) / 3
    is_visible = a2 > 30
    is_dark_blue = is_visible & (brightness < 100) & (b2 > r2 * 1.2)
    is_warm = (r2 > b2 * 1.3) & is_visible
    mask = is_dark_blue & ~is_warm
    arr2[mask, 0] = 255; arr2[mask, 1] = 255; arr2[mask, 2] = 255
    transition = is_visible & (brightness >= 50) & (brightness < 150) & (b2 > r2) & ~is_warm
    for ch in range(3):
        arr2[transition, ch] = np.clip(arr2[transition, ch] * 0.3 + 255 * 0.7, 0, 255)
    Image.fromarray(arr2.astype(np.uint8)).save(LOGO_WHITE)
    print("✅ Logos processadas.")


def _get_logo_ratio():
    img = Image.open(LOGO_COLOR)
    return img.height / img.width


def _rodape(c, W, FT_H, dark_blue, orange, white):
    ratio = _get_logo_ratio()
    c.setFillColor(dark_blue); c.rect(0, 0, W, FT_H, fill=1, stroke=0)
    c.setFillColor(orange); c.rect(0, FT_H, W, 1.2*mm, fill=1, stroke=0)
    FLW = 30*mm; FLH = FLW * ratio
    c.drawImage(LOGO_WHITE, 10*mm, (FT_H - FLH)/2, width=FLW, height=FLH, mask='auto')
    c.setFillColor(white); c.setFont("Helvetica", 6)
    c.drawRightString(W - 10*mm, 11*mm,
                      "Apos o vencimento: multa de 2% + juros de 0,1627% ao dia (valor SOLEV).")


def _pagina1(d, path):
    ratio = _get_logo_ratio()
    c = canvas.Canvas(path, pagesize=A4)
    W, H = A4
    dark_blue = HexColor("#1a2a4a"); orange = HexColor("#f5a623")
    light_gray = HexColor("#f4f4f4"); mid_gray = HexColor("#cccccc")
    green = HexColor("#2e7d32"); white = colors.white; black = colors.black
    slate = HexColor("#455a64"); amber_bg = HexColor("#fff8e1")
    amber_text = HexColor("#7a5c00"); green_bg = HexColor("#e8f5e9")
    MX = 10*mm; FS = 8.5; FSB = 9.0; ROW = 6*mm; GAP = 6*mm
    CW = (W - 2*MX)/2 - 2*mm

    # Header
    HH = 22*mm
    c.setFillColor(white); c.rect(0, H - HH, W, HH, fill=1, stroke=0)
    DT = W * 0.50; DB = W * 0.58
    p = c.beginPath()
    p.moveTo(DT, H); p.lineTo(W, H); p.lineTo(W, H - HH); p.lineTo(DB, H - HH); p.close()
    c.setFillColor(dark_blue); c.drawPath(p, fill=1, stroke=0)
    S = 1.8*mm; p2 = c.beginPath()
    p2.moveTo(DT - S*.5, H); p2.lineTo(DT + S*.5, H)
    p2.lineTo(DB + S*.5, H - HH); p2.lineTo(DB - S*.5, H - HH); p2.close()
    c.setFillColor(orange); c.drawPath(p2, fill=1, stroke=0)
    c.rect(0, H - HH - 1.5*mm, W, 1.5*mm, fill=1, stroke=0)
    LW = 40*mm; LH = LW * ratio
    c.drawImage(LOGO_COLOR, MX, H - HH + (HH - LH)/2, width=LW, height=LH, mask='auto')
    rcx = DT + (W - DT)/2 + 4*mm
    c.setFillColor(HexColor("#aabbcc")); c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(rcx, H - 6*mm, "FATURA DE ENERGIA")
    c.setStrokeColor(orange); c.setLineWidth(0.5)
    lw = (W - DT) * 0.6; c.line(rcx - lw/2, H - 8.5*mm, rcx + lw/2, H - 8.5*mm)
    c.setFillColor(white); c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(rcx, H - 15.5*mm, d["mes_ano_fatura"])

    # ID da fatura — texto discreto no canto superior direito do header escuro
    _id_fatura = d.get("id_fatura")
    if _id_fatura:
        c.setFillColor(HexColor("#aabbcc")); c.setFont("Helvetica", 6.5)
        c.drawRightString(W - MX, H - 3.5*mm, f"#{int(_id_fatura)}")

    y = H - HH - 1.5*mm - GAP
    FT_H = 16*mm; PBH = 30*mm; PG = 3*mm
    PB = FT_H + 1.2*mm + PG; PTH = 8*mm
    CONT = y - (PB + PBH + PTH + GAP)
    STH = 5*mm; DBH = 36*mm; CHH = 9*mm; TBH = 14*mm; EBH = 16.5*mm
    CPH = STH + 6*mm + 7*mm + 7*mm; AVH = 7*mm
    # Listas montadas antes dos calculos de altura para dimensionamento preciso
    sf = [("Consumo",                   d["consumo_kwh_fmt"],  False),
          ("Tarifa (R$/kWh)",           d["tarifa_sem_fmt"],   False),
          ("Subtotal Energia",          d["subtotal_sem_fmt"], True)]
    cf = [("Consumo Compensado",        d["consumo_comp_fmt"],  False),
          ("Consumo Nao Compensado",    d["consumo_ncomp_fmt"], False),
          ("Tarifa c/ Desc. (R$/kWh)", d["tarifa_com_fmt"],    False),
          ("Desconto Aplicado",         d["desconto_pct_fmt"],  False),
          ("Subtotal Energia",          d["subtotal_com_fmt"],  True)]
    fi_sem = [("Iluminacao Publica", d["ilum_fmt"],  False),
              ("Multa",              d["multa_fmt"], False),
              ("Juros",              d["juros_fmt"], False)]
    if d.get("_ipca", 0) > 0:
        fi_sem.append(("Correcao IPCA", d["ipca_fmt"], False))
    # COM SOLEV: mostra multa/juros/IPCA da Equatorial (repassados ao cliente)
    # Se tambem houve atraso no pagamento SOLEV, adiciona como linha extra
    fi_com = [("Iluminacao Publica", d["ilum_fmt"],  False),
              ("Multa",              d["multa_fmt"],  False),
              ("Juros",              d["juros_fmt"],  False)]
    if d.get("_ipca", 0) > 0:
        fi_com.append(("Correcao IPCA", d["ipca_fmt"], False))
    # Bandeira tarifaria — valores diferentes entre SEM e COM SOLEV:
    # SEM SOLEV: bandeira sobre TODO o consumo (cliente nao teria SCEE)
    # COM SOLEV: ADC Equatorial passado + SOLEV opcional (so sem_bandeira)
    if d.get("_band_amar_total_sem", 0) > 0 or d.get("_band_amar_total_com", 0) > 0:
        fi_sem.append(("Bandeira Amarela", d.get("band_amar_total_sem_fmt", ""), False))
        fi_com.append(("Bandeira Amarela", d.get("band_amar_total_com_fmt", ""), False))
    if d.get("_band_verm_total_sem", 0) > 0 or d.get("_band_verm_total_com", 0) > 0:
        fi_sem.append(("Bandeira Vermelha", d.get("band_verm_total_sem_fmt", ""), False))
        fi_com.append(("Bandeira Vermelha", d.get("band_verm_total_com_fmt", ""), False))
    if d.get("_multa_com", 0) > 0:
        fi_com.append(("Multa SOLEV", d["multa_com_fmt"], False))
    if d.get("_juros_com", 0) > 0:
        fi_com.append(("Juros SOLEV", d["juros_com_fmt"], False))
    if d.get("difci", 0) > 0:
        fi_com.append(("DIFCI",     d["difci_fmt"],     False))
    if d.get("ecnisenta", 0) > 0:
        fi_com.append(("ECNISENTA", d["ecnisenta_fmt"], False))
    if d.get("ajuste_valor", 0) > 0:
        fi_sem.append(("Acrescimo", d["ajuste_valor_fmt"], False))
        fi_com.append(("Acrescimo", d["ajuste_valor_fmt"], False))
    elif d.get("ajuste_valor", 0) < 0:
        fi_sem.append(("Desconto", f"- {d['ajuste_valor_fmt']}", False))
        fi_com.append(("Desconto", f"- {d['ajuste_valor_fmt']}", False))
    if d.get("compensacao_dic", 0) != 0:
        fi_sem.append(("Comp. DIC Mensal", f"- {d['compensacao_dic_fmt']}", False))
        fi_com.append(("Comp. DIC Mensal", f"- {d['compensacao_dic_fmt']}", False))
    ROW_FI = (5 if len(fi_com) > 3 else 6) * mm
    FH  = max(len(sf), len(cf)) * ROW + 8*mm
    FIH = max(len(fi_sem), len(fi_com)) * ROW_FI + 6*mm
    CLSH = CHH + FH + FIH + TBH
    FXH = STH + GAP + DBH + GAP + CLSH + GAP + EBH + GAP + CPH + GAP + AVH
    EG = max(GAP, GAP + (CONT - FXH)/6)

    def st(lbl, yy):
        c.setFillColor(dark_blue); c.setFont("Helvetica-Bold", FSB)
        c.drawString(MX, yy, lbl)
        c.setStrokeColor(dark_blue); c.setLineWidth(0.6)
        c.line(MX, yy - 2*mm, W - MX, yy - 2*mm)

    def kv(lx, yy, lbl, val):
        c.setFillColor(dark_blue); c.setFont("Helvetica-Bold", FS)
        c.drawString(lx, yy, lbl)
        vx = lx + c.stringWidth(lbl, "Helvetica-Bold", FS) + 1.5*mm
        c.setFillColor(black); c.setFont("Helvetica", FS); c.drawString(vx, yy, val)

    def cs(x, yy, title, items, row_h=None):
        if row_h is None: row_h = ROW
        c.setFillColor(dark_blue); c.setFont("Helvetica-Bold", FSB)
        c.drawString(x, yy, title)
        c.setStrokeColor(mid_gray); c.setLineWidth(0.4)
        c.line(x, yy - 2*mm, x + CW, yy - 2*mm)
        ry = yy - row_h
        for lbl, val, bold in items:
            c.setFillColor(black)
            c.setFont("Helvetica-Bold" if bold else "Helvetica", FS)
            c.drawString(x + 1*mm, ry, lbl)
            if val.endswith("%"):
                bw = c.stringWidth(val, "Helvetica-Bold", FS) + 3.5*mm
                bh = 3.5*mm; bx = x + CW - bw; by = ry - bh/2 + 2*mm
                c.setFillColor(orange); c.roundRect(bx, by, bw, bh, 1.2*mm, fill=1, stroke=0)
                c.setFillColor(dark_blue); c.setFont("Helvetica-Bold", FS)
                c.drawCentredString(bx + bw/2, by + bh/2 - 2.5, val)
            else:
                c.setFillColor(black)
                c.setFont("Helvetica-Bold" if bold else "Helvetica", FS)
                c.drawRightString(x + CW, ry, val)
            ry -= row_h

    st("DADOS DO CLIENTE  /  INFORMACOES DE LEITURA", y); y -= STH + 2*mm
    c.setFillColor(light_gray); c.setStrokeColor(mid_gray); c.setLineWidth(0.5)
    c.roundRect(MX, y - DBH, W - 2*MX, DBH + 0.5*mm, 2.5*mm, fill=1, stroke=1)
    D1 = MX + (W - 2*MX) * 0.43; D2 = MX + (W - 2*MX) * 0.70
    for dx in [D1, D2]:
        c.setStrokeColor(mid_gray); c.line(dx, y - DBH + 3*mm, dx, y - 2*mm)
    LX = MX + 3*mm
    IND = LX + c.stringWidth("Endereco: ", "Helvetica-Bold", FS) + 1.5*mm
    R1 = y - 5.5*mm; R2 = y - 11.5*mm; R3 = y - 17.5*mm; R4 = y - 23.5*mm; R5 = y - 29.5*mm; R6 = y - 35.5*mm; R7 = y - 41.5*mm
    kv(LX, R1, "Nome:", d["nome"]); kv(LX, R2, "CPF:", d.get("cpf_fmt") or d.get("cpf", ""))

    # ── Endereco com quebra automatica na coluna 1 ──
    # Monta endereco completo (formato novo ou legado)
    _end_full = d.get("endereco", "")
    if not _end_full:
        _parts = [d.get("endereco_linha1", ""), d.get("endereco_linha2", ""), d.get("endereco_linha3", "")]
        _end_full = ", ".join(p for p in _parts if p)
    # Quebra em linhas que caibam na coluna 1
    _max_w = D1 - IND - 2*mm
    _end_lines = []
    _words = _end_full.split()
    _cur = ""
    for _w in _words:
        _test = (_cur + " " + _w).strip() if _cur else _w
        if c.stringWidth(_test, "Helvetica", FS) <= _max_w:
            _cur = _test
        else:
            if _cur: _end_lines.append(_cur)
            _cur = _w
    if _cur: _end_lines.append(_cur)
    if not _end_lines: _end_lines = [""]

    # Desenha label "Endereco:" + primeira linha
    kv(LX, R3, "Endereco:", _end_lines[0])
    # Linhas seguintes do endereco (indentadas) — aumentado de 2 para 4 linhas
    c.setFillColor(black); c.setFont("Helvetica", FS)
    _end_rows = [R4, R5, R6, R7]  # +2 linhas de buffer para enderecos longos
    for _i, _ln in enumerate(_end_lines[1:]):
        if _i < len(_end_rows):
            c.drawString(IND, _end_rows[_i], _ln)

    # ── Coluna 2: UC, Tipo, Mes (com font ajustavel) ──
    MD = D1 + 3*mm
    _col2_w = D2 - D1 - 6*mm
    # UC — ajusta fonte se muito longo
    _uc_label = "UC: "
    _uc_val = d["unidade_consumidora"]
    _uc_fs = FS
    while c.stringWidth(_uc_label, "Helvetica-Bold", _uc_fs) + c.stringWidth(_uc_val, "Helvetica", _uc_fs) > _col2_w and _uc_fs > 6:
        _uc_fs -= 0.3
    c.setFillColor(dark_blue); c.setFont("Helvetica-Bold", _uc_fs)
    c.drawString(MD, R1, _uc_label)
    _uc_vx = MD + c.stringWidth(_uc_label, "Helvetica-Bold", _uc_fs) + 1*mm
    c.setFillColor(black); c.setFont("Helvetica", _uc_fs)
    c.drawString(_uc_vx, R1, _uc_val)

    kv(MD, R2, "Tipo Fornecimento:", d["tipo_fornecimento"])
    kv(MD, R3, "Mes Referencia:", d["mes_referencia"])

    # ── Coluna 3: Leituras ──
    RG = D2 + 3*mm
    kv(RG, R1, "Leit. Anterior:", d["anterior_leitura"]); kv(RG, R2, "Leitura:", d["data_leitura"])
    kv(RG, R3, "Prox. Leitura:", d["proxima_leitura"]); kv(RG, R4, "N. Dias:", d["num_dias"])
    kv(RG, R5, "Venc. Equatorial:", d["venc_equatorial"])
    y -= DBH + EG

    CLX = MX; CRX = W/2 + 2*mm
    c.setFillColor(slate); c.roundRect(CLX, y - CHH, CW, CHH, 2.5*mm, fill=1, stroke=0)
    c.setFillColor(white); c.setFont("Helvetica-Bold", 9.5)
    c.drawCentredString(CLX + CW/2, y - CHH/2 - 3, "SEM SOLEV")
    c.setFillColor(dark_blue); c.roundRect(CRX, y - CHH, CW, CHH, 2.5*mm, fill=1, stroke=0)
    c.setFillColor(orange); c.setFont("Helvetica-Bold", 9.5)
    c.drawCentredString(CRX + CW/2, y - CHH/2 - 3, "COM SOLEV")
    y -= CHH + 4*mm

    cs(CLX, y, "FORNECIMENTO", sf); cs(CRX, y, "FORNECIMENTO", cf)
    y -= max(len(sf), len(cf)) * ROW + 8*mm
    cs(CLX, y, "ITENS FINANCEIROS", fi_sem, ROW_FI); cs(CRX, y, "ITENS FINANCEIROS", fi_com, ROW_FI)
    y -= max(len(fi_sem), len(fi_com)) * ROW_FI + 6*mm

    c.setFillColor(slate); c.roundRect(CLX, y - TBH, CW, TBH, 2.5*mm, fill=1, stroke=0)
    c.setFillColor(white); c.setFont("Helvetica", 7.5)
    c.drawString(CLX + 3*mm, y - 5*mm, "TOTAL A PAGAR")
    c.setFont("Helvetica-Bold", 14); c.drawString(CLX + 3*mm, y - 10.5*mm, d["total_sem_fmt"])
    c.setFillColor(dark_blue); c.roundRect(CRX, y - TBH, CW, TBH, 2.5*mm, fill=1, stroke=0)
    c.setFillColor(orange); c.setFont("Helvetica", 7.5)
    c.drawString(CRX + 3*mm, y - 5*mm, "VALOR A PAGAR")
    c.setFont("Helvetica-Bold", 14); c.drawString(CRX + 3*mm, y - 10.5*mm, d["total_com_fmt"])
    y -= TBH + EG

    ER = 2.5*mm; GW = 26*mm; EBH2 = EBH + 0.5*mm
    c.setFillColor(green_bg); c.setStrokeColor(green); c.setLineWidth(0.8)
    c.roundRect(MX, y - EBH, W - 2*MX, EBH2, ER, fill=1, stroke=1)
    c.saveState()
    pc = c.beginPath(); pc.roundRect(MX, y - EBH, W - 2*MX, EBH2, ER)
    c.clipPath(pc, stroke=0)
    c.setFillColor(green); c.roundRect(MX, y - EBH, GW, EBH2, ER, fill=1, stroke=0)
    c.restoreState()
    c.setFillColor(white); c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(MX + GW/2, y - EBH + EBH2/2 - 3.5, "ECONOMIA")
    c.setFillColor(green); c.setFont("Helvetica-Bold", 8)
    c.drawString(MX + GW + 4*mm, y - 5.5*mm, "Economia este mes:")
    c.setFont("Helvetica-Bold", 15); c.drawString(MX + GW + 4*mm, y - 13.5*mm, d["economia_mes_fmt"])
    c.setFillColor(dark_blue); c.setFont("Helvetica-Bold", 8)
    c.drawString(W/2 + 10*mm, y - 5.5*mm, "Economia acumulada:")
    c.setFont("Helvetica-Bold", 15); c.drawString(W/2 + 10*mm, y - 13.5*mm, d["economia_acum_fmt"])
    y -= EBH + EG

    BW = W - 2*MX
    st("COMPARATIVO", y); y -= STH + 2*mm
    c.setFillColor(slate); c.roundRect(MX, y - TBH, BW, TBH, 2.5*mm, fill=1, stroke=0)
    MY1 = y - TBH/2 - 3.5
    c.setFillColor(white); c.setFont("Helvetica-Bold", 14)
    c.drawString(MX + 3*mm, MY1, f"SEM SOLEV: {d['total_sem_fmt']}")
    y -= TBH + 2*mm
    c.setFillColor(dark_blue); c.roundRect(MX, y - TBH, BW, TBH, 2.5*mm, fill=1, stroke=0)
    MY = y - TBH/2 - 3.5
    c.setFillColor(orange); c.setFont("Helvetica-Bold", 14)
    c.drawString(MX + 3*mm, MY, f"COM SOLEV: {d['total_com_fmt']}")
    c.drawRightString(MX + BW - 3*mm, MY, f"VENCIMENTO: {d['venc_contalev']}")

    SYP = PB + PBH + PTH - 1*mm; st("FORMAS DE PAGAMENTO", SYP)
    AT = SYP + 3*mm; AB = AT - AVH
    c.setFillColor(amber_bg); c.setStrokeColor(orange); c.setLineWidth(0.5)
    c.roundRect(MX, AB, W - 2*MX, AVH, 2*mm, fill=1, stroke=1)
    c.setFillColor(amber_text); c.setFont("Helvetica-Bold", 7.5)
    lw2 = c.stringWidth("IMPORTANTE:  ", "Helvetica-Bold", 7.5)
    c.drawString(MX + 3*mm, AB + AVH/2 - 2.5, "IMPORTANTE:")
    c.setFont("Helvetica", 7.5)
    c.drawString(MX + 3*mm + lw2, AB + AVH/2 - 2.5,
                 f"{d['desconto_pct_fmt']} de desconto sobre a tarifa Equatorial GO. Pague ate {d['venc_contalev']}.")

    c.setFillColor(light_gray); c.setStrokeColor(mid_gray); c.setLineWidth(0.5)
    c.roundRect(MX, PB, W - 2*MX, PBH, 2*mm, fill=1, stroke=1)
    DX = MX + (W - 2*MX) * 0.70; BX = MX + 3*mm; BAW = DX - BX - 4*mm
    MV = 3*mm; NH = 4*mm; BBH = PBH - MV - 5*mm - NH - MV
    c.setFillColor(dark_blue); c.setFont("Helvetica-Bold", 7)
    c.drawString(BX, PB + PBH - MV - 2*mm, f"BOLETO  —  Venc.: {d['venc_contalev']}  |  {d['total_com_fmt']}")
    BY2 = PB + MV + NH; bd = d["codigo_barras"]
    if bd.replace(" ", "").isdigit() and len(bd.replace(" ", "")) >= 10:
        bc = code128.Code128(bd, barHeight=BBH, barWidth=0.72, humanReadable=False)
        sx = BAW / bc.width if bc.width > 0 else 1.0
        c.saveState(); c.translate(BX, BY2); c.scale(sx, 1.0); bc.drawOn(c, 0, 0); c.restoreState()
    else:
        c.setFillColor(mid_gray); c.rect(BX, BY2, BAW, BBH, fill=1, stroke=0)
        c.setFillColor(HexColor("#777777")); c.setFont("Helvetica", 7)
        c.drawCentredString(BX + BAW/2, BY2 + BBH/2 - 3, "CODIGO DE BARRAS EM DESENVOLVIMENTO")
    c.setFillColor(black); c.setFont("Helvetica", 6)
    c.drawCentredString(BX + BAW/2, PB + MV - 0.5*mm, d["linha_digitavel"])
    c.setStrokeColor(mid_gray); c.setLineWidth(0.4)
    c.line(DX, PB + 2*mm, DX, PB + PBH - 2*mm)
    rw = W - MX - DX - 2*mm; PCX = DX + rw/2
    # Reserva 7mm na base para 2 linhas de texto (instrucao + chave PIX legivel)
    # e 5mm no topo para o titulo "PIX". QR fica no meio.
    _QR_PAD_TOP, _QR_PAD_BOTTOM = 5*mm, 7*mm
    QS = min(rw - 6*mm, PBH - _QR_PAD_TOP - _QR_PAD_BOTTOM)
    QX = PCX - QS/2
    QY = PB + _QR_PAD_BOTTOM + (PBH - _QR_PAD_TOP - _QR_PAD_BOTTOM - QS)/2
    c.setFillColor(dark_blue); c.setFont("Helvetica-Bold", 7.5)
    c.drawCentredString(PCX, PB + PBH - MV - 3*mm, "PIX")
    pix = d.get("pix_payload", "")
    pix_qr_img = d.get("pix_qr_path", "")
    _qr_drawn = False
    # Prioridade 1: QR Code ja gerado como imagem PNG
    if pix_qr_img and os.path.exists(pix_qr_img):
        try:
            from reportlab.lib.utils import ImageReader
            c.drawImage(ImageReader(pix_qr_img), QX, QY, QS, QS)
            _qr_drawn = True
        except: pass
    # Prioridade 2: Payload PIX como texto (gera QR inline)
    if not _qr_drawn and pix and len(pix) >= 20:
        qrw = qr.QrCodeWidget(pix); bnds = qrw.getBounds()
        qw = bnds[2] - bnds[0]; qh = bnds[3] - bnds[1]
        d2 = Drawing(QS, QS)
        d2.add(shapes.Group(qrw, transform=[QS/qw, 0, 0, QS/qh, 0, 0]))
        renderPDF.draw(d2, c, QX, QY)
        _qr_drawn = True
    # Fallback: placeholder cinza
    if not _qr_drawn:
        c.setFillColor(mid_gray); c.rect(QX, QY, QS, QS, fill=1, stroke=0)

    # Texto: instrucao + chave PIX legivel (fallback se QR nao escanear)
    _chave_disp = d.get("pix_chave_display", "")
    c.setFillColor(HexColor("#555555")); c.setFont("Helvetica", 6)
    if _chave_disp:
        # Duas linhas: instrucao + chave (espacadas em ~3mm uma da outra)
        c.drawCentredString(PCX, PB + 4.5*mm, "Escaneie ou use a chave PIX:")
        c.setFont("Helvetica-Bold", 6.5); c.setFillColor(dark_blue)
        c.drawCentredString(PCX, PB + 1.5*mm, _chave_disp)
    else:
        c.drawCentredString(PCX, PB + 1.5*mm, "Escaneie para pagar")

    _rodape(c, W, FT_H, dark_blue, orange, white)
    c.save()


def _pagina2(d, path):
    A4W, A4H = A4
    dark_blue = HexColor("#1a2a4a"); orange = HexColor("#f5a623"); white = colors.white
    FT_H = 16*mm
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(d["equatorial_pdf"])
    page = doc[0]
    pil_img = page.render(scale=200/72).to_pil()
    doc.close()
    arr = np.array(pil_img); oh = arr.shape[0]
    gray = np.mean(arr, axis=2)
    cy = None
    for y_pos in range(int(oh * 0.58), oh):
        if float(np.mean(gray[y_pos])) < 60 and float(np.std(gray[y_pos])) < 40:
            cy = y_pos; break
    if cy is None: cy = int(oh * 0.63)
    cy = max(0, cy - 8)
    tp = path.replace(".pdf", "_top.png")
    Image.fromarray(arr[:cy, :]).save(tp)
    ch = A4H * (cy / oh); BH = 28*mm
    c = canvas.Canvas(path, pagesize=A4)
    c.drawImage(tp, 0, A4H - ch, width=A4W, height=ch, preserveAspectRatio=False)
    by = A4H - ch - BH
    c.setFillColor(dark_blue); c.roundRect(8*mm, by, A4W - 16*mm, BH, 3*mm, fill=1, stroke=0)
    c.setFillColor(orange); c.rect(8*mm, by + BH - 1.5*mm, A4W - 16*mm, 1.5*mm, fill=1, stroke=0)
    c.setFillColor(white); c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(A4W/2, by + BH/2 - 5, "Simples Conferencia — Boleto a ser pago pela SOLEV")
    sc = FT_H + 1.2*mm + (by - FT_H - 1.2*mm)/2; cx = A4W/2
    c.setStrokeColor(orange); c.setLineWidth(1)
    c.line(cx - 60*mm, sc + 14*mm, cx + 60*mm, sc + 14*mm)
    c.line(cx - 60*mm, sc - 16*mm, cx + 60*mm, sc - 16*mm)
    c.setFillColor(dark_blue); c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(cx, sc + 8*mm, "Obrigado pela sua confianca!")
    c.setFillColor(HexColor("#444444")); c.setFont("Helvetica", 9)
    c.drawCentredString(cx, sc + 2.5*mm, "E um prazer cuidar da sua energia e da sua economia.")
    c.setFillColor(orange); c.setFont("Helvetica-BoldOblique", 9)
    c.drawCentredString(cx, sc - 5*mm, '"Porque sou eu que conheco os planos que tenho para voces,')
    c.drawCentredString(cx, sc - 9.5*mm, 'planos de prosperidade e nao de calamidade,')
    c.drawCentredString(cx, sc - 14*mm, 'planos de dar a voces esperanca e um futuro."')
    c.setFillColor(HexColor("#888888")); c.setFont("Helvetica", 7.5)
    c.drawCentredString(cx, sc - 19*mm, "Jeremias 29:11")
    _rodape(c, A4W, FT_H, dark_blue, orange, white)
    c.save()
    os.remove(tp)


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

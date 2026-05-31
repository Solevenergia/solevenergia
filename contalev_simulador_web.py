"""
CONTALEV — Gerador PDF Simulacao de Economia
Layout profissional A4 · 1 pagina
Formula: tarifa_com = tarifa × (1 - desc), desc_mostrado = (total_kwh - tc) / total_kwh
"""
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image
import numpy as np, unicodedata, os

_DIR = os.path.dirname(os.path.abspath(__file__))
# Logos do handoff oficial solev-logo/ (30/05/2026). Wordmark em paths
# (não depende de fonte). Substitui logo_transparent.png e logo_white_v_colored.png.
LOGO_COLOR = os.path.join(_DIR, "static", "logo", "solev-wordmark-navy.png")   # sobre fundo claro
LOGO_WHITE = os.path.join(_DIR, "static", "logo", "solev-wordmark-areia.png")  # sobre fundo escuro
LOGO_JPEG  = os.path.join(_DIR, "LOGO_CONTALEV.jpeg")
LOGOS_DIR  = os.path.join(_DIR, "logos_clientes")

_FN = "Helvetica-Bold"
try:
    for fp in [r"C:\Windows\Fonts\bahnschrift.ttf", r"C:\Windows\Fonts\Bahnschrift.ttf"]:
        if os.path.exists(fp):
            pdfmetrics.registerFont(TTFont("Bahnschrift", fp))
            _FN = "Bahnschrift"; break
except:
    pass

# ── Formatadores ──────────────────────────────────────────
def _f(v):
    """Formata valor monetario: R$ 1.234,56"""
    if v == 0: return "R$ 0,00"
    return "R$ {:,.2f}".format(v).replace(",", "X").replace(".", ",").replace("X", ".")

def _ft(v):
    """Formata tarifa R$/kWh com 6 decimais"""
    return "R$ {:.6f}".format(v).replace(".", ",")

# ── Preparacao de logos ───────────────────────────────────
def _preparar_logos():
    if os.path.exists(LOGO_COLOR) and os.path.exists(LOGO_WHITE):
        return
    if not os.path.exists(LOGO_JPEG):
        raise FileNotFoundError(f"Logo nao encontrada: {LOGO_JPEG}")
    img = Image.open(LOGO_JPEG).convert('RGBA')
    arr = np.array(img)
    r, g, b, a = arr[:,:,0], arr[:,:,1], arr[:,:,2], arr[:,:,3]
    wm = (r > 235) & (g > 235) & (b > 235); arr[wm, 3] = 0
    nw = (r > 210) & (g > 210) & (b > 210) & ~wm
    avg = (r[nw].astype(int) + g[nw].astype(int) + b[nw].astype(int)) // 3
    arr[nw, 3] = (255 - (avg - 210) * 255 // 45).clip(0, 255).astype(np.uint8)
    t = Image.fromarray(arr)
    bb = t.getbbox()
    if bb: t = t.crop(bb)
    t.save(LOGO_COLOR)
    # Versao branca para rodape
    a2 = np.array(t.copy(), dtype=np.float64)
    r2, g2, b2, a2a = a2[:,:,0], a2[:,:,1], a2[:,:,2], a2[:,:,3]
    br = (r2 + g2 + b2) / 3; vis = a2a > 30
    db = vis & (br < 100) & (b2 > r2 * 1.2); warm = (r2 > b2 * 1.3) & vis
    m = db & ~warm; a2[m, 0] = 255; a2[m, 1] = 255; a2[m, 2] = 255
    tr = vis & (br >= 50) & (br < 150) & (b2 > r2) & ~warm
    for ch in range(3):
        a2[tr, ch] = np.clip(a2[tr, ch] * 0.3 + 255 * 0.7, 0, 255)
    Image.fromarray(a2.astype(np.uint8)).save(LOGO_WHITE)

def _lr():
    return Image.open(LOGO_COLOR).height / Image.open(LOGO_COLOR).width


# ══════════════════════════════════════════════════════════
#  GERADOR PRINCIPAL
# ══════════════════════════════════════════════════════════
def gerar_simulacao_web(d):
    _preparar_logos()

    # ── Dados de entrada ──────────────────────────────────
    consumo = d["consumo_kwh"]
    tarifa  = d["tarifa_sem"]
    desc    = d["desconto_pct"]
    ilum    = d["iluminacao_publica"]
    ba      = d.get("bandeira_amarela", 0)
    bv      = d.get("bandeira_vermelha", 0)
    multa   = d.get("multa", 0)
    juros   = d.get("juros", 0)
    modo    = d.get("modo_bandeira", "com_bandeira")
    comp    = d.get("compensado", consumo)
    ncomp   = d.get("nao_comp", 0)

    _ms = {1:"Janeiro", 2:"Fevereiro", 3:"Marco", 4:"Abril", 5:"Maio", 6:"Junho",
           7:"Julho", 8:"Agosto", 9:"Setembro", 10:"Outubro", 11:"Novembro", 12:"Dezembro"}
    mn, ano = d["mes_referencia"].split("/")
    mes_ano = f"{_ms[int(mn)]} / {ano}"

    # ── Calculos (conforme Base_calculo.xlsx) ─────────────
    en_sem     = consumo * tarifa
    ba_kwh     = ba / consumo if ba > 0 and consumo > 0 else 0
    bv_kwh     = bv / consumo if bv > 0 and consumo > 0 else 0
    band_total = ba + bv
    band_kwh   = ba_kwh + bv_kwh
    total_kwh  = tarifa + band_kwh
    tot_sem    = en_sem + band_total + ilum + multa + juros

    tc     = tarifa * (1 - desc)
    en_com = consumo * tc

    if modo == "sem_bandeira" and band_total > 0:
        tot_com = en_com + band_total + ilum + multa + juros
        desc_mostrado = round(desc * 100, 2)
    else:
        tot_com = en_com + ilum + multa + juros
        if band_total > 0:
            desc_mostrado = round((total_kwh - tc) / total_kwh * 100, 2)
        else:
            desc_mostrado = round(desc * 100, 2)

    eco    = tot_sem - tot_com
    eco_an = eco * 12

    # ── Nome do arquivo ───────────────────────────────────
    nl  = unicodedata.normalize('NFKD', d["nome"]).encode('ascii', 'ignore').decode('ascii')
    na  = "".join(w.capitalize() for w in nl.split())
    mr  = d["mes_referencia"].replace("/", "")
    out = os.path.join(_DIR, f"{mr}-CONTALEV{na}.pdf")

    # ── Canvas e paleta ───────────────────────────────────
    ratio = _lr()
    c = canvas.Canvas(out, pagesize=A4)
    W, H = A4

    DB  = HexColor("#1a2a4a")   # Azul escuro
    OR  = HexColor("#f5a623")   # Laranja
    SL  = HexColor("#455a64")   # Cinza azulado
    GR  = HexColor("#2e7d32")   # Verde
    GB  = HexColor("#e8f5e9")   # Verde claro (fundo)
    LG  = HexColor("#f4f4f4")   # Cinza claro
    MG  = HexColor("#cccccc")   # Cinza medio
    DG  = HexColor("#666666")   # Cinza escuro
    WH  = colors.white
    BK  = colors.black

    MX  = 8 * mm        # Margem horizontal
    FS  = 7.5            # Font size padrao
    ROW = 4.5 * mm       # Altura de linha
    FTH = 14 * mm        # Altura do rodape

    # ── Helper: label + valor lado a lado ─────────────────
    def kv(lx, yy, lbl, val):
        c.setFillColor(DB); c.setFont("Helvetica-Bold", 6.5)
        c.drawString(lx, yy, lbl)
        lw = c.stringWidth(lbl, "Helvetica-Bold", 6.5)
        c.setFillColor(BK); c.setFont("Helvetica", 6.5)
        c.drawString(lx + lw + 1.2*mm, yy, str(val))

    # ══════════════════════════════════════════════════════
    #  1. HEADER — Faixa diagonal com logo
    # ══════════════════════════════════════════════════════
    HH = 18 * mm
    c.setFillColor(WH); c.rect(0, H - HH, W, HH, fill=1, stroke=0)

    DT  = W * 0.50
    DBx = W * 0.58
    p = c.beginPath()
    p.moveTo(DT, H); p.lineTo(W, H); p.lineTo(W, H - HH); p.lineTo(DBx, H - HH); p.close()
    c.setFillColor(DB); c.drawPath(p, fill=1, stroke=0)

    S = 1.5 * mm
    p2 = c.beginPath()
    p2.moveTo(DT - S*.5, H); p2.lineTo(DT + S*.5, H)
    p2.lineTo(DBx + S*.5, H - HH); p2.lineTo(DBx - S*.5, H - HH); p2.close()
    c.setFillColor(OR); c.drawPath(p2, fill=1, stroke=0)
    c.rect(0, H - HH - 1*mm, W, 1*mm, fill=1, stroke=0)

    LW = 35 * mm; LH = LW * ratio
    c.drawImage(LOGO_COLOR, MX, H - HH + (HH - LH)/2, width=LW, height=LH, mask='auto')

    rcx = DT + (W - DT) / 2 + 3*mm
    c.setFillColor(HexColor("#aabbcc")); c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(rcx, H - 5*mm, "SIMULACAO DE ECONOMIA")
    c.setFillColor(WH); c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(rcx, H - 13*mm, mes_ano)

    y = H - HH - 1*mm - 5*mm

    # ══════════════════════════════════════════════════════
    #  2. SIMULACAO PARA — Nome do cliente
    # ══════════════════════════════════════════════════════
    c.setFillColor(DB); c.setFont("Helvetica-Bold", 8)
    c.drawString(MX, y, "SIMULACAO PARA")
    c.setStrokeColor(DB); c.setLineWidth(0.5)
    c.line(MX, y - 1.5*mm, W - MX, y - 1.5*mm)
    y -= 5.5 * mm

    NH = 9 * mm
    c.setFillColor(DB); c.roundRect(MX, y - NH, W - 2*MX, NH, 2*mm, fill=1, stroke=0)
    nome = d["nome"]
    bxw = W - 2*MX - 6*mm
    ns = 13
    while ns > 7:
        if c.stringWidth(nome, _FN, ns) <= bxw:
            break
        ns -= 0.5
    c.setFillColor(OR); c.setFont(_FN, ns)
    c.drawCentredString(W / 2, y - NH/2 - ns * 0.35, nome)
    y -= NH + 3 * mm

    # ══════════════════════════════════════════════════════
    #  3. DADOS DO CLIENTE — Bloco informativo 3 colunas
    # ══════════════════════════════════════════════════════
    uc  = str(d.get("uc", ""))
    cpf = str(d.get("cpf", ""))
    tf  = str(d.get("tipo_fornecimento", ""))
    end = str(d.get("endereco", ""))
    al  = str(d.get("anterior_leitura", ""))
    dl  = str(d.get("data_leitura", ""))
    pl  = str(d.get("proxima_leitura", ""))
    nd  = str(d.get("n_dias", ""))

    if uc or cpf or end or al:
        bw  = W - 2*MX
        c1w = bw * 0.42
        c2w = bw * 0.29
        c3w = bw * 0.29
        c1x = MX + 2*mm
        c2x = MX + c1w + 1*mm
        c3x = MX + c1w + c2w + 1*mm
        lh  = 3.8 * mm

        # Quebra endereco em linhas de ~65 chars (aumentado para reduzir quebras)
        el = []
        if end:
            ws = end.split()
            cur = ""
            for w in ws:
                if len(cur + " " + w) > 65 and cur:  # Era 45, agora 65 para menos linhas
                    el.append(cur.strip()); cur = w
                else:
                    cur = (cur + " " + w).strip()
            if cur:
                el.append(cur.strip())

        rl = max(len(el) + 2, 6 if al else 3, 3)  # +2 garante espaco extra para nao cortar
        bh = rl * lh + 4 * mm

        c.setFillColor(LG); c.setStrokeColor(MG); c.setLineWidth(0.3)
        c.roundRect(MX, y - bh, bw, bh, 2*mm, fill=1, stroke=1)

        # Separadores verticais
        c.setStrokeColor(HexColor("#dddddd")); c.setLineWidth(0.2)
        c.line(MX + c1w, y - 2.5*mm, MX + c1w, y - bh + 2.5*mm)
        c.line(MX + c1w + c2w, y - 2.5*mm, MX + c1w + c2w, y - bh + 2.5*mm)

        ry = y - 4 * mm

        # ── Coluna 1: Endereco ──
        c.setFillColor(DB); c.setFont("Helvetica-Bold", 6.5)
        c.drawString(c1x, ry, "Endereco:")
        ry2 = ry - lh
        c.setFillColor(BK); c.setFont("Helvetica", 6)
        for ln in el:
            c.drawString(c1x, ry2, ln)
            ry2 -= lh

        # ── Coluna 2: UC, Tipo, Leituras ──
        r2 = y - 4 * mm
        if uc:   kv(c2x, r2, "UC:", uc);                r2 -= lh
        if tf:   kv(c2x, r2, "Tipo:", tf);              r2 -= lh
        if al:   kv(c2x, r2, "Leit. Ant.:", al);        r2 -= lh
        if dl:   kv(c2x, r2, "Leit. Atual:", dl);       r2 -= lh
        if nd:   kv(c2x, r2, "Nº Dias:", nd);           r2 -= lh

        # ── Coluna 3: CPF, Ref, Prox, Compensado ──
        r3 = y - 4 * mm
        if cpf:  kv(c3x, r3, "CPF/CNPJ:", cpf);        r3 -= lh
        kv(c3x, r3, "Referencia:", d["mes_referencia"]); r3 -= lh
        if pl:   kv(c3x, r3, "Prox. Leit.:", pl);       r3 -= lh
        cs2 = "{:,.0f}".format(comp).replace(",", ".")
        kv(c3x, r3, "Compensado:", f"{cs2} kWh");        r3 -= lh
        if ncomp > 0:
            ns2 = "{:,.0f}".format(ncomp).replace(",", ".")
            kv(c3x, r3, "Nao Comp.:", f"{ns2} kWh")

        y -= bh + 3 * mm

    # ══════════════════════════════════════════════════════
    #  4. DETALHAMENTO — Colunas SEM × COM
    # ══════════════════════════════════════════════════════
    CW  = (W - 2*MX) / 2 - 2*mm
    CLX = MX
    CRX = W / 2 + 2*mm
    CH  = 6.5 * mm

    # Cabecalhos das colunas
    c.setFillColor(SL); c.roundRect(CLX, y - CH, CW, CH, 2*mm, fill=1, stroke=0)
    c.setFillColor(WH); c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(CLX + CW/2, y - CH/2 - 2, "SEM CONTALEV")

    c.setFillColor(DB); c.roundRect(CRX, y - CH, CW, CH, 2*mm, fill=1, stroke=0)
    c.setFillColor(OR); c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(CRX + CW/2, y - CH/2 - 2, "COM CONTALEV")
    y -= CH + 3 * mm

    # ── Funcao: renderiza coluna de detalhamento ──────────
    def col(x, yy, items):
        c.setFillColor(DB); c.setFont("Helvetica-Bold", 7)
        c.drawString(x + 1*mm, yy, "Detalhamento")
        c.setStrokeColor(MG); c.setLineWidth(0.3)
        c.line(x, yy - 1.2*mm, x + CW, yy - 1.2*mm)
        ry = yy - ROW - 0.5*mm
        for lbl, val, bold, sep in items:
            if sep:
                # Separador "Itens financeiros"
                c.setStrokeColor(MG); c.setLineWidth(0.3)
                c.line(x + 1*mm, ry + 1.5*mm, x + CW - 1*mm, ry + 1.5*mm)
                c.setFillColor(DG); c.setFont("Helvetica", 5.5)
                c.drawString(x + 1.5*mm, ry - 0.5*mm, lbl)
                ry -= ROW * 0.75
                continue
            fn = "Helvetica-Bold" if bold else "Helvetica"
            c.setFillColor(BK if not bold else DB)
            c.setFont(fn, FS)
            c.drawString(x + 1.5*mm, ry, lbl)
            # Badge para percentual
            if "%" in str(val) and "R$" not in str(val):
                bw2 = c.stringWidth(str(val), "Helvetica-Bold", FS) + 3*mm
                bh2 = 3.2*mm
                bx2 = x + CW - bw2 - 0.5*mm
                by2 = ry - bh2/2 + 1.5*mm
                c.setFillColor(OR); c.roundRect(bx2, by2, bw2, bh2, 1*mm, fill=1, stroke=0)
                c.setFillColor(DB); c.setFont("Helvetica-Bold", FS)
                c.drawCentredString(bx2 + bw2/2, by2 + bh2/2 - 2, str(val))
            else:
                c.setFont(fn, FS)
                c.drawRightString(x + CW - 1*mm, ry, str(val))
            ry -= ROW
        return ry

    # ── Montagem: SEM CONTALEV ────────────────────────────
    sf = [("Tarifa (R$/kWh):", _ft(tarifa), False, False)]
    if ba > 0:
        sf.append(("Band. Amarela (R$/kWh):", _ft(ba_kwh), False, False))
    if bv > 0:
        sf.append(("Band. Vermelha (R$/kWh):", _ft(bv_kwh), False, False))
    sf.append(("Subtotal Energia:", _f(en_sem + band_total), True, False))
    sf.append(("Itens financeiros", "", False, True))
    sf.append(("Iluminacao Publica:", _f(ilum), False, False))
    if multa > 0:
        sf.append(("Multa:", _f(multa), False, False))
    if juros > 0:
        sf.append(("Juros:", _f(juros), False, False))

    # ── Montagem: COM CONTALEV ────────────────────────────
    dp = f"{desc_mostrado}%"
    cf = [("Tarifa c/ Desc. (R$/kWh):", _ft(tc), False, False)]
    cf.append(("Desconto aplicado:", dp, False, False))
    cf.append(("Subtotal Energia:", _f(en_com), True, False))
    cf.append(("Itens financeiros", "", False, True))
    cf.append(("Iluminacao Publica:", _f(ilum), False, False))
    if multa > 0:
        cf.append(("Multa:", _f(multa), False, False))
    if juros > 0:
        cf.append(("Juros:", _f(juros), False, False))

    ry1 = col(CLX, y, sf)
    ry2 = col(CRX, y, cf)
    y = min(ry1, ry2) - 3 * mm

    # ══════════════════════════════════════════════════════
    #  5. TOTAIS — Blocos de destaque
    # ══════════════════════════════════════════════════════
    TH = 10 * mm

    c.setFillColor(SL); c.roundRect(CLX, y - TH, CW, TH, 2*mm, fill=1, stroke=0)
    c.setFillColor(WH); c.setFont("Helvetica", 6.5)
    c.drawString(CLX + 3*mm, y - 3.5*mm, "VOCE PAGA HOJE")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(CLX + 3*mm, y - 8.5*mm, _f(tot_sem))

    c.setFillColor(DB); c.roundRect(CRX, y - TH, CW, TH, 2*mm, fill=1, stroke=0)
    c.setFillColor(OR); c.setFont("Helvetica", 6.5)
    c.drawString(CRX + 3*mm, y - 3.5*mm, "COM A CONTALEV")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(CRX + 3*mm, y - 8.5*mm, _f(tot_com))

    y -= TH + 4 * mm

    # ══════════════════════════════════════════════════════
    #  6. ECONOMIA — Quadro verde de destaque
    # ══════════════════════════════════════════════════════
    EH = 16 * mm
    c.setFillColor(GB); c.setStrokeColor(GR); c.setLineWidth(0.8)
    c.roundRect(MX, y - EH, W - 2*MX, EH, 2*mm, fill=1, stroke=1)

    GW = 22 * mm
    c.saveState()
    pc = c.beginPath()
    pc.roundRect(MX, y - EH, W - 2*MX, EH, 2*mm)
    c.clipPath(pc, stroke=0)
    c.setFillColor(GR); c.roundRect(MX, y - EH, GW, EH, 2*mm, fill=1, stroke=0)
    c.restoreState()

    c.setFillColor(WH); c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(MX + GW/2, y - EH/2 + 3, "SUA")
    c.drawCentredString(MX + GW/2, y - EH/2 - 5, "ECONOMIA")

    bx = MX + GW + 4*mm
    c.setFillColor(GR); c.setFont("Helvetica-Bold", 7)
    c.drawString(bx, y - 5*mm, f"Economia mensal ({desc_mostrado}% de desconto):")
    c.setFont("Helvetica-Bold", 13)
    c.drawString(bx, y - 11*mm, _f(eco))

    ax = W/2 + 10*mm
    c.setFillColor(DB); c.setFont("Helvetica-Bold", 7)
    c.drawString(ax, y - 5*mm, "Projecao anual estimada:")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(ax, y - 11*mm, _f(eco_an))

    c.setFillColor(DG); c.setFont("Helvetica", 5)
    c.drawString(bx, y - 15*mm, "* Valores sujeitos a variacao conforme consumo e tarifas vigentes.")

    y -= EH + 4 * mm

    # ══════════════════════════════════════════════════════
    #  7. PROJECAO ANUAL — Grafico de barras 12 meses
    # ══════════════════════════════════════════════════════
    c.setFillColor(DB); c.setFont("Helvetica-Bold", 8)
    c.drawString(MX, y, "PROJECAO DE ECONOMIA ANUAL")
    c.setStrokeColor(DB); c.setLineWidth(0.5)
    c.line(MX, y - 1.5*mm, W - MX, y - 1.5*mm)
    y -= 4 * mm

    mn2 = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]
    CW2 = W - 2*MX
    CH2 = 22 * mm
    cx  = MX
    cy  = y - CH2

    c.setFillColor(LG); c.roundRect(cx, cy, CW2, CH2, 2*mm, fill=1, stroke=0)

    bp  = 3 * mm
    baw = CW2 - 2*bp
    bwb = baw / 12 - 1.5*mm
    mbh = CH2 - 8*mm
    ac  = 0
    for i in range(12):
        ac += eco
        bxp = cx + bp + i * (baw / 12) + 0.75*mm
        bht = mbh * ((i + 1) / 12)
        c.setFillColor(OR if i % 2 == 0 else DB)
        c.roundRect(bxp, cy + 2*mm, bwb, bht, 0.8*mm, fill=1, stroke=0)
        c.setFillColor(DG); c.setFont("Helvetica", 4.5)
        c.drawCentredString(bxp + bwb/2, cy - 1*mm, mn2[i])
        c.setFillColor(DB); c.setFont("Helvetica-Bold", 4)
        vt = "{:.1f}k".format(ac / 1000) if ac >= 1000 else "{:.0f}".format(ac)
        c.drawCentredString(bxp + bwb/2, cy + 2*mm + bht + 0.8*mm, vt)

    y = cy - 3 * mm

    # ══════════════════════════════════════════════════════
    #  8. BARRAS COMPARATIVAS — Antes × Depois
    # ══════════════════════════════════════════════════════
    BH2 = 7 * mm
    FW  = W - 2*MX

    c.setFillColor(SL); c.roundRect(MX, y - BH2, FW, BH2, 2*mm, fill=1, stroke=0)
    c.setFillColor(WH); c.setFont("Helvetica-Bold", 8)
    c.drawString(MX + 3*mm, y - BH2/2 - 2, f"SEM CONTALEV     {_f(tot_sem)}")
    y -= BH2 + 1.5*mm

    c.setFillColor(DB); c.roundRect(MX, y - BH2, FW, BH2, 2*mm, fill=1, stroke=0)
    c.setFillColor(OR); c.setFont("Helvetica-Bold", 8)
    c.drawString(MX + 3*mm, y - BH2/2 - 2, f"COM CONTALEV     {_f(tot_com)}")
    y -= BH2 + 3.5*mm

    # ══════════════════════════════════════════════════════
    #  9. CHAMADA PARA ACAO — Frases de fechamento
    # ══════════════════════════════════════════════════════
    c.setStrokeColor(OR); c.setLineWidth(0.6)
    c.line(MX, y, W - MX, y)
    y -= 4 * mm

    tw = W - 2*MX
    st_main = ParagraphStyle('main',
        fontName='Helvetica-Bold', fontSize=8.5, leading=10.5,
        textColor=DB, alignment=TA_CENTER)
    frase = ("Cada dia que voce espera e dinheiro que deixa na mesa. "
             "Sem investimento, sem fidelidade e com economia ja na proxima fatura "
             "— vamos comecar agora?")
    p = Paragraph(frase, st_main)
    pw, ph = p.wrap(tw, 200)
    p.drawOn(c, MX, y - ph)
    y -= ph + 2 * mm

    st_cta = ParagraphStyle('cta',
        fontName='Helvetica-BoldOblique', fontSize=7.5, leading=9,
        textColor=OR, alignment=TA_CENTER)
    p = Paragraph("Entre em contato e comece a economizar hoje mesmo!", st_cta)
    pw, ph = p.wrap(tw, 200)
    p.drawOn(c, MX, y - ph)
    y -= ph + 3 * mm

    # ══════════════════════════════════════════════════════
    #  10. CLIENTES — Logomarcas em 2 linhas (6 + 5)
    # ══════════════════════════════════════════════════════
    c.setStrokeColor(MG); c.setLineWidth(0.3)
    c.line(MX, y, W - MX, y)
    y -= 4 * mm

    c.setFillColor(DB); c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(W / 2, y, "ALGUNS DE NOSSOS CLIENTES")
    y -= 3 * mm

    logos_files = [
        "canto_do_gallo.png", "mundial.png", "inst_longevidade.png",
        "giggio.png", "petit_pao.png", "buycar.png",
        "concept_motors.png", "cp_pizza.png", "atelie_salada.png",
        "kidgarden.png", "destak.png"
    ]
    lw  = 26 * mm
    lhg = 11 * mm
    gp  = 2 * mm

    def _draw_logos(n, start_idx):
        nonlocal y
        total_w = n * lw + (n - 1) * gp
        sx = (W - total_w) / 2
        for i in range(n):
            lx  = sx + i * (lw + gp)
            idx = start_idx + i
            lp  = os.path.join(LOGOS_DIR, logos_files[idx]) if idx < len(logos_files) else ""
            if lp and os.path.exists(lp):
                try:
                    c.drawImage(lp, lx, y - lhg, width=lw, height=lhg,
                                preserveAspectRatio=True, mask='auto')
                except:
                    c.setStrokeColor(MG); c.setLineWidth(0.3)
                    c.roundRect(lx, y - lhg, lw, lhg, 1.5*mm, fill=0, stroke=1)
            else:
                c.setStrokeColor(MG); c.setLineWidth(0.3)
                c.roundRect(lx, y - lhg, lw, lhg, 1.5*mm, fill=0, stroke=1)
        y -= lhg + 1.5*mm

    _draw_logos(6, 0)   # Linha 1: 6 logos
    _draw_logos(5, 6)   # Linha 2: 5 logos

    # ══════════════════════════════════════════════════════
    #  11. RODAPE
    # ══════════════════════════════════════════════════════
    c.setFillColor(DB); c.rect(0, 0, W, FTH, fill=1, stroke=0)
    c.setFillColor(OR); c.rect(0, FTH, W, 1*mm, fill=1, stroke=0)

    FLW = 25 * mm
    FLH = FLW * ratio
    c.drawImage(LOGO_WHITE, 8*mm, (FTH - FLH) / 2, width=FLW, height=FLH, mask='auto')

    c.setFillColor(WH); c.setFont("Helvetica", 5.5)
    c.drawRightString(W - 8*mm, 9*mm, "Simulacao ilustrativa. Valores sujeitos a variacao conforme tarifas vigentes.")
    c.setFont("Helvetica", 4.5)
    c.drawRightString(W - 8*mm, 5.5*mm, "CONTALEV © 2026 — Energia solar por assinatura")

    c.save()
    return out

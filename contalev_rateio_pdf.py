"""
contalev_rateio_pdf.py
======================
Geracao do PDF de Formulario de Rateio (padrao Equatorial).

Exporta:
    gerar_pdf_rateio(usina, uid, vinculados) -> str  (caminho do PDF gerado)

Funcoes internas:
    _safe_pdf_str(s)                        — sanitiza strings para ReportLab/Helvetica
    _gerar_assinatura_image_dinamica(uid)   — gera PNG de assinatura com data/hora dinamica
"""

import os

_DIR = os.path.dirname(os.path.abspath(__file__))


# ─────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────

def _safe_pdf_str(s):
    """Remove caracteres fora do Latin-1 que quebram o ReportLab (Helvetica)."""
    if not s:
        return ""
    return "".join(c if ord(c) < 256 and c != "\ufffd" else "" for c in str(s))


def _uc_so_digitos(s):
    """Remove pontua\u00e7\u00e3o (pontos, h\u00edfens, espa\u00e7os) das UCs para o Formul\u00e1rio
    de Solicita\u00e7\u00e3o de Rateio \u2014 Equatorial pede formato cru, s\u00f3 d\u00edgitos."""
    if not s:
        return ""
    return "".join(c for c in str(s) if c.isdigit())


def _gerar_assinatura_image_dinamica(uid):
    """Carrega a imagem base de assinatura e sobrescreve apenas a linha 'Dados:'
    com a data/hora atual no fuso de Brasilia. Mantem o mesmo corpo de fonte das
    demais linhas do bloco direito (Assinado de forma digital por / Nome / CPF) e
    alinha o inicio da linha Dados com a coluna do nome (x=1309)."""
    from PIL import Image, ImageDraw, ImageFont
    from datetime import datetime, timezone, timedelta

    base_path = os.path.join(_DIR, "assets", "assinatura_base.png")
    if not os.path.exists(base_path):
        return None

    base = Image.open(base_path).convert("RGBA")
    bw, bh = base.size

    # Canvas estendido a direita para caber a linha "Dados:" na fonte cheia
    new_w = max(bw, 2320)
    canvas = Image.new("RGBA", (new_w, bh), (255, 255, 255, 255))
    canvas.paste(base, (0, 0), base)

    d = ImageDraw.Draw(canvas)
    # Limpa a faixa da linha "Assinado..." (para realinhar) e a linha "Dados:".
    # Na faixa de Assinado o texto grande da esquerda nao alcanca x>=1150, por isso
    # podemos apagar a partir de x=1200 sem afetar o bloco esquerdo.
    d.rectangle([(1200, 95), (new_w, 190)], fill=(255, 255, 255, 255))
    d.rectangle([(1300, 350), (new_w, 432)], fill=(255, 255, 255, 255))

    # Arial Narrow 72px → cap height ~52, mesmo corpo das demais linhas do bloco direito.
    # Em producao (Linux/Railway) nao existem fontes do Windows: a cascata cai na
    # Liberation Sans Narrow do repo (metricamente compativel com a Arial Narrow).
    candidatas = (
        ("C:/Windows/Fonts/ARIALN.TTF", 72),
        ("C:/Windows/Fonts/arialn.ttf", 72),
        (os.path.join(_DIR, "assets", "fonts", "LiberationSansNarrow-Regular.ttf"), 72),
        ("C:/Windows/Fonts/arial.ttf", 60),
        (os.path.join(_DIR, "static", "fonts", "Manrope-400-normal.ttf"), 60),
    )
    font = None
    for fp, tam in candidatas:
        if os.path.exists(fp):
            font = ImageFont.truetype(fp, tam)
            break
    if font is None:
        try:
            font = ImageFont.load_default(size=60)  # Pillow >= 10.1
        except TypeError:
            font = ImageFont.load_default()

    brt = timezone(timedelta(hours=-3))
    now = datetime.now(brt)

    # "Assinado de forma digital por" redesenhado alinhado com DANILO/DE SOUSA (x=1309)
    d.text((1309, 95), "Assinado de forma digital por", fill=(0, 0, 0, 255), font=font)

    # Linha Dados dinamica
    txt = f"Dados: {now.strftime('%Y.%m.%d %H:%M:%S')} -03'00\""
    d.text((1309, 351), txt, fill=(0, 0, 0, 255), font=font)

    out_path = os.path.join(_DIR, f"_assinatura_{uid}.png")
    canvas.save(out_path)
    return out_path


# ─────────────────────────────────────────────────────────────
# Funcao principal — exportada
# ─────────────────────────────────────────────────────────────

def _nome_rateio_arquivo(usina, uid, mes_ref: str = "") -> str:
    """Monta o nome do arquivo de rateio: YYYYMM-RateioNomeUsina.pdf

    Ex: 202605-RateioUSDaniloEvangelista70.pdf
    """
    import re
    from datetime import datetime

    # Prefixo YYYYMM
    if mes_ref:
        partes = mes_ref.strip().split("/")
        try:
            yyyymm = f"{int(partes[-1])}{int(partes[0]):02d}" if len(partes) == 2 else mes_ref.replace("/", "")
        except Exception:
            yyyymm = datetime.now().strftime("%Y%m")
    else:
        yyyymm = datetime.now().strftime("%Y%m")

    # Nome limpo da usina (remove espaços, acentos problemáticos e chars inválidos)
    nome_base = usina.get("nome") or str(uid)
    nome_limpo = re.sub(r"[\\/:*?\"<>|'\s]", "", nome_base)
    if not nome_limpo:
        nome_limpo = str(uid)

    return f"{yyyymm}-Rateio{nome_limpo}.pdf"


def gerar_pdf_rateio(usina, uid, vinculados, mes_ref: str = ""):
    """Gera PDF do formulario de rateio no padrao Equatorial (layout platypus)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                     TableStyle, KeepTogether, PageBreak)

    output = os.path.join(_DIR, _nome_rateio_arquivo(usina, uid, mes_ref))

    # ── Paleta em cinza/formal ──
    c_dark   = colors.HexColor("#1f1f1f")
    c_mid    = colors.HexColor("#4a4a4a")
    c_line   = colors.HexColor("#9e9e9e")
    c_zebra  = colors.HexColor("#f2f2f2")
    c_header = colors.HexColor("#2e2e2e")
    c_total  = colors.HexColor("#d9d9d9")

    # ── Estilos ──
    styles = getSampleStyleSheet()
    st_title = ParagraphStyle("title", parent=styles["Normal"], fontName="Helvetica-Bold",
                              fontSize=13, alignment=TA_CENTER, textColor=c_dark, leading=16,
                              spaceAfter=2)
    st_sub = ParagraphStyle("sub", parent=styles["Normal"], fontName="Helvetica",
                            fontSize=8.5, alignment=TA_CENTER, textColor=c_mid, leading=11)
    st_section = ParagraphStyle("section", parent=styles["Normal"], fontName="Helvetica-Bold",
                                fontSize=10, textColor=colors.white, leading=12,
                                leftIndent=4, spaceBefore=0, spaceAfter=0)
    st_label = ParagraphStyle("label", parent=styles["Normal"], fontName="Helvetica-Bold",
                              fontSize=8.5, textColor=c_dark, leading=11)
    st_value = ParagraphStyle("value", parent=styles["Normal"], fontName="Helvetica",
                              fontSize=8.5, textColor=c_dark, leading=11)
    st_note = ParagraphStyle("note", parent=styles["Normal"], fontName="Helvetica",
                             fontSize=8, textColor=c_mid, leading=10)
    st_sig = ParagraphStyle("sig", parent=styles["Normal"], fontName="Helvetica-Bold",
                            fontSize=9.5, alignment=TA_CENTER, textColor=c_dark, leading=12)
    st_sig_sub = ParagraphStyle("sigsub", parent=styles["Normal"], fontName="Helvetica",
                                fontSize=8.5, alignment=TA_CENTER, textColor=c_mid, leading=11)

    doc = SimpleDocTemplate(
        output, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=8*mm, bottomMargin=10*mm,
        title=f"Formulario de Rateio - {usina.get('nome', uid)}",
    )
    content_w = doc.width  # largura util

    story = []

    # ── Cabecalho ──
    story.append(Paragraph("Formulario de Solicitacao de Rateio — GD", st_title))
    story.append(Paragraph("Geracao Distribuida — Equatorial Energia", st_sub))
    story.append(Spacer(1, 2*mm))

    # ── 1. Identificacao da UC ──
    sec1 = Table([[Paragraph("1. Identificacao da Unidade Consumidora (UC)", st_section)]],
                 colWidths=[content_w])
    sec1.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), c_header),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(sec1)

    uc_ger = _uc_so_digitos(usina.get("uc_geradora", ""))
    titular = _safe_pdf_str(usina.get("titular_uc", ""))
    cpf_tit = _safe_pdf_str(usina.get("cpf_titular", ""))
    endereco = _safe_pdf_str(usina.get("endereco", ""))
    cep = _safe_pdf_str(usina.get("cep", ""))
    cidade = _safe_pdf_str(usina.get("cidade_uf", ""))

    classe   = _safe_pdf_str(usina.get("classe", ""))
    telefone = _safe_pdf_str(usina.get("telefone", ""))
    email    = _safe_pdf_str(usina.get("email_titular", ""))

    info_rows = [
        [Paragraph("Codigo da UC:", st_label), Paragraph(uc_ger, st_value),
         Paragraph("Classe:", st_label), Paragraph(classe, st_value)],
        [Paragraph("Titular da UC:", st_label), Paragraph(titular, st_value),
         Paragraph("CPF/CNPJ:", st_label), Paragraph(cpf_tit, st_value)],
        [Paragraph("Endereco:", st_label), Paragraph(endereco, st_value),
         Paragraph("CEP:", st_label), Paragraph(cep, st_value)],
        [Paragraph("Cidade/UF:", st_label), Paragraph(cidade, st_value),
         Paragraph("Telefone:", st_label), Paragraph(telefone, st_value)],
        [Paragraph("E-mail:", st_label), Paragraph(email, st_value),
         Paragraph("", st_label), Paragraph("", st_value)],
    ]
    col_w = [28*mm, (content_w - 28*mm - 22*mm - 40*mm), 22*mm, 40*mm]
    tbl_info = Table(info_rows, colWidths=col_w, rowHeights=[9*mm]*5)
    tbl_info.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, c_line),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        # Ultima linha: e-mail ocupa as 4 colunas
        ("SPAN", (1, 4), (3, 4)),
    ]))
    story.append(tbl_info)
    story.append(Spacer(1, 3*mm))

    # ── 2. Lista de UCs participantes ──
    titulo2 = ("2. Lista de Unidades Consumidoras Participantes do Sistema de Compensacao, "
               "indicando a porcentagem de rateio dos creditos e o enquadramento "
               "(conforme incisos VI a VIII do art. 2º da Resolucao Normativa nº 482/2012).")
    sec2 = Table([[Paragraph(titulo2, ParagraphStyle("s2", parent=st_section, fontSize=9, leading=11))]],
                 colWidths=[content_w])
    sec2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), c_header),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(sec2)
    story.append(Spacer(1, 2*mm))

    # ── Tipo ──
    tipo_row = Table(
        [[Paragraph("<b>Tipo:</b>", st_value),
          Paragraph("Inclusao  ( X )", st_value),
          Paragraph("Alteracao ( X )", st_value),
          Paragraph("Exclusao  ( X )", st_value)]],
        colWidths=[20*mm, (content_w - 20*mm)/3, (content_w - 20*mm)/3, (content_w - 20*mm)/3],
    )
    tipo_row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("BOX", (0, 0), (-1, -1), 0.3, c_line),
    ]))
    story.append(tipo_row)
    story.append(Spacer(1, 2*mm))

    # ── Tabela de rateio ──
    header = ["Nº", "Codigo da UC", "CPF/CNPJ", "Rateio (%)"]
    data = [header]
    total_pct = 0.0
    for i, (uc, cli) in enumerate(vinculados, 1):
        pct = cli.get("rateio_pct", 0) or 0
        total_pct += pct
        data.append([
            str(i),
            _uc_so_digitos(cli.get("uc_display", uc)),
            _safe_pdf_str(cpf_tit),
            f"{pct:.2f}%",
        ])
    data.append(["", "", "TOTAL", f"{total_pct:.2f}%"])

    col_rt = [14*mm, (content_w - 14*mm - 38*mm - 32*mm), 38*mm, 32*mm]
    tbl_rt = Table(data, colWidths=col_rt, repeatRows=1)
    ts = TableStyle([
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), c_header),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("ALIGN", (2, 0), (2, 0), "CENTER"),
        ("ALIGN", (3, 0), (3, 0), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, 0), 3),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
        # Body
        ("FONTNAME", (0, 1), (-1, -2), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -2), 8.5),
        ("ALIGN", (0, 1), (0, -2), "CENTER"),
        ("ALIGN", (1, 1), (1, -2), "CENTER"),
        ("ALIGN", (2, 1), (2, -2), "CENTER"),
        ("ALIGN", (3, 1), (3, -2), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, c_line),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 1), (-1, -2), 2),
        ("BOTTOMPADDING", (0, 1), (-1, -2), 2),
        # Total row
        ("BACKGROUND", (0, -1), (-1, -1), c_total),
        ("FONTNAME", (2, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (2, -1), (-1, -1), 9),
        ("ALIGN", (2, -1), (2, -1), "RIGHT"),
        ("ALIGN", (3, -1), (3, -1), "RIGHT"),
        ("TOPPADDING", (0, -1), (-1, -1), 3),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 3),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, c_dark),
    ])
    # Zebra striping
    for row_idx in range(1, len(data) - 1):
        if row_idx % 2 == 0:
            ts.add("BACKGROUND", (0, row_idx), (-1, row_idx), c_zebra)
    tbl_rt.setStyle(ts)
    story.append(tbl_rt)
    story.append(Spacer(1, 2*mm))

    # ── Assinatura digital (imagem base com data/hora dinamica) ──
    from reportlab.platypus import Image as RLImage

    st_sig_label = ParagraphStyle(
        "siglabel2", parent=styles["Normal"],
        fontName="Helvetica", fontSize=11,
        textColor=c_dark, leading=14,
    )

    sig_img_path = _gerar_assinatura_image_dinamica(uid)
    if sig_img_path:
        # Le dimensoes reais (canvas pode ter sido estendido para caber a fonte)
        try:
            from PIL import Image as PILImage
            _piw, _pih = PILImage.open(sig_img_path).size
        except Exception:
            _piw, _pih = 2320, 480
        sig_img_w = 105 * mm
        sig_img_h = sig_img_w * (_pih / float(_piw))
        sig_image_flow = RLImage(sig_img_path, width=sig_img_w, height=sig_img_h)
    else:
        sig_image_flow = Spacer(1, 18*mm)

    inner_sig = Table(
        [[sig_image_flow]],
        colWidths=[content_w - 25*mm],
    )
    inner_sig.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    label_w = 25*mm

    # Linha superior: bloco da assinatura posicionado acima da linha
    sig_upper = Table(
        [["", inner_sig]],
        colWidths=[label_w, content_w - label_w],
    )
    sig_upper.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    # Linha inferior: rotulo "Titular:" + linha de assinatura
    sig_lower = Table(
        [[Paragraph("Titular:", st_sig_label), ""]],
        colWidths=[label_w, content_w - label_w],
    )
    sig_lower.setStyle(TableStyle([
        ("LINEBELOW", (1, 0), (1, 0), 0.8, c_dark),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    sig_block = [
        Paragraph("TITULAR DA UC OU REPRESENTANTE LEGAL", st_sig),
        Spacer(1, 1*mm),
        sig_upper,
        sig_lower,
    ]
    story.append(KeepTogether(sig_block))

    doc.build(story)

    # ── Anexa documentos do cadastro da usina (se houver) ──
    _doc_campos = ("path_doc_cnh_rg", "path_doc_procuracao", "path_doc_cnh_rg_proc")
    docs_para_anexar = [p for c in _doc_campos
                        if (p := usina.get(c, "")) and os.path.exists(p)]
    # fallback legado
    if not docs_para_anexar:
        _leg_doc = usina.get("documento_titular_pdf", "")
        if _leg_doc and os.path.exists(_leg_doc):
            docs_para_anexar.append(_leg_doc)

    if docs_para_anexar:
        try:
            from pypdf import PdfWriter, PdfReader
            writer = PdfWriter()
            for page in PdfReader(output).pages:
                writer.add_page(page)
            for doc_path in docs_para_anexar:
                ext = os.path.splitext(doc_path)[1].lower()
                if ext == ".pdf":
                    for page in PdfReader(doc_path).pages:
                        writer.add_page(page)
                elif ext in (".jpg", ".jpeg", ".png"):
                    from PIL import Image as _PILImage
                    from reportlab.lib.pagesizes import A4 as _A4
                    from reportlab.lib.units import mm as _mm
                    _img_pdf = doc_path + "_tmp_rateio.pdf"
                    _img = _PILImage.open(doc_path)
                    _w_pt, _h_pt = _A4
                    _margin = 10 * _mm
                    _iw, _ih = _img.size
                    _scale = min((_w_pt - 2*_margin) / _iw, (_h_pt - 2*_margin) / _ih)
                    _nw, _nh = _iw * _scale, _ih * _scale
                    _canvas_img = _PILImage.new("RGB", (int(_w_pt), int(_h_pt)), (255, 255, 255))
                    _canvas_img.paste(_img.convert("RGB"),
                                      (int(_margin + (_w_pt - 2*_margin - _nw)/2),
                                       int(_margin + (_h_pt - 2*_margin - _nh)/2)))
                    _canvas_img = _canvas_img.resize((int(_w_pt), int(_h_pt)))
                    _canvas_img.save(_img_pdf, "PDF", resolution=150)
                    for page in PdfReader(_img_pdf).pages:
                        writer.add_page(page)
                    os.remove(_img_pdf)
            merged = output.replace(".pdf", "_merged.pdf")
            with open(merged, "wb") as f_out:
                writer.write(f_out)
            os.replace(merged, output)
            print(f"[OK] {len(docs_para_anexar)} documento(s) anexado(s) ao PDF")
        except Exception as e:
            print(f"[ERRO] Ao anexar documentos: {e}")

    return output

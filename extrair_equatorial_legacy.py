"""
CONTALEV — Extrator de Fatura Equatorial Goias
═══════════════════════════════════════════════════════════════
Compativel com layout 2025/2026 (2 paginas)
REN 1095/24 ANEEL: UC padronizada (10–16 digitos)
Lei 14.300/21: PARC INJET S/DESC extraida e mapeada

Campos retornados:
  uc, mes_referencia, consumo_kwh, tarifa_scee,
  compensado_kwh, nao_comp_kwh,
  pct_parc_injet, tarifa_nao_comp, valor_parc_injet,
  iluminacao_publica, bandeira_amarela, bandeira_vermelha,
  multa, juros, total_fatura, vencimento,
  data_leitura_anterior, data_leitura_atual, n_dias, proxima_leitura,
  leitura_anterior, leitura_atual, constante,
  tipo_fornecimento, nome, cpf, endereco,
  geracao_ciclo_kwh, saldo_kwh, excedente_recebido_kwh,
  credito_recebido_kwh, saldo_expirar_30d_kwh, saldo_expirar_60d_kwh,
  compensacao_dic
"""

import re
import os

# ── Mapa mes abreviado → numero ──────────────────────────
_MESES = {
    "JAN": "1",  "FEV": "2",  "MAR": "3",  "ABR": "4",
    "MAI": "5",  "JUN": "6",  "JUL": "7",  "AGO": "8",
    "SET": "9",  "OUT": "10", "NOV": "11", "DEZ": "12",
}


def _n(s) -> float:
    """Converte '1.234,56' → 1234.56. Retorna 0.0 se invalido."""
    if not s:
        return 0.0
    try:
        return float(str(s).strip().replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def _ultimo_brl_na_str(s: str) -> float:
    """Retorna o ultimo valor monetario BRL (com virgula) encontrado na string."""
    nums = [n for n in re.findall(r'[\d.,]+', s) if ',' in n]
    return _n(nums[-1]) if nums else 0.0


def _ocr_pagina(caminho_pdf: str, pagina: int = 0) -> str:
    """
    Renderiza uma pagina do PDF como imagem e aplica OCR via winocr
    (OCR nativo do Windows 10/11). Usado como fallback quando as
    bibliotecas de extracao de texto retornam string vazia (PDF baseado
    em imagem, fontes embutidas com encoding nao-padrao, etc.).

    Retorna o texto reconhecido ou string vazia se OCR nao disponivel.
    """
    try:
        import pypdfium2 as pdfium
        from winocr import recognize_pil_sync

        doc = pdfium.PdfDocument(caminho_pdf)
        page = doc[pagina]
        bitmap = page.render(scale=4)  # ~288 DPI
        img = bitmap.to_pil()
        doc.close()

        result = recognize_pil_sync(img, "pt")
        return result["text"] if isinstance(result, dict) else result.text
    except ImportError:
        return ""
    except Exception:
        return ""


def _extrair_texto_pagina1(caminho_pdf: str) -> tuple[str, int]:
    """
    Extrai o texto SOMENTE da pagina 1 do PDF.
    A pagina 2 da Equatorial Goias (a partir de 2025) e puramente
    informativa e nao contem dados de faturamento.

    Ordem de tentativa:
      1. pypdfium2  — ja instalado como dep. do pdfplumber (win-arm64 ok)
      2. pdfplumber — pode falhar no win-arm64 por falta do cryptography
      3. PyMuPDF    — fallback extra se instalado
      4. OCR (winocr) — para PDFs baseados em imagem

    Retorna (texto, total_de_paginas).
    """
    n_pag = 1

    # ── pypdfium2 (ja instalado, funciona no win-arm64) ──
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(caminho_pdf)
        n_pag = len(doc)
        page = doc[0]
        textpage = page.get_textpage()
        texto = textpage.get_text_range()
        doc.close()
        if texto.strip():
            return texto, n_pag
    except ImportError:
        pass
    except Exception:
        pass  # tenta proxima biblioteca

    # ── pdfplumber ───────────────────────────────────────
    try:
        import pdfplumber
        with pdfplumber.open(caminho_pdf) as pdf:
            n_pag = len(pdf.pages)
            texto = pdf.pages[0].extract_text() or ""
            if texto.strip():
                return texto, n_pag
    except ImportError:
        pass
    except Exception:
        pass

    # ── PyMuPDF (fitz) ───────────────────────────────────
    try:
        import fitz
        doc = fitz.open(caminho_pdf)
        n_pag = doc.page_count
        texto = doc[0].get_text()
        if texto.strip():
            return texto, n_pag
    except ImportError:
        pass

    # ── OCR via winocr (fallback para PDFs baseados em imagem) ──
    texto = _ocr_pagina(caminho_pdf, pagina=0)
    if texto.strip():
        return texto, n_pag

    raise ImportError(
        "Nenhuma biblioteca PDF disponivel.\n"
        "O pypdfium2 deveria estar instalado junto com o pdfplumber.\n"
        "Tente: python -m pip install pypdfium2"
    )


def _extrair_texto_completo(caminho_pdf: str) -> str:
    """Extrai texto de TODAS as paginas do PDF.
    Necessario para capturar INFORMACOES DO SCEE (geralmente na pagina 2)."""
    n_pag = 1

    # ── pypdfium2 ──
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(caminho_pdf)
        n_pag = len(doc)
        partes = []
        for i in range(n_pag):
            page = doc[i]
            textpage = page.get_textpage()
            partes.append(textpage.get_text_range())
        doc.close()
        texto = "\n".join(partes)
        if texto.strip():
            return texto
    except ImportError:
        pass
    except Exception:
        pass

    # ── pdfplumber ──
    try:
        import pdfplumber
        with pdfplumber.open(caminho_pdf) as pdf:
            n_pag = len(pdf.pages)
            partes = []
            for page in pdf.pages:
                partes.append(page.extract_text() or "")
            texto = "\n".join(partes)
            if texto.strip():
                return texto
    except ImportError:
        pass
    except Exception:
        pass

    # ── PyMuPDF ──
    try:
        import fitz
        doc = fitz.open(caminho_pdf)
        n_pag = doc.page_count
        partes = [doc[i].get_text() for i in range(n_pag)]
        texto = "\n".join(partes)
        if texto.strip():
            return texto
    except ImportError:
        pass

    # ── OCR via winocr (fallback para PDFs baseados em imagem) ──
    partes = []
    for i in range(n_pag):
        partes.append(_ocr_pagina(caminho_pdf, pagina=i))
    texto = "\n".join(partes)
    if texto.strip():
        return texto

    return ""


# ════════════════════════════════════════════════════════
#  FUNCAO PRINCIPAL
# ════════════════════════════════════════════════════════
def extrair_equatorial(caminho_pdf: str, verbose: bool = False) -> dict:
    """
    Extrai todos os campos da fatura Equatorial Goias.

    Parametros
    ----------
    caminho_pdf : str
        Caminho completo para o arquivo PDF da fatura.

    Retorna
    -------
    dict com os campos extraidos (ver docstring do modulo).

    Raises
    ------
    ValueError  — se o texto da pagina 1 estiver vazio.
    ImportError — se nenhuma biblioteca PDF estiver instalada.
    """
    texto, n_pag = _extrair_texto_pagina1(caminho_pdf)

    # Normaliza quebras de linha (pypdfium2 usa \r\n, pdfplumber usa \n)
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")

    # Texto de todas as paginas — necessario para itens financeiros que
    # transbordam para pagina 2 (ex: muitas linhas de IPCA/MULTA/JUROS)
    # e para a secao MENSAGENS IMPORTANTES com dados SCEE.
    texto_completo = _extrair_texto_completo(caminho_pdf)
    texto_completo = texto_completo.replace("\r\n", "\n").replace("\r", "\n")


    if not texto.strip():
        raise ValueError(
            f"Nao foi possivel extrair texto da pagina 1 de: {caminho_pdf}"
        )

    r: dict = {"_n_paginas": n_pag}

    # ── 1. UC ─────────────────────────────────────────────
    # Formatos reais da Equatorial Goias:
    #   Antigo curto (8 dig):       14912016
    #   Antigo longo (10-16 dig):   10041040692, 000043522501209
    #   Novo c/ pontos (13 dig):    4.044.065.012-41, 00003.605.133.012-74
    #   Novo c/ pontos (11 dig):    310.639.012-73 (CPF-like)
    # A UC pode vir com zeros variaveis a esquerda (00, 000, 0000, 00000).
    # Usa \d{1,6} no inicio da parte formatada para tolerar qualquer padding.
    _UC_DIGITOS      = r'(\d{8,16})'
    _UC_FORMATADA_13 = r'(\d{1,6}(?:\.\d{3}){3}-\d{2})'   # 13 dig, 3 grupos: inequivocamente UC (nunca CPF)
    _UC_FORMATADA    = r'(\d{1,6}(?:\.\d{3}){2,3}-\d{2})' # 11 ou 13 digitos
    _UC_QUALQUER     = r'(\d{8,16}|\d{1,6}(?:\.\d{3}){2,3}-\d{2})'
    # Inclui 1 grupo de pontos (UC sem zeros iniciais: ex 910.012-12 de 0000.000.910.012-12)
    _UC_QUALQUER_AMPLO = r'(\d{8,16}|\d{1,6}(?:\.\d{3}){1,3}-\d{2})'
    _MES_PATTERN     = r'(?:JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)/\d{4}'

    # PRIORIDADE 0: UC explicitamente rotulada como "UNIDADE CONSUMIDORA".
    # Usa padrao amplo: label e inequivoco, entao aceita ate 1 grupo de pontos.
    uc_m = re.search(
        r'UNIDADE\s+CONSUMIDORA\s*:?\s*' + _UC_QUALQUER_AMPLO,
        texto, re.IGNORECASE
    )

    # PRIORIDADE 1: UC formatada de 13 digitos (3 grupos) em qualquer lugar.
    # Sem ambiguidade — nao e CPF (2 grupos) nem Nota Fiscal (13 dig puros).
    # Resolve o caso Juliano (UC na linha "PERDAS DE TRANSFORMACAO").
    if not uc_m:
        uc_m = re.search(_UC_FORMATADA_13, texto)

    # PRIORIDADE 1b: UC formatada com 2 grupos (11 digitos, padrao XXX.XXX.XXX-XX).
    # Visualmente identica ao CPF, mas fora do campo "CNPJ/CPF:" e inequivocamente UC.
    # Exemplo: "698.066.012-99" — sem zeros iniciais, apenas 2 grupos de 3 digitos.
    # Evita capturar o CPF do cliente verificando o contexto anterior (30 chars).
    if not uc_m:
        for _m in re.finditer(r'(?<!\d)(\d{1,4}\.\d{3}\.\d{3}-\d{2})', texto):
            _antes = texto[max(0, _m.start() - 30):_m.start()]
            if not re.search(r'CNPJ/CPF\s*:', _antes, re.IGNORECASE):
                uc_m = _m
                break

    # PRIORIDADE 1c: UC formatada com 1 grupo de pontos (ex: 910.012-12).
    # Ocorre quando grupos iniciais de zeros sao omitidos na impressao da fatura.
    # CPF tem formato XXX.XXX.XXX-XX (2 pontos), nao conflita com 1 ponto.
    # Verifica contexto para evitar capturar fragmento de CEP ou outros numeros.
    if not uc_m:
        for _m in re.finditer(r'(?<!\d)(\d{1,6}\.\d{3}-\d{2})(?!\d)', texto):
            _antes = texto[max(0, _m.start() - 50):_m.start()]
            if not re.search(r'CNPJ|CPF|CEP', _antes, re.IGNORECASE):
                uc_m = _m
                break

    # PRIORIDADE 2: UC adjacente ao padrao MES/ANO (contexto forte).
    # Resolve o caso Maria de Fatima: "14912016 MAR/2026" e "MAR/2026\n14912016"
    # (formato 8 digitos, extraido por pypdfium2).
    if not uc_m:
        uc_m = re.search(
            r'(?<!\d)' + _UC_QUALQUER + r'\s+' + _MES_PATTERN,
            texto, re.IGNORECASE
        )
    if not uc_m:
        uc_m = re.search(
            _MES_PATTERN + r'\s*\n\s*' + _UC_QUALQUER + r'\b',
            texto, re.IGNORECASE
        )
    if not uc_m:
        # Fallback: UC apos "PERDAS DE TRANSFORMACAO / RAMAL:" (layout nova Nota Fiscal)
        uc_m = re.search(
            r'PERDAS\s+DE\s+TRANSFORMA\S*\s*/\s*RAMAL[^\n]*?\s' + _UC_FORMATADA,
            texto, re.IGNORECASE
        )
    if not uc_m:
        # Fallback: UC no final da linha do CEP
        uc_m = re.search(r'GOIANIA GO BRASIL\s+' + _UC_QUALQUER, texto, re.IGNORECASE)
    if not uc_m:
        # Fallback amplo: qualquer cidade/estado + UC formatada
        uc_m = re.search(r'BRASIL\s+' + _UC_QUALQUER, texto, re.IGNORECASE)
    if not uc_m:
        # OCR fallback: "Unidade Consumidora 10788141"
        uc_m = re.search(r'Unidade Consumidora\s+(\d{7,16})', texto, re.IGNORECASE)
    r["uc"] = uc_m.group(1).strip() if uc_m else ""

    # ── 2. Referencia (mes/ano) → formato "MM/AAAA" ──────
    ref_m = re.search(
        r'\b(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)/(\d{4})\b',
        texto, re.IGNORECASE
    )
    if ref_m:
        r["mes_referencia"] = f"{_MESES[ref_m.group(1).upper()]}/{ref_m.group(2)}"
    else:
        r["mes_referencia"] = ""

    # ── OCR: extrair linha "Valor (R$)" com 5 valores ──────
    # Em texto OCR, a tabela de itens e linearizada por coluna.
    # A linha "Valor (R$) 113,58 25,58 0,04 2,25 141,45" contem
    # [consumo_valor, iluminacao, juros, multa, total] nessa ordem.
    # Usada como fallback quando padroes in-line nao casam.
    _ocr_valores = None
    _ocr_val_m = re.search(
        r'Valor\s*\(R\$\)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)',
        texto, re.IGNORECASE
    )
    if _ocr_val_m:
        _ocr_valores = {
            "consumo_valor": _n(_ocr_val_m.group(1)),
            "iluminacao":    _n(_ocr_val_m.group(2)),
            "juros":         _n(_ocr_val_m.group(3)),
            "multa":         _n(_ocr_val_m.group(4)),
            "total":         _n(_ocr_val_m.group(5)),
        }

    # ── 3. Consumo NAO COMPENSADO (kWh e tarifa convencional) ─
    # Linha: "CONSUMO NAO COMPENSADO kWh 14,69 1,125925 16,54 ..."
    # Aparece quando parte do consumo nao e coberta por creditos GD.
    # A tarifa nesta linha e a tarifa convencional (TUSD+TE) completa.
    nao_comp_m = re.search(
        r'CONSUMO\s+N[AA\xc3]O\s+COMPENSADO\s+kWh\s+([\d.,]+)\s+([\d.,]+)',
        texto, re.IGNORECASE
    )
    r["consumo_nao_comp_kwh"] = _n(nao_comp_m.group(1)) if nao_comp_m else 0.0
    r["tarifa_convencional"]  = _n(nao_comp_m.group(2)) if nao_comp_m else 0.0

    # OCR fallback: consumo e tarifa em linhas separadas
    if r["consumo_nao_comp_kwh"] == 0 and re.search(
        r'CONSUMO\s+N[AAAA]O\s+COMPENSADO', texto, re.IGNORECASE
    ):
        # kWh na coluna "Quant."
        quant_m = re.search(r'Quant\.?\s+([\d.,]+)', texto, re.IGNORECASE)
        if quant_m:
            r["consumo_nao_comp_kwh"] = _n(quant_m.group(1))
        # Tarifa na coluna "Preco unit (R$) com tributos"
        tarifa_m = re.search(
            r'Pre[cc]o\s+unit.*?com\s+tributos\s+([\d.,]+)',
            texto, re.IGNORECASE
        )
        if tarifa_m:
            r["tarifa_convencional"] = _n(tarifa_m.group(1))

    # ── 3b. Consumo SCEE (kWh e tarifa) ──────────────────
    # Linha: "CONSUMO SCEE kWh 417,00 0,780764 325,58 ..."
    consumo_m = re.search(
        r'CONSUMO\s+SCEE\s+kWh\s+([\d.,]+)\s+([\d.,]+)',
        texto, re.IGNORECASE
    )
    consumo_scee_kwh = _n(consumo_m.group(1)) if consumo_m else 0.0
    r["tarifa_scee"]  = _n(consumo_m.group(2)) if consumo_m else 0.0
    # Consumo total = SCEE + nao compensado
    r["consumo_kwh"] = consumo_scee_kwh + r["consumo_nao_comp_kwh"]

    # ── 3c. Consumo convencional (fatura sem GD/solar) ───
    # Formatos conhecidos:
    #   "CONSUMO kWh 482,00 1,135823 ..."      → tipo=kWh, unidade=kWh (uma unica vez)
    #   "CONSUMO kWh kWh 369,00 1,125925 ..."  → tipo=kWh, unidade=kWh (duplicado — novo layout)
    # Aparece em faturas residenciais convencionais (sem creditos GD).
    # So usa se consumo_kwh ainda e 0 (nao sobrescreve GD).
    if r["consumo_kwh"] == 0:
        consumo_conv_m = re.search(
            r'(?<!\S)CONSUMO\s+kWh\s+(?:kWh\s+)?([\d.,]+)\s+([\d.,]+)',
            texto, re.IGNORECASE
        )
        if consumo_conv_m:
            r["consumo_kwh"] = _n(consumo_conv_m.group(1))
            r["consumo_nao_comp_kwh"] = r["consumo_kwh"]
            r["tarifa_convencional"] = _n(consumo_conv_m.group(2))

    # ── 4. Injecoes SCEE (kWh compensado) ────────────────
    # Podem existir varias linhas de injecao simultaneamente (multiplas usinas):
    #   "INJECAO SCEE - UC 000395795301259 - GD I  kWh   4,93"
    #   "INJECAO SCEE - UC 000428444201202 - GD II 2 kWh 593,04"
    # Ambas devem ser somadas — os dois findall rodam sempre (nao sao mutuamente exclusivos).
    # Encoding pypdfium2: INJE\xc3\x87\xc3\x83O, pdfplumber: INJECAO
    inj_gd2 = re.findall(
        r'INJE.{1,4}O\s+SCEE\s*-\s*UC\s+[\d.\-]+\s*-\s*GD\s+II\s+2\s+kWh\s+([\d.,]+)',
        texto, re.IGNORECASE
    )
    # GD I: cliente com usina geradora (sem "UC xxxx - ") OU com UC mas GD I
    inj_gd1 = re.findall(
        r'INJE.{1,4}O\s+SCEE\s*-\s*(?:UC\s+[\d.\-]+\s*-\s*)?GD\s+I\b[^\n]*kWh\s+([\d.,]+)',
        texto, re.IGNORECASE
    )
    comp_total = sum(_n(v) for v in inj_gd2) + sum(_n(v) for v in inj_gd1)
    r["compensado_kwh"] = comp_total
    r["nao_comp_kwh"]   = max(0.0, r["consumo_kwh"] - comp_total)

    # ── 4b. DIFCI (Diferenca de Consumo Isento) ───────────
    # DIFCI = valor CONSUMO SCEE - valor INJECAO SCEE
    # = consumo_scee_kwh × tarifa_scee - Σ(inj_kwh × tarifa_inj)
    # Captura (kwh, tarifa) de cada linha de injecao para calcular o valor monetario.
    inj_gd2_tf = re.findall(
        r'INJE.{1,4}O\s+SCEE\s*-\s*UC\s+[\d.\-]+\s*-\s*GD\s+II\s+2\s+kWh\s+([\d.,]+)\s+([\d.,]+)',
        texto, re.IGNORECASE
    )
    inj_gd1_tf = re.findall(
        r'INJE.{1,4}O\s+SCEE\s*-\s*(?:UC\s+[\d.\-]+\s*-\s*)?GD\s+I\b[^\n]*kWh\s+([\d.,]+)\s+([\d.,]+)',
        texto, re.IGNORECASE
    )
    consumo_scee_valor = consumo_scee_kwh * r["tarifa_scee"]
    injecao_scee_valor = (sum(_n(v[0]) * _n(v[1]) for v in inj_gd2_tf) +
                          sum(_n(v[0]) * _n(v[1]) for v in inj_gd1_tf))
    r["difci"] = round(max(0.0, consumo_scee_valor - injecao_scee_valor), 2)

    # ── 4c. ECNISENTA (Energia Compensada Nao Isenta de tributos) ──
    # Linha: "ENERGIA COMP NAO ISENTA (TRIBUTOS) - UC xxxx  2,94  2,94"
    # Pode haver mais de uma linha (multiplas usinas) — soma tudo.
    ecni_linhas = re.findall(r'ENERGIA\s+COMP\s+N.{1,4}O\s+ISENTA[^\n]+', texto_completo, re.IGNORECASE)
    r["ecnisenta"] = round(sum(_ultimo_brl_na_str(l) for l in ecni_linhas), 2)
    if r["ecnisenta"] == 0.0:
        # Fatura com quebra de linha apos rotulo: valor cai na linha seguinte
        # Ex: "ENERGIA COMP NAO ISENTA...\n000396876901252 2,94"
        ecni_next = re.findall(
            r'ENERGIA\s+COMP\s+N.{1,4}O\s+ISENTA[^\n]*\n\S+\s+([\d.,]+)',
            texto_completo, re.IGNORECASE)
        r["ecnisenta"] = round(sum(_n(v) for v in ecni_next), 2)

    # ── 5. PARC INJET S/DESC (Lei 14.300/21) ─────────────
    # Percentual nao descontado
    pct_m = re.search(
        r'PARC\s+INJET\s+S/DESC\s*-\s*([\d.,]+)%',
        texto, re.IGNORECASE
    )
    r["pct_parc_injet"] = _n(pct_m.group(1)) if pct_m else 0.0

    # Linhas de detalhe: "II 2 kWh <kwh> <tarifa> <valor>" ou "GD II 2 kWh ..."
    # (continuacao das linhas PARC INJET que sao quebradas no PDF)
    parc_linhas = re.findall(
        r'^(?:GD\s+)?II 2\s+kWh\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)',
        texto, re.MULTILINE
    )
    r["tarifa_nao_comp"]  = _n(parc_linhas[0][1]) if parc_linhas else 0.0
    r["valor_parc_injet"] = sum(_n(p[2]) for p in parc_linhas)

    # ── 6. Iluminacao publica ─────────────────────────────
    ilum_m = re.search(
        r'CONTRIB\.?\s*ILUM\.?\s*P.{0,3}BLICA[^\d\n]+([\d.,]+)',
        texto, re.IGNORECASE
    )
    # Fallback: "ILUM ... MUNICIPAL valor" (cobre variacao de encoding do U-agudo)
    if not ilum_m:
        ilum_m = re.search(
            r'ILUM[^\n]{0,30}MUNICIPAL[^\d\n]*([\d.,]+)',
            texto, re.IGNORECASE
        )
    ilum_val = _n(ilum_m.group(1)) if ilum_m else 0.0
    # OCR fallback: em texto OCR, o padrao [^\d\n] pode casar valor errado
    # (ex: captura "100,00" do Quant. ao inves de "25,58" da iluminacao).
    # Usa a linha "Valor (R$)" estruturada quando disponivel.
    if _ocr_valores and (ilum_val == 0 or ilum_val == r.get("consumo_nao_comp_kwh", 0)):
        ilum_val = _ocr_valores["iluminacao"]
    r["iluminacao_publica"] = ilum_val

    # ── 7. Bandeiras ──────────────────────────────────────
    # Captura de TARIFA (R$/kWh) — primeira ocorrencia "BANDEIRA AMARELA"
    # geralmente aparece numa tabela de tarifas
    ba_m = re.search(r'BANDEIRA\s+AMARELA[^\d\n]+([\d.,]+)', texto, re.IGNORECASE)
    bv_m = re.search(r'BANDEIRA\s+VERMELHA[^\d\n]+([\d.,]+)', texto, re.IGNORECASE)
    r["bandeira_amarela"]  = _n(ba_m.group(1)) if ba_m else 0.0
    r["bandeira_vermelha"] = _n(bv_m.group(1)) if bv_m else 0.0

    # Captura do VALOR efetivamente cobrado pela Equatorial:
    # "ADC BANDEIRA AMARELA" ou "ADC BANDEIRA VERMELHA" — linha de cobranca
    # que aparece quando a ANEEL aciona a bandeira no mes.
    # Linha tipica: "ADC BANDEIRA AMARELA kWh 30,00 0,003965 0,12 0 0,12 ..."
    # Colunas: Descricao | Unid | Quant | Tarifa | Valor(R$) | BC | Valor | %ICMS | ICMS | Tar.trib
    # O 3o numero da linha eh o Valor(R$) que queremos.
    def _extrair_adc(linha_regex: str, texto: str) -> float:
        m = re.search(linha_regex + r'[^\n]*', texto, re.IGNORECASE)
        if not m:
            return 0.0
        # Pega todos os tokens numericos (com ou sem decimal) da linha
        nums = re.findall(r'\d+[.,]?\d*', m.group(0))
        # Posicao 2 (3o numero) = Valor (R$) na maioria dos PDFs Equatorial
        if len(nums) >= 3:
            return _n(nums[2])
        return 0.0

    r["adc_bandeira_amarela"]  = _extrair_adc(r'ADC\s+BANDEIRA\s+AMARELA',  texto)
    r["adc_bandeira_vermelha"] = _extrair_adc(r'ADC\s+BANDEIRA\s+VERMELHA', texto)

    # ── 8. Multa, Juros e Correcao IPCA ──────────────────
    # Cada item pode aparecer em MULTIPLAS linhas (ex: juros de meses distintos).
    # Solucao: findall em todas as linhas, pega o ULTIMO numero BRL de cada uma e soma.
    # Linha tipica: "JUROS MORATORIA. 131,00 15,82"  → queremos 15,82 (ultimo)
    # Linha IPCA:   "VALOR CORRECAO IPCA. 70,00 1,32" → queremos 1,32
    if _ocr_valores:
        # Em texto OCR a linha "Valor (R$)" e mais confiavel — nao tem IPCA separado.
        r["multa"] = _ocr_valores["multa"]
        r["juros"] = _ocr_valores["juros"]
        r["correcao_ipca"] = 0.0
    else:
        # findall: captura TODAS as linhas de cada tipo e soma os valores.
        # Negativo lookahead em MULTA: ignora "MULTA (+) OUTROS ACRESCIMOS" (cabecalho boleto).
        multa_linhas = re.findall(r'\bMULTA\b(?!\s*\(\+\))[^\n]+', texto_completo, re.IGNORECASE)
        juros_linhas = re.findall(r'\bJUROS\b[^\n]+', texto_completo, re.IGNORECASE)
        ipca_linhas  = re.findall(r'VALOR\s+CORRE.{1,4}O\s+IPCA[^\n]+', texto_completo, re.IGNORECASE)

        multa_val = sum(_ultimo_brl_na_str(l) for l in multa_linhas)
        juros_val = sum(_ultimo_brl_na_str(l) for l in juros_linhas)
        ipca_val  = sum(_ultimo_brl_na_str(l) for l in ipca_linhas)

        # Sanidade: valores acima de 9999 indicam captura errada (ex: codigo PIX)
        r["multa"]         = round(multa_val, 2) if multa_val <= 9999 else 0.0
        r["juros"]         = round(juros_val, 2) if juros_val <= 9999 else 0.0
        r["correcao_ipca"] = round(ipca_val,  2) if ipca_val  <= 9999 else 0.0

    # ── 8b. Compensacao DIC Mensal ───────────────────────
    # Linha: "COMPENSACAO DE DIC MENSAL -637,82"
    # Valor negativo = credito ao cliente (reduz o total a pagar).
    # ATENCAO: PDFs da Equatorial chegam com encoding garbled — C e A viram
    # � (replacement char). Os regex usam .{1,4} para cobrir qualquer variante:
    #   COMPENSACAO → COMPENSA.{1,4}O (normal)
    #   COMPENSA��O → coberto pelo mesmo padrao
    #   COMPENSACAO → tambem coberto
    dic_m = re.search(
        r'COMPENSA.{1,4}O\s+DE\s+DIC\s+MENSAL\s+(-?[\d.,]+)',
        texto, re.IGNORECASE
    )
    if not dic_m:
        dic_m = re.search(
            r'COMPENSA.{1,4}O\s+DIC[^\d\n]*(-?[\d.,]+)',
            texto, re.IGNORECASE
        )
    r["compensacao_dic"] = _n(dic_m.group(1)) if dic_m else 0.0
    # Garante negativo (credito): se o PDF trouxer positivo por engano, converte
    if r["compensacao_dic"] > 0:
        r["compensacao_dic"] = -r["compensacao_dic"]

    # ── 9. Total a pagar ──────────────────────────────────
    # "MAR/2026 R$**********98,60 16/04/2026"
    total_m = re.search(r'R\$\*+([\d.,]+)', texto)
    if not total_m:
        # Fallback: "TOTAL 98,60 0,00 0,00 0,00"
        total_m = re.search(r'\bTOTAL\b\s+([\d.,]+)\s+0,00', texto, re.IGNORECASE)
    if not total_m:
        # OCR fallback: "Total a pagar R$ 141,45"
        total_m = re.search(r'Total a pagar\s+R\$\s*([\d.,]+)', texto, re.IGNORECASE)
    if not total_m:
        # OCR fallback: "VALOR DOCUMENTO 141,45"
        total_m = re.search(r'VALOR DOCUMENTO\s+([\d.,]+)', texto, re.IGNORECASE)
    r["total_fatura"] = _n(total_m.group(1)) if total_m else 0.0
    # Validacao cruzada com linha "Valor (R$)" do OCR
    if r["total_fatura"] == 0 and _ocr_valores:
        r["total_fatura"] = _ocr_valores["total"]

    # ── 10. Vencimento ────────────────────────────────────
    # Data imediatamente apos "R$**98,60"
    venc_m = re.search(r'R\$\*+[\d.,]+\s+(\d{2}/\d{2}/\d{4})', texto)
    if not venc_m:
        venc_m = re.search(r'PAGAVEL EM QUALQUER BANCO\s+(\d{2}/\d{2}/\d{4})', texto, re.IGNORECASE)
    if not venc_m:
        # OCR fallback: "Vencimento 01/04/2026"
        venc_m = re.search(r'Vencimento\s+(\d{2}/\d{2}/\d{4})', texto, re.IGNORECASE)
    if not venc_m:
        # OCR fallback: "VENCIMENTO 01/04/2026"
        venc_m = re.search(r'VENCIMENTO\s+(\d{2}/\d{2}/\d{4})', texto, re.IGNORECASE)
    r["vencimento"] = venc_m.group(1) if venc_m else ""

    # ── 11. Datas de leitura ──────────────────────────────
    # pdfplumber: tudo na mesma linha "27/02/2026 30/03/2026 31 29/04/2026"
    # pypdfium2:  datas em uma linha, n_dias+proxima em outra ("31 29/04/2026")
    leit_m = re.search(
        r'(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(\d{1,3})\s+(\d{2}/\d{2}/\d{4})',
        texto
    )
    if leit_m:
        r["data_leitura_anterior"] = leit_m.group(1)
        r["data_leitura_atual"]    = leit_m.group(2)
        r["n_dias"]                = int(leit_m.group(3))
        r["proxima_leitura"]       = leit_m.group(4)
    else:
        # pypdfium2: datas separadas do n_dias/proxima
        datas_m = re.search(r'(\d{2}/\d{2}/\d{4})[ \t]+(\d{2}/\d{2}/\d{4})', texto)
        dias_m  = re.search(r'\b(2\d|3\d|4[0-5])\s+(\d{2}/\d{2}/\d{4})', texto)
        r["data_leitura_anterior"] = datas_m.group(1) if datas_m else ""
        r["data_leitura_atual"]    = datas_m.group(2) if datas_m else ""
        r["n_dias"]                = int(dias_m.group(1)) if dias_m else 0
        r["proxima_leitura"]       = dias_m.group(2) if dias_m else ""

    # OCR fallback: "Leitura Anterior 11/02/2026", "Leitura Atual 12/03/2026", etc.
    if not r["data_leitura_anterior"]:
        la_m = re.search(r'Leitura Anterior\s+(\d{2}/\d{2}/\d{4})', texto, re.IGNORECASE)
        if la_m:
            r["data_leitura_anterior"] = la_m.group(1)
    if not r["data_leitura_atual"]:
        lat_m = re.search(r'Leitura Atual\s+(\d{2}/\d{2}/\d{4})', texto, re.IGNORECASE)
        if lat_m:
            r["data_leitura_atual"] = lat_m.group(1)
    if r["n_dias"] == 0:
        nd_m = re.search(r'N.?\s*de Dias\s+(\d+)', texto, re.IGNORECASE)
        if nd_m:
            r["n_dias"] = int(nd_m.group(1))
    if not r["proxima_leitura"]:
        pl_m = re.search(r'Pr[oo]xima Leitura\s+(\d{2}/\d{2}/\d{4})', texto, re.IGNORECASE)
        if pl_m:
            r["proxima_leitura"] = pl_m.group(1)

    # ── 12. Leituras do medidor ───────────────────────────
    # "ENERGIA ATIVA - KWH UNICO 02079 02496 1,000000 417"
    med_m = re.search(
        r'ENERGIA ATIVA.*?[UU]NICO\s+(\d+)\s+(\d+)\s+([\d.,]+)',
        texto, re.IGNORECASE
    )
    if med_m:
        r["leitura_anterior"] = med_m.group(1)
        r["leitura_atual"]    = med_m.group(2)
        r["constante"]        = _n(med_m.group(3))
    else:
        # OCR fallback: "Leitura Anterior 000006 022200" (ativa + geracao na mesma linha)
        med_ocr = re.search(
            r'Leitura Anterior\s+(\d{4,})\s+\d{4,}.*?Leitura Atual\s+(\d{4,})',
            texto, re.IGNORECASE | re.DOTALL
        )
        if not med_ocr:
            # Tentativa simplificada: numeros apos "Leitura Anterior" e "Leitura Atual"
            la_nums = re.search(r'Leitura Anterior\s+(\d{4,})', texto, re.IGNORECASE)
            lu_nums = re.search(r'Leitura Atual\s+(\d{4,})', texto, re.IGNORECASE)
            if la_nums and lu_nums:
                r["leitura_anterior"] = la_nums.group(1)
                r["leitura_atual"]    = lu_nums.group(1)
                r["constante"]        = 1.0
            else:
                r["leitura_anterior"] = ""
                r["leitura_atual"]    = ""
                r["constante"]        = 1.0
        else:
            r["leitura_anterior"] = med_ocr.group(1)
            r["leitura_atual"]    = med_ocr.group(2)
            r["constante"]        = 1.0

    # ── 13. Tipo de fornecimento ──────────────────────────
    tf_m = re.search(r'Tipo de fornecimento:\s*(\S+)', texto, re.IGNORECASE)
    r["tipo_fornecimento"] = tf_m.group(1).strip() if tf_m else ""

    # ── 14. Nome ──────────────────────────────────────────
    # Linha imediatamente antes do primeiro "CNPJ/CPF:"
    nome_m = re.search(
        r'\n([A-ZAEIOUAEIOUAOC][A-ZAEIOUAEIOUAOC ]+)\nCNPJ/CPF:',
        texto
    )
    if not nome_m:
        # OCR fallback: nome na mesma linha que CNPJ/CPF (sem newlines)
        nome_m = re.search(
            r'([A-ZAEIOUAEIOUAOC][A-ZAEIOUAEIOUAOC ]{5,}?)\s+CNPJ/CPF:',
            texto
        )
    r["nome"] = nome_m.group(1).strip() if nome_m else ""
    # Limpar prefixos de ruido OCR (ex: "V DANILO" → "DANILO")
    if r["nome"] and len(r["nome"]) > 2:
        r["nome"] = re.sub(r'^[A-Z]\s+', '', r["nome"])

    # ── 15. CPF / CNPJ ────────────────────────────────────
    cpf_m = re.search(r'CNPJ/CPF:\s*([\d./-]+)', texto)
    r["cpf"] = cpf_m.group(1).strip() if cpf_m else ""

    # ── 16. Endereco ──────────────────────────────────────
    # Linhas entre o CPF e o campo CEP (primeira ocorrencia)
    end_m = re.search(
        r'CNPJ/CPF:.*?\n(.*?)(?=CEP:|PERDAS)',
        texto, re.DOTALL
    )
    if end_m:
        palavras_ruido = {"NOTA FISCAL", "SERIE", "DATA DE EMISSAO"}
        linhas = []
        for ln in end_m.group(1).splitlines():
            ln = ln.strip()
            if ln and not any(rn in ln for rn in palavras_ruido):
                linhas.append(ln)
        r["endereco"] = " ".join(linhas)
    else:
        r["endereco"] = ""

    # OCR fallback: texto entre CPF e CEP na mesma linha
    if not r["endereco"]:
        end_ocr = re.search(
            r'CNPJ/CPF:\s*[\d./-]+\s+(.*?)CEP:',
            texto, re.DOTALL
        )
        if end_ocr:
            palavras_ruido = {"NOTA FISCAL", "SERIE", "DATA DE EMISSAO"}
            linhas = []
            for ln in end_ocr.group(1).splitlines():
                ln = ln.strip()
                if ln and not any(rn in ln for rn in palavras_ruido):
                    linhas.append(ln)
            r["endereco"] = " ".join(linhas)

    # ── 17. INFORMACOES DO SCEE (geracao, saldo, excedente) ─
    # Essa secao fica nas MENSAGENS IMPORTANTES, frequentemente na pagina 2.
    # Padrao: GERACAO CICLO (3/2026) KWH: UC 10040601542 : 13.777,00
    # (texto_completo ja extraido no inicio da funcao)

    # Geracao do ciclo
    # Texto real: "GERACAO CICLO (3/2026) KWH: UC 10040601542 : 13.777,00,"
    # Novo formato: "GERACAO CICLO (3/2026) KWH: UC 4.044.065.012-41 : 13.777,00,"
    # O padrao termina em \d para nao capturar a virgula separadora
    # UC pode ser digitos puros ou formatada com pontos/hifen
    # GERA.{1,4}O cobre: GERACAO, GERA\xc3\x87AO, GERAÇÃO (pypdfium2 → fitz fallbacks)
    _UC_SCEE = r'UC\s+[\d.\-]+\s*:'
    ger_ciclo_m = re.search(
        r'GERA.{1,4}O\s+CICLO\s*\([^)]*\)\s*KWH\s*:\s*' + _UC_SCEE + r'\s*([\d.,]+\d)',
        texto_completo, re.IGNORECASE
    )
    r["geracao_ciclo_kwh"] = _n(ger_ciclo_m.group(1)) if ger_ciclo_m else 0.0

    # Excedente recebido
    exc_m = re.search(
        r'EXCEDENTE\s+RECEBIDO\s+KWH\s*:\s*' + _UC_SCEE + r'\s*([\d.,]+\d)',
        texto_completo, re.IGNORECASE
    )
    r["excedente_recebido_kwh"] = _n(exc_m.group(1)) if exc_m else 0.0

    # Credito recebido
    cred_m = re.search(
        r'CR[EE]DITO\s+RECEBIDO\s+KWH\s+([\d.,]+\d)',
        texto_completo, re.IGNORECASE
    )
    r["credito_recebido_kwh"] = _n(cred_m.group(1)) if cred_m else 0.0

    # Saldo (cuidado: nao pegar "SALDO A EXPIRAR")
    saldo_m = re.search(
        r'(?<!EXPIRAR\s)SALDO\s+KWH\s*:\s*([\d.,]+\d)',
        texto_completo, re.IGNORECASE
    )
    r["saldo_kwh"] = _n(saldo_m.group(1)) if saldo_m else 0.0

    # Saldo a expirar 30 dias
    saldo30_m = re.search(
        r'SALDO\s+A\s+EXPIRAR\s+EM\s+30\s+DIAS\s+KWH\s*:\s*([\d.,]+\d)',
        texto_completo, re.IGNORECASE
    )
    r["saldo_expirar_30d_kwh"] = _n(saldo30_m.group(1)) if saldo30_m else 0.0

    # Saldo a expirar 60 dias
    saldo60_m = re.search(
        r'SALDO\s+A\s+EXPIRAR\s+EM\s+60\s+DIAS\s+KWH\s*:\s*([\d.,]+\d)',
        texto_completo, re.IGNORECASE
    )
    r["saldo_expirar_60d_kwh"] = _n(saldo60_m.group(1)) if saldo60_m else 0.0

    # ── Fallback compensado_kwh por credito_recebido_kwh ─
    # Se nenhuma injecao foi detectada pelos regex acima mas o campo
    # CREDITO RECEBIDO KWH existe na secao SCEE, usa ele como compensado.
    # Garante que nao_comp_kwh = consumo_nao_comp_kwh quando disponivel.
    if r["compensado_kwh"] == 0 and r.get("credito_recebido_kwh", 0) > 0:
        r["compensado_kwh"] = r["credito_recebido_kwh"]
        r["nao_comp_kwh"]   = max(0.0, r["consumo_kwh"] - r["compensado_kwh"])
    # Se consumo_nao_comp_kwh foi explicitamente extraido do PDF e e consistente,
    # usa ele para confirmar nao_comp_kwh (linha "CONSUMO NAO COMPENSADO kWh xxx")
    if r["consumo_nao_comp_kwh"] > 0:
        r["nao_comp_kwh"] = r["consumo_nao_comp_kwh"]

    # ── Aliases de retrocompatibilidade com app.py ───────
    # Mantem os nomes antigos para nao quebrar o restante do sistema
    r["unidade_consumidora"] = r["uc"]           # antigo: "unidade_consumidora"
    # tarifa_sem: usa SCEE quando disponivel; fallback = tarifa convencional
    # (clientes sem GD tem tarifa_scee=0 mas tarifa_convencional extraida do PDF)
    r["tarifa_sem"]          = r["tarifa_scee"] or r.get("tarifa_convencional", 0)
    r["nome_cliente"]        = r["nome"]         # antigo: "nome_cliente"
    r["consumo_compensado"]  = r["compensado_kwh"]  # antigo: "consumo_compensado"
    r["consumo_nao_comp"]    = r["nao_comp_kwh"]    # antigo: "consumo_nao_comp"
    r["anterior_leitura"]    = r["leitura_anterior"]       # compat: numero do medidor (ex: "11912")
    r["data_leitura"]        = r["data_leitura_atual"]    # compat: data da leitura atual (ex: "11/04/2026")
    r["venc_equatorial"]     = r["vencimento"]   # antigo: "venc_equatorial"
    r["endereco_fatura"]     = r["endereco"]     # antigo: "endereco_fatura"

    return r


# ════════════════════════════════════════════════════════
#  CLI — diagnostico / uso direto
# ════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Uso: python extrair_equatorial.py fatura.pdf [--debug]")
        sys.exit(1)

    debug = "--debug" in sys.argv
    resultado = extrair_equatorial(sys.argv[1])

    if debug:
        # Mostra tambem o texto bruto da pagina 1
        texto_bruto, _ = _extrair_texto_pagina1(sys.argv[1])
        print("─" * 70)
        print("TEXTO BRUTO PAGINA 1:")
        print(texto_bruto)
        print("─" * 70)

    print(json.dumps(resultado, ensure_ascii=False, indent=2))

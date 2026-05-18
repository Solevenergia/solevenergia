"""Secao: cabecalho da fatura (UC, mes, datas, total, vencimento)."""
import re
from extracao.helpers import _n, _mes_para_num

_MES_PAT = r"(?:JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)/\d{4}"
_UC_F13  = r"(\d{1,6}(?:\.\d{3}){3}-\d{2})"   # 13 digitos formatados
_UC_F11  = r"(\d{1,4}(?:\.\d{3}){2}-\d{2})"   # 11 digitos formatados
_UC_DIG  = r"(\d{8,16})"
_UC_ANY  = r"(\d{8,16}|\d{1,6}(?:\.\d{3}){1,3}-\d{2})"


def _extrair_uc(texto: str) -> str:
    # Prioridade 1: formatada 13 digitos (nunca e CPF)
    m = re.search(_UC_F13, texto)
    if m:
        return m.group(1)

    # Prioridade 2: formatada 11 digitos, fora do campo CNPJ/CPF
    for m in re.finditer(_UC_F11, texto):
        antes = texto[max(0, m.start() - 30): m.start()]
        if not re.search(r"CNPJ/CPF\s*:", antes, re.IGNORECASE):
            return m.group(1)

    # Prioridade 3: UC adjacente ao mes de referencia
    m = re.search(r"(?<!\d)" + _UC_DIG + r"\s+" + _MES_PAT, texto, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(_MES_PAT + r"\s*\n\s*" + _UC_DIG + r"\b", texto, re.IGNORECASE)
    if m:
        return m.group(1)

    # Prioridade 4: apos cidade GO BRASIL
    m = re.search(r"BRASIL\s+" + _UC_ANY, texto, re.IGNORECASE)
    if m:
        return m.group(1)

    return ""


def parse_cabecalho(texto: str, _texto_completo: str) -> dict:
    r: dict = {}

    r["uc"] = _extrair_uc(texto)

    # Mes de referencia
    ref = re.search(
        r"\b(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)/(\d{4})\b",
        texto, re.IGNORECASE,
    )
    if ref:
        num = _mes_para_num(ref.group(1))
        r["mes_referencia"] = f"{num}/{ref.group(2)}"
    else:
        r["mes_referencia"] = ""

    # Total e vencimento: "R$*****121,93 21/05/2026"
    tot = re.search(r"R\$\*+([\d.,]+)\s+(\d{2}/\d{2}/\d{4})", texto)
    if tot:
        r["total_fatura"] = _n(tot.group(1))
        r["vencimento"]   = tot.group(2)
    else:
        tot2 = re.search(r"\bTOTAL\b\s+([\d.,]+)\s+[\d.,]+\s+[\d.,]+\s+[\d.,]+", texto, re.IGNORECASE)
        r["total_fatura"] = _n(tot2.group(1)) if tot2 else 0.0
        venc = re.search(r"PAGAVEL EM QUALQUER BANCO\s+(\d{2}/\d{2}/\d{4})", texto, re.IGNORECASE)
        r["vencimento"] = venc.group(1) if venc else ""

    # Datas de leitura: "DD/MM/YYYY DD/MM/YYYY NN DD/MM/YYYY"
    leit = re.search(
        r"(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(\d{1,3})\s+(\d{2}/\d{2}/\d{4})",
        texto,
    )
    if leit:
        r["data_leitura_anterior"] = leit.group(1)
        r["data_leitura_atual"]    = leit.group(2)
        r["n_dias"]                = int(leit.group(3))
        r["proxima_leitura"]       = leit.group(4)
    else:
        datas = re.search(r"(\d{2}/\d{2}/\d{4})[ \t]+(\d{2}/\d{2}/\d{4})", texto)
        dias  = re.search(r"\b(2\d|3[0-5])\s+(\d{2}/\d{2}/\d{4})", texto)
        r["data_leitura_anterior"] = datas.group(1) if datas else ""
        r["data_leitura_atual"]    = datas.group(2) if datas else ""
        r["n_dias"]                = int(dias.group(1)) if dias else 0
        r["proxima_leitura"]       = dias.group(2) if dias else ""

    return r

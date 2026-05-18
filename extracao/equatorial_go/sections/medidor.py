"""Secao: leituras do medidor, NF-e, VRC, tensao, PIX, boleto."""
import re
from extracao.helpers import _n


def parse_medidor(texto: str, texto_completo: str) -> dict:
    r: dict = {}

    # ENERGIA ATIVA — KWH UNICO: medidor ant atu constante consumo
    ea = re.search(
        r"ENERGIA\s+ATIVA\s*-\s*KWH\s+.{0,6}NICO\s+(\d+)\s+(\d+)\s+([\d.,]+)\s+(\d+)",
        texto, re.IGNORECASE,
    )
    if ea:
        r["leitura_anterior"] = ea.group(1)
        r["leitura_atual"]    = ea.group(2)
        r["constante"]        = _n(ea.group(3))
    else:
        r["leitura_anterior"] = ""
        r["leitura_atual"]    = ""
        r["constante"]        = 1.0

    # ENERGIA GERACAO — KWH UNICO (so UC geradora)
    eg = re.search(
        r"ENERGIA\s+GERA.{1,4}O\s*-\s*KWH\s+.{0,6}NICO\s+(\d+)\s+(\d+)\s+[\d.,]+\s+(\d+)",
        texto, re.IGNORECASE,
    )
    if eg:
        r["geracao_leitura_anterior"] = eg.group(1)
        r["geracao_leitura_atual"]    = eg.group(2)
        r["geracao_medidor_kwh"]      = _n(eg.group(3))
    else:
        r["geracao_leitura_anterior"] = ""
        r["geracao_leitura_atual"]    = ""
        r["geracao_medidor_kwh"]      = 0.0

    # CFOP
    cfop = re.search(r"CFOP\s+(\d{4})\s*:\s*(.+)", texto, re.IGNORECASE)
    r["cfop"]          = cfop.group(1) if cfop else ""
    r["cfop_descricao"] = cfop.group(2).strip() if cfop else ""

    # Nota Fiscal
    nf = re.search(r"NOTA\s+FISCAL\s+N[°\.]?\s*(\d+)", texto, re.IGNORECASE)
    r["nota_fiscal_num"] = nf.group(1) if nf else ""

    # Protocolo + chave de acesso NF-e
    prot = re.search(r"Protocolo de autoriza.{1,4}o:\s*([\d]+)", texto, re.IGNORECASE)
    r["protocolo_autorizacao"] = prot.group(1) if prot else ""
    chave = re.search(r"\b(\d{44})\b", texto)
    r["chave_acesso"] = chave.group(1) if chave else ""

    # Data emissao NF-e
    emiss = re.search(r"DATA\s+DE\s+EMISS.{1,4}O:\s*(\d{2}/\d{2}/\d{4})", texto, re.IGNORECASE)
    r["data_emissao_nf"] = emiss.group(1) if emiss else ""

    # Tensao nominal
    ten = re.search(r"Tens.{1,3}o\s+Nominal\s+Disp:\s*([\d,]+)\s*V", texto, re.IGNORECASE)
    r["tensao_nominal"] = _n(ten.group(1)) if ten else 0.0

    # VRC continuidade
    vrc = re.search(r"VRC\s*=\s*R\$\s*([\d.,]+)", texto_completo, re.IGNORECASE)
    r["vrc"] = _n(vrc.group(1)) if vrc else 0.0

    # Codigo de barras boleto (linha BANCO DO BRASIL 00190...)
    bb = re.search(r"(00190\.[\d ]+)", texto_completo)
    r["codigo_barras"] = bb.group(1).strip() if bb else ""

    # PIX BR Code
    pix = re.search(r"(000201\d{2}0\d{4}[A-Za-z0-9.+/:%]+)", texto_completo)
    if not pix:
        pix = re.search(r"(00020101[A-Za-z0-9.+/:%\-_]{20,})", texto_completo)
    r["pix_br_code"] = pix.group(1) if pix else ""

    return r

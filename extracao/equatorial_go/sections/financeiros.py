"""Secao: itens financeiros — multa, juros, IPCA, DIC."""
import re
from extracao.helpers import _n, _ultimo_brl
from extracao.models import ItemFinanceiro


def parse_financeiros(texto: str, texto_completo: str) -> dict:
    r: dict = {}
    itens: list[ItemFinanceiro] = []

    # Multa — formato: "MULTA - 03/2026. 131,00 15,82"
    # Negativo lookahead: ignora "MULTA (+) OUTROS ACRESCIMOS" (cabecalho boleto)
    for m in re.finditer(r"\bMULTA\b(?!\s*\(\+\))([^\n]+)", texto_completo, re.IGNORECASE):
        linha = m.group(0)
        mes_m = re.search(r"(\d{2}/\d{4})", linha)
        nums = re.findall(r"[\d.,]+", linha)
        if not nums:
            continue
        valor = _n(nums[-1])
        base  = _n(nums[-2]) if len(nums) >= 2 else 0.0
        if valor > 9999:
            continue
        itens.append(ItemFinanceiro(
            tipo="MULTA",
            mes_origem=mes_m.group(1) if mes_m else "",
            base=base,
            valor=valor,
        ))

    # Juros — formato: "JUROS MORATORIA. 131,00 15,82"
    for m in re.finditer(r"\bJUROS\b([^\n]+)", texto_completo, re.IGNORECASE):
        linha = m.group(0)
        nums = re.findall(r"[\d.,]+", linha)
        if not nums:
            continue
        valor = _n(nums[-1])
        base  = _n(nums[-2]) if len(nums) >= 2 else 0.0
        if valor > 9999:
            continue
        itens.append(ItemFinanceiro(
            tipo="JUROS",
            mes_origem="",
            base=base,
            valor=valor,
        ))

    # Correcao IPCA
    ipca_val = 0.0
    for m in re.finditer(r"VALOR\s+CORRE.{1,4}O\s+IPCA([^\n]+)", texto_completo, re.IGNORECASE):
        linha = m.group(0)
        v = _ultimo_brl(linha)
        if v <= 9999:
            ipca_val += v
            itens.append(ItemFinanceiro(tipo="CORRECAO_IPCA", mes_origem="", base=0.0, valor=v))

    r["itens_financeiros"] = itens
    r["multa"]         = round(sum(i.valor for i in itens if i.tipo == "MULTA"), 2)
    r["juros"]         = round(sum(i.valor for i in itens if i.tipo == "JUROS"), 2)
    r["correcao_ipca"] = round(ipca_val, 2)

    # Compensacao DIC
    dic = re.search(r"COMPENSA.{1,4}O\s+DE\s+DIC\s+MENSAL\s+(-?[\d.,]+)", texto, re.IGNORECASE)
    if not dic:
        dic = re.search(r"COMPENSA.{1,4}O\s+DIC[^\d\n]*(-?[\d.,]+)", texto, re.IGNORECASE)
    val_dic = _n(dic.group(1)) if dic else 0.0
    r["compensacao_dic"] = -abs(val_dic) if val_dic != 0 else 0.0

    return r

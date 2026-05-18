"""Secao: SCEE — geracao, saldo, excedente, rateio."""
import re
from extracao.helpers import _n
from extracao.models import ScopeSCEE, RateioItem

_UC_SCEE = r"UC\s+[\d.\-]+"


def parse_scee(texto: str, texto_completo: str) -> dict:
    r: dict = {}

    # GERACAO CICLO
    ger = re.search(
        r"GERA.{1,4}O\s+CICLO\s*\([^)]*\)\s*KWH\s*:\s*" + _UC_SCEE + r"\s*:\s*([\d.,]+\d)",
        texto_completo, re.IGNORECASE,
    )
    geracao_kwh = _n(ger.group(1)) if ger else 0.0
    ger_uc = ""
    if ger:
        um = re.search(r"UC\s+([\d.\-]+)", ger.group(0), re.IGNORECASE)
        ger_uc = um.group(1).strip() if um else ""

    # EXCEDENTE RECEBIDO
    exc = re.search(
        r"EXCEDENTE\s+RECEBIDO\s+KWH\s*:\s*" + _UC_SCEE + r"\s*:\s*([\d.,]+\d)",
        texto_completo, re.IGNORECASE,
    )
    # CREDITO RECEBIDO
    cred = re.search(
        r"CR.{1,3}DITO\s+RECEBIDO\s+KWH\s+([\d.,]+\d)",
        texto_completo, re.IGNORECASE,
    )
    # SALDO KWH (nao pegar SALDO A EXPIRAR)
    saldo = re.search(
        r"(?<!\bEXPIRAR\s)SALDO\s+KWH\s*:\s*([\d.,]+\d)",
        texto_completo, re.IGNORECASE,
    )
    s30 = re.search(
        r"SALDO\s+A\s+EXPIRAR\s+EM\s+30\s+DIAS\s+KWH\s*:\s*([\d.,]+\d)",
        texto_completo, re.IGNORECASE,
    )
    s60 = re.search(
        r"SALDO\s+A\s+EXPIRAR\s+EM\s+60\s+DIAS\s+KWH\s*:\s*([\d.,]+\d)",
        texto_completo, re.IGNORECASE,
    )

    # CADASTRO RATEIO GERACAO — percentual deste consumidor
    rateio_items: list[RateioItem] = []
    for rm in re.finditer(
        r"CADASTRO\s+RATEIO\s+GERA.{1,4}O\s*:\s*UC\s+([\d.\-]+)\s*=\s*([\d.,]+)%",
        texto_completo, re.IGNORECASE,
    ):
        rateio_items.append(RateioItem(
            uc_geradora=rm.group(1).strip(),
            percentual=_n(rm.group(2)),
        ))

    excedente_kwh   = _n(exc.group(1))   if exc   else 0.0
    credito_kwh     = _n(cred.group(1))  if cred  else 0.0
    saldo_kwh       = _n(saldo.group(1)) if saldo  else 0.0
    saldo_30        = _n(s30.group(1))   if s30   else 0.0
    saldo_60        = _n(s60.group(1))   if s60   else 0.0

    r["geracao_ciclo_kwh"]       = geracao_kwh
    r["excedente_recebido_kwh"]  = excedente_kwh
    r["credito_recebido_kwh"]    = credito_kwh
    r["saldo_kwh"]               = saldo_kwh
    r["saldo_expirar_30d_kwh"]   = saldo_30
    r["saldo_expirar_60d_kwh"]   = saldo_60
    r["rateio"]                  = rateio_items

    if geracao_kwh > 0 or excedente_kwh > 0 or credito_kwh > 0:
        r["scee"] = ScopeSCEE(
            uc_geradora=ger_uc,
            geracao_ciclo_kwh=geracao_kwh,
            excedente_recebido_kwh=excedente_kwh,
            credito_recebido_kwh=credito_kwh,
            saldo_kwh=saldo_kwh,
            saldo_expirar_30d_kwh=saldo_30,
            saldo_expirar_60d_kwh=saldo_60,
            rateio=rateio_items,
        )
    else:
        r["scee"] = None

    return r

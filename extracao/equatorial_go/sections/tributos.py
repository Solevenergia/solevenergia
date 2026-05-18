"""Secao: tributos PIS/COFINS/ICMS."""
import re
from extracao.helpers import _n


def parse_tributos(texto: str, _texto_completo: str) -> dict:
    r: dict = {}

    def _tributo(nome: str) -> tuple:
        m = re.search(
            nome + r"\s+([\d.,]+)\s+([\d.,]+)%\s+([\d.,]+)",
            texto, re.IGNORECASE,
        )
        if m:
            return _n(m.group(1)), _n(m.group(2)), _n(m.group(3))
        return 0.0, 0.0, 0.0

    pb, pa, pv = _tributo(r"PIS/PASEP")
    r["pis_pasep_base"] = pb; r["pis_pasep_aliquota"] = pa; r["pis_pasep_valor"] = pv

    cb, ca, cv = _tributo(r"COFINS")
    r["cofins_base"] = cb; r["cofins_aliquota"] = ca; r["cofins_valor"] = cv

    ib, ia, iv = _tributo(r"ICMS")
    r["icms_base"] = ib; r["icms_aliquota"] = ia; r["icms_valor"] = iv

    return r

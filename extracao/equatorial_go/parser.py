"""Orchestrador: chama cada section parser e monta a Fatura."""
import dataclasses
from extracao.helpers import fix_encoding
from extracao.models import Fatura
from extracao.equatorial_go.sections.cabecalho   import parse_cabecalho
from extracao.equatorial_go.sections.titular      import parse_titular
from extracao.equatorial_go.sections.consumo_scee import parse_consumo_scee
from extracao.equatorial_go.sections.tributos     import parse_tributos
from extracao.equatorial_go.sections.financeiros  import parse_financeiros
from extracao.equatorial_go.sections.scee         import parse_scee
from extracao.equatorial_go.sections.historico    import parse_historico
from extracao.equatorial_go.sections.medidor      import parse_medidor


def parse(texto_p1: str, texto_completo: str, n_paginas: int) -> Fatura:
    # Normaliza encoding e quebras de linha
    t1 = fix_encoding(texto_p1.replace("\r\n", "\n").replace("\r", "\n"))
    tc = fix_encoding(texto_completo.replace("\r\n", "\n").replace("\r", "\n"))

    resultado: dict = {"_n_paginas": n_paginas}

    for parser_fn in (
        parse_cabecalho,
        parse_titular,
        parse_consumo_scee,
        parse_tributos,
        parse_financeiros,
        parse_scee,
        parse_historico,
        parse_medidor,
    ):
        try:
            parcial = parser_fn(t1, tc)
            resultado.update(parcial)
        except Exception:
            # Isola falha de um parser — continua com os demais
            pass

    # Fallback compensado_kwh por credito_recebido_kwh
    if resultado.get("compensado_kwh", 0) == 0 and resultado.get("credito_recebido_kwh", 0) > 0:
        resultado["compensado_kwh"] = resultado["credito_recebido_kwh"]
        resultado["nao_comp_kwh"]   = max(
            0.0,
            resultado.get("consumo_kwh", 0) - resultado["compensado_kwh"],
        )
    if resultado.get("consumo_nao_comp_kwh", 0) > 0:
        resultado["nao_comp_kwh"] = resultado["consumo_nao_comp_kwh"]

    # Monta dataclass — ignora chaves que nao existem nos campos
    campos_validos = {f.name for f in dataclasses.fields(Fatura)}
    kwargs = {k: v for k, v in resultado.items() if k in campos_validos}
    return Fatura(**kwargs)

"""Secao: consumo, SCEE, encargos, tipo de UC."""
import re
from extracao.helpers import _n, _ultimo_brl


def _adc_bandeira(prefixo: str, texto: str) -> float:
    m = re.search(prefixo + r"[^\n]*", texto, re.IGNORECASE)
    if not m:
        return 0.0
    nums = re.findall(r"\d+[.,]?\d*", m.group(0))
    return _n(nums[2]) if len(nums) >= 3 else 0.0


def _tarifa_bandeira(prefixo: str, texto: str) -> float:
    """Tarifa R$/kWh EXATA impressa na linha ADC BANDEIRA.
    Layout: 'ADC BANDEIRA AMARELA kWh <qtd> <TARIFA> <valor_R$> ...' -> 2o numero."""
    m = re.search(prefixo + r"[^\n]*", texto, re.IGNORECASE)
    if not m:
        return 0.0
    nums = re.findall(r"\d+[.,]?\d*", m.group(0))
    return _n(nums[1]) if len(nums) >= 3 else 0.0


def parse_consumo_scee(texto: str, texto_completo: str) -> dict:
    r: dict = {}

    # Detecta tipo UC: geradora tem linha "ENERGIA GERACAO - KWH UNICO"
    r["tipo_uc"] = "geradora" if re.search(
        r"ENERGIA\s+GERA.{1,4}O\s*-\s*KWH\s+.{0,6}NICO",
        texto, re.IGNORECASE
    ) else "consumidora"

    # CONSUMO NAO COMPENSADO
    nao_comp = re.search(
        r"CONSUMO\s+N.{1,4}O\s+COMPENSADO\s+kWh\s+([\d.,]+)\s+([\d.,]+)",
        texto, re.IGNORECASE,
    )
    r["consumo_nao_comp_kwh"] = _n(nao_comp.group(1)) if nao_comp else 0.0
    r["tarifa_convencional"]  = _n(nao_comp.group(2)) if nao_comp else 0.0

    # CONSUMO SCEE
    consumo = re.search(
        r"CONSUMO\s+SCEE\s+kWh\s+([\d.,]+)\s+([\d.,]+)",
        texto, re.IGNORECASE,
    )
    consumo_scee_kwh   = _n(consumo.group(1)) if consumo else 0.0
    r["tarifa_scee"]   = _n(consumo.group(2)) if consumo else 0.0
    r["consumo_kwh"]   = consumo_scee_kwh + r["consumo_nao_comp_kwh"]

    # Consumo convencional (sem GD)
    if r["consumo_kwh"] == 0:
        conv = re.search(
            r"(?<!\S)CONSUMO\s+kWh\s+(?:kWh\s+)?([\d.,]+)\s+([\d.,]+)",
            texto, re.IGNORECASE,
        )
        if conv:
            r["consumo_kwh"]         = _n(conv.group(1))
            r["consumo_nao_comp_kwh"] = r["consumo_kwh"]
            r["tarifa_convencional"]  = _n(conv.group(2))

    # Injecoes SCEE (GD II e GD I) — soma multiplas linhas
    # UC opcional: quando ha 2+ usinas injetando, uma das linhas vem SEM "UC <n> -"
    # (ex: "INJECAO SCEE - GD II 2 kWh 640,00"). Sem o opcional, essa injecao seria
    # ignorada -> os kWh dela virariam "nao compensado" e o valor viraria DIFCI falsa.
    inj2 = re.findall(
        r"INJE.{1,4}O\s+SCEE\s*-\s*(?:UC\s+[\d.\-]+\s*-\s*)?GD\s+II\s+2\s+kWh\s+([\d.,]+)",
        texto, re.IGNORECASE,
    )
    inj1 = re.findall(
        r"INJE.{1,4}O\s+SCEE\s*-\s*(?:UC\s+[\d.\-]+\s*-\s*)?GD\s+I\b[^\n]*kWh\s+([\d.,]+)",
        texto, re.IGNORECASE,
    )
    r["compensado_kwh"] = sum(_n(v) for v in inj2) + sum(_n(v) for v in inj1)
    r["nao_comp_kwh"]   = max(0.0, r["consumo_kwh"] - r["compensado_kwh"])

    # DIFCI
    inj2_tf = re.findall(
        r"INJE.{1,4}O\s+SCEE\s*-\s*(?:UC\s+[\d.\-]+\s*-\s*)?GD\s+II\s+2\s+kWh\s+([\d.,]+)\s+([\d.,]+)",
        texto, re.IGNORECASE,
    )
    inj1_tf = re.findall(
        r"INJE.{1,4}O\s+SCEE\s*-\s*(?:UC\s+[\d.\-]+\s*-\s*)?GD\s+I\b[^\n]*kWh\s+([\d.,]+)\s+([\d.,]+)",
        texto, re.IGNORECASE,
    )
    consumo_val  = consumo_scee_kwh * r["tarifa_scee"]
    injecao_val  = (sum(_n(v[0]) * _n(v[1]) for v in inj2_tf) +
                    sum(_n(v[0]) * _n(v[1]) for v in inj1_tf))
    r["difci"]   = round(max(0.0, consumo_val - injecao_val), 2)

    # ECNISENTA — valor pode estar na mesma linha ou na linha seguinte (apos UC longa)
    ecni = re.findall(r"ENERGIA\s+COMP\s+N.{1,4}O\s+ISENTA[^\n]+", texto_completo, re.IGNORECASE)
    r["ecnisenta"] = round(sum(_ultimo_brl(l) for l in ecni), 2)
    if r["ecnisenta"] == 0.0:
        ecni_next = re.findall(
            r"ENERGIA\s+COMP\s+N.{1,4}O\s+ISENTA[^\n]*\n\S+\s+([\d.,]+)",
            texto_completo, re.IGNORECASE,
        )
        r["ecnisenta"] = round(sum(_n(v) for v in ecni_next), 2)

    # PARC INJET S/DESC
    pct = re.search(r"PARC\s+INJET\s+S/DESC\s*-\s*([\d.,]+)%", texto, re.IGNORECASE)
    r["pct_parc_injet"] = _n(pct.group(1)) if pct else 0.0
    parc = re.findall(
        r"^(?:GD\s+)?II 2\s+kWh\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)",
        texto, re.MULTILINE,
    )
    r["tarifa_nao_comp"]  = _n(parc[0][1]) if parc else 0.0
    r["valor_parc_injet"] = sum(_n(p[2]) for p in parc)

    # Iluminacao publica
    ilum = re.search(r"CONTRIB\.?\s*ILUM\.?\s*P.{0,3}BLICA[^\d\n]+([\d.,]+)", texto, re.IGNORECASE)
    if not ilum:
        ilum = re.search(r"ILUM[^\n]{0,30}MUNICIPAL[^\d\n]*([\d.,]+)", texto, re.IGNORECASE)
    r["iluminacao_publica"] = _n(ilum.group(1)) if ilum else 0.0

    # Bandeiras (tarifa publicada + valor cobrado)
    ba = re.search(r"BANDEIRA\s+AMARELA[^\d\n]+([\d.,]+)", texto, re.IGNORECASE)
    bv = re.search(r"BANDEIRA\s+VERMELHA[^\d\n]+([\d.,]+)", texto, re.IGNORECASE)
    r["bandeira_amarela"]  = _n(ba.group(1)) if ba else 0.0
    r["bandeira_vermelha"] = _n(bv.group(1)) if bv else 0.0
    r["adc_bandeira_amarela"]  = _adc_bandeira(r"ADC\s+BANDEIRA\s+AMARELA",  texto)
    r["adc_bandeira_vermelha"] = _adc_bandeira(r"ADC\s+BANDEIRA\s+VERMELHA", texto)
    r["tarifa_bandeira_amarela_pdf"]  = _tarifa_bandeira(r"ADC\s+BANDEIRA\s+AMARELA",  texto)
    r["tarifa_bandeira_vermelha_pdf"] = _tarifa_bandeira(r"ADC\s+BANDEIRA\s+VERMELHA", texto)

    # Fallback compensado por credito SCEE
    if r["compensado_kwh"] == 0 and r.get("credito_recebido_kwh", 0) > 0:
        r["compensado_kwh"] = r["credito_recebido_kwh"]
        r["nao_comp_kwh"]   = max(0.0, r["consumo_kwh"] - r["compensado_kwh"])
    if r["consumo_nao_comp_kwh"] > 0:
        r["nao_comp_kwh"] = r["consumo_nao_comp_kwh"]

    return r

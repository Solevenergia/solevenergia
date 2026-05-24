"""Secao: SCEE — geracao, saldo, excedente, rateio.

Suporta MULTIPLAS usinas geradoras por UC consumidora (cliente recebe
credito de N usinas diferentes). O texto da fatura aparece assim:

  GERAÇÃO CICLO (4/2026) KWH:
    UC <ID1> : 7.053,00, UC <ID2> : 15.154,00, UC <ID3> : ...
  EXCEDENTE RECEBIDO KWH:
    UC <ID1> : 7.053,00, UC <ID2> : 7.577,00, UC <ID3> : ...
  CRÉDITO RECEBIDO KWH 10.838,00   ← ja vem agregado
  SALDO KWH: 10.065,12              ← ja vem agregado

Retorna:
- `usinas_geradoras`: list[dict] com {uc, geracao_kwh, excedente_kwh}
- `geracao_ciclo_kwh`, `excedente_recebido_kwh`: SOMA (compat com codigo antigo)
- `credito_recebido_kwh`, `saldo_kwh`, `saldo_expirar_*`: escalares ja agregados
"""
import re
from extracao.helpers import _n
from extracao.models import ScopeSCEE, RateioItem

_UC_VALOR_RE = re.compile(r"UC\s+([\d.\-]+)\s*:\s*([\d.,]+\d)", re.IGNORECASE)


def _extrair_lista_uc_valor(texto: str, marcador_inicio: str, marcador_fim_regex: str) -> list[tuple[str, float]]:
    """Captura o bloco entre `marcador_inicio` e o proximo marcador, retorna lista de (uc, valor)."""
    pat = re.compile(
        re.escape(marcador_inicio) + r"(.*?)(?=" + marcador_fim_regex + r"|$)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pat.search(texto)
    if not m:
        return []
    bloco = m.group(1)
    return [(um.group(1).strip(), _n(um.group(2))) for um in _UC_VALOR_RE.finditer(bloco)]


def parse_scee(texto: str, texto_completo: str) -> dict:
    r: dict = {}

    # ── Mes do ciclo: "(4/2026)" → "04/2026" ────────────────────
    ciclo_mes = ""
    cm = re.search(r"GERA.{1,4}O\s+CICLO\s*\((\d{1,2}/\d{4})\)", texto_completo, re.IGNORECASE)
    if cm:
        partes = cm.group(1).split("/")
        ciclo_mes = f"{int(partes[0]):02d}/{partes[1]}"

    # ── GERACAO CICLO por UC (lista) ────────────────────────────
    # Marcador inicio: "GERAÇÃO CICLO (X/YYYY) KWH:"
    # Fim: proxima secao SCEE (EXCEDENTE/CREDITO/SALDO/CADASTRO)
    geracao_pat_inicio = re.compile(
        r"GERA.{1,4}O\s+CICLO\s*\([^)]*\)\s*KWH\s*:",
        re.IGNORECASE,
    )
    gm = geracao_pat_inicio.search(texto_completo)
    geracoes_por_uc: list[tuple[str, float]] = []
    if gm:
        # Bloco depois do marcador, ate o proximo marcador SCEE
        tail = texto_completo[gm.end():]
        fim_re = r"EXCEDENTE\s+RECEBIDO|CR.{1,3}DITO\s+RECEBIDO|SALDO\s+KWH|CADASTRO\s+RATEIO|$"
        fim_match = re.search(fim_re, tail, re.IGNORECASE)
        bloco_ger = tail[:fim_match.start()] if fim_match else tail
        geracoes_por_uc = [(um.group(1).strip(), _n(um.group(2))) for um in _UC_VALOR_RE.finditer(bloco_ger)]

    # ── EXCEDENTE RECEBIDO por UC (lista) ───────────────────────
    excedentes_por_uc = _extrair_lista_uc_valor(
        texto_completo, "EXCEDENTE RECEBIDO KWH:",
        r"CR.{1,3}DITO\s+RECEBIDO|SALDO\s+KWH|CADASTRO\s+RATEIO",
    )

    # ── Combina geracao + excedente por UC em lista detalhada ──
    ucs_set = sorted({u for u, _ in geracoes_por_uc} | {u for u, _ in excedentes_por_uc})
    ger_dict = dict(geracoes_por_uc)
    exc_dict = dict(excedentes_por_uc)
    usinas_geradoras: list[dict] = [
        {
            "uc":             u,
            "geracao_kwh":    ger_dict.get(u, 0.0),
            "excedente_kwh":  exc_dict.get(u, 0.0),
        }
        for u in ucs_set
    ]

    # Somas (compat com codigo antigo que espera escalares)
    geracao_kwh   = sum(v for _, v in geracoes_por_uc)
    excedente_kwh = sum(v for _, v in excedentes_por_uc)

    # UC principal (compat: primeira UC encontrada na geracao)
    ger_uc = geracoes_por_uc[0][0] if geracoes_por_uc else ""

    # ── CREDITO RECEBIDO (escalar - ja vem agregado) ────────────
    cred = re.search(
        r"CR.{1,3}DITO\s+RECEBIDO\s+KWH\s+([\d.,]+\d)",
        texto_completo, re.IGNORECASE,
    )
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

    credito_kwh = _n(cred.group(1))  if cred  else 0.0
    saldo_kwh   = _n(saldo.group(1)) if saldo else 0.0
    saldo_30    = _n(s30.group(1))   if s30   else 0.0
    saldo_60    = _n(s60.group(1))   if s60   else 0.0

    # ── CADASTRO RATEIO GERACAO — percentual deste consumidor ──
    rateio_items: list[RateioItem] = []
    for rm in re.finditer(
        r"CADASTRO\s+RATEIO\s+GERA.{1,4}O\s*:\s*UC\s+([\d.\-]+)\s*=\s*([\d.,]+)%",
        texto_completo, re.IGNORECASE,
    ):
        rateio_items.append(RateioItem(
            uc_geradora=rm.group(1).strip(),
            percentual=_n(rm.group(2)),
        ))

    # ── Retorno ─────────────────────────────────────────────────
    r["ciclo_geracao_mes"]       = ciclo_mes
    r["geracao_ciclo_kwh"]       = geracao_kwh
    r["excedente_recebido_kwh"]  = excedente_kwh
    r["credito_recebido_kwh"]    = credito_kwh
    r["saldo_kwh"]               = saldo_kwh
    r["saldo_expirar_30d_kwh"]   = saldo_30
    r["saldo_expirar_60d_kwh"]   = saldo_60
    r["rateio"]                  = rateio_items
    r["usinas_geradoras"]        = usinas_geradoras  # NOVO — lista detalhada

    if geracao_kwh > 0 or excedente_kwh > 0 or credito_kwh > 0:
        r["scee"] = ScopeSCEE(
            uc_geradora=ger_uc,
            geracao_ciclo_kwh=geracao_kwh,
            excedente_recebido_kwh=excedente_kwh,
            credito_recebido_kwh=credito_kwh,
            saldo_kwh=saldo_kwh,
            saldo_expirar_30d_kwh=saldo_30,
            saldo_expirar_60d_kwh=saldo_60,
            ciclo_mes=ciclo_mes,
            rateio=rateio_items,
        )
    else:
        r["scee"] = None

    return r

"""Secao: historico de consumo dos ultimos 12 meses."""
import re
from extracao.helpers import _n
from extracao.models import HistoricoMes


def parse_historico(texto: str, _texto_completo: str) -> dict:
    """
    Extrai historico de consumo. O PDF renderiza a tabela em 3 colunas:
    (consumo kWh, faturamento R$, dias). O extractor de texto lineariza
    as colunas em pares intercalados: (R$, kWh) por linha, depois bloco
    de dias, depois status.
    """
    r: dict = {}

    inicio = re.search(
        r"CONSUMO\s+FATURADO\s*\(kWh\)\s+FATURAMENTO",
        texto, re.IGNORECASE,
    )
    if not inicio:
        r["historico_meses"] = []
        return r

    # Texto da secao historico ate "BANCO DO BRASIL" ou fim
    trecho = texto[inicio.end():]
    fim = re.search(r"BANCO\s+DO\s+BRASIL|PAGAVEL", trecho, re.IGNORECASE)
    if fim:
        trecho = trecho[:fim.start()]

    # Extrai floats (com virgula) e inteiros (20-45 = dias tipicos)
    floats  = [_n(m) for m in re.findall(r"\d+,\d+", trecho)]
    inteiros = [int(m) for m in re.findall(r"\b(\d{2})\b", trecho)
                if 20 <= int(m) <= 45]
    status_raw = re.findall(r"\b(LIDA|M.{1,4}NIMO)\b", trecho, re.IGNORECASE)
    status_list = []
    for s in status_raw:
        s_up = s.upper()
        status_list.append("MINIMO" if "NIM" in s_up else "LIDA")

    # Pares (R$, kWh) — extrai ate 13 pares
    n_pares = min(len(floats) // 2, 13)
    n_dias  = len(inteiros)
    meses: list[HistoricoMes] = []

    for i in range(n_pares):
        val_rs  = floats[i * 2]
        val_kwh = floats[i * 2 + 1]
        dias    = inteiros[i] if i < n_dias else 0
        st      = status_list[i] if i < len(status_list) else ""
        meses.append(HistoricoMes(
            consumo_kwh=val_kwh,
            valor_rs=val_rs,
            dias=dias,
            status=st,
        ))

    r["historico_meses"] = meses
    return r

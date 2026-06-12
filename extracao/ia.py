"""Extracao de fatura via Claude API — reforco do parser regex.

Papel no fluxo (ver extrair_equatorial.py):
  1. Regex roda sempre (rapido, deterministico, gratis).
  2. Se o PDF nao for reconhecido (LayoutDesconhecido) -> IA extrai tudo.
  3. Se o regex devolver campos VITAIS zerados/vazios (sintoma de secao que
     quebrou em silencio — parser.py engole excecoes) -> IA extrai e o
     resultado preenche apenas os buracos (regex vence onde tem valor).

Sem ANTHROPIC_API_KEY (ou com SOLEV_IA_EXTRACAO=0) este modulo vira no-op:
o comportamento e identico ao de antes. `anthropic`/`pydantic` so sao
importados na hora da chamada.

CLI de auditoria (caca erro silencioso, ex. caso multiusina):
  python -m extracao.ia fatura.pdf             -> extrai via IA, imprime JSON
  python -m extracao.ia fatura.pdf --comparar  -> diff regex x IA campo a campo
"""
from __future__ import annotations

import base64
import dataclasses
import os

from extracao.exceptions import ExtracaoError
from extracao.models import Fatura

MODELO_PADRAO = "claude-opus-4-8"

# Campos preenchidos individualmente quando o regex deixou vazio/zerado.
_CAMPOS_FILL = (
    "uc", "mes_referencia", "nome", "cpf", "endereco", "cidade", "uf", "cep",
    "vencimento", "total_fatura",
    "data_leitura_anterior", "data_leitura_atual", "n_dias", "proxima_leitura",
    "leitura_anterior", "leitura_atual",
    "iluminacao_publica", "multa", "juros", "ecnisenta",
    "adc_bandeira_amarela", "adc_bandeira_vermelha",
    "bandeira_amarela", "bandeira_vermelha",
    "tarifa_bandeira_amarela_pdf", "tarifa_bandeira_vermelha_pdf",
)

# Bloco de consumo: adotado em conjunto (os campos derivam uns dos outros —
# misturar fontes geraria compensado de um lado e nao_comp de outro).
_BLOCO_CONSUMO = (
    "consumo_kwh", "tarifa_scee", "compensado_kwh", "nao_comp_kwh",
    "consumo_nao_comp_kwh", "tarifa_convencional", "difci",
    "pct_parc_injet", "tarifa_nao_comp", "valor_parc_injet",
)

# Bloco SCEE: idem (somas/listas coerentes entre si).
_BLOCO_SCEE = (
    "ciclo_geracao_mes", "geracao_ciclo_kwh", "excedente_recebido_kwh",
    "credito_recebido_kwh", "saldo_kwh",
    "saldo_expirar_30d_kwh", "saldo_expirar_60d_kwh",
    "usinas_geradoras", "scee",
)


def ia_disponivel() -> bool:
    """True se a extracao via IA pode ser usada (chave + lib instalada + nao desligada)."""
    if os.environ.get("SOLEV_IA_EXTRACAO", "1").strip().lower() in ("0", "false", "off", "nao"):
        return False
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def motivos_escalonamento(f: Fatura) -> list[str]:
    """Campos vitais que o regex deixou vazios — sintoma de secao quebrada."""
    motivos = []
    if not f.uc:
        motivos.append("uc vazia")
    if not f.mes_referencia:
        motivos.append("mes_referencia vazio")
    if not f.vencimento:
        motivos.append("vencimento vazio")
    if f.total_fatura <= 0:
        motivos.append("total_fatura zerado")
    if f.consumo_kwh <= 0:
        motivos.append("consumo zerado")
    elif f.tarifa_scee <= 0 and f.tarifa_convencional <= 0:
        motivos.append("tarifas zeradas")
    return motivos


def extrair_com_ia(caminho_pdf: str) -> Fatura:
    """Extrai a fatura inteira com Claude (structured outputs sobre o PDF).

    Levanta ExtracaoError se a IA tambem nao conseguir identificar a fatura.
    """
    import anthropic
    from extracao.ia_schema import FaturaIA, PROMPT_SISTEMA, para_fatura

    with open(caminho_pdf, "rb") as fh:
        pdf_b64 = base64.standard_b64encode(fh.read()).decode("ascii")

    # timeout < gunicorn --timeout 120 (Procfile): a chamada precisa caber
    # dentro do request de upload sem o worker ser morto no meio.
    client = anthropic.Anthropic(timeout=90.0, max_retries=0)
    resposta = client.messages.parse(
        model=os.environ.get("SOLEV_IA_MODELO", MODELO_PADRAO),
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=PROMPT_SISTEMA,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64,
                    },
                },
                {"type": "text", "text": "Extraia os dados desta fatura conforme o schema."},
            ],
        }],
        output_format=FaturaIA,
    )

    fatura = para_fatura(resposta.parsed_output)
    if not fatura.uc and fatura.total_fatura <= 0:
        raise ExtracaoError(f"IA nao identificou a fatura: {caminho_pdf}")
    return fatura


def _vazio(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (int, float)):
        return v == 0
    if isinstance(v, list):
        return len(v) == 0
    return False


def mesclar(regex: Fatura, ia: Fatura) -> Fatura:
    """Preenche com a IA apenas o que o regex deixou vazio.

    Regra: regex vence onde extraiu (valores exatos, ex. tarifa impressa);
    blocos interdependentes (consumo, SCEE) sao adotados em conjunto.
    """
    resultado = dataclasses.replace(regex)
    preencheu = False

    for campo in _CAMPOS_FILL:
        if _vazio(getattr(resultado, campo)) and not _vazio(getattr(ia, campo)):
            setattr(resultado, campo, getattr(ia, campo))
            preencheu = True

    # Bloco consumo: nucleo quebrado -> adota o conjunto da IA
    consumo_quebrado = (
        regex.consumo_kwh <= 0
        or (regex.tarifa_scee <= 0 and regex.tarifa_convencional <= 0)
        or (regex.compensado_kwh <= 0 and ia.compensado_kwh > 0)
    )
    if consumo_quebrado and ia.consumo_kwh > 0:
        for campo in _BLOCO_CONSUMO:
            setattr(resultado, campo, getattr(ia, campo))
        preencheu = True

    # Bloco SCEE: regex sem nada e IA achou -> adota o conjunto
    scee_vazio = (
        regex.geracao_ciclo_kwh <= 0
        and regex.credito_recebido_kwh <= 0
        and regex.saldo_kwh <= 0
    )
    scee_ia_tem = (
        ia.geracao_ciclo_kwh > 0 or ia.credito_recebido_kwh > 0 or ia.saldo_kwh > 0
    )
    if scee_vazio and scee_ia_tem:
        for campo in _BLOCO_SCEE:
            setattr(resultado, campo, getattr(ia, campo))
        preencheu = True

    if not resultado.rateio and ia.rateio:
        resultado.rateio = ia.rateio
        preencheu = True

    if preencheu:
        resultado.fonte_extracao = "regex+ia"
    return resultado


# ──────────────────────────────────────────────────────────────────
# CLI de auditoria
# ──────────────────────────────────────────────────────────────────

_CAMPOS_COMPARAR = (
    "uc", "mes_referencia", "tipo_uc", "nome", "vencimento", "total_fatura",
    "consumo_kwh", "tarifa_scee", "compensado_kwh", "nao_comp_kwh",
    "consumo_nao_comp_kwh", "tarifa_convencional", "difci", "ecnisenta",
    "pct_parc_injet", "valor_parc_injet", "iluminacao_publica",
    "adc_bandeira_amarela", "adc_bandeira_vermelha",
    "tarifa_bandeira_amarela_pdf", "tarifa_bandeira_vermelha_pdf",
    "multa", "juros",
    "ciclo_geracao_mes", "geracao_ciclo_kwh", "excedente_recebido_kwh",
    "credito_recebido_kwh", "saldo_kwh",
    "data_leitura_anterior", "data_leitura_atual", "n_dias", "proxima_leitura",
)


def _comparar(caminho_pdf: str) -> int:
    from extracao import extrair

    print(f"Comparando regex x IA: {caminho_pdf}\n")
    fr = extrair(caminho_pdf)
    fi = extrair_com_ia(caminho_pdf)

    divergencias = 0
    for campo in _CAMPOS_COMPARAR:
        vr, vi = getattr(fr, campo), getattr(fi, campo)
        iguais = (
            abs(vr - vi) < 0.015
            if isinstance(vr, (int, float)) and isinstance(vi, (int, float))
            else str(vr).strip() == str(vi).strip()
        )
        if not iguais:
            divergencias += 1
            print(f"  DIVERGE  {campo:32s} regex={vr!r}  ia={vi!r}")

    # Listas: rateio e usinas geradoras
    rr = [(r.uc_geradora, r.percentual) for r in fr.rateio]
    ri = [(r.uc_geradora, r.percentual) for r in fi.rateio]
    if rr != ri:
        divergencias += 1
        print(f"  DIVERGE  {'rateio':32s} regex={rr!r}  ia={ri!r}")
    ur = [(u["uc"], u["geracao_kwh"], u["excedente_kwh"]) for u in fr.usinas_geradoras]
    ui = [(u["uc"], u["geracao_kwh"], u["excedente_kwh"]) for u in fi.usinas_geradoras]
    if ur != ui:
        divergencias += 1
        print(f"  DIVERGE  {'usinas_geradoras':32s} regex={ur!r}  ia={ui!r}")

    if divergencias == 0:
        print("  OK — regex e IA concordam em todos os campos comparados.")
    else:
        print(f"\n  {divergencias} divergencia(s). Regex pode ter quebrado em silencio — conferir no PDF.")
    return divergencias


if __name__ == "__main__":
    import json
    import sys

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Uso: python -m extracao.ia fatura.pdf [--comparar]")
        sys.exit(1)
    if not ia_disponivel():
        print("IA indisponivel: defina ANTHROPIC_API_KEY (e instale `pip install anthropic`).")
        sys.exit(2)

    if "--comparar" in sys.argv:
        sys.exit(1 if _comparar(args[0]) else 0)

    fatura = extrair_com_ia(args[0])
    print(json.dumps(dataclasses.asdict(fatura), ensure_ascii=False, indent=2, default=str))

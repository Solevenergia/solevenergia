"""
Testes da camada de IA da extracao (extracao/ia.py + ia_schema.py).

Nenhum teste chama a API — cobrem a logica pura: disponibilidade,
escalonamento, merge regex x IA e derivacoes do schema (multiusina).

Execucao:
    cd C:\\Rede\\SOLEV && python -m pytest tests/test_extracao_ia.py -v
"""
import os

import pytest

from extracao import extrair, ia
from extracao.models import Fatura

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "equatorial_go")


def _pdf(nome: str) -> str:
    return os.path.join(FIXTURES, nome)


# ---------------------------------------------------------------------------
# Disponibilidade
# ---------------------------------------------------------------------------
def test_indisponivel_sem_chave(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert ia.ia_disponivel() is False


def test_desligavel_por_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-teste")
    monkeypatch.setenv("SOLEV_IA_EXTRACAO", "0")
    assert ia.ia_disponivel() is False


# ---------------------------------------------------------------------------
# Escalonamento — campos vitais
# ---------------------------------------------------------------------------
def test_fatura_saudavel_nao_escala():
    f = extrair(_pdf("consumidora-residencial-cleibio.pdf"))
    assert ia.motivos_escalonamento(f) == []


def test_fatura_quebrada_escala():
    m = ia.motivos_escalonamento(Fatura())
    assert "uc vazia" in m
    assert "total_fatura zerado" in m
    assert "consumo zerado" in m


def test_tarifas_zeradas_escala():
    f = Fatura(uc="1", mes_referencia="5/2026", vencimento="01/06/2026",
               total_fatura=100.0, consumo_kwh=300.0)
    assert ia.motivos_escalonamento(f) == ["tarifas zeradas"]


# ---------------------------------------------------------------------------
# Merge regex x IA
# ---------------------------------------------------------------------------
def test_mesclar_regex_vence_onde_tem_valor():
    regex_f = Fatura(uc="123", total_fatura=100.0, iluminacao_publica=30.0,
                     consumo_kwh=300.0, tarifa_scee=1.05)
    ia_f    = Fatura(uc="999", total_fatura=999.0, iluminacao_publica=99.0,
                     vencimento="21/05/2026")
    m = ia.mesclar(regex_f, ia_f)
    assert m.uc == "123"
    assert m.total_fatura == 100.0
    assert m.iluminacao_publica == 30.0
    assert m.vencimento == "21/05/2026"   # buraco preenchido
    assert m.fonte_extracao == "regex+ia"


def test_mesclar_adota_bloco_consumo_quando_nucleo_quebrado():
    regex_f = Fatura(uc="123", total_fatura=100.0)   # consumo zerado
    ia_f = Fatura(consumo_kwh=500.0, tarifa_scee=1.05, compensado_kwh=400.0,
                  nao_comp_kwh=100.0, difci=2.5)
    m = ia.mesclar(regex_f, ia_f)
    assert m.consumo_kwh == 500.0
    assert m.compensado_kwh == 400.0
    assert m.nao_comp_kwh == 100.0
    assert m.difci == 2.5


def test_mesclar_adota_bloco_scee_quando_vazio():
    regex_f = Fatura(uc="123", total_fatura=100.0, consumo_kwh=300.0, tarifa_scee=1.0)
    ia_f = Fatura(geracao_ciclo_kwh=7000.0, credito_recebido_kwh=400.0,
                  saldo_kwh=120.0,
                  usinas_geradoras=[{"uc": "111", "geracao_kwh": 7000.0,
                                     "excedente_kwh": 3500.0}])
    m = ia.mesclar(regex_f, ia_f)
    assert m.geracao_ciclo_kwh == 7000.0
    assert m.saldo_kwh == 120.0
    assert len(m.usinas_geradoras) == 1


def test_mesclar_sem_buracos_mantem_fonte_regex():
    f = extrair(_pdf("consumidora-residencial-cleibio.pdf"))
    m = ia.mesclar(f, Fatura())
    assert m.fonte_extracao == "regex"


# ---------------------------------------------------------------------------
# Schema IA — derivacoes (espelham o parser regex)
# ---------------------------------------------------------------------------
def _fatura_ia_minima(**kw):
    from extracao.ia_schema import FaturaIA
    base = dict(
        uc="123", mes_referencia="5/2026", tipo_uc="consumidora",
        nome="X", cpf="", endereco="", cidade="", uf="GO", cep="",
        vencimento="21/05/2026", total_fatura=100.0,
        data_leitura_anterior="", data_leitura_atual="", n_dias=30,
        proxima_leitura="", leitura_anterior="", leitura_atual="",
        consumo_scee_kwh=0.0, tarifa_scee=0.0,
        consumo_nao_compensado_kwh=0.0, tarifa_nao_compensado=0.0,
        injecoes=[], iluminacao_publica=0.0,
        adc_bandeira_amarela_kwh=0.0, tarifa_bandeira_amarela_pdf=0.0,
        adc_bandeira_amarela=0.0, adc_bandeira_vermelha_kwh=0.0,
        tarifa_bandeira_vermelha_pdf=0.0, adc_bandeira_vermelha=0.0,
        pct_parc_injet=0.0, tarifa_parc_injet=0.0, valor_parc_injet=0.0,
        ecnisenta=0.0, multa=0.0, juros=0.0,
        ciclo_geracao_mes="", usinas_geradoras=[],
        credito_recebido_kwh=0.0, saldo_kwh=0.0,
        saldo_expirar_30d_kwh=0.0, saldo_expirar_60d_kwh=0.0, rateio=[],
    )
    base.update(kw)
    return FaturaIA(**base)


def test_para_fatura_multiusina_injecao_sem_uc():
    """Caso do bug multiusina: linha de injecao SEM 'UC n -' deve somar."""
    from extracao.ia_schema import InjecaoIA, UsinaGeradoraIA, para_fatura
    fia = _fatura_ia_minima(
        consumo_scee_kwh=4999.01, tarifa_scee=0.989661,
        injecoes=[
            InjecaoIA(uc_geradora="2240026395", grupo="GD II",
                      kwh=4359.01, tarifa=0.989661, valor=4313.95),
            InjecaoIA(uc_geradora="", grupo="GD II",
                      kwh=640.0, tarifa=0.989661, valor=633.38),
        ],
        usinas_geradoras=[
            UsinaGeradoraIA(uc="2240026395", geracao_kwh=7053.0, excedente_kwh=2694.0),
            UsinaGeradoraIA(uc="1060971135", geracao_kwh=15154.0, excedente_kwh=7577.0),
        ],
        credito_recebido_kwh=4999.01,
    )
    f = para_fatura(fia)
    assert f.compensado_kwh == pytest.approx(4999.01, abs=0.001)
    assert f.nao_comp_kwh == 0.0
    assert f.difci == pytest.approx(0.0, abs=0.01)   # tarifas iguais -> sem DIFCI
    assert f.geracao_ciclo_kwh == 22207.0
    assert len(f.usinas_geradoras) == 2
    assert f.fonte_extracao == "ia"


def test_para_fatura_difci_legitima():
    """DIFCI > 0 legitima: tarifa do consumo maior que tarifa da injecao."""
    from extracao.ia_schema import InjecaoIA, para_fatura
    fia = _fatura_ia_minima(
        consumo_scee_kwh=100.0, tarifa_scee=1.00,
        injecoes=[InjecaoIA(uc_geradora="1", grupo="GD II",
                            kwh=100.0, tarifa=0.90, valor=90.0)],
    )
    f = para_fatura(fia)
    assert f.difci == pytest.approx(10.0, abs=0.01)


def test_para_fatura_fallback_credito():
    """Sem linhas de injecao, compensado cai no credito recebido (igual parser)."""
    from extracao.ia_schema import para_fatura
    fia = _fatura_ia_minima(
        consumo_scee_kwh=300.0, tarifa_scee=1.0, credito_recebido_kwh=250.0,
    )
    f = para_fatura(fia)
    assert f.compensado_kwh == 250.0
    assert f.nao_comp_kwh == 50.0

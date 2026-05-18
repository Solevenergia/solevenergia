"""
Testes parametricos do modulo extracao para as 6 faturas de referencia.

Execucao:
    cd C:\Rede\SOLEV && python -m pytest tests/test_extracao.py -v
"""
import os
import pytest
from extracao import extrair

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "equatorial_go")


def _pdf(nome: str) -> str:
    return os.path.join(FIXTURES, nome)


# ---------------------------------------------------------------------------
# Estrutura basica — todos os PDFs devem retornar Fatura valida
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nome", [
    "consumidora-residencial-cleibio.pdf",
    "consumidora-residencial-juliana.pdf",
    "consumidora-comercial-carlucio.pdf",
    "consumidora-comercial-paulo.pdf",
    "consumidora-com-multa-nilton.pdf",
    "geradora-usina-nilton.pdf",
])
def test_retorna_fatura(nome):
    f = extrair(_pdf(nome))
    assert f.uc != "", f"uc vazio em {nome}"
    assert f.mes_referencia != "", f"mes_referencia vazio em {nome}"
    assert f.total_fatura > 0, f"total_fatura=0 em {nome}"
    assert f.nome != "", f"nome vazio em {nome}"
    assert f.cpf  != "", f"cpf vazio em {nome}"
    assert f.vencimento != "", f"vencimento vazio em {nome}"


# ---------------------------------------------------------------------------
# Cleibio — consumidora residencial simples
# ---------------------------------------------------------------------------
def test_cleibio():
    f = extrair(_pdf("consumidora-residencial-cleibio.pdf"))
    assert f.total_fatura == pytest.approx(88.05, abs=0.02)
    assert f.consumo_kwh  == pytest.approx(363.0, abs=1)
    assert f.tipo_uc      == "consumidora"
    assert f.compensado_kwh > 0
    # rateio: UC geradora com percentual
    assert len(f.rateio) >= 1
    assert f.rateio[0].percentual > 0 or f.rateio[0].uc_geradora != ""


# ---------------------------------------------------------------------------
# Juliana — consumidora residencial com geradora diferente
# ---------------------------------------------------------------------------
def test_juliana():
    f = extrair(_pdf("consumidora-residencial-juliana.pdf"))
    assert f.total_fatura == pytest.approx(114.36, abs=0.02)
    assert f.consumo_kwh  == pytest.approx(432.0, abs=1)
    assert f.tipo_uc      == "consumidora"
    assert len(f.rateio) >= 1


# ---------------------------------------------------------------------------
# Paulo — consumidora comercial com ENERGIA COMP NAO ISENTA
# ---------------------------------------------------------------------------
def test_paulo():
    f = extrair(_pdf("consumidora-comercial-paulo.pdf"))
    assert f.total_fatura == pytest.approx(919.24, abs=0.05)
    assert f.consumo_kwh  == pytest.approx(3599.0, abs=1)
    assert f.tipo_uc      == "consumidora"
    assert f.ecnisenta    > 0
    assert len(f.rateio)  >= 1


# ---------------------------------------------------------------------------
# Nilton consumidora com multa/juros
# ---------------------------------------------------------------------------
def test_nilton_multa():
    f = extrair(_pdf("consumidora-com-multa-nilton.pdf"))
    assert f.tipo_uc == "consumidora"
    assert f.multa > 0 or f.juros > 0, "esperava multa ou juros"
    assert len(f.itens_financeiros) > 0


# ---------------------------------------------------------------------------
# Nilton UC geradora
# ---------------------------------------------------------------------------
def test_nilton_geradora():
    f = extrair(_pdf("geradora-usina-nilton.pdf"))
    assert f.tipo_uc            == "geradora"
    assert f.total_fatura       == pytest.approx(121.93, abs=0.02)
    assert f.geracao_ciclo_kwh  > 0, "geracao_ciclo_kwh deve ser > 0"
    assert f.geracao_medidor_kwh > 0, "geracao_medidor_kwh deve ser > 0"
    assert f.consumo_nao_comp_kwh == pytest.approx(100.0, abs=1)
    # geradora tem rateio = 0% para si mesma
    assert len(f.rateio) >= 1
    assert f.rateio[0].percentual == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# Todos devem ter rateio com pelo menos um item
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nome", [
    "consumidora-residencial-cleibio.pdf",
    "consumidora-residencial-juliana.pdf",
    "consumidora-comercial-paulo.pdf",
    "geradora-usina-nilton.pdf",
])
def test_rateio_presente(nome):
    f = extrair(_pdf(nome))
    assert len(f.rateio) >= 1, f"rateio vazio em {nome}"
    assert f.rateio[0].uc_geradora != "", f"uc_geradora vazia em {nome}"

"""
extracao — modulo de extracao de dados de faturas PDF

API publica:
    from extracao import extrair
    fatura = extrair("caminho/da/fatura.pdf")   # retorna dataclass Fatura

Estrutura interna:
    extracao/
        text_extractor.py     # PDF -> texto bruto
        registry.py           # detecta layout e roteia para parser
        models.py             # dataclasses tipados
        exceptions.py         # erros semanticos
        helpers.py            # utilitarios compartilhados (encoding, numeros, datas)
        equatorial_go/        # parser da Equatorial Goias
            parser.py
            fingerprint.py
            sections/
"""
from extracao.models import Fatura, ItemFinanceiro, HistoricoMes, ScopeSCEE, RateioItem
from extracao.exceptions import (
    ExtracaoError,
    CampoNaoEncontrado,
    LayoutDesconhecido,
    PdfInvalido,
)
from extracao.registry import extrair

__all__ = [
    "extrair",
    "Fatura",
    "ItemFinanceiro",
    "HistoricoMes",
    "ScopeSCEE",
    "RateioItem",
    "ExtracaoError",
    "CampoNaoEncontrado",
    "LayoutDesconhecido",
    "PdfInvalido",
]

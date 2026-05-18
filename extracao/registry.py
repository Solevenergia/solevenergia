"""Detecta o layout do PDF e roteia para o parser correto."""
from extracao.text_extractor import extrair_texto
from extracao.exceptions import LayoutDesconhecido
from extracao.models import Fatura


def extrair(caminho_pdf: str) -> Fatura:
    """
    Extrai dados de uma fatura PDF.

    Retorna Fatura com todos os campos tipados.
    Levanta LayoutDesconhecido se o PDF nao for reconhecido.
    """
    texto_p1, texto_completo, n_pag = extrair_texto(caminho_pdf)

    from extracao.equatorial_go.fingerprint import is_equatorial_go
    if is_equatorial_go(texto_p1) or is_equatorial_go(texto_completo):
        from extracao.equatorial_go.parser import parse
        return parse(texto_p1, texto_completo, n_pag)

    raise LayoutDesconhecido(
        f"PDF nao reconhecido por nenhum parser: {caminho_pdf}"
    )

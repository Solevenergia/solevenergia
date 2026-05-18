"""Excecoes semanticas do modulo extracao."""


class ExtracaoError(Exception):
    """Erro base de extracao."""


class CampoNaoEncontrado(ExtracaoError):
    def __init__(self, campo: str, contexto: str = ""):
        self.campo = campo
        msg = f"Campo nao encontrado: '{campo}'"
        if contexto:
            msg += f" — {contexto}"
        super().__init__(msg)


class LayoutDesconhecido(ExtracaoError):
    """Texto do PDF nao corresponde a nenhum layout reconhecido."""


class PdfInvalido(ExtracaoError):
    """Arquivo PDF invalido ou ilegivel."""

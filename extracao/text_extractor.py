"""Extracao de texto de PDFs — tenta pypdfium2, pdfplumber, PyMuPDF, OCR nessa ordem."""

import os

# Caminho do Tesseract no Windows (instalado via winget)
_TESSERACT_WIN = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def extrair_texto(caminho_pdf: str) -> tuple[str, str, int]:
    """
    Retorna (texto_pagina1, texto_completo, n_paginas).
    Levanta PdfInvalido se nenhuma biblioteca disponivel ou PDF vazio.
    """
    from extracao.exceptions import PdfInvalido

    # ── pypdfium2 ──
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(caminho_pdf)
        n = len(doc)
        partes = []
        for i in range(n):
            tp = doc[i].get_textpage()
            partes.append(tp.get_text_range())
        doc.close()
        completo = "\n".join(partes)
        if completo.strip():
            return partes[0], completo, n
    except ImportError:
        pass
    except Exception:
        pass

    # ── pdfplumber ──
    try:
        import pdfplumber
        with pdfplumber.open(caminho_pdf) as pdf:
            n = len(pdf.pages)
            partes = [p.extract_text() or "" for p in pdf.pages]
        completo = "\n".join(partes)
        if completo.strip():
            return partes[0], completo, n
    except ImportError:
        pass
    except Exception:
        pass

    # ── PyMuPDF ──
    try:
        import fitz
        doc = fitz.open(caminho_pdf)
        n = doc.page_count
        partes = [doc[i].get_text() for i in range(n)]
        completo = "\n".join(partes)
        if completo.strip():
            return partes[0], completo, n
    except ImportError:
        pass
    except Exception:
        pass

    # ── OCR via pytesseract + pdf2image (PDFs escaneados) ──
    try:
        import pytesseract
        from pdf2image import convert_from_path

        if os.path.isfile(_TESSERACT_WIN):
            pytesseract.pytesseract.tesseract_cmd = _TESSERACT_WIN

        images = convert_from_path(caminho_pdf, dpi=300)
        n = len(images)
        partes = [
            pytesseract.image_to_string(img, lang="por+eng")
            for img in images
        ]
        completo = "\n".join(partes)
        if completo.strip():
            return partes[0], completo, n
    except ImportError:
        pass
    except Exception:
        pass

    raise PdfInvalido(
        f"Nenhuma biblioteca PDF disponivel ou PDF vazio: {caminho_pdf}\n"
        "Instale: pip install pypdfium2"
    )

import re


def is_equatorial_go(texto: str) -> bool:
    """Retorna True se o texto parece ser fatura Equatorial Goias 2025/2026."""
    marcadores = [
        r"EQUATORIAL\s+GOI",
        r"EQUATORIAL\s+ENERGIA",
        r"CONTRIB\.?\s*ILUM\.?\s*P.{0,3}BLICA",
        r"PARC\s+INJET\s+S/DESC",
        r"SCEE",
    ]
    return sum(bool(re.search(m, texto, re.IGNORECASE)) for m in marcadores) >= 2

import re

_MESES = {
    "JAN": "1", "FEV": "2",  "MAR": "3",  "ABR": "4",
    "MAI": "5", "JUN": "6",  "JUL": "7",  "AGO": "8",
    "SET": "9", "OUT": "10", "NOV": "11", "DEZ": "12",
}


def fix_encoding(s: str) -> str:
    """Corrige mojibake: bytes UTF-8 interpretados como latin-1."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


def _n(s) -> float:
    """Converte '1.234,56' -> 1234.56. Retorna 0.0 se invalido."""
    if not s:
        return 0.0
    try:
        return float(str(s).strip().replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def _ultimo_brl(s: str) -> float:
    """Retorna o ultimo valor BRL (com virgula) encontrado na string."""
    nums = [n for n in re.findall(r"[\d.,]+", s) if "," in n]
    return _n(nums[-1]) if nums else 0.0


def _mes_para_num(abbrev: str) -> str:
    """MAI -> '5', JAN -> '1'."""
    return _MESES.get(abbrev.upper(), "")

"""Secao: dados do titular (nome, CPF, endereco, classificacao, tipo fornecimento)."""
import re


def parse_titular(texto: str, _texto_completo: str) -> dict:
    r: dict = {}

    # Tipo de fornecimento
    tf = re.search(r"Tipo de fornecimento:\s*(\S+)", texto, re.IGNORECASE)
    raw_tf = tf.group(1).strip() if tf else ""
    # normaliza mojibake TRIFASICO / MONOFASICO / BIFASICO
    raw_tf = (raw_tf
              .replace("\xc3\x83", "A")
              .replace("\xc3\x93", "O")
              .replace("TRIF\x83SICO", "TRIFASICO")
              .replace("MONOF\x83SICO", "MONOFASICO"))
    r["tipo_fornecimento"] = raw_tf

    # Classificacao: "Classificacao: B B1 RESIDENCIAL ..."
    cls = re.search(r"Classifica.{1,4}o:\s*(.+)", texto, re.IGNORECASE)
    r["classificacao"] = cls.group(1).strip() if cls else ""

    # Nome — linha imediatamente antes de CNPJ/CPF
    nome = re.search(r"\n([A-Z][A-Z ]{4,})\nCNPJ/CPF:", texto)
    if not nome:
        nome = re.search(r"([A-Z][A-Z ]{4,}?)\s+CNPJ/CPF:", texto)
    r["nome"] = nome.group(1).strip() if nome else ""
    # Remove prefixo de ruido OCR ("V DANILO" -> "DANILO")
    if r["nome"] and len(r["nome"]) > 2:
        r["nome"] = re.sub(r"^[A-Z]\s+", "", r["nome"])

    # CPF / CNPJ
    cpf = re.search(r"CNPJ/CPF:\s*([\d./-]+)", texto)
    r["cpf"] = cpf.group(1).strip() if cpf else ""

    # Endereco: linhas entre CNPJ e CEP/PERDAS
    end = re.search(r"CNPJ/CPF:.*?\n(.*?)(?=CEP:|PERDAS)", texto, re.DOTALL)
    if end:
        linhas = [
            ln.strip() for ln in end.group(1).splitlines()
            if ln.strip() and "NOTA FISCAL" not in ln and "SERIE" not in ln
        ]
        r["endereco"] = " ".join(linhas)
    else:
        r["endereco"] = ""

    # CEP, Cidade, UF
    cep = re.search(r"CEP:\s*(\d{5,8})\s+([A-Z ]+)\s+(GO|DF|MG|SP|RJ|BA|PR|RS|SC|MT|MS|TO|PA|AM|CE|PE|MA|PI|RN|PB|SE|AL|ES|RO|AC|AP|RR)\s+BRASIL", texto, re.IGNORECASE)
    if cep:
        r["cep"]    = cep.group(1)
        r["cidade"] = cep.group(2).strip()
        r["uf"]     = cep.group(3).upper()
    else:
        r["cep"] = r["cidade"] = r["uf"] = ""

    return r

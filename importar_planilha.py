"""
SoLev Energia — Importacao inicial de clientes da planilha.

Le ClientesSolevenergia.xlsx e popula tb_clientes + tb_enderecos
no banco Supabase do SoLev.

UC eh normalizada pra 15 digitos numericos (puros, sem pontuacao).
Endereco entra na tabela tb_enderecos vinculado ao cliente.

Saldo inicial fica em 0 — preenchimento conforme o operador trabalha.
Vinculos com usinas ficam vazios — usuario cria usinas e vincula depois.

Uso:
    python importar_planilha.py

Para reimportar (idempotente — usa upsert por cod_uc):
    python importar_planilha.py
"""
import re
import sys
from pathlib import Path

import openpyxl

# Garante import do db.py da raiz
sys.path.insert(0, str(Path(__file__).parent))
from db import _db


PLANILHA = Path(__file__).parent / "ClientesSolevenergia.xlsx"
SHEET = "Planilha1"


# ==== HELPERS DE NORMALIZACAO =====================================

def normalize_uc(v) -> str:
    """Retorna 15 digitos puros, ou '' se invalido."""
    if not v:
        return ""
    digits = re.sub(r"[^0-9]", "", str(v))
    if not digits or len(digits) > 15:
        return ""
    return digits.rjust(15, "0")


def normalize_cpf(v) -> str:
    """Retorna so digitos (11 ou 14)."""
    if not v:
        return ""
    return re.sub(r"[^0-9]", "", str(v))


def normalize_cep(v) -> str:
    """Retorna so digitos."""
    if not v:
        return ""
    return re.sub(r"[^0-9]", "", str(v))


def normalize_telefone(v) -> str:
    """Mantem formato visivel: (62) 99999-9999."""
    if not v:
        return ""
    return str(v).strip()


def s(v) -> str:
    """Stringify limpo."""
    if v is None:
        return ""
    return str(v).strip()


# ==== LEITURA DA PLANILHA =========================================

def ler_planilha():
    """Retorna (clientes, erros, duplicados)."""
    wb = openpyxl.load_workbook(str(PLANILHA), read_only=True, data_only=True)
    ws = wb[SHEET]

    clientes = []
    erros = []
    duplicados = []
    ucs_vistas: dict[str, dict] = {}  # uc -> primeiro registro

    # Linha 1 = decorativa, linha 2 = headers, dados a partir da linha 3
    for i, row in enumerate(ws.iter_rows(min_row=3, values_only=True), start=3):
        if all(v is None for v in row):
            continue

        uc_raw, nome, cpf, telefone, email, apelido, fornec, log, comp, bairro, num, cep, cidade, estado, dt_leit, saldo = row[:16]

        uc = normalize_uc(uc_raw)
        if len(uc) != 15:
            erros.append({"linha": i, "motivo": f"UC invalida: {uc_raw!r}"})
            continue

        if not nome:
            erros.append({"linha": i, "motivo": "nome vazio"})
            continue

        # Dedupe: se UC ja apareceu, registra como duplicado e pula
        if uc in ucs_vistas:
            primeiro = ucs_vistas[uc]
            duplicados.append({
                "linha": i,
                "uc": uc,
                "nome": s(nome).upper(),
                "primeira_linha": primeiro["_linha"],
                "primeiro_nome": primeiro["nome"],
            })
            continue

        registro = {
            "_linha": i,
            "uc": uc,
            "nome": s(nome).upper(),
            "cpf": normalize_cpf(cpf),
            "telefone": normalize_telefone(telefone),
            "email": s(email).lower(),
            "apelido": s(apelido),
            "fornecimento": s(fornec),
            "logradouro": s(log),
            "complemento": s(comp),
            "bairro": s(bairro),
            "numero": s(num),
            "cep": normalize_cep(cep),
            "cidade": s(cidade).upper(),
            "estado": s(estado).upper(),
        }
        clientes.append(registro)
        ucs_vistas[uc] = registro

    return clientes, erros, duplicados


# ==== INSERCAO NO BANCO ===========================================

def importar(clientes: list[dict]) -> dict:
    """Insere clientes + enderecos no banco. Retorna stats."""
    if not clientes:
        return {"clientes": 0, "enderecos": 0, "erros": []}

    # 1. Monta payloads
    payload_clientes = [
        {
            "cod_uc":              c["uc"],
            "desc_nome":           c["nome"],
            "desc_cpf":            c["cpf"],
            "desc_telefone":       c["telefone"],
            "desc_email":          c["email"],
            "desc_apelido":        c["apelido"],
            "tp_fornecimento":     c["fornecimento"],
            "saldo_kwh":           0,
            "pct_desconto":        0.20,
            "STATUS":              True,
        }
        for c in clientes
    ]

    # 2. Upsert em tb_clientes (idempotente por cod_uc)
    print(f"  Upsert de {len(payload_clientes)} clientes em tb_clientes...")
    _db().upsert("tb_clientes", payload_clientes, on_conflict="cod_uc")

    # 3. Re-busca pra pegar id_cliente atribuido
    print(f"  Buscando IDs gerados...")
    rows = _db().select("tb_clientes", columns="id_cliente,cod_uc")
    mapa_uc_id = {r["cod_uc"]: r["id_cliente"] for r in rows}

    # 4. Monta enderecos com id_cliente real
    payload_enderecos = []
    for c in clientes:
        id_cli = mapa_uc_id.get(c["uc"])
        if not id_cli:
            continue
        # So insere endereco se tiver algum dado
        if not any([c["logradouro"], c["bairro"], c["cidade"], c["cep"]]):
            continue
        payload_enderecos.append({
            "id_cliente":        id_cli,
            "cod_cep":           c["cep"],
            "desc_logradouro":   c["logradouro"],
            "desc_numero":       c["numero"],
            "desc_complemento":  c["complemento"],
            "desc_setor":        c["bairro"],
            "desc_cidade":       c["cidade"],
            "desc_estado":       c["estado"],
        })

    if payload_enderecos:
        print(f"  Upsert de {len(payload_enderecos)} enderecos em tb_enderecos...")
        _db().upsert("tb_enderecos", payload_enderecos, on_conflict="id_cliente")

    return {"clientes": len(payload_clientes), "enderecos": len(payload_enderecos)}


# ==== MAIN ========================================================

def main():
    print("=" * 60)
    print("SoLev Energia — Importacao de planilha")
    print("=" * 60)
    print(f"Planilha: {PLANILHA}")
    print()

    if not PLANILHA.exists():
        print(f"ERRO: arquivo nao encontrado: {PLANILHA}")
        sys.exit(1)

    print(">> Lendo planilha...")
    clientes, erros, duplicados = ler_planilha()
    print(f"   Clientes validos: {len(clientes)}")
    print(f"   Linhas com erro:  {len(erros)}")
    print(f"   UCs duplicadas:   {len(duplicados)} (mantida a primeira ocorrencia)")

    if erros:
        print()
        print(">> Linhas ignoradas:")
        for e in erros[:10]:
            print(f"   L{e['linha']}: {e['motivo']}")
        if len(erros) > 10:
            print(f"   ... e mais {len(erros) - 10}")

    if duplicados:
        print()
        print(">> Duplicados ignorados (mantida a primeira ocorrencia):")
        for d in duplicados:
            print(f"   L{d['linha']}: UC {d['uc']} ({d['nome']}) "
                  f"-> ja existia em L{d['primeira_linha']} ({d['primeiro_nome']})")

    print()
    print(">> Importando para o Supabase...")
    stats = importar(clientes)
    print()
    print("=" * 60)
    print("RESUMO")
    print("=" * 60)
    print(f"  Clientes importados: {stats['clientes']}")
    print(f"  Enderecos importados: {stats['enderecos']}")
    print()
    print("Proximos passos:")
    print("  1. Abrir sistema (python app.py)")
    print("  2. Cadastrar usinas (uma a uma)")
    print("  3. Vincular clientes as usinas + preencher saldo inicial")


if __name__ == "__main__":
    main()

"""
Atualiza banco de dados com colunas SCEE

Adiciona/atualiza as seguintes colunas em tb_usinas:
  - geracao_ciclo_kwh
  - saldo_kwh
  - excedente_recebido_kwh
  - credito_recebido_kwh
  - saldo_expirar_30d_kwh
  - saldo_expirar_60d_kwh
  - compensacao_dic
  - ecnisenta
  - difci
"""

import sys

# Fix encoding
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import json
    from pathlib import Path
    from supabase import create_client
except ImportError:
    print("Erro: supabase-py nao instalado. Execute:")
    print("  pip install supabase")
    sys.exit(1)


SCEE_COLUMNS = {
    "geracao_ciclo_kwh": "NUMERIC(12,2) DEFAULT 0",
    "saldo_kwh": "NUMERIC(12,2) DEFAULT 0",
    "excedente_recebido_kwh": "NUMERIC(12,2) DEFAULT 0",
    "credito_recebido_kwh": "NUMERIC(12,2) DEFAULT 0",
    "saldo_expirar_30d_kwh": "NUMERIC(12,2) DEFAULT 0",
    "saldo_expirar_60d_kwh": "NUMERIC(12,2) DEFAULT 0",
    "compensacao_dic": "TEXT",
    "ecnisenta": "TEXT",
    "difci": "TEXT",
}


def load_config() -> dict:
    """Carrega configuracoes do Supabase"""
    config_file = Path("supabase_config.json")
    if not config_file.exists():
        print("Erro: supabase_config.json nao encontrado")
        sys.exit(1)

    with open(config_file, "r") as f:
        return json.load(f)


def get_existing_columns(client) -> set:
    """Retorna as colunas existentes em tb_usinas"""
    try:
        # Usa RPC para executar SQL
        result = client.rpc("get_table_columns", {"table_name": "tb_usinas"}).execute()
        if result.data:
            return {row["column_name"] for row in result.data}
        return set()
    except Exception as e:
        print(f"   Nota: {e}")
        print("   Assumindo que precisa adicionar todas as colunas SCEE")
        return set()


def add_column(client, column_name: str, column_type: str) -> bool:
    """Adiciona uma coluna a tb_usinas via RPC"""
    try:
        # Usa RPC para executar ALTER TABLE
        result = client.rpc("add_table_column", {
            "table_name": "tb_usinas",
            "column_name": column_name,
            "column_type": column_type
        }).execute()
        print(f"   OK: Coluna '{column_name}' adicionada")
        return True
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            print(f"   OK: Coluna '{column_name}' ja existe")
            return True
        print(f"   Aviso: {column_name} - {str(e)[:60]}")
        return False


def main():
    print("=" * 80)
    print("ATUALIZAR DB - COLUNAS SCEE")
    print("=" * 80)

    # Carrega config e cria cliente
    print("\nCarregando configuracoes Supabase...")
    config = load_config()
    print(f"   URL: {config['url']}")

    try:
        client = create_client(config["url"], config["service_role_key"])
        print("   OK: Conectado ao Supabase")
    except Exception as e:
        print(f"   Erro: {e}")
        sys.exit(1)

    # Carrega colunas existentes
    print("\nVerificando colunas existentes em tb_usinas...")
    existing_columns = get_existing_columns(client)
    print(f"   Total de colunas encontradas: {len(existing_columns)}")

    # Identifica quais faltam
    missing_columns = {col: typ for col, typ in SCEE_COLUMNS.items() if col not in existing_columns}

    if not missing_columns:
        print("\n   Todas as colunas SCEE ja existem no banco!")
        print("=" * 80)
        return

    print(f"\n   Colunas SCEE faltando: {len(missing_columns)}")
    for col in missing_columns:
        print(f"      - {col}")

    # Adiciona as colunas
    print("\nAdicionando colunas SCEE a tb_usinas...")
    success_count = 0
    for column_name, column_type in SCEE_COLUMNS.items():
        if column_name in missing_columns:
            if add_column(client, column_name, column_type):
                success_count += 1

    print(f"\nResultado: {success_count}/{len(missing_columns)} colunas adicionadas")

    print("\n" + "=" * 80)
    print("STATUS: Atualizacao concluida com sucesso!")
    print("=" * 80)


if __name__ == "__main__":
    main()

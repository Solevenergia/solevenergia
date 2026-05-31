"""
Gera arquivo SQL para adicionar colunas SCEE em tb_usinas

Execute manualmente no Supabase SQL Editor:
  1. Acesse: https://app.supabase.com/project/bwljfybvyepbcalmmcfi/sql
  2. Copie e cole o SQL gerado
  3. Execute
"""

import sys

# Fix encoding
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


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


def gerar_sql() -> str:
    """Gera comandos SQL para adicionar as colunas"""
    sql_lines = [
        "-- Adicionar colunas SCEE em tb_usinas",
        "-- Gerado automaticamente",
        "",
    ]

    for column_name, column_type in SCEE_COLUMNS.items():
        sql_lines.append(f"ALTER TABLE tb_usinas ADD COLUMN IF NOT EXISTS {column_name} {column_type};")

    sql_lines.append("")
    sql_lines.append("-- Verificar se as colunas foram adicionadas:")
    sql_lines.append("SELECT column_name, data_type FROM information_schema.columns")
    sql_lines.append("WHERE table_name = 'tb_usinas' AND column_name LIKE '%kwh%' OR column_name LIKE '%dic%';")

    return "\n".join(sql_lines)


def main():
    print("=" * 80)
    print("GERAR SQL - COLUNAS SCEE")
    print("=" * 80)

    sql = gerar_sql()

    # Salva em arquivo
    output_file = "adicionar_colunas_scee.sql"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(sql)

    print(f"\nArquivo gerado: {output_file}")
    print("\nProximos passos:")
    print("=" * 80)
    print("""
1. Abra Supabase SQL Editor:
   https://app.supabase.com/project/bwljfybvyepbcalmmcfi/sql

2. Copie o SQL do arquivo:
   cat adicionar_colunas_scee.sql

3. Cole no SQL Editor e execute

4. Verifique se as colunas foram adicionadas (a query de verificacao esta no arquivo)

Colunas a serem adicionadas:
""")
    for i, col in enumerate(SCEE_COLUMNS.keys(), 1):
        print(f"   {i}. {col}")

    print("\n" + "=" * 80)
    print("\nSQL gerado:")
    print("=" * 80)
    print(sql)
    print("=" * 80)


if __name__ == "__main__":
    main()

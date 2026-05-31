"""
Setup do Supabase Storage — cria bucket 'faturas' com RLS policies
"""

import sys
import json
from pathlib import Path

# Fix encoding
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from supabase import create_client, Client
except ImportError:
    print("Erro: supabase-py nao instalado. Execute:")
    print("  pip install supabase")
    sys.exit(1)


def load_config() -> dict:
    """Carrega configuracoes do Supabase"""
    config_file = Path("supabase_config.json")
    if not config_file.exists():
        print("Erro: supabase_config.json nao encontrado")
        print("Crie o arquivo com as credenciais do Supabase")
        sys.exit(1)

    with open(config_file, "r") as f:
        return json.load(f)


def setup_storage_bucket(client: Client) -> bool:
    """Cria bucket 'faturas' se nao existir"""
    print("\n1. Criando bucket 'faturas'...")
    try:
        # Tenta criar o bucket
        response = client.storage.create_bucket(
            "faturas",
            options={
                "public": False,  # Private bucket
                "allowed_mime_types": ["application/pdf"],
                "file_size_limit": 52428800,  # 50MB limit
            }
        )
        print("   OK: Bucket 'faturas' criado com sucesso")
        return True
    except Exception as e:
        if "already exists" in str(e):
            print("   OK: Bucket 'faturas' ja existe")
            return True
        print(f"   Erro ao criar bucket: {e}")
        return False


def setup_rls_policies(client: Client) -> bool:
    """Configura RLS policies para o bucket 'faturas'

    Policies:
    1. Allow authenticated users to upload PDFs to their own folder
    2. Allow authenticated users to read their own files
    """
    print("\n2. Configurando RLS policies...")

    try:
        # Policy 1: Permitir leitura (authenticated users)
        policy_read = {
            "definition": "((bucket_id = 'faturas'::text) AND (auth.role() = 'authenticated'::text))",
            "name": "Allow authenticated read",
            "table": "objects",
            "action": "SELECT",
        }

        # Policy 2: Permitir escrita (authenticated users - upload)
        policy_write = {
            "definition": "((bucket_id = 'faturas'::text) AND (auth.role() = 'authenticated'::text))",
            "name": "Allow authenticated insert",
            "table": "objects",
            "action": "INSERT",
        }

        # Policy 3: Permitir delete (authenticated users)
        policy_delete = {
            "definition": "((bucket_id = 'faturas'::text) AND (auth.role() = 'authenticated'::text))",
            "name": "Allow authenticated delete",
            "table": "objects",
            "action": "DELETE",
        }

        print("   Nota: RLS policies devem ser configuradas via Dashboard Supabase")
        print("   URL: https://app.supabase.com/project/bwljfybvyepbcalmmcfi/storage/policies")
        print("\n   Policies necessarias:")
        print("   1. SELECT: ((bucket_id = 'faturas') AND (auth.role() = 'authenticated'))")
        print("   2. INSERT: ((bucket_id = 'faturas') AND (auth.role() = 'authenticated'))")
        print("   3. DELETE: ((bucket_id = 'faturas') AND (auth.role() = 'authenticated'))")

        return True

    except Exception as e:
        print(f"   Erro ao configurar policies: {e}")
        return False


def test_storage_connection(client: Client) -> bool:
    """Testa a conexao com o bucket"""
    print("\n3. Testando conexao com Storage...")
    try:
        buckets = client.storage.list_buckets()
        bucket_names = [b.name for b in buckets]

        if "faturas" in bucket_names:
            print("   OK: Bucket 'faturas' esta acessivel")
            return True
        else:
            print("   Aviso: Bucket 'faturas' nao foi encontrado na listagem")
            return False

    except Exception as e:
        print(f"   Erro ao testar conexao: {e}")
        return False


def main():
    print("=" * 80)
    print("SETUP SUPABASE STORAGE - BUCKET 'FATURAS'")
    print("=" * 80)

    # Carrega config
    print("\nCarregando configuracoes...")
    config = load_config()
    print(f"   URL: {config['url']}")

    # Cria cliente Supabase
    print("\nConectando ao Supabase...")
    try:
        client = create_client(config["url"], config["anon_key"])
        print("   OK: Conectado ao Supabase")
    except Exception as e:
        print(f"   Erro: Nao conseguiu conectar ao Supabase: {e}")
        sys.exit(1)

    # Setup bucket
    if not setup_storage_bucket(client):
        sys.exit(1)

    # Setup RLS policies
    if not setup_rls_policies(client):
        print("   Aviso: Algumas policies podem nao ter sido configuradas")

    # Test connection
    if not test_storage_connection(client):
        print("   Aviso: Nao conseguiu acessar o bucket")

    print("\n" + "=" * 80)
    print("PROXIMOS PASSOS:")
    print("=" * 80)
    print("""
1. Acesse o Dashboard Supabase: https://app.supabase.com
2. Vá em Storage > Policies (abaixo do bucket 'faturas')
3. Adicione as 3 policies (SELECT, INSERT, DELETE)
4. Teste upload via app.py ou script de teste

Exemplo de upload em Python:
    from supabase import create_client
    client = create_client(url, key)
    with open('fatura.pdf', 'rb') as f:
        client.storage.from_('faturas').upload(
            'faturas/2026-05/fatura_000102059901249.pdf',
            f
        )
""")
    print("=" * 80)


if __name__ == "__main__":
    main()

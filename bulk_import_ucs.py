"""
Bulk Import de UCs no SOLEV

Importa as UCs faltando do arquivo ucs_faltando.txt
Requer dados minimos: UC, CPF, Nome

Uso:
  python bulk_import_ucs.py --arquivo ucs_faltando.txt --cpf 01873853190 --nome "Pessoa Titular"
  python bulk_import_ucs.py --csv dados_ucs.csv --dry-run  (simular sem salvar)
"""

import sys
import argparse
import csv
from pathlib import Path
from typing import Optional, List, Dict

# Fix encoding
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from db import tb_get_cliente_por_uc, tb_save_cliente, tb_get_usinas_do_cliente, tb_save_cliente_usina
except ImportError:
    print("Erro: nao conseguiu importar db.py")
    sys.exit(1)


def carregar_ucs_texto(arquivo: str) -> List[str]:
    """Carrega UCs de arquivo texto (uma por linha)"""
    try:
        with open(arquivo, "r", encoding="utf-8") as f:
            ucs = [line.strip() for line in f if line.strip()]
        return ucs
    except Exception as e:
        print(f"Erro ao carregar {arquivo}: {e}")
        return []


def carregar_ucs_csv(arquivo: str) -> List[Dict]:
    """Carrega UCs de arquivo CSV com colunas: UC,CPF,Nome,Endereco,CEP,Cidade,UF"""
    try:
        dados = []
        with open(arquivo, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dados.append(row)
        return dados
    except Exception as e:
        print(f"Erro ao carregar {arquivo}: {e}")
        return []


def registrar_cliente(uc: str, cpf: str, nome: str, endereco: str = "", cep: str = "",
                     cidade: str = "", uf: str = "") -> Optional[dict]:
    """Registra um novo cliente no banco"""
    try:
        # Verifica se ja existe
        cliente = tb_get_cliente_por_uc(uc)
        if cliente:
            return {"status": "existe", "id_cliente": cliente["id_cliente"]}

        # Cria novo cliente
        dados_cliente = {
            "cod_uc": uc,
            "desc_cpf": cpf,
            "desc_nome": nome,
            "desc_endereco": endereco,
            "desc_cep": cep,
            "desc_cidade": cidade,
            "desc_uf": uf,
        }

        resultado = tb_save_cliente(dados_cliente)
        if resultado:
            return {"status": "criado", "id_cliente": resultado.get("id_cliente")}
        else:
            return {"status": "erro", "mensagem": "Nao conseguiu criar cliente"}

    except Exception as e:
        return {"status": "erro", "mensagem": str(e)}


def registrar_cliente_usina(id_cliente: int, id_usina: int = 1) -> bool:
    """Vincula cliente a uma usina (geradora solar)"""
    try:
        # Usa a usina padrao (id=1) ou primeira disponivel
        dados = {"dt_inicio": "2026-05-24", "dt_fim": None}
        tb_save_cliente_usina(id_cliente, id_usina, dados)
        return True
    except Exception as e:
        print(f"      Erro ao vincular usina: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Bulk import de UCs no SOLEV",
        epilog="""
Exemplos:
  python bulk_import_ucs.py --arquivo ucs_faltando.txt --cpf 01873853190 --nome "Titular"
  python bulk_import_ucs.py --csv dados_ucs.csv --dry-run
        """
    )

    parser.add_argument("--arquivo", help="Arquivo texto com UCs (uma por linha)")
    parser.add_argument("--csv", help="Arquivo CSV com dados completos (UC,CPF,Nome,Endereco,CEP,Cidade,UF)")
    parser.add_argument("--cpf", help="CPF para todas as UCs (quando usando --arquivo)")
    parser.add_argument("--nome", default="Cliente SOLEV", help="Nome para todas as UCs")
    parser.add_argument("--dry-run", action="store_true", help="Simular sem salvar no banco")
    parser.add_argument("--usina-id", type=int, default=1, help="ID da usina para vincular (padrao: 1)")

    args = parser.parse_args()

    # Validacoes
    if not args.arquivo and not args.csv:
        print("Erro: Especifique --arquivo ou --csv")
        sys.exit(1)

    if args.arquivo and not args.cpf:
        print("Erro: Ao usar --arquivo, especifique --cpf")
        sys.exit(1)

    print("=" * 80)
    print("BULK IMPORT DE UCs - SOLEV")
    print("=" * 80)

    # Carrega dados
    if args.arquivo:
        print(f"\nCarregando UCs de {args.arquivo}...")
        ucs = carregar_ucs_texto(args.arquivo)
        if not ucs:
            print("Erro: Nenhuma UC foi carregada")
            sys.exit(1)

        dados_import = [{"uc": uc, "cpf": args.cpf, "nome": args.nome} for uc in ucs]

    else:  # CSV
        print(f"\nCarregando dados de {args.csv}...")
        csv_data = carregar_ucs_csv(args.csv)
        if not csv_data:
            print("Erro: Nenhum dado foi carregado")
            sys.exit(1)

        dados_import = [
            {
                "uc": row.get("UC", "").strip(),
                "cpf": row.get("CPF", "").strip(),
                "nome": row.get("Nome", "").strip(),
                "endereco": row.get("Endereco", "").strip(),
                "cep": row.get("CEP", "").strip(),
                "cidade": row.get("Cidade", "").strip(),
                "uf": row.get("UF", "").strip(),
            }
            for row in csv_data
        ]

    print(f"Total de UCs a registrar: {len(dados_import)}")

    if args.dry_run:
        print("\n[DRY RUN] Nenhuma alteracao sera feita")

    # Processa cada UC
    print(f"\nProcessando {len(dados_import)} registros...")
    print("-" * 80)

    criados = 0
    existentes = 0
    erros = 0

    for i, dados in enumerate(dados_import, 1):
        uc = dados.get("uc")
        cpf = dados.get("cpf")
        nome = dados.get("nome")

        print(f"{i:3d}. UC {uc} - {nome[:30]}")

        if args.dry_run:
            print(f"       [DRY] Seria criado/atualizado")
            criados += 1
            continue

        # Registra cliente
        resultado = registrar_cliente(
            uc, cpf, nome,
            endereco=dados.get("endereco", ""),
            cep=dados.get("cep", ""),
            cidade=dados.get("cidade", ""),
            uf=dados.get("uf", "")
        )

        if not resultado:
            print(f"       Erro ao registrar")
            erros += 1
            continue

        status = resultado.get("status")
        if status == "criado":
            id_cliente = resultado.get("id_cliente")
            # Vincula a usina
            if registrar_cliente_usina(id_cliente, args.usina_id):
                print(f"       Criado e vinculado com sucesso")
                criados += 1
            else:
                print(f"       Criado mas falhou vinculacao com usina")
                erros += 1

        elif status == "existe":
            print(f"       Ja existe no banco")
            existentes += 1

        else:
            msg = resultado.get("mensagem", "Erro desconhecido")
            print(f"       Erro: {msg}")
            erros += 1

    # Resumo
    print("\n" + "=" * 80)
    print("RESUMO:")
    print("=" * 80)
    print(f"  Total processado:  {len(dados_import)}")
    print(f"  Novos registros:   {criados}")
    print(f"  Ja existentes:     {existentes}")
    print(f"  Erros:             {erros}")

    if args.dry_run:
        print(f"\n[DRY RUN] Para executar de verdade, remova --dry-run")

    print("=" * 80)


if __name__ == "__main__":
    main()

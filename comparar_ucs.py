"""
Compara UCs do portal Equatorial com as UCs cadastradas no SOLEV.

Identifica quais UCs precisam ser cadastradas.
"""

import json
import sys
from pathlib import Path

# Fix encoding for Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Adiciona diretório ao path para importar db
sys.path.insert(0, str(Path(__file__).parent))

try:
    from db import tb_mapa_uc_para_usina
except ImportError as e:
    print(f"❌ Erro ao importar db.py: {e}")
    sys.exit(1)


def carregar_ucs_equatorial(arquivo_json: str = "ucs_equatorial.json") -> list:
    """Carrega lista de UCs do arquivo JSON gerado pelo listar_ucs_equatorial.py"""
    try:
        with open(arquivo_json, "r", encoding="utf-8") as f:
            dados = json.load(f)
        return [uc["valor"].strip() for uc in dados if uc.get("valor")]
    except Exception as e:
        print(f"Erro ao carregar {arquivo_json}: {e}")
        return []


def carregar_ucs_solev() -> list:
    """Carrega todas as UCs já cadastradas no SOLEV"""
    try:
        mapa = tb_mapa_uc_para_usina()
        if not mapa:
            return []
        return list(mapa.keys())
    except Exception as e:
        print(f"Erro ao carregar UCs do SOLEV: {e}")
        return []


def main():
    print("=" * 90)
    print("COMPARACAO DE UCs - EQUATORIAL vs SOLEV")
    print("=" * 90)

    # Carrega UCs do Equatorial
    print("\nCarregando UCs do portal Equatorial...")
    ucs_equatorial = carregar_ucs_equatorial()
    print(f"   OK: Total de UCs no Equatorial: {len(ucs_equatorial)}")

    if not ucs_equatorial:
        print("ERRO: Nenhuma UC foi carregada do arquivo.")
        sys.exit(1)

    # Carrega UCs do SOLEV
    print("\nCarregando UCs cadastradas no SOLEV...")
    ucs_solev = carregar_ucs_solev()
    print(f"   OK: Total de UCs no SOLEV: {len(ucs_solev)}")

    # Converte para set para comparação
    set_equatorial = set(ucs_equatorial)
    set_solev = set(ucs_solev)

    # Identifica UCs faltando
    faltando = set_equatorial - set_solev
    extras = set_solev - set_equatorial

    # Resultados
    print("\n" + "=" * 90)
    print("RESULTADOS:")
    print("=" * 90)
    print(f"  Total no Equatorial: {len(set_equatorial)}")
    print(f"  Total no SOLEV:      {len(set_solev)}")
    print(f"  Ja cadastradas:      {len(set_equatorial & set_solev)}")
    print(f"  FALTANDO:            {len(faltando)}")
    print(f"  EXTRAS (no SOLEV mas nao no Equatorial): {len(extras)}")

    if faltando:
        print(f"\nUCs FALTANDO ({len(faltando)}):")
        print("-" * 90)
        for i, uc in enumerate(sorted(faltando), 1):
            print(f"  {i:3d}. {uc}")

        # Salva em arquivo
        output_file = "ucs_faltando.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(faltando)))
        print(f"\nLista salva em: {output_file}")

    if extras:
        print(f"\nUCs EXTRAS no SOLEV ({len(extras)}):")
        print("-" * 90)
        for i, uc in enumerate(sorted(extras), 1):
            print(f"  {i:3d}. {uc}")

    print("\n" + "=" * 90)


if __name__ == "__main__":
    main()

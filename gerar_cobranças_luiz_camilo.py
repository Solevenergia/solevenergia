"""
gerar_cobranças_luiz_camilo.py
Gera cobranças SOLEV para os 2 UCs do Luiz Camilo de Oliveira (abril/2026),
usando os PDFs Equatorial já presentes em Desktop\\Usinas\\Todos.

Cliente 263 (UC 000148948401217) → vínculo FIXO 90% USJoseOliveira88
Cliente 264 (UC 000358864801258) → vínculo FIXO 100% USJoseOliveira93 + 10% USJoseOliveira88

Execute: python gerar_cobranças_luiz_camilo.py
"""
import os, sys, io
sys.path.insert(0, r"C:\Rede\SOLEV")
sys.path.insert(0, r"C:\Rede\SOLEV\scripts")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from baixar_equatorial import gerar_cobranca_cliente

MES_STR = "202604"

# (uc, nome_camel, pdf_path)
ALVOS = [
    (
        "000148948401217",
        "LuizCamiloOliveira17",
        r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\LuizOliveira17-0001.489.484012-17\202604-EquatorialLuizOliveria17.pdf",
    ),
    (
        "000358864801258",
        "LuizCamiloOliveira58",
        r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\LuizOliveira58-0003.588.648.012-58\202604-EquatorialLuizOliveria58.pdf",
    ),
]


def main():
    print(f"\n{'='*60}")
    print(f"  Geracao de cobrancas — Luiz Camilo de Oliveira")
    print(f"  Mes referencia: 04/2026")
    print(f"{'='*60}\n")

    ok = falha = 0
    for uc, nome_camel, pdf in ALVOS:
        print(f"\n--- UC {uc} ---")
        if not os.path.exists(pdf):
            print(f"  X PDF nao encontrado: {pdf}")
            falha += 1
            continue
        print(f"  PDF: {os.path.basename(pdf)}")
        pasta_cli = os.path.dirname(pdf)

        # Checa se cobranca ja existe
        cob_esperada = os.path.join(pasta_cli, f"{MES_STR}-SoLev{nome_camel}.pdf")
        if os.path.exists(cob_esperada):
            print(f"  -> Cobranca ja existe: {os.path.basename(cob_esperada)}")
            ok += 1
            continue

        try:
            resultado = gerar_cobranca_cliente(pdf, pasta_cli, MES_STR, nome_camel, uc)
            if resultado:
                ok += 1
            else:
                # tenta achar com nome alternativo
                achado = False
                for arq in os.listdir(pasta_cli):
                    if arq.startswith(MES_STR) and "SoLev" in arq:
                        print(f"  OK cobranca encontrada: {arq}")
                        ok += 1
                        achado = True
                        break
                if not achado:
                    falha += 1
        except Exception as e:
            print(f"  X Erro: {e}")
            import traceback
            traceback.print_exc()
            falha += 1

    print(f"\n{'='*60}")
    print(f"  Geradas: {ok}  |  Falhas: {falha}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

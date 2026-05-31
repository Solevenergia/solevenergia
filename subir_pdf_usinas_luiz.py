"""
subir_pdf_usinas_luiz.py
Sobe os PDFs Equatorial das usinas Jose Oliveira (88 e 93) para o Supabase Storage.
Convenção: bucket 'faturas' + key 'usinas/<id_usina>/<YYYYMM>.pdf'

Executa uma vez. Idempotente (sobrescreve se já existir).
"""
import os, sys, io
sys.path.insert(0, r"C:\Rede\SOLEV")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from db import storage_upload_pdf

# (id_usina, "MM/YYYY") → caminho local
USINAS = {
    (23, "03/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USjoseOliveira88-0003.954.137.012-88\202603-EquatorialUCJoseOliveira88.pdf",
    (23, "04/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USjoseOliveira88-0003.954.137.012-88\202604-EquatorialUCJoseOliveira88.pdf",
    (23, "05/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USjoseOliveira88-0003.954.137.012-88\202605-EquatorialUCJoseOliveira88.pdf",
    (22, "03/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USJoseOliveira93-0004.322.044.012-93\202603-EquatorialUCJoseOliveira93.pdf",
    (22, "04/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USJoseOliveira93-0004.322.044.012-93\202604-EquatorialUCJoseOliveira93.pdf",
}


def main():
    print(f"\n{'='*60}")
    print("  Upload PDFs Equatorial USINAS -> Supabase Storage")
    print(f"{'='*60}\n")
    ok = falha = 0
    for (id_usina, ciclo), caminho in USINAS.items():
        if not os.path.exists(caminho):
            print(f"  X (id={id_usina} {ciclo}) PDF nao encontrado: {caminho}")
            falha += 1
            continue
        mes, ano = ciclo.split("/")
        yyyymm = f"{ano}{int(mes):02d}"
        storage_filename = f"usinas/{id_usina}/{yyyymm}.pdf"
        try:
            path = storage_upload_pdf(caminho, storage_filename, bucket="faturas")
            print(f"  OK id={id_usina} {ciclo} -> {path}")
            ok += 1
        except Exception as e:
            print(f"  X id={id_usina} {ciclo}: {e}")
            falha += 1
    print(f"\n  Total: {ok} OK, {falha} falhas\n")


if __name__ == "__main__":
    main()

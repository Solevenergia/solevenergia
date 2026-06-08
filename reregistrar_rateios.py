"""Re-registra os rateios de 28/05 em tb_rateios_mensais a partir dos PDFs assinados.

Re-rodável: registra os rateios cuja usina geradora JÁ existe em tb_usinas;
pula (com aviso) os de usinas ainda não recadastradas. Quando as usinas
faltantes forem criadas, rode de novo e os pendentes entram.

Só grava o SNAPSHOT mensal (tb_rateios_mensais) — não mexe em vínculos.
"""
import sys, re, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pdfplumber
from db import _db, tb_save_rateio_mes

MES_REF = "5/2026"  # mês de referência (ajuste aqui se precisar mudar onde aparece)
PDFS = ["Rateio_27.pdf", "Rateio_30.pdf", "Rateio_31.pdf"]


def digitos(s):
    return re.sub(r"\D", "", str(s or ""))


def main():
    db = _db()
    usinas = {digitos(u.get("cod_uc_geradora")): u for u in db.select("tb_usinas")}
    cli_por_uc = {digitos(c.get("cod_uc")): c.get("desc_nome", "")
                  for c in db.select("tb_clientes") if c.get("cod_uc")}

    registrados, pendentes = 0, []
    for pdf in PDFS:
        if not os.path.exists(pdf):
            print(f"{pdf}: arquivo não encontrado, pulando."); continue
        with pdfplumber.open(pdf) as p:
            txt = "\n".join((pg.extract_text() or "") for pg in p.pages)

        ger = re.search(r"Codigo da UC:\s*([\d.\-]+)", txt)
        ger_uc = ger.group(1) if ger else ""
        rows = re.findall(r"^\s*(\d+)\s+([\d.]+-\d+)\s+([\d./-]+)\s+([\d.]+)%", txt, re.M)
        # data_registro é coluna date/time no Supabase → precisa ser ISO (YYYY-MM-DD[ HH:MM:SS])
        sig = re.search(r"Dados:\s*(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}:\d{2}:\d{2})", txt)
        data_reg = (f"{sig.group(1)}-{sig.group(2)}-{sig.group(3)} {sig.group(4)}"
                    if sig else "2026-05-28 12:00:00")

        beneficiarios = [{
            "uc":         digitos(uc),
            "percentual": float(pct),
            "cpf":        cpf,
            "nome":       cli_por_uc.get(digitos(uc), ""),
        } for _, uc, cpf, pct in rows]
        soma = round(sum(b["percentual"] for b in beneficiarios), 2)

        u = usinas.get(digitos(ger_uc))
        print(f"\n{pdf}: geradora {ger_uc} | {len(beneficiarios)} benef | soma {soma}% | registro {data_reg}")
        if u:
            tb_save_rateio_mes(u["id_usina"], MES_REF, beneficiarios, soma, data_reg)
            registrados += 1
            print(f"  -> REGISTRADO: usina id={u['id_usina']} {u['desc_nome']} | mês {MES_REF}")
        else:
            pendentes.append((pdf, ger_uc))
            print(f"  -> PENDENTE: usina geradora UC {ger_uc} ainda não recadastrada")

    print(f"\n{'='*60}")
    print(f"Registrados: {registrados} | Pendentes: {len(pendentes)}")
    for pdf, uc in pendentes:
        print(f"  pendente: {pdf} (geradora {uc}) — recadastre a usina e rode de novo")


if __name__ == "__main__":
    main()

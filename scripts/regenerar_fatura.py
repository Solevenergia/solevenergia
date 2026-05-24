"""
Regenera o PDF de uma ou mais faturas existentes e faz upload pro Supabase Storage.

Uso:
    python scripts/regenerar_fatura.py 6              # regenera fatura id=6
    python scripts/regenerar_fatura.py 6 49           # regenera 6 e 49
    python scripts/regenerar_fatura.py 6 --so-upload  # nao regenera, so faz upload do PDF existente

Faz:
  1) Lê fatura + cliente + tarifa do mês do Supabase
  2) Recalcula valores com a lógica corrente (calcular)
  3) Gera novo PDF em uploads/
  4) Faz upload pro bucket 'faturas/' no Storage
  5) Atualiza tb_faturas (pdf_solev, pdf_solev_url, valores)
  6) Recalcula economia acumulada do cliente
"""
import sys, os, argparse
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv; load_dotenv()
from db import _db, storage_upload_pdf, recalcular_economia_acumulada
from utils import obter_tarifa_mes
from contalev_cobranca_v2_padrao import gerar_cobranca, calcular

db = _db()


def montar_dados(fatura, cliente, tarifa_mes):
    """Reusa lógica do regenerar_paulo.py."""
    from datetime import datetime
    mes_ref_br = f"{fatura['mes_referencia']:d}/{fatura['ano_referencia']}"

    def _iso_to_br(s):
        if not s: return ""
        try: return datetime.strptime(str(s)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception: return str(s)

    return {
        "id_cliente":   cliente.get("id_cliente"),
        "id_fatura":    fatura.get("id_fatura"),
        "nome":         cliente.get("desc_nome", ""),
        "cpf":          cliente.get("desc_cpf", ""),
        "endereco":     cliente.get("desc_endereco", ""),
        "endereco_linha1": cliente.get("desc_endereco_linha1", ""),
        "endereco_linha2": cliente.get("desc_endereco_linha2", ""),
        "endereco_linha3": cliente.get("desc_endereco_linha3", ""),
        "cep":          cliente.get("cod_cep", ""),
        "unidade_consumidora": cliente.get("cod_uc", ""),
        "tipo_fornecimento":   cliente.get("tp_fornecimento", "Trifásico") or "Trifásico",
        "modo_bandeira":   cliente.get("tp_bandeira", "com_bandeira") or "com_bandeira",
        "desconto_pct":    float(cliente.get("pct_desconto") or 0),
        "mes_referencia":  mes_ref_br,
        "tarifa_sem":           float(tarifa_mes.get("tarifa_sem") or 0),
        "bandeira_tarifa_amar": float(tarifa_mes.get("bandeira_amarela") or 0),
        "bandeira_tarifa_verm": float(tarifa_mes.get("bandeira_vermelha") or 0),
        "consumo_kwh":          float(fatura.get("qtd_consumo_kwh") or 0),
        "consumo_compensado":   float(fatura.get("qtd_compensado_kwh") or 0),
        "consumo_nao_comp":     float(fatura.get("qtd_consumo_kwh") or 0) - float(fatura.get("qtd_compensado_kwh") or 0),
        "iluminacao_publica":   float(fatura.get("vlr_ilum_publica") or 0),
        "multa":                float(fatura.get("vlr_multa_equatorial") or 0),
        "juros":                float(fatura.get("vlr_juros_equatorial") or 0),
        "difci":                float(fatura.get("difci") or 0),
        "ecnisenta":            float(fatura.get("ecnisenta") or 0),
        "ajuste_valor":         float(fatura.get("ajuste_valor") or 0),
        "compensacao_dic":      float(fatura.get("vlr_compensacao_dic") or 0),
        "economia_acumulada_anterior": 0,
        "valor_cobranca_anterior": 0,
        "venc_solev_anterior": "",
        "data_pagamento_anterior": "",
        "anterior_leitura":  fatura.get("anterior_leitura") or "",
        "data_leitura":      _iso_to_br(fatura.get("dt_leitura_atual")),
        "proxima_leitura":   "",
        "n_dias":            fatura.get("n_dias") or 30,
        "venc_equatorial":   _iso_to_br(fatura.get("dt_venc_equatorial")),
        "vencimento_solev":  _iso_to_br(fatura.get("dt_venc_solev")),
        "pix_payload":       cliente.get("desc_pix_payload", "") or "",
        "codigo_barras":     "CODIGO DE BARRA EM DESENVOLVIMENTO",
        "linha_digitavel":   "XXXX.XXXX  XXXXX.XXXXX  XXXXX.XXXXX  X  XXXXXXXXXXXXXX",
        "equatorial_pdf":    os.path.join("uploads", str(fatura.get("pdf_equatorial") or "")) if fatura.get("pdf_equatorial") else None,
    }


def regenerar(id_fatura, so_upload=False):
    print(f"\n{'='*60}\n  FATURA #{id_fatura}\n{'='*60}")
    fats = db.select("tb_faturas", filtros={"id_fatura": id_fatura})
    if not fats:
        print(f"  ERRO: fatura {id_fatura} não encontrada"); return False
    fatura = fats[0]

    cli = db.select("tb_clientes", filtros={"id_cliente": fatura["id_cliente"]})[0]
    print(f"  Cliente: {cli['desc_nome']}  UC: {cli.get('cod_uc')}")
    mes_ref_br = f"{fatura['mes_referencia']:d}/{fatura['ano_referencia']}"

    if so_upload:
        # Pula geração — só faz upload do arquivo que já existe
        nome = fatura.get("pdf_solev")
        if not nome:
            print(f"  ERRO: tb_faturas.pdf_solev vazio — sem nome de arquivo pra subir"); return False
        path = os.path.join("uploads", nome)
        if not os.path.isfile(path):
            print(f"  ERRO: arquivo local não existe: {path}"); return False
        print(f"  Upload (só) de {path}...")
        url = storage_upload_pdf(path, nome, "faturas")
        db.patch("tb_faturas", {"id_fatura": id_fatura}, {"pdf_solev_url": url})
        print(f"  ✓ pdf_solev_url atualizado: {url[:80]}...")
        return True

    tarifa = obter_tarifa_mes(mes_ref_br)
    if not tarifa:
        print(f"  ERRO: tarifa {mes_ref_br} não encontrada"); return False

    dados = montar_dados(fatura, cli, tarifa)

    print(f"\n  Gerando PDF...")
    gerar_cobranca(dados)
    novo_pdf = dados.get("output_path", "")
    if not novo_pdf or not os.path.isfile(novo_pdf):
        print(f"  ERRO: PDF não foi gerado: {novo_pdf}"); return False
    print(f"  PDF: {novo_pdf}")

    calc = calcular(dados)
    print(f"  total_sem=R$ {calc['_total_sem']:.2f}  total_com=R$ {calc['_total_com']:.2f}  economia=R$ {calc['_economia_mes']:.2f}")

    print(f"\n  Upload pro Storage...")
    try:
        url = storage_upload_pdf(novo_pdf, os.path.basename(novo_pdf), "faturas")
        print(f"  URL: {url[:100]}...")
    except Exception as e:
        print(f"  AVISO upload falhou: {e}"); url = ""

    update = {
        "vlr_total_sem":       round(calc["_total_sem"], 2),
        "vlr_total_com":       round(calc["_total_com"], 2),
        "vlr_economia_mes":    round(calc["_economia_mes"], 2),
        "vlr_band_amar_solev": round(calc["_band_amar_solev"], 2),
        "vlr_band_verm_solev": round(calc["_band_verm_solev"], 2),
        "pdf_solev":           os.path.basename(novo_pdf),
    }
    if url: update["pdf_solev_url"] = url
    db.patch("tb_faturas", {"id_fatura": id_fatura}, update)
    print(f"  ✓ tb_faturas atualizado")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ids", nargs="+", type=int, help="IDs de fatura(s) pra regenerar")
    p.add_argument("--so-upload", action="store_true", help="Pula geração, só faz upload do PDF local")
    args = p.parse_args()

    ok = 0
    clientes_afetados = set()
    for id_fat in args.ids:
        try:
            if regenerar(id_fat, so_upload=args.so_upload):
                ok += 1
                fat = db.select("tb_faturas", filtros={"id_fatura": id_fat})
                if fat: clientes_afetados.add(fat[0]["id_cliente"])
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  ERRO em {id_fat}: {e}")

    print(f"\n{'='*60}\n  {ok}/{len(args.ids)} faturas processadas\n{'='*60}")

    if clientes_afetados and not args.so_upload:
        print("\nRecalculando economia acumulada...")
        for cid in clientes_afetados:
            v = recalcular_economia_acumulada(cid)
            print(f"  cliente id={cid}: economia_acumulada = R$ {v}")


if __name__ == "__main__":
    main()

"""
Regenera as faturas/PDFs do Paulo Ricardo (faturas 63 e 65) aplicando
a lógica corrigida de bandeira (modo "Não compensar" = bandeira embutida).

Uso:
    python scripts/regenerar_paulo.py
"""
import sys, os
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv; load_dotenv()
from db import _db, inserir_fatura, storage_ensure_bucket, storage_upload_pdf
from utils import obter_tarifa_mes, _formatar_chave_pix_display, gerar_qrcode_pix
from contalev_cobranca_v2_padrao import gerar_cobranca, calcular

db = _db()

# Faturas a regenerar
IDS_FATURAS = [63, 65]


def montar_dados_da_fatura(fatura, cliente, tarifa_mes):
    """Monta dict de input pra calcular() a partir do que tá no banco."""
    mes_ref_br = f"{fatura['mes_referencia']:d}/{fatura['ano_referencia']}"

    # Vencimentos: vem como ISO no banco
    def _iso_to_br(s):
        if not s: return ""
        try:
            from datetime import datetime
            return datetime.strptime(str(s)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            return str(s)

    return {
        # Identificação
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

        # Modo bandeira + desconto (do cadastro do cliente)
        "modo_bandeira":   cliente.get("tp_bandeira", "com_bandeira") or "com_bandeira",
        "desconto_pct":    float(cliente.get("pct_desconto") or 0),

        # Mês
        "mes_referencia": mes_ref_br,

        # Tarifas (do tb_tarifas)
        "tarifa_sem":           float(tarifa_mes.get("tarifa_sem") or 0),
        "bandeira_tarifa_amar": float(tarifa_mes.get("bandeira_amarela") or 0),
        "bandeira_tarifa_verm": float(tarifa_mes.get("bandeira_vermelha") or 0),

        # Energia
        "consumo_kwh":          float(fatura.get("qtd_consumo_kwh") or 0),
        "consumo_compensado":   float(fatura.get("qtd_compensado_kwh") or 0),
        "consumo_nao_comp":     float(fatura.get("qtd_consumo_kwh") or 0) - float(fatura.get("qtd_compensado_kwh") or 0),

        # Itens fiscais da Equatorial
        "iluminacao_publica":   float(fatura.get("vlr_ilum_publica") or 0),
        "multa":                float(fatura.get("vlr_multa_equatorial") or 0),
        "juros":                float(fatura.get("vlr_juros_equatorial") or 0),
        "difci":                float(fatura.get("difci") or 0),
        "ecnisenta":            float(fatura.get("ecnisenta") or 0),
        "ajuste_valor":         float(fatura.get("ajuste_valor") or 0),
        "compensacao_dic":      float(fatura.get("vlr_compensacao_dic") or 0),

        # Economia anterior — recalcular_economia_acumulada vai consertar depois
        "economia_acumulada_anterior": 0,
        "valor_cobranca_anterior": 0,
        "venc_solev_anterior": "",
        "data_pagamento_anterior": "",

        # Datas
        "anterior_leitura":  fatura.get("anterior_leitura") or "",
        "data_leitura":      _iso_to_br(fatura.get("dt_leitura_atual")),
        "proxima_leitura":   "",
        "n_dias":            fatura.get("n_dias") or 30,
        "venc_equatorial":   _iso_to_br(fatura.get("dt_venc_equatorial")),
        "vencimento_solev":  _iso_to_br(fatura.get("dt_venc_solev")),

        # PIX (mantém do cadastro do cliente se houver)
        "pix_payload":       cliente.get("desc_pix_payload", "") or "",
        "codigo_barras":     "CODIGO DE BARRA EM DESENVOLVIMENTO",
        "linha_digitavel":   "XXXX.XXXX  XXXXX.XXXXX  XXXXX.XXXXX  X  XXXXXXXXXXXXXX",

        # PDF Equatorial (pra page 2)
        "equatorial_pdf":    os.path.join("uploads", str(fatura.get("pdf_equatorial") or "")) if fatura.get("pdf_equatorial") else None,
    }


def regenerar(id_fatura):
    print(f"\n{'='*60}")
    print(f"  REGENERANDO FATURA #{id_fatura}")
    print(f"{'='*60}")

    # Carrega fatura
    fats = db.select("tb_faturas", filtros={"id_fatura": id_fatura})
    if not fats:
        print(f"  Fatura {id_fatura} não encontrada!")
        return
    fatura = fats[0]

    # Carrega cliente
    cli = db.select("tb_clientes", filtros={"id_cliente": fatura["id_cliente"]})[0]
    print(f"  Cliente: {cli['desc_nome']}  UC: {cli['cod_uc']}")
    print(f"  Modo bandeira: {cli.get('tp_bandeira')}  Desconto: {cli.get('pct_desconto')}")

    # Carrega tarifa do mês
    mes_ref_br = f"{fatura['mes_referencia']:d}/{fatura['ano_referencia']}"
    tarifa = obter_tarifa_mes(mes_ref_br)
    if not tarifa:
        print(f"  ERRO: tarifa para {mes_ref_br} não encontrada!")
        return
    print(f"  Tarifa {mes_ref_br}: {tarifa.get('tarifa_sem')}  band_am={tarifa.get('bandeira_amarela')}  band_vm={tarifa.get('bandeira_vermelha')}")

    # Monta inputs
    dados = montar_dados_da_fatura(fatura, cli, tarifa)

    # Valores atuais (antes)
    print(f"\n  ANTES (banco):")
    print(f"    vlr_total_sem:       R$ {fatura.get('vlr_total_sem')}")
    print(f"    vlr_total_com:       R$ {fatura.get('vlr_total_com')}")
    print(f"    vlr_economia_mes:    R$ {fatura.get('vlr_economia_mes')}")
    print(f"    vlr_band_amar_solev: R$ {fatura.get('vlr_band_amar_solev')}  ← deveria ser 0 no modo 'sem_bandeira'")

    # Gera novo PDF
    print(f"\n  Gerando PDF novo...")
    gerar_cobranca(dados)
    novo_pdf = dados.get("output_path", "")
    print(f"  PDF gerado: {novo_pdf}")

    # Pega valores recalculados
    calc = calcular(dados)
    print(f"\n  DEPOIS (recalculado):")
    print(f"    total_sem:       R$ {calc['_total_sem']:.2f}")
    print(f"    total_com:       R$ {calc['_total_com']:.2f}")
    print(f"    economia_mes:    R$ {calc['_economia_mes']:.2f}")
    print(f"    band_amar_solev: R$ {calc['_band_amar_solev']:.2f}  ← deve ser 0")
    print(f"    band_verm_solev: R$ {calc['_band_verm_solev']:.2f}  ← deve ser 0")

    # Upload pro Storage (substitui o antigo).
    # Pula storage_ensure_bucket (bucket ja existe, e RLS impede a criacao)
    print(f"\n  Upload pro Supabase Storage...")
    try:
        pdf_url = storage_upload_pdf(novo_pdf, os.path.basename(novo_pdf), "faturas")
        print(f"  URL: {pdf_url}")
    except Exception as e:
        print(f"  AVISO: upload falhou ({e}) — PDF local OK, mas Storage nao atualizado")
        pdf_url = ""

    # Atualiza tb_faturas com novos valores
    print(f"\n  Atualizando tb_faturas...")
    update_data = {
        "vlr_total_sem":      round(calc["_total_sem"], 2),
        "vlr_total_com":      round(calc["_total_com"], 2),
        "vlr_economia_mes":   round(calc["_economia_mes"], 2),
        "vlr_band_amar_solev": round(calc["_band_amar_solev"], 2),
        "vlr_band_verm_solev": round(calc["_band_verm_solev"], 2),
        "pdf_solev":          os.path.basename(novo_pdf),
    }
    if pdf_url:
        update_data["pdf_solev_url"] = pdf_url
    db.patch("tb_faturas", {"id_fatura": id_fatura}, update_data)
    print(f"  ✓ Salvo.")
    return True


def main():
    ok = 0
    for id_fat in IDS_FATURAS:
        try:
            if regenerar(id_fat):
                ok += 1
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"\n  ERRO regenerando fatura {id_fat}: {e}")

    print(f"\n\n{'='*60}")
    print(f"  TOTAL: {ok}/{len(IDS_FATURAS)} faturas regeneradas")
    print(f"{'='*60}")

    # Após regenerar, recalcula economia acumulada idempotente (das clientes 110 e 197)
    print("\nRecalculando economia acumulada dos clientes...")
    from db import recalcular_economia_acumulada
    for id_cli in [110, 197]:
        v = recalcular_economia_acumulada(id_cli)
        print(f"  cliente id={id_cli}: economia_acumulada = R$ {v}")


if __name__ == "__main__":
    main()

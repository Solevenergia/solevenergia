"""
Extrator de Fatura Equatorial Goias — wrapper sobre extracao/

Campos retornados (identicos ao extrair_equatorial original + novos):
  uc, mes_referencia, consumo_kwh, tarifa_scee,
  compensado_kwh, nao_comp_kwh,
  pct_parc_injet, tarifa_nao_comp, valor_parc_injet,
  iluminacao_publica, bandeira_amarela, bandeira_vermelha,
  multa, juros, total_fatura, vencimento,
  data_leitura_anterior, data_leitura_atual, n_dias, proxima_leitura,
  leitura_anterior, leitura_atual, constante,
  tipo_fornecimento, classificacao, nome, cpf, endereco,
  cep, cidade, uf,
  geracao_ciclo_kwh, saldo_kwh, excedente_recebido_kwh,
  credito_recebido_kwh, saldo_expirar_30d_kwh, saldo_expirar_60d_kwh,
  compensacao_dic, ecnisenta, difci,
  rateio (lista de {uc_geradora, percentual}),
  itens_financeiros (lista de {tipo, mes_origem, base, valor}),
  historico_meses (lista de {consumo_kwh, valor_rs, dias, status}),
  tributos (pis_pasep, cofins, icms),
  nota_fiscal_num, chave_acesso, cfop, pix_br_code, codigo_barras,
  tensao_nominal, vrc, tipo_uc
  + aliases de retrocompatibilidade: unidade_consumidora, nome_cliente, etc.
"""
import dataclasses
from extracao import extrair
from extracao.exceptions import ExtracaoError
from extracao.models import Fatura
from extracao import ia as extracao_ia


def _fatura_para_dict(f: Fatura) -> dict:
    """Converte Fatura em dict com todos os campos + aliases legados."""
    d = dataclasses.asdict(f)

    # aliases de retrocompatibilidade com app.py / baixar_equatorial.py
    d["unidade_consumidora"] = f.uc
    d["tarifa_sem"]          = f.tarifa_scee or f.tarifa_convencional
    d["nome_cliente"]        = f.nome
    d["consumo_compensado"]  = f.compensado_kwh
    d["consumo_nao_comp"]    = f.nao_comp_kwh
    d["anterior_leitura"]    = f.leitura_anterior
    d["data_leitura"]        = f.data_leitura_atual
    d["venc_equatorial"]     = f.vencimento
    d["endereco_fatura"]     = f.endereco

    # aliases SCEE — campos planos para o formulário / front-end
    d["scee_ciclo_mes"]    = f.ciclo_geracao_mes
    d["scee_uc_geradora"]  = (f.scee.uc_geradora if f.scee else "") or (f.rateio[0].uc_geradora if f.rateio else "")
    d["scee_pct_rateio"]   = f.rateio[0].percentual if f.rateio else 0.0

    return d


def extrair_equatorial(caminho_pdf: str, verbose: bool = False) -> dict:
    """
    Extrai todos os campos da fatura Equatorial Goias.

    Parametros
    ----------
    caminho_pdf : str   — caminho para o PDF
    verbose     : bool  — ignorado (mantido por compatibilidade)

    Retorna
    -------
    dict com todos os campos (inclui aliases legados).

    Reforco com IA (extracao/ia.py) — so atua quando ANTHROPIC_API_KEY existe:
      - PDF nao reconhecido pelo regex -> IA extrai tudo;
      - campos vitais zerados (secao quebrou em silencio) -> IA preenche os buracos.
    Sem chave, o comportamento e identico ao regex puro.
    """
    try:
        fatura = extrair(caminho_pdf)
    except ExtracaoError:
        if not extracao_ia.ia_disponivel():
            raise
        print(f"[extracao] regex nao reconheceu o PDF — extraindo com IA: {caminho_pdf}")
        fatura = extracao_ia.extrair_com_ia(caminho_pdf)
    else:
        motivos = extracao_ia.motivos_escalonamento(fatura)
        if motivos and extracao_ia.ia_disponivel():
            print(f"[extracao] campos vitais ausentes ({', '.join(motivos)}) — completando com IA")
            try:
                fatura = extracao_ia.mesclar(fatura, extracao_ia.extrair_com_ia(caminho_pdf))
            except Exception as e:
                print(f"[extracao] IA falhou ({e}) — mantendo resultado do regex")
    return _fatura_para_dict(fatura)


# CLI — uso direto
if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Uso: python extrair_equatorial.py fatura.pdf [--debug]")
        sys.exit(1)

    resultado = extrair_equatorial(sys.argv[1])
    if "--debug" in sys.argv:
        from extracao.text_extractor import extrair_texto
        from extracao.helpers import fix_encoding
        t1, _, _ = extrair_texto(sys.argv[1])
        print("-" * 70)
        print("TEXTO BRUTO PAGINA 1:")
        print(fix_encoding(t1))
        print("-" * 70)

    print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))

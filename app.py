"""
=============================================================
  SOLEV — Aplicativo Web v2
=============================================================
  Uso: python app.py  (abre em http://localhost:5000)
=============================================================
"""
import json, os, sys, shutil, threading, urllib.parse, traceback, logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify, Response
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env
load_dotenv()

# Variáveis de ambiente (do arquivo .env)
SUPABASE_TOKEN = os.getenv("SUPABASE_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_PROJECT_ID = os.getenv("SUPABASE_PROJECT_ID")

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── LOGGING — Configuracao para registrar operacoes ──
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(_LOG_DIR, "app.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
logger.info("=" * 50)
logger.info("Iniciando SOLEV v2")
logger.info("=" * 50)

# Garante UTF-8 no stdout/stderr — evita falha de encoding com emojis no Windows (cp1252)
for _s in (sys.stdout, sys.stderr):
    if _s and hasattr(_s, 'reconfigure'):
        try: _s.reconfigure(encoding='utf-8', errors='replace')
        except Exception: pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extrair_equatorial import extrair_equatorial
from contalev_cobranca_v2_padrao import gerar_cobranca, calcular, _fmt_brl
from contalev_rateio_pdf import gerar_pdf_rateio
from utils import (
    _iso_to_br, _fmt_uc15, _fmt_cpf_cnpj, _fmt_cep, _data_br_para_iso,
    PIX_CHAVE, PIX_NOME, PIX_CIDADE,
    _build_pix_payload, gerar_qrcode_pix, _formatar_chave_pix_display,
    _buscar_cliente_por_uc, _carregar_cliente_hibrido,
    obter_tarifa_mes,
)

app = Flask(__name__)
app.secret_key = "contalev-2026-secret"
app.config["TEMPLATES_AUTO_RELOAD"] = True   # recarrega templates sem reiniciar

# Atrás de proxy (Railway, Nginx, Cloudflare): respeita X-Forwarded-Proto/Host
# para que url_for(_external=True) gere URLs HTTPS corretas (não HTTP).
# Sem isso, og:image vira http:// e WhatsApp/Telegram bloqueiam o preview.
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

from routes.tarifas import bp as bp_tarifas
from routes.recebedores import bp as bp_recebedores
from routes.titulares import bp as bp_titulares
from routes.whatsapp import bp as bp_whatsapp
from routes.contrato import bp as bp_contrato
from routes.investidor import bp as bp_investidor
from routes.simulador import bp as bp_simulador
from routes.importar import bp as bp_importar
from routes.conciliacao import bp as bp_conciliacao
from routes.inter import bp as bp_inter
app.register_blueprint(bp_tarifas)
app.register_blueprint(bp_recebedores)
app.register_blueprint(bp_titulares)
app.register_blueprint(bp_whatsapp)
app.register_blueprint(bp_contrato)
app.register_blueprint(bp_investidor)
app.register_blueprint(bp_simulador)
app.register_blueprint(bp_importar)
app.register_blueprint(bp_conciliacao)
app.register_blueprint(bp_inter)

@app.after_request
def _no_cache(response):
    """Impede o navegador de cachear paginas HTML — garante que mudancas de template
    aparecam imediatamente sem precisar de Ctrl+F5."""
    if "text/html" in response.content_type:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response



# Log de erros em arquivo para diagnostico
_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "erro_flask.log")
logging.basicConfig(filename=_LOG_FILE, level=logging.ERROR,
                    format='%(asctime)s %(levelname)s: %(message)s')

@app.errorhandler(Exception)
def handle_exception(e):
    # HTTPException (404, 403, 405 etc.) — deixa passar como é, não converte em 500.
    # Sem isso, o /robots.txt cai em 500 e o scraper do Facebook desiste de raspar.
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e

    tb = traceback.format_exc()
    logger.error(f"[ERRO_500] Requisicao: {request.url} - Metodo: {request.method}\n{tb}")
    with open(_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*60}\n{datetime.now()} - {request.url}\n{tb}\n")
    # Retorna JSON se a requisicao for fetch/AJAX, texto simples caso contrario
    _best = request.accept_mimetypes.best_match(["application/json", "text/html"]) or ""
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest" \
            or "application/json" == _best:
        return jsonify({"erro": str(e)}), 500
    return f"Erro interno: {e}", 500


# robots.txt liberando geral — necessário pro scraper do Facebook/WhatsApp/etc.
# antes de raspar Open Graph, eles checam aqui pra ver se podem.
@app.route("/robots.txt")
def robots_txt():
    return ("User-agent: *\nAllow: /\n", 200, {"Content-Type": "text/plain"})

@app.template_filter('basename')
def _basename_filter(path):
    if not path: return ""
    return os.path.basename(str(path).replace("\\", "/"))

@app.template_filter('fmt_uc15')
def _fmt_uc15_filter(v):
    return _fmt_uc15(v)


@app.template_filter('fmt_kwh_br')
def _fmt_kwh_br_filter(v):
    """Formata kWh no padrão BR: 1.234,56 (ponto pra milhar, vírgula pra decimal,
    sempre 2 casas decimais). Aceita None/'' (retorna '0,00')."""
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        n = 0.0
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

@app.template_filter('data_br')
def _data_br_filter(v):
    """Converte data ISO (YYYY-MM-DD ou primeiros 10 chars de um timestamp ISO)
    para formato BR (DD/MM/AAAA). Vazio/invalido → '—'."""
    return _iso_to_br(v) or "—"


@app.context_processor
def _inject_helpers_portal():
    """Helpers globais disponiveis em todos os templates."""
    def saudacao_horario():
        from datetime import datetime as _dt
        h = _dt.now().hour
        if h < 12:  return "Bom dia"
        if h < 18:  return "Boa tarde"
        return "Boa noite"
    return {"saudacao_horario": saudacao_horario}

_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────
# CUSTO DE DISPONIBILIDADE (ANEEL / Equatorial)
# ─────────────────────────────────────────────────────────────────────
# Mínimo de kWh que a concessionária cobra/não-compensa por tipo de
# ligação. Esses kWh aparecem como "consumo não compensado" mesmo quando
# o cliente tem saldo SCEE disponível. Usado para calcular a necessidade
# real de rateio: necessidade = max(0, previsão − CD − saldo).
CUSTO_DISPONIBILIDADE_KWH = {
    "MONOFASICO": 25,
    "BIFASICO":   45,
    "TRIFASICO":  80,
}
def _cd_kwh(tp_fornecimento: str) -> int:
    """Retorna o custo de disponibilidade (kWh) baseado no tipo. Default: bifásico."""
    if not tp_fornecimento:
        return CUSTO_DISPONIBILIDADE_KWH["BIFASICO"]
    t = str(tp_fornecimento).upper().strip()
    # Aceita variações: "Monofásico", "MONOFASICO", "Mono", etc.
    if t.startswith("MONO"): return CUSTO_DISPONIBILIDADE_KWH["MONOFASICO"]
    if t.startswith("TRI"):  return CUSTO_DISPONIBILIDADE_KWH["TRIFASICO"]
    return CUSTO_DISPONIBILIDADE_KWH["BIFASICO"]  # default + casos "BIF" / "BI"

try:
    from contalev_cobranca_v2_padrao import _preparar_logos
    _preparar_logos()
except Exception as e:
    print(f"[AVISO] Logo: {e}")

# ── Helpers ──────────────────────────────────────────────────
# Todas as tabelas persistentes vem do Supabase (PostgreSQL). Ver db.py.
from db import (
    carregar_clientes, salvar_clientes,
    carregar_usinas, salvar_usinas,
    carregar_faturas,
    carregar_tarifas, salvar_tarifas, salvar_tarifa_mes,
    carregar_geracao_mensal, salvar_geracao_mensal,
    carregar_geracao, salvar_geracao,
    carregar_investidor_hist, salvar_investidor_hist,
)

# ── Codigo curto base62 (6 chars) derivado do id_fatura ──────────────
# Usado em URLs publicas /luz/<code> e /pix/<code> para mensagens de WhatsApp.
# Deterministico (SHA-256 truncado): mesmo id sempre gera o mesmo codigo,
# entao nao precisa armazenar nada no banco e funciona retroativamente.
_BASE62_ALPHA = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

def _id_to_short_code(item_id):
    """Converte id hex (12 chars) em codigo curto base62 (6 chars)."""
    import hashlib
    if not item_id:
        return ""
    h = hashlib.sha256(str(item_id).encode("utf-8")).digest()
    n = int.from_bytes(h[:6], "big")  # 48 bits ~ 6 chars base62
    code = ""
    for _ in range(6):
        code = _BASE62_ALPHA[n % 62] + code
        n //= 62
    return code

def _find_item_by_code(historico, code):
    """Busca item no historico por short_code OU id direto (backward compat).
    DEPRECATED: usar _buscar_fatura_compat. Mantido pra rotas legadas."""
    if not code:
        return None
    code_str = str(code).strip()
    if len(code_str) <= 8:
        for h in historico:
            if _id_to_short_code(h.get("id", "")) == code_str:
                return h
    for h in historico:
        if str(h.get("id", "")) == code_str:
            return h
    return None


def _adicionar_aliases_legados(f):
    """Injeta no dict da fatura os nomes de campo legados pra templates antigos.
    Idempotente — se chamar 2x nao quebra."""
    if not f:
        return f
    f["id"]               = str(f.get("id_fatura") or "")
    f["nome"]             = f.get("_nome") or f.get("nome") or ""
    f["uc"]               = f.get("_cod_uc") or f.get("uc") or ""
    f["_uc_nova"]         = f.get("_cod_uc") or f.get("_uc_nova") or ""
    f["mes_referencia"]   = f.get("_mes_ref_br") or f.get("mes_referencia") or ""
    f["total_com"]        = f.get("vlr_total_com") or f.get("total_com") or 0
    f["total_sem"]        = f.get("vlr_total_sem") or f.get("total_sem") or 0
    f["economia_mes"]     = f.get("vlr_economia_mes") or f.get("economia_mes") or 0
    v = f.get("dt_venc_solev")
    if v and "vencimento" not in f:
        try:
            from datetime import date as _d
            f["vencimento"] = _d.fromisoformat(str(v)).strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            f["vencimento"] = str(v)
    elif "vencimento" not in f:
        f["vencimento"] = ""
    f["pdf"]      = f.get("pdf_solev") or f.get("pdf") or ""
    f["pdf_url"]  = f.get("pdf_solev_url") or f.get("pdf_url") or ""
    return f


def _buscar_fatura_compat(code_or_id):
    """Busca fatura em tb_faturas por id_fatura (int) OU short_code (6 chars).
    Retorna dict com aliases legados ja injetados. None se nao achar."""
    from db import tb_get_fatura_por_id, _db as _get_db, _FATURA_COLS_EMBED, _enriquecer_fatura
    if not code_or_id:
        return None
    code_str = str(code_or_id).strip()
    fatura = None

    # 1. id_fatura direto (int)
    if code_str.isdigit():
        try:
            fatura = tb_get_fatura_por_id(int(code_str))
        except Exception:
            fatura = None

    # 2. short_code (6 chars base62 derivados do id_fatura)
    if not fatura and 4 <= len(code_str) <= 8:
        try:
            rows = _get_db().select("tb_faturas",
                                    columns=_FATURA_COLS_EMBED,
                                    order="id_fatura.desc")
            for r in rows:
                if _id_to_short_code(r.get("id_fatura")) == code_str:
                    fatura = _enriquecer_fatura(r)
                    break
        except Exception as e:
            app.logger.warning(f"[buscar_fatura] short_code falhou: {e}")

    return _adicionar_aliases_legados(fatura) if fatura else None


def _buscar_fatura_por_pdf(filename):
    """Busca fatura em tb_faturas pelo nome do PDF (pdf_solev).
    Retorna dict com aliases legados. None se nao achar."""
    from db import _db as _get_db, _FATURA_COLS_EMBED, _enriquecer_fatura
    if not filename:
        return None
    fname = os.path.basename(filename)
    try:
        rows = _get_db().select("tb_faturas",
                                columns=_FATURA_COLS_EMBED,
                                filtros={"pdf_solev": fname})
        if rows:
            return _adicionar_aliases_legados(_enriquecer_fatura(rows[0]))
    except Exception as e:
        app.logger.warning(f"[buscar_fatura_pdf] falhou: {e}")
    return None

def _gerar_uma_cobranca(pdf_path, uc_override=None):
    """Gera cobranca de um PDF. Retorna (sucesso, mensagem, dados_calc)."""
    try:
        equatorial = extrair_equatorial(pdf_path, verbose=False)
        uc = uc_override or equatorial.get("uc", "")
        if not uc:
            return False, "UC nao encontrada no PDF.", None

        chave_real, cliente = _carregar_cliente_hibrido(uc)
        if not cliente:
            return False, f"Cliente UC {uc} nao cadastrado.", None
        chave_real = chave_real or uc

        # Busca tarifa/bandeira do mes de referencia
        mes_ref = equatorial["mes_referencia"]
        tarifa_mes = obter_tarifa_mes(mes_ref)

        # Cadastro automatico: se a tarifa do mes nao existe, registra
        # com base nos dados extraidos da fatura
        if not tarifa_mes or not tarifa_mes.get("tarifa_sem"):
            tarifa_valor = 0
            tarifa_origem = ""

            # 1) Se a fatura tem CONSUMO NAO COMPENSADO → usa tarifa convencional
            #    Linha: "CONSUMO NAO COMPENSADO kWh 14,69 1,125925 ..."
            tarifa_conv = equatorial.get("tarifa_convencional", 0) or 0
            if tarifa_conv > 0:
                tarifa_valor = tarifa_conv
                tarifa_origem = "tarifa convencional da fatura"

            # 2) Se todo consumo e compensado → tarifa SCEE + 45%
            if tarifa_valor <= 0 and (equatorial.get("tarifa_scee", 0) or 0) > 0:
                tarifa_valor = round(equatorial["tarifa_scee"] * 1.45, 6)
                tarifa_origem = "tarifa SCEE + 45%"

            if tarifa_valor > 0:
                tarifas = carregar_tarifas()
                nova_tarifa = {
                    "tarifa_sem": tarifa_valor,
                    "bandeira_amarela": 0,
                    "bandeira_vermelha": 0,
                    "fio_b": 0,
                    "observacao": f"Cadastro automatico - {tarifa_origem} - via UC {uc}",
                }
                tarifas[mes_ref] = nova_tarifa
                salvar_tarifas(tarifas)
                tarifa_mes = nova_tarifa

        if not tarifa_mes or not tarifa_mes.get("tarifa_sem"):
            return False, f"Tarifa do mes {mes_ref} nao cadastrada e nao foi possivel extrair da fatura. Cadastre em Tarifas antes de gerar.", None

        # Endereco: suporte a campo unico (novo) e legado (3 linhas)
        _end = cliente.get("endereco", "")
        if not _end:
            _end = ", ".join(p for p in [
                cliente.get("endereco_linha1", ""),
                cliente.get("endereco_linha2", ""),
                cliente.get("endereco_linha3", ""),
            ] if p)

        # Idempotencia da economia acumulada (mesma logica do gerar_manual):
        # desconta a economia ja registrada na fatura deste mes (se houver),
        # para regerar a mesma cobranca nao duplicar — no PDF e no banco.
        _eco_acum_ant = max(0, cliente.get("economia_acumulada_anterior", 0) or 0)
        if cliente.get("_fonte") == "tb_clientes" and cliente.get("_id_cliente"):
            import re as _re_eco_a
            _mm_a = _re_eco_a.match(r"^\s*(\d{1,2})/(\d{4})\s*$", str(mes_ref or ""))
            if _mm_a:
                from db import tb_economia_mes_fatura
                _eco_acum_ant = max(0.0, _eco_acum_ant - tb_economia_mes_fatura(
                    cliente["_id_cliente"], _mm_a.group(2), _mm_a.group(1)))

        dados = {
            "nome": cliente["nome"], "cpf": cliente.get("cpf", ""),
            "endereco": _end,
            "endereco_linha1": cliente.get("endereco_linha1", _end[:50] if _end else ""),
            "endereco_linha2": cliente.get("endereco_linha2", ""),
            "endereco_linha3": cliente.get("endereco_linha3", ""),
            "desconto_pct": cliente["desconto_pct"],
            "tarifa_sem": tarifa_mes["tarifa_sem"],
            "valor_cobranca_anterior": cliente.get("valor_cobranca_anterior", 0) or 0,
            "venc_solev_anterior": cliente.get("venc_solev_anterior", ""),
            "data_pagamento_anterior": cliente.get("data_pagamento_anterior", ""),
            "economia_acumulada_anterior": _eco_acum_ant,
            "codigo_barras": cliente.get("codigo_barras", "CODIGO DE BARRA EM DESENVOLVIMENTO"),
            "linha_digitavel": cliente.get("linha_digitavel", "XXXX.XXXX  XXXXX.XXXXX  XXXXX.XXXXX  X  XXXXXXXXXXXXXX"),
            "pix_payload": cliente.get("pix_payload", ""),
            "unidade_consumidora": cliente.get("cod_uc") or equatorial["uc"],
            "tipo_fornecimento": equatorial["tipo_fornecimento"],
            "mes_referencia": mes_ref,
            "anterior_leitura": equatorial["data_leitura_anterior"],
            "data_leitura": equatorial["data_leitura_atual"],
            "proxima_leitura": equatorial["proxima_leitura"],
            "n_dias": equatorial.get("n_dias", ""),
            "venc_equatorial": equatorial["vencimento"],
            "consumo_kwh": equatorial["consumo_kwh"],
            "consumo_compensado": equatorial["compensado_kwh"],
            "consumo_nao_comp": equatorial["nao_comp_kwh"],
            "iluminacao_publica": equatorial["iluminacao_publica"],
            "multa": equatorial["multa"], "juros": equatorial["juros"],
            "correcao_ipca": equatorial.get("correcao_ipca", 0) or 0,
            "difci":         equatorial.get("difci", 0) or 0,
            "ecnisenta":     equatorial.get("ecnisenta", 0) or 0,
            "ajuste_valor":  0,
            "equatorial_pdf": pdf_path,
            # Lei 14.300/21 — cobranca parcial sobre energia compensada
            "valor_parc_injet": equatorial.get("valor_parc_injet", 0) or 0,
            "pct_parc_injet":   equatorial.get("pct_parc_injet", 0) or 0,
            "bandeira_amarela": (tarifa_mes.get("bandeira_amarela", 0) or 0) * equatorial["consumo_kwh"],
            "bandeira_vermelha": (tarifa_mes.get("bandeira_vermelha", 0) or 0) * equatorial["consumo_kwh"],
            # Bandeiras — campos novos consumidos pelo calculator
            "bandeira_tarifa_amar":   tarifa_mes.get("bandeira_amarela", 0) or 0,
            "bandeira_tarifa_verm":   tarifa_mes.get("bandeira_vermelha", 0) or 0,
            "adc_bandeira_amarela":   equatorial.get("adc_bandeira_amarela", 0) or 0,
            "adc_bandeira_vermelha":  equatorial.get("adc_bandeira_vermelha", 0) or 0,
            # Qtd kWh sob bandeira — calcular() usa p/ achar a tarifa REAL do mes
            # (adc_R$ / qtd), em vez do valor velho do tb_tarifas.
            "_bandeira_amarela_qtd":  equatorial.get("bandeira_amarela", 0) or 0,
            "_bandeira_vermelha_qtd": equatorial.get("bandeira_vermelha", 0) or 0,
            "tarifa_bandeira_amarela_pdf":  equatorial.get("tarifa_bandeira_amarela_pdf", 0) or 0,
            "tarifa_bandeira_vermelha_pdf": equatorial.get("tarifa_bandeira_vermelha_pdf", 0) or 0,
            "modo_bandeira":          cliente.get("modo_bandeira", "com_bandeira"),
            "compensacao_dic": equatorial.get("compensacao_dic", 0) or 0,
        }

        # Gera QR Code PIX dinamico com dados do recebedor da usina do cliente
        dados_calc_pre = calcular(dados)
        _total = dados_calc_pre.get("_total_com", 0)
        _qr = None
        try:
            _id_cliente = cliente.get("_id_cliente")
            if _id_cliente:
                from db import tb_get_usinas_do_cliente, tb_get_pix_da_usina
                _vinculos = tb_get_usinas_do_cliente(_id_cliente)
                if _vinculos:
                    _rec = tb_get_pix_da_usina(_vinculos[0]["id_usina"])
                    if _rec:
                        _qr = gerar_qrcode_pix(
                            _total,
                            chave_pix=_rec.get("desc_pix"),
                            nome_pix=_rec.get("desc_nome_pix") or _rec.get("desc_nome"),
                            cidade_pix=_rec.get("desc_cidade_pix"),
                        )
                        # Chave formatada para mostrar abaixo do QR
                        dados["pix_chave_display"] = _formatar_chave_pix_display(
                            _rec.get("desc_pix"))
        except Exception as _e:
            app.logger.warning(f"[pix] Falha ao buscar recebedor: {_e}")
        if _qr:
            dados["pix_qr_path"] = _qr

        # Resolve id_cliente (nome do arquivo) e id_fatura (texto no PDF)
        try:
            from db import _resolver_id_cliente_por_uc, tb_reservar_id_fatura
            _id_cli_pdf = _resolver_id_cliente_por_uc(chave_real)
            if _id_cli_pdf:
                dados["id_cliente"] = _id_cli_pdf
                _mr_pdf = equatorial.get("mes_referencia", "")
                import re as _re_mr_pdf
                _mm = _re_mr_pdf.match(r"^(\d{1,2})/(\d{4})$", str(_mr_pdf).strip())
                if _mm:
                    dados["id_fatura"] = tb_reservar_id_fatura(
                        _id_cli_pdf, int(_mm.group(2)), int(_mm.group(1)))
        except Exception as _e_res:
            app.logger.warning(f"[gerar] resolver id_cliente/id_fatura falhou: {_e_res}")

        gerar_cobranca(dados)
        dados_calc = calcular(dados)

        # Write-back de valores pos-cobranca
        _pl    = equatorial.get("proxima_leitura", "")
        _saldo = equatorial.get("saldo_kwh", 0)
        if cliente.get("_fonte") == "tb_clientes":
            # Cliente veio da nova tabela — persiste estado pos-cobranca em tb_clientes
            from db import tb_save_cliente
            tb_save_cliente({
                "cod_uc":                chave_real,
                "id_cliente":            cliente.get("_id_cliente"),
                "vlr_cobranca_anterior": round(dados_calc["_total_com"], 2),
                "dt_venc_anterior":      _parse_data_br_iso(dados_calc.get("venc_solev", "")),
                "dt_ultimo_pagamento":   None,
                "qtd_economia_acumulada":round(dados_calc["_economia_acum"], 2),
            })
        else:
            clientes_wb = carregar_clientes()
            if chave_real in clientes_wb:
                clientes_wb[chave_real]["valor_cobranca_anterior"]    = round(dados_calc["_total_com"], 2)
                clientes_wb[chave_real]["venc_solev_anterior"]      = dados_calc["venc_solev"]
                clientes_wb[chave_real]["data_pagamento_anterior"]     = ""
                clientes_wb[chave_real]["economia_acumulada_anterior"] = round(dados_calc["_economia_acum"], 2)
                if _pl:    clientes_wb[chave_real]["proxima_leitura"] = _pl
                if _saldo: clientes_wb[chave_real]["saldo_kwh"]       = _saldo
                salvar_clientes(clientes_wb)

        # Upload de ambos os PDFs ao Supabase Storage
        _pdf_url = ""
        _pdf_eq_url = ""
        _output_path = dados_calc.get("output_path", "")
        try:
            from db import storage_ensure_bucket, storage_upload_pdf
            storage_ensure_bucket("faturas")
            if _output_path and os.path.exists(_output_path):
                _pdf_url = storage_upload_pdf(_output_path, os.path.basename(_output_path), "faturas")
            if pdf_path and os.path.exists(pdf_path):
                _pdf_eq_url = storage_upload_pdf(pdf_path, os.path.basename(pdf_path), "faturas")
        except Exception as _se:
            app.logger.warning(f"[storage] Upload falhou: {_se}")

        from db import inserir_fatura as _inserir_hist
        _inserir_hist(
            uc=chave_real,
            nome=cliente["nome"],
            mes_ref=equatorial["mes_referencia"],
            total_sem=round(dados_calc["_total_sem"], 2),
            total_com=round(dados_calc["_total_com"], 2),
            economia_mes=round(dados_calc["_economia_mes"], 2),
            economia_acum=round(dados_calc["_economia_acum"], 2),
            venc=dados_calc["venc_solev"],
            pdf_path=_output_path,
            consumo_kwh=equatorial.get("consumo_kwh", 0),
            compensado_kwh=equatorial.get("compensado_kwh", 0),
            data_leitura_atual=equatorial.get("data_leitura_atual", ""),
            pdf_url=_pdf_url,
            pdf_equatorial=pdf_path,
            pdf_equatorial_url=_pdf_eq_url,
            venc_equatorial=equatorial.get("venc_equatorial", ""),
            saldo_kwh=equatorial.get("saldo_kwh", 0),
            multa_equatorial=equatorial.get("multa", 0),
            juros_equatorial=equatorial.get("juros", 0),
            multa_mes=dados_calc.get("_multa_com", 0),
            juros_mes=dados_calc.get("_juros_com", 0),
            fatura_equatorial=equatorial.get("total_fatura", 0),
            fio_b=equatorial.get("valor_parc_injet", 0),
            ilum_publica=equatorial.get("iluminacao_publica", 0),
            band_amar_equatorial=dados_calc.get("_band_amar_equatorial", 0),
            band_verm_equatorial=dados_calc.get("_band_verm_equatorial", 0),
            band_amar_solev=dados_calc.get("_band_amar_solev", 0),
            band_verm_solev=dados_calc.get("_band_verm_solev", 0),
            ajuste_valor=dados_calc.get("ajuste_valor", 0),
            difci=dados_calc.get("difci", 0),
            ecnisenta=dados_calc.get("ecnisenta", 0),
            anterior_leitura=equatorial.get("data_leitura_anterior", ""),
            proxima_leitura=equatorial.get("proxima_leitura", ""),
            n_dias=int(equatorial.get("n_dias", 0) or 0),
            # SCEE — dados da geração solar extraídos do PDF Equatorial
            scee_ciclo_mes=equatorial.get("scee_ciclo_mes", "") or equatorial.get("ciclo_geracao_mes", ""),
            scee_uc_geradora=equatorial.get("scee_uc_geradora", ""),
            scee_pct_rateio=equatorial.get("scee_pct_rateio", 0) or 0,
            scee_geracao_usina_kwh=equatorial.get("geracao_ciclo_kwh", 0) or 0,
            scee_excedente_kwh=equatorial.get("excedente_recebido_kwh", 0) or 0,
            scee_credito_kwh=equatorial.get("credito_recebido_kwh", 0) or 0,
            scee_saldo_exp_30d_kwh=equatorial.get("saldo_expirar_30d_kwh", 0) or 0,
            scee_saldo_exp_60d_kwh=equatorial.get("saldo_expirar_60d_kwh", 0) or 0,
        )
        msg = f"{cliente['nome']} — {_fmt_brl(dados_calc['_total_com'])} (economia: {_fmt_brl(dados_calc['_economia_mes'])})"
        return True, msg, dados_calc
    except Exception as e:
        import traceback; traceback.print_exc()
        return False, str(e), None

def _montar_dados_de_pdf(pdf_path, uc_override=None):
    """Espelho de _gerar_uma_cobranca, mas SEM gerar PDF.
    Faz extracao + cliente + tarifa (incl. auto-cadastro) + monta dict 'dados'.
    Retorna (ok, mensagem, dados, cliente, chave_real, equatorial).
    Usado pelo fluxo de preview da rota /gerar.
    """
    try:
        equatorial = extrair_equatorial(pdf_path, verbose=False)
        uc = uc_override or equatorial.get("uc", "")
        if not uc:
            return False, "UC nao encontrada no PDF.", None, None, None, None

        chave_real, cliente = _carregar_cliente_hibrido(uc)
        if not cliente:
            return False, f"Cliente UC {uc} nao cadastrado.", None, None, None, None
        chave_real = chave_real or uc

        mes_ref = equatorial["mes_referencia"]
        tarifa_mes = obter_tarifa_mes(mes_ref)

        if not tarifa_mes or not tarifa_mes.get("tarifa_sem"):
            tarifa_valor = 0
            tarifa_origem = ""
            tarifa_conv = equatorial.get("tarifa_convencional", 0) or 0
            if tarifa_conv > 0:
                tarifa_valor = tarifa_conv
                tarifa_origem = "tarifa convencional da fatura"
            if tarifa_valor <= 0 and (equatorial.get("tarifa_scee", 0) or 0) > 0:
                tarifa_valor = round(equatorial["tarifa_scee"] * 1.45, 6)
                tarifa_origem = "tarifa SCEE + 45%"
            if tarifa_valor > 0:
                tarifas = carregar_tarifas()
                nova_tarifa = {
                    "tarifa_sem": tarifa_valor,
                    "bandeira_amarela": 0,
                    "bandeira_vermelha": 0,
                    "fio_b": 0,
                    "observacao": f"Cadastro automatico - {tarifa_origem} - via UC {uc}",
                }
                tarifas[mes_ref] = nova_tarifa
                salvar_tarifas(tarifas)
                tarifa_mes = nova_tarifa

        if not tarifa_mes or not tarifa_mes.get("tarifa_sem"):
            return False, f"Tarifa do mes {mes_ref} nao cadastrada e nao foi possivel extrair da fatura.", None, None, None, None

        _end = cliente.get("endereco", "")
        if not _end:
            _end = ", ".join(p for p in [
                cliente.get("endereco_linha1", ""),
                cliente.get("endereco_linha2", ""),
                cliente.get("endereco_linha3", ""),
            ] if p)

        # Idempotencia da economia acumulada (mesma logica do gerar_manual):
        # desconta a economia ja registrada na fatura deste mes (se houver),
        # para regerar a mesma cobranca nao duplicar — no PDF e no banco.
        _eco_acum_ant = max(0, cliente.get("economia_acumulada_anterior", 0) or 0)
        if cliente.get("_fonte") == "tb_clientes" and cliente.get("_id_cliente"):
            import re as _re_eco_a
            _mm_a = _re_eco_a.match(r"^\s*(\d{1,2})/(\d{4})\s*$", str(mes_ref or ""))
            if _mm_a:
                from db import tb_economia_mes_fatura
                _eco_acum_ant = max(0.0, _eco_acum_ant - tb_economia_mes_fatura(
                    cliente["_id_cliente"], _mm_a.group(2), _mm_a.group(1)))

        dados = {
            "nome": cliente["nome"], "cpf": cliente.get("cpf", ""),
            "endereco": _end,
            "endereco_linha1": cliente.get("endereco_linha1", _end[:50] if _end else ""),
            "endereco_linha2": cliente.get("endereco_linha2", ""),
            "endereco_linha3": cliente.get("endereco_linha3", ""),
            "desconto_pct": cliente["desconto_pct"],
            "tarifa_sem": tarifa_mes["tarifa_sem"],
            "valor_cobranca_anterior": cliente.get("valor_cobranca_anterior", 0) or 0,
            "venc_solev_anterior": cliente.get("venc_solev_anterior", ""),
            "data_pagamento_anterior": cliente.get("data_pagamento_anterior", ""),
            "economia_acumulada_anterior": _eco_acum_ant,
            "codigo_barras": cliente.get("codigo_barras", "CODIGO DE BARRA EM DESENVOLVIMENTO"),
            "linha_digitavel": cliente.get("linha_digitavel", "XXXX.XXXX  XXXXX.XXXXX  XXXXX.XXXXX  X  XXXXXXXXXXXXXX"),
            "pix_payload": cliente.get("pix_payload", ""),
            "unidade_consumidora": cliente.get("cod_uc") or equatorial["uc"],
            "tipo_fornecimento": equatorial["tipo_fornecimento"],
            "mes_referencia": mes_ref,
            "anterior_leitura": equatorial["data_leitura_anterior"],
            "data_leitura": equatorial["data_leitura_atual"],
            "proxima_leitura": equatorial["proxima_leitura"],
            "n_dias": equatorial.get("n_dias", ""),
            "venc_equatorial": equatorial["vencimento"],
            "consumo_kwh": equatorial["consumo_kwh"],
            "consumo_compensado": equatorial["compensado_kwh"],
            "consumo_nao_comp": equatorial["nao_comp_kwh"],
            "iluminacao_publica": equatorial["iluminacao_publica"],
            "multa": equatorial["multa"], "juros": equatorial["juros"],
            "correcao_ipca": equatorial.get("correcao_ipca", 0) or 0,
            "difci":         equatorial.get("difci", 0) or 0,
            "ecnisenta":     equatorial.get("ecnisenta", 0) or 0,
            "ajuste_valor":  0,
            "equatorial_pdf": pdf_path,
            "valor_parc_injet": equatorial.get("valor_parc_injet", 0) or 0,
            "pct_parc_injet":   equatorial.get("pct_parc_injet", 0) or 0,
            "bandeira_amarela": (tarifa_mes.get("bandeira_amarela", 0) or 0) * equatorial["consumo_kwh"],
            "bandeira_vermelha": (tarifa_mes.get("bandeira_vermelha", 0) or 0) * equatorial["consumo_kwh"],
            # Bandeiras "puras" R$/kWh para preview (campos editaveis)
            "_band_am_kwh": tarifa_mes.get("bandeira_amarela", 0) or 0,
            "_band_vm_kwh": tarifa_mes.get("bandeira_vermelha", 0) or 0,
        }
        return True, "", dados, cliente, chave_real, equatorial
    except Exception as e:
        import traceback; traceback.print_exc()
        return False, str(e), None, None, None, None


# ── ROTAS ────────────────────────────────────────────────────

@app.route("/ping")
def ping():
    """Health check ultra-rápido (sem queries no DB).
    Usado pelo launcher SOLEV.vbs pra detectar se o servidor está vivo."""
    return "pong", 200, {"Cache-Control": "no-cache"}


# ── PORTAL DO CLIENTE ───────────────────────────────────────
@app.route("/c/<token>")
def portal_cliente(token):
    """Portal do cliente — acesso via token UUID único por fatura.

    Mostra: valor, vencimento, economia, PIX copia-e-cola, botões pra
    abrir app do banco, PDF da fatura, histórico do cliente.

    Segurança:
      - Token é UUID v4 (128 bits — impossível adivinhar)
      - Sem login: token == permissão de acesso AQUELA fatura
      - Cliente vê apenas suas próprias faturas (do mesmo id_cliente)
      - Apenas LEITURA (sem edição de dados sensíveis)
    """
    from db import _db, storage_signed_url, tb_get_pix_da_usina, tb_get_usinas_do_cliente
    from datetime import datetime, date

    # 1) Valida token e carrega fatura
    fats = _db().select("tb_faturas", filtros={"token_acesso": token})
    if not fats:
        return render_template("portal_cliente_erro.html",
                               erro="Link inválido ou expirado."), 404
    fatura = fats[0]

    # 2) Carrega cliente
    cli_rows = _db().select("tb_clientes", filtros={"id_cliente": fatura.get("id_cliente")})
    if not cli_rows:
        return render_template("portal_cliente_erro.html",
                               erro="Cliente não encontrado."), 404
    cliente = cli_rows[0]

    # 3) PIX da usina vinculada (se houver)
    pix_chave = ""
    pix_nome  = "SOLEV ENERGIA"
    pix_chave_display = ""
    try:
        vinculos = tb_get_usinas_do_cliente(cliente["id_cliente"])
        if vinculos:
            rec = tb_get_pix_da_usina(vinculos[0]["id_usina"])
            if rec:
                pix_chave = rec.get("desc_pix", "")
                pix_nome  = rec.get("desc_nome_pix") or rec.get("desc_nome", "SOLEV")
                pix_chave_display = _formatar_chave_pix_display(pix_chave)
    except Exception as e:
        app.logger.warning(f"[portal] PIX lookup falhou: {e}")

    # 4) URL temporária do PDF (1 hora)
    pdf_signed_url = ""
    pdf_storage_path = fatura.get("pdf_solev_url") or ""
    if pdf_storage_path and not pdf_storage_path.startswith("http"):
        # E formato 'faturas/arquivo.pdf'
        try:
            pdf_signed_url = storage_signed_url(pdf_storage_path, expires_in=3600)
        except Exception as e:
            app.logger.warning(f"[portal] signed URL falhou: {e}")
    elif pdf_storage_path.startswith("http"):
        pdf_signed_url = pdf_storage_path

    # 5) Status visual da fatura
    status = fatura.get("status") or "pendente"
    dt_venc = fatura.get("dt_venc_solev")
    dias_p_vencimento = None
    venc_status = "ok"
    if dt_venc:
        try:
            dt_v = datetime.strptime(str(dt_venc)[:10], "%Y-%m-%d").date()
            hoje = date.today()
            dias_p_vencimento = (dt_v - hoje).days
            if status == "pago":
                venc_status = "pago"
            elif dias_p_vencimento < 0:
                venc_status = "atrasado"
            elif dias_p_vencimento <= 3:
                venc_status = "urgente"
            else:
                venc_status = "ok"
            dt_venc_br = dt_v.strftime("%d/%m/%Y")
        except Exception:
            dt_venc_br = str(dt_venc)
    else:
        dt_venc_br = "—"

    # 6) Formatadores
    def _brl(v): return f"R$ {float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # 7) Histórico do cliente (todas as faturas, pra contar e achar primeira)
    historico = []
    fats_cli = []
    try:
        fats_cli = _db().select(
            "tb_faturas",
            filtros={"id_cliente": cliente["id_cliente"]},
            order="ano_referencia.asc,mes_referencia.asc",
            columns="id_fatura,ano_referencia,mes_referencia,vlr_total_com,vlr_economia_mes,status,token_acesso",
        )
        for f in fats_cli[-6:][::-1]:  # ultimas 6 em ordem desc
            historico.append({
                "mes":    f"{f.get('mes_referencia',0):02d}/{f.get('ano_referencia',0)}",
                "total":  _brl(f.get("vlr_total_com")),
                "economia": _brl(f.get("vlr_economia_mes")),
                "status": f.get("status") or "pendente",
                "token":  f.get("token_acesso") or "",
                "is_atual": f.get("id_fatura") == fatura.get("id_fatura"),
            })
    except Exception as e:
        app.logger.warning(f"[portal] historico falhou: {e}")

    # ── Monta dicts no formato do novo layout (handoff Claude Design) ──
    MESES_BR = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
                "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    MESES_BR_CAP = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

    # Cliente — primeiro_nome + iniciais (max 2 letras)
    nome_full = (cliente.get("desc_nome") or "").strip()
    nome_partes = nome_full.split()
    primeiro_nome = nome_partes[0].title() if nome_partes else "Cliente"
    if len(nome_partes) >= 2:
        iniciais = (nome_partes[0][:1] + nome_partes[-1][:1]).upper()
    elif nome_partes:
        iniciais = nome_partes[0][:2].upper()
    else:
        iniciais = "??"

    cliente_view = {
        "primeiro_nome":    primeiro_nome,
        "iniciais":         iniciais,
        "tem_notificacao":  False,  # placeholder pra futura feature
    }

    # Fatura — separa valor em reais/centavos, formata data por extenso
    valor_num = float(fatura.get("vlr_total_com") or 0)
    valor_reais = f"{int(valor_num):,}".replace(",", ".")
    valor_cents = f"{int(round((valor_num - int(valor_num)) * 100)):02d}"

    mes_fat = int(fatura.get("mes_referencia") or 0)
    ano_fat = int(fatura.get("ano_referencia") or 0)
    mes_label = f"{MESES_BR_CAP[mes_fat]} · {ano_fat}" if 1 <= mes_fat <= 12 else f"{mes_fat:02d}/{ano_fat}"

    venc_data_extenso = ""
    if dt_venc:
        try:
            dt_v = datetime.strptime(str(dt_venc)[:10], "%Y-%m-%d").date()
            venc_data_extenso = f"{dt_v.day} de {MESES_BR[dt_v.month]}"
        except Exception:
            venc_data_extenso = dt_venc_br

    fatura_view = {
        "mes_label":         mes_label,
        "valor_reais":       valor_reais,
        "valor_centavos":    valor_cents,
        "vencimento_data":   venc_data_extenso or dt_venc_br,
        "vencimento_dias":   dias_p_vencimento if dias_p_vencimento is not None else 0,
        "pix_payload":       (_build_pix_payload(valor_num, chave_pix=pix_chave, nome_pix=pix_nome) if pix_chave else ""),
        "pix_nome":          pix_nome,
        "pix_chave_display": pix_chave_display,
        "pdf_url":           pdf_signed_url,
        "codigo_barras":     "",  # nao temos linha digitavel ainda em tb_faturas
        "venc_br":           dt_venc_br,
        "venc_status":       venc_status,
        "status":            status,
    }

    # Economia — total acumulado + data da primeira fatura + contagem
    qtd_faturas = len(fats_cli)
    desde_data = ""
    if fats_cli:
        primeira = fats_cli[0]
        m0 = int(primeira.get("mes_referencia") or 0)
        a0 = int(primeira.get("ano_referencia") or 0)
        if 1 <= m0 <= 12 and a0:
            desde_data = f"{MESES_BR[m0]} de {a0}"

    eco_acum_num = float(fatura.get("vlr_economia_acum") or 0)
    eco_acum_reais = f"{int(eco_acum_num):,}".replace(",", ".")
    eco_acum_cents = f"{int(round((eco_acum_num - int(eco_acum_num)) * 100)):02d}"

    eco_mes_num = float(fatura.get("vlr_economia_mes") or 0)
    eco_mes_fmt = f"{eco_mes_num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    economia_view = {
        "acumulada_reais":  eco_acum_reais,
        "acumulada_cents":  eco_acum_cents,
        "desde_data":       desde_data or "—",
        "qtd_faturas":      qtd_faturas,
        "mes_valor":        eco_mes_fmt,
    }

    return render_template("portal_cliente.html",
        # Novos dicts (formato handoff Claude Design)
        cliente=cliente_view,
        fatura=fatura_view,
        economia=economia_view,
        # Mantém compatibilidade com OG meta tags (variaveis antigas)
        nome_cliente=nome_full,
        valor_total=_brl(valor_num),
        venc_br=dt_venc_br,
        # Histórico (pra futuras telas, nao usado no layout principal)
        historico=historico,
    )


# ──────────────────────────────────────────────────────────────
#  OG image — ESTÁTICA, vinda do handoff oficial em solev-logo/ (30/05/2026)
#  Arquivos: static/og_background.png (1200×630, horizontal — Twitter/FB)
#            static/og_square_logo.png (1000×1000, quadrado — WhatsApp thumb)
#  Ambos com fundo navy + wordmark areia + brilho solar atrás do "o".
#
#  As infos dinâmicas (nome, valor, venc) aparecem no og:title/og:description
#  ao lado da thumb — não precisamos mais compor o card via Pillow.
#
#  Histórico: até 29/05/2026 a gente compunha o card dinamicamente via
#  solev_og_card.py + 4 rotas Flask (/c/<token>/og.png, .../og-square.png,
#  /cliente/<id>/cobranca.png e -square.png). O designer entregou em 30/05
#  OG cards estáticos puramente da marca. Decisão: adotar os estáticos;
#  todo código dinâmico foi removido.
# ──────────────────────────────────────────────────────────────


# Rota /logo/<filename> removida em 30/05/2026 — servia as logos antigas da
# raiz do projeto (ja deletadas). Tudo usa /static/logo/ ou /static/icons/
# agora via Flask static serve.


# DASHBOARD
@app.route("/")
def dashboard():
    from db import (tb_carregar_clientes, tb_carregar_usinas,
                    tb_carregar_todas_vinculacoes)

    # ── Novas tabelas normalizadas ────────────────────────
    tb_clientes_lst = tb_carregar_clientes()
    tb_usinas_lst   = tb_carregar_usinas()
    vinculos        = tb_carregar_todas_vinculacoes()   # {id_cliente: [vinculos]}

    total_clientes = len(tb_clientes_lst)

    # Clientes sem nenhuma usina vinculada
    ids_com_usina = {id_c for id_c, vlist in vinculos.items() if vlist}
    clientes_sem_usina = [
        {"uc": c["cod_uc"], "nome": c.get("desc_nome", c["cod_uc"])}
        for c in tb_clientes_lst
        if c.get("id_cliente") not in ids_com_usina
    ]

    # Contagem de clientes por id_usina (novas tabelas)
    from collections import defaultdict
    clientes_por_usina = defaultdict(int)
    for vlist in vinculos.values():
        for v in vlist:
            clientes_por_usina[v["id_usina"]] += 1

    # ── Faturas (tb_faturas) com aliases legados para o template ────
    from db import tb_get_faturas_paginado
    faturas_rows, _total = tb_get_faturas_paginado(
        page=1, per_page=999999, status="todos"
    )
    historico = [_adicionar_aliases_legados(f) for f in faturas_rows]

    geracao    = carregar_geracao()
    usinas_leg = carregar_usinas()          # uid → usina (para cruzar geracao)
    clientes_leg = carregar_clientes()      # uc  → cliente (para cruzar receita)

    # Economia acumulada ainda vem do sistema legado (clientes.json)
    total_economia = sum((c.get("economia_acumulada_anterior", 0) or 0) for c in clientes_leg.values())
    pendentes      = sum(1 for item in historico if item.get("status") == "pendente")
    total_receita  = sum(float(item.get("vlr_total_com") or 0) for item in historico)

    # ── Alertas de vencimento ──────────
    hoje = datetime.now().date()
    alertas_vencendo = []
    alertas_vencidas = []
    alertas_a_vencer = []
    for item in historico:
        if item.get("status") in ("pago", "cancelado"):
            continue
        venc_iso = item.get("dt_venc_solev")
        if not venc_iso:
            continue
        try:
            venc_date = datetime.fromisoformat(str(venc_iso)).date()
        except (ValueError, TypeError):
            continue
        diff = (venc_date - hoje).days
        if diff == 0:
            alertas_vencendo.append(item)
        elif diff < 0:
            alertas_vencidas.append(item)
        elif diff <= 3:
            alertas_a_vencer.append(item)

    # ── Usinas chart — lista da nova tabela, dados de geracao/receita do legado ──
    # Mapa nome → uid legado para cruzar geracao diaria
    nome_para_uid = {u.get("nome", ""): uid for uid, u in usinas_leg.items()}

    usinas_chart = []
    for u in tb_usinas_lst:
        nome    = u.get("desc_nome", "")
        uid_leg = nome_para_uid.get(nome, "")

        # kWh acumulado da geracao diaria legada
        registros = geracao.get(uid_leg, []) if uid_leg else []
        kwh_total = sum((r.get("kwh", 0) or 0) for r in registros)

        # Receita e economia do historico legado (por UCs vinculadas no legado)
        vinculados_ucs = {uc for uc, c in clientes_leg.items() if c.get("usina_id") == uid_leg}
        receita_usina  = sum((item.get("total_com", 0) or 0)   for item in historico if item.get("uc") in vinculados_ucs)
        economia_usina = sum((item.get("economia_mes", 0) or 0) for item in historico if item.get("uc") in vinculados_ucs)

        usinas_chart.append({
            "nome":     nome[:20],
            "kwh":      round(kwh_total, 1),
            "receita":  round(receita_usina, 2),
            "economia": round(economia_usina, 2),
            "clientes": clientes_por_usina.get(u["id_usina"], 0),
            "potencia": u.get("qtd_potencia_kwp", 0) or 0,
        })

    # ── Alertas de rateio ─────────────────────────────────
    from routes.whatsapp import _calcular_alertas_rateio
    alertas_rateio = _calcular_alertas_rateio()
    alertas_rateio_ativos = [a for a in alertas_rateio if a["status"] in ("atrasado", "urgente", "proximo")]

    return render_template("dashboard.html",
        total_clientes=total_clientes,
        total_economia=_fmt_brl(total_economia),
        total_receita=_fmt_brl(total_receita),
        pendentes=pendentes,
        ultimas=historico[:5],
        alertas_vencendo=alertas_vencendo,
        alertas_vencidas=alertas_vencidas,
        alertas_a_vencer=alertas_a_vencer,
        clientes_sem_usina=clientes_sem_usina,
        usinas_chart=usinas_chart,
        usinas_labels=json.dumps([u["nome"] for u in usinas_chart]),
        usinas_kwh=json.dumps([u["kwh"] for u in usinas_chart]),
        usinas_receita=json.dumps([u["receita"] for u in usinas_chart]),
        usinas_economia=json.dumps([u["economia"] for u in usinas_chart]),
        alertas_rateio=alertas_rateio,
        alertas_rateio_ativos=alertas_rateio_ativos,
        fmt=_fmt_brl
    )

# CLIENTES
_PER_PAGE_CLIENTES_OPTS = [20, 50, 100]
_PER_PAGE_CLIENTES_DEF  = 20

@app.route("/clientes")
def clientes_lista():
    from db import (tb_carregar_clientes_paginado, tb_carregar_usinas,
                    tb_carregar_todos_enderecos, tb_carregar_todas_vinculacoes)

    page  = max(1, int(request.args.get("page", 1)))
    busca = request.args.get("q", "").strip()
    filtro_usina = request.args.get("filtro_usina", "").strip()
    try:
        per_page = int(request.args.get("per_page", _PER_PAGE_CLIENTES_DEF))
        if per_page not in _PER_PAGE_CLIENTES_OPTS:
            per_page = _PER_PAGE_CLIENTES_DEF
    except (ValueError, TypeError):
        per_page = _PER_PAGE_CLIENTES_DEF

    clientes, total = tb_carregar_clientes_paginado(page, per_page, busca)
    total_pages = max(1, (total + per_page - 1) // per_page)

    usinas   = {u["id_usina"]: u for u in tb_carregar_usinas()}
    enderecos = tb_carregar_todos_enderecos()
    vinculos  = tb_carregar_todas_vinculacoes()

    for c in clientes:
        id_c = c.get("id_cliente")
        end  = enderecos.get(id_c, {})
        c["_endereco"] = ", ".join(filter(None, [
            end.get("desc_logradouro", ""),
            end.get("desc_numero", ""),
            end.get("desc_complemento", ""),
            end.get("desc_setor", ""),
            end.get("desc_cidade", ""),
        ]))
        c["_usinas"] = [
            {**usinas[v["id_usina"]], "id_usina": v["id_usina"]}
            for v in vinculos.get(id_c, [])
            if v["id_usina"] in usinas
        ]
        # Normaliza STATUS (banco usa maiuscula) para c.status no template
        st = c.get("STATUS")
        c["status"] = True if st is None else bool(st)

        # Busca data de leitura atual da fatura mais recente
        # Nome real em tb_faturas: dt_leitura_atual (nao data_leitura_atual)
        from db import tb_get_faturas_por_cliente
        faturas = tb_get_faturas_por_cliente(id_c, limite=1)
        c["_data_leitura_atual"] = faturas[0].get("dt_leitura_atual", "")[:10] if faturas and faturas[0].get("dt_leitura_atual") else None

    # Filtrar por usina se especificado
    if filtro_usina:
        if filtro_usina == "__sem__":
            clientes = [c for c in clientes if not c["_usinas"]]
        else:
            clientes = [c for c in clientes if any(u["id_usina"] == int(filtro_usina) for u in c["_usinas"])]

    return render_template("clientes.html",
        clientes=clientes, usinas=usinas,
        page=page, total_pages=total_pages, total=total,
        busca=busca, filtro_usina=filtro_usina, per_page=per_page,
        per_page_opts=_PER_PAGE_CLIENTES_OPTS,
        fmt=_fmt_brl)


@app.route("/clientes/ver/<path:uc>")
def cliente_ver(uc):
    from db import (tb_get_cliente_por_uc, tb_get_endereco_cliente,
                    tb_get_usinas_do_cliente, tb_carregar_usinas,
                    tb_get_pix_da_usina,
                    tb_get_faturas_por_cliente)

    cliente = tb_get_cliente_por_uc(uc)
    if not cliente:
        logger.warning(f"[CLIENTE_VER] Cliente nao encontrado para UC: {uc}")
        flash("Cliente nao encontrado!", "danger")
        return redirect(url_for("clientes_lista"))

    id_cliente = cliente["id_cliente"]
    endereco = tb_get_endereco_cliente(id_cliente) or {}
    usinas = {u["id_usina"]: u for u in tb_carregar_usinas()}
    usinas_cliente = [
        {**usinas[v["id_usina"]], "id_usina": v["id_usina"]}
        for v in tb_get_usinas_do_cliente(id_cliente)
        if v["id_usina"] in usinas
    ]

    # Formata endereço completo
    endereco_completo = ", ".join(filter(None, [
        endereco.get("desc_logradouro", ""),
        endereco.get("desc_numero", ""),
        endereco.get("desc_complemento", ""),
        endereco.get("desc_setor", ""),
        endereco.get("desc_cidade", ""),
        endereco.get("desc_estado", ""),
    ]))

    # Busca PIX das usinas vinculadas
    pix_info = {}
    for usina in usinas_cliente:
        id_usina = usina["id_usina"]
        pix = tb_get_pix_da_usina(id_usina)
        if pix:
            pix_info[id_usina] = pix

    # Busca histórico de faturas (últimas 12)
    todas_faturas = tb_get_faturas_por_cliente(id_cliente, limite=12)
    ultima_fatura = todas_faturas[0] if todas_faturas else None

    # Monta dados de consumo para o gráfico
    consumo_historico = []
    for fatura in reversed(todas_faturas):  # inverte para ordem cronológica
        mes_ano = f"{fatura.get('mes_fatura', '00')}/{fatura.get('ano_fatura', '0000')}"
        kwh = fatura.get('kwh_consumido', 0) or 0
        consumo_historico.append({
            'mes_ano': mes_ano,
            'kwh': float(kwh)
        })

    from db import tb_get_documentos_cliente, tb_get_outras_ucs
    documentos = tb_get_documentos_cliente(id_cliente)
    outras_ucs = tb_get_outras_ucs(
        id_cliente,
        desc_cpf=cliente.get("desc_cpf", ""),
        desc_nome=cliente.get("desc_nome", ""),
    )

    return render_template("clientes_detalhes.html",
        cliente=cliente, endereco=endereco, endereco_completo=endereco_completo,
        usinas_cliente=usinas_cliente, pix_info=pix_info, ultima_fatura=ultima_fatura,
        todas_faturas=todas_faturas, consumo_historico=consumo_historico,
        documentos=documentos, outras_ucs=outras_ucs)


@app.route("/clientes/ver/<path:uc>/upload_documento", methods=["POST"])
def cliente_upload_documento(uc):
    from db import (tb_get_cliente_por_uc, tb_save_documento_cliente,
                    storage_upload_pdf, storage_ensure_bucket)
    cliente = tb_get_cliente_por_uc(uc)
    if not cliente:
        flash("Cliente não encontrado.", "danger")
        return redirect(url_for("clientes_lista"))

    f = request.files.get("documento")
    if not f or not f.filename:
        flash("Nenhum arquivo enviado.", "warning")
        return redirect(url_for("cliente_ver", uc=uc))

    if not f.filename.lower().endswith(".pdf"):
        flash("Apenas arquivos PDF são aceitos.", "danger")
        return redirect(url_for("cliente_ver", uc=uc))

    tipo_doc = request.form.get("tipo_doc", "outro")
    nome_custom = request.form.get("nome_arquivo", "").strip()
    nome_arquivo = nome_custom if nome_custom else f.filename
    if not nome_arquivo.lower().endswith(".pdf"):
        nome_arquivo += ".pdf"

    from datetime import datetime
    id_cliente = cliente["id_cliente"]
    storage_name = f"cliente{id_cliente}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{nome_arquivo}"
    tmp_path = os.path.join(UPLOAD_FOLDER, storage_name)
    f.save(tmp_path)

    try:
        storage_ensure_bucket("documentos")
        storage_path = storage_upload_pdf(tmp_path, storage_name, bucket="documentos")
        os.unlink(tmp_path)
    except Exception:
        storage_path = f"local/{storage_name}"

    tb_save_documento_cliente(
        id_cliente=id_cliente,
        nome_arquivo=nome_arquivo,
        tipo_doc=tipo_doc,
        storage_path=storage_path,
    )
    flash("Documento salvo com sucesso!", "success")
    return redirect(url_for("cliente_ver", uc=uc) + "?aba=documentos")


@app.route("/clientes/ver/<path:uc>/download_documento/<int:id_doc>")
def cliente_download_documento(uc, id_doc):
    from db import (tb_get_cliente_por_uc, tb_get_documentos_cliente, storage_signed_url)
    from flask import send_file as _send
    cliente = tb_get_cliente_por_uc(uc)
    if not cliente:
        flash("Cliente não encontrado.", "danger")
        return redirect(url_for("clientes_lista"))

    docs = tb_get_documentos_cliente(cliente["id_cliente"])
    doc = next((d for d in docs if d.get("id") == id_doc), None)
    if not doc:
        flash("Documento não encontrado.", "danger")
        return redirect(url_for("cliente_ver", uc=uc))

    storage_path = doc.get("storage_path", "")

    if storage_path.startswith("local/"):
        fname = storage_path[len("local/"):]
        local_path = os.path.join(UPLOAD_FOLDER, fname)
        if os.path.exists(local_path):
            return _send(local_path, as_attachment=True,
                         download_name=doc.get("nome_arquivo", fname))
        flash("Arquivo não encontrado localmente.", "danger")
        return redirect(url_for("cliente_ver", uc=uc))

    try:
        signed_url = storage_signed_url(storage_path, expires_in=300)
        return redirect(signed_url)
    except Exception as e:
        flash(f"Erro ao acessar documento: {e}", "danger")
        return redirect(url_for("cliente_ver", uc=uc))


@app.route("/clientes/ver/<path:uc>/deletar_documento/<int:id_doc>", methods=["POST"])
def cliente_deletar_documento(uc, id_doc):
    from db import (tb_get_cliente_por_uc, tb_get_documentos_cliente,
                    tb_delete_documento_cliente, storage_delete_arquivo)
    cliente = tb_get_cliente_por_uc(uc)
    if not cliente:
        flash("Cliente não encontrado.", "danger")
        return redirect(url_for("clientes_lista"))

    docs = tb_get_documentos_cliente(cliente["id_cliente"])
    doc = next((d for d in docs if d.get("id") == id_doc), None)
    if doc:
        sp = doc.get("storage_path", "")
        if sp and not sp.startswith("local/"):
            try:
                storage_delete_arquivo(sp)
            except Exception:
                pass
        elif sp.startswith("local/"):
            fname = sp[len("local/"):]
            lp = os.path.join(UPLOAD_FOLDER, fname)
            try:
                if os.path.exists(lp):
                    os.remove(lp)
            except Exception:
                pass
        tb_delete_documento_cliente(id_doc)
        flash("Documento removido.", "warning")

    return redirect(url_for("cliente_ver", uc=uc) + "?aba=documentos")


@app.route("/clientes/novo", methods=["GET", "POST"])
def cliente_novo():
    from db import tb_save_cliente, tb_save_endereco, tb_save_cliente_usina, tb_carregar_usinas_com_titular
    usinas = tb_carregar_usinas_com_titular()
    if request.method == "POST":
        nome_cliente = request.form.get("desc_nome", "").strip().upper()
        logger.info(f"[CLIENTE_NOVO] Tentativa de cadastro do cliente: {nome_cliente}")
        try:
            import re as _re_uc
            uc_nova_raw = request.form.get("cod_uc", "").strip()  # UC principal (formato visual)
            uc_nova     = _re_uc.sub(r'\D', '', uc_nova_raw)                  # somente digitos (banco)
            uc_antiga   = request.form.get("uc", "").strip()                  # UC Antiga (formato legado)
            if not uc_nova and not uc_antiga:
                flash("Informe a UC ou a UC Antiga!", "danger")
                return redirect(url_for("cliente_novo"))
            # cod_uc (chave unica DB) = UC Antiga se informada; senao digitos da UC nova
            cod_uc = uc_antiga if uc_antiga else uc_nova
            desc = float(request.form.get("pct_desconto", "20").replace(",", ".") or "20")
            if desc > 1: desc = desc / 100

            # Salva cliente
            def _kwh_field(name):
                try: return float(request.form.get(name, "").replace(",", ".") or 0) or None
                except Exception: return None
            cliente = tb_save_cliente({
                "cod_uc":                  uc_nova,
                "desc_nome":               nome_cliente,
                "desc_apelido":            request.form.get("desc_apelido", "").strip() or None,
                "desc_cpf":                request.form.get("desc_cpf", "").strip(),
                "desc_telefone":           request.form.get("desc_telefone", "").strip(),
                "desc_email":              request.form.get("desc_email", "").strip().lower(),
                "desc_titular_fatura":     request.form.get("desc_titular_fatura", "").strip().upper(),
                "tp_fornecimento":         request.form.get("tp_fornecimento", "").strip(),
                "tp_bandeira":             request.form.get("tp_bandeira", "com_bandeira"),
                "pct_desconto":            desc,
                "dt_adesao":               _data_br_para_iso(request.form.get("dt_adesao", "")),
                "STATUS":                  request.form.get("status_ativo") == "1",
                "qtd_consumo_medio_kwh":   _kwh_field("qtd_consumo_medio_kwh"),
                "qtd_saldo_inicial_kwh":   _kwh_field("qtd_saldo_inicial_kwh"),
                # Titularidade própria do cliente (override do titular da usina p/ login Equatorial)
                "flg_titularidade_propria":     request.form.get("flg_titularidade_propria") == "1",
                "desc_nome_titular_fatura":     request.form.get("desc_nome_titular_fatura", "").strip().upper() or None,
                "desc_cpf_titular_fatura":      request.form.get("desc_cpf_titular_fatura", "").strip() or None,
                "dt_nascimento_titular_fatura": request.form.get("dt_nascimento_titular_fatura", "").strip() or None,
                "proxima_leitura":              request.form.get("proxima_leitura", "").strip() or None,
            })
            id_cliente = cliente.get("id_cliente")

            # Salva endereco
            tb_save_endereco(id_cliente, {
                "desc_logradouro": request.form.get("desc_logradouro", "").strip().upper(),
                "desc_numero":     request.form.get("desc_numero", "").strip(),
                "desc_complemento":request.form.get("desc_complemento", "").strip().upper(),
                "desc_setor":      request.form.get("desc_setor", "").strip().upper(),
                "desc_cidade":     request.form.get("desc_cidade", "").strip().upper(),
                "desc_estado":     request.form.get("desc_estado", "").strip().upper(),
                "cod_cep":         request.form.get("cod_cep", "").strip(),
            })

            # Salva vinculos com usinas
            ids_usinas = request.form.getlist("id_usinas")
            for id_usina in ids_usinas:
                tb_save_cliente_usina(id_cliente, int(id_usina), {})

            logger.info(f"[CLIENTE_NOVO] Cliente criado com sucesso - ID: {id_cliente}, UC: {cod_uc}, Nome: {nome_cliente}")
            flash(f"Cliente {nome_cliente} cadastrado!", "success")
            return redirect(url_for("clientes_lista"))
        except Exception as e:
            import traceback; traceback.print_exc()
            logger.error(f"[CLIENTE_NOVO] Erro ao cadastrar cliente {nome_cliente}: {str(e)}\n{traceback.format_exc()}")
            flash(f"Erro ao cadastrar: {e}", "danger")
            return redirect(url_for("cliente_novo"))
    return render_template("cliente_form.html", cliente=None, endereco=None,
                           usinas=usinas, usinas_cliente=[])


@app.route("/clientes/nova_uc/<path:uc>")
def cliente_nova_uc(uc):
    from db import (tb_get_cliente_por_uc,
                    tb_get_usinas_do_cliente, tb_carregar_usinas_com_titular)
    origem = tb_get_cliente_por_uc(uc)
    if not origem:
        flash("Cliente nao encontrado!", "danger")
        return redirect(url_for("clientes_lista"))
    id_cliente = origem["id_cliente"]
    usinas = tb_carregar_usinas_com_titular()
    usinas_cliente = [v["id_usina"] for v in tb_get_usinas_do_cliente(id_cliente)]
    return render_template("cliente_form.html",
                           cliente=None,
                           prefill=origem,
                           endereco=None,
                           usinas=usinas,
                           usinas_cliente=usinas_cliente)


@app.route("/clientes/editar/<path:uc>", methods=["GET", "POST"])
def cliente_editar(uc):
    from db import (tb_get_cliente_por_uc, tb_save_cliente, tb_save_endereco,
                    tb_get_endereco_cliente, tb_save_cliente_usina,
                    tb_delete_cliente_usina, tb_get_usinas_do_cliente,
                    tb_carregar_usinas_com_titular)
    cliente = tb_get_cliente_por_uc(uc)
    if not cliente:
        logger.warning(f"[CLIENTE_EDITAR] Cliente nao encontrado para UC: {uc}")
        flash("Cliente nao encontrado!", "danger")
        return redirect(url_for("clientes_lista"))
    id_cliente = cliente["id_cliente"]
    usinas = tb_carregar_usinas_com_titular()

    if request.method == "POST":
        nome_cliente = request.form.get("desc_nome", "").strip().upper()
        logger.info(f"[CLIENTE_EDITAR] Atualizacao do cliente ID: {id_cliente}, UC: {uc}, Nome: {nome_cliente}")
        try:
            import re as _re_uc_edit
            nova_uc_nova_raw = request.form.get("cod_uc", "").strip()
            nova_uc_nova     = _re_uc_edit.sub(r'\D', '', nova_uc_nova_raw)  # somente digitos (banco)
            nova_uc_antiga   = request.form.get("uc", "").strip()
            if not nova_uc_nova and not nova_uc_antiga:
                flash("Informe a UC ou a UC Antiga!", "danger")
                return redirect(url_for("cliente_editar", uc=uc))
            novo_cod_uc = nova_uc_antiga if nova_uc_antiga else nova_uc_nova

            desc = float(request.form.get("pct_desconto", "20").replace(",", ".") or "20")
            if desc > 1: desc = desc / 100

            # Atualiza cliente
            def _kwh_field_e(name):
                try: return float(request.form.get(name, "").replace(",", ".") or 0) or None
                except Exception: return None
            tb_save_cliente({
                "id_cliente":              id_cliente,
                "cod_uc":                  nova_uc_nova,
                "desc_nome":               nome_cliente,
                "desc_apelido":            request.form.get("desc_apelido", "").strip() or None,
                "desc_cpf":                request.form.get("desc_cpf", "").strip(),
                "desc_telefone":           request.form.get("desc_telefone", "").strip(),
                "desc_email":              request.form.get("desc_email", "").strip().lower(),
                "desc_titular_fatura":     request.form.get("desc_titular_fatura", "").strip().upper(),
                "tp_fornecimento":         request.form.get("tp_fornecimento", "").strip(),
                "tp_bandeira":             request.form.get("tp_bandeira", "com_bandeira"),
                "pct_desconto":            desc,
                "dt_adesao":               _data_br_para_iso(request.form.get("dt_adesao", "")),
                "STATUS":                  request.form.get("status_ativo") == "1",
                "qtd_consumo_medio_kwh":   _kwh_field_e("qtd_consumo_medio_kwh"),
                "qtd_saldo_inicial_kwh":   _kwh_field_e("qtd_saldo_inicial_kwh"),
                # Titularidade própria do cliente
                "flg_titularidade_propria":     request.form.get("flg_titularidade_propria") == "1",
                "desc_nome_titular_fatura":     request.form.get("desc_nome_titular_fatura", "").strip().upper() or None,
                "desc_cpf_titular_fatura":      request.form.get("desc_cpf_titular_fatura", "").strip() or None,
                "dt_nascimento_titular_fatura": request.form.get("dt_nascimento_titular_fatura", "").strip() or None,
                "proxima_leitura":              request.form.get("proxima_leitura", "").strip() or None,
            })

            # Atualiza endereco
            tb_save_endereco(id_cliente, {
                "desc_logradouro": request.form.get("desc_logradouro", "").strip().upper(),
                "desc_numero":     request.form.get("desc_numero", "").strip(),
                "desc_complemento":request.form.get("desc_complemento", "").strip().upper(),
                "desc_setor":      request.form.get("desc_setor", "").strip().upper(),
                "desc_cidade":     request.form.get("desc_cidade", "").strip().upper(),
                "desc_estado":     request.form.get("desc_estado", "").strip().upper(),
                "cod_cep":         request.form.get("cod_cep", "").strip(),
            })

            # Atualiza vinculos com usinas
            ids_novos  = set(int(x) for x in request.form.getlist("id_usinas"))
            ids_atuais = set(v["id_usina"] for v in tb_get_usinas_do_cliente(id_cliente))
            for id_usina in ids_atuais - ids_novos:
                tb_delete_cliente_usina(id_cliente, id_usina)
            for id_usina in ids_novos - ids_atuais:
                tb_save_cliente_usina(id_cliente, id_usina, {})

            logger.info(f"[CLIENTE_EDITAR] Cliente atualizado com sucesso - ID: {id_cliente}, Novo UC: {novo_cod_uc}")
            flash("Cliente atualizado!", "success")
            return redirect(url_for("clientes_lista"))
        except Exception as e:
            import traceback; traceback.print_exc()
            msg = str(e)
            logger.error(f"[CLIENTE_EDITAR] Erro ao atualizar cliente ID: {id_cliente}, UC: {uc} - {str(e)}\n{traceback.format_exc()}")
            if "23505" in msg and "cod_uc" in msg:
                flash("Essa UC ja esta cadastrada para outro cliente. Verifique se ha duplicatas.", "danger")
            else:
                flash(f"Erro ao salvar: {e}", "danger")
            return redirect(url_for("cliente_editar", uc=uc))

    endereco       = tb_get_endereco_cliente(id_cliente)
    usinas_cliente = [v["id_usina"] for v in tb_get_usinas_do_cliente(id_cliente)]
    return render_template("cliente_form.html", cliente=cliente, endereco=endereco,
                           usinas=usinas, usinas_cliente=usinas_cliente)


@app.route("/clientes/remover/<path:uc>")
def cliente_remover(uc):
    from db import tb_get_cliente_por_uc, tb_delete_cliente, tb_delete_endereco_cliente
    logger.info(f"[CLIENTE_REMOVER] Tentativa de remocao da UC: {uc}")
    cliente = tb_get_cliente_por_uc(uc)
    if cliente:
        id_cliente = cliente["id_cliente"]
        nome_cliente = cliente.get("desc_nome", "")
        tb_delete_endereco_cliente(id_cliente)
        tb_delete_cliente(id_cliente)
        logger.warning(f"[CLIENTE_REMOVER] Cliente removido - ID: {id_cliente}, UC: {uc}, Nome: {nome_cliente}")
        flash(f"Cliente {nome_cliente} removido!", "warning")
    else:
        logger.warning(f"[CLIENTE_REMOVER] Cliente nao encontrado para UC: {uc}")
    return redirect(url_for("clientes_lista"))

@app.route("/clientes/remover_post", methods=["POST"])
def cliente_remover_post():
    """Remove cliente por POST (para UCs com caracteres especiais)."""
    from db import tb_get_cliente_por_uc, tb_delete_cliente, tb_delete_endereco_cliente
    uc = request.form.get("uc", "")
    logger.info(f"[CLIENTE_REMOVER_POST] Tentativa de remocao via POST da UC: {uc}")
    cliente = tb_get_cliente_por_uc(uc)
    if cliente:
        id_cliente = cliente["id_cliente"]
        nome_cliente = cliente.get("desc_nome", "")
        tb_delete_endereco_cliente(id_cliente)
        tb_delete_cliente(id_cliente)
        logger.warning(f"[CLIENTE_REMOVER_POST] Cliente removido - ID: {id_cliente}, UC: {uc}, Nome: {nome_cliente}")
        flash(f"Cliente {nome_cliente} removido!", "warning")
    else:
        logger.warning(f"[CLIENTE_REMOVER_POST] Cliente nao encontrado para UC: {uc}")
        flash(f"UC '{uc}' nao encontrada!", "danger")
    return redirect(url_for("clientes_lista"))

# ── COBRANCAS DO DIA: lista clientes com leitura no intervalo + status ───────
@app.route("/cobrancas/dia", methods=["GET"])
def cobrancas_dia():
    """Lista clientes com proxima_leitura num intervalo de datas, com status
    da cobranca de cada um (sem fatura / PDF baixado / cobranca gerada / pago).

    Query params:
      de   = DD/MM/AAAA (default: hoje)
      ate  = DD/MM/AAAA (default: hoje + 10 dias)
    """
    from datetime import date, timedelta
    from db import _db

    def _parse_br(s, default):
        if not s:
            return default
        try:
            d, m, a = s.split("/")
            return date(int(a), int(m), int(d))
        except Exception:
            return default

    # Default: leitura entre hoje-10 e hoje+3.
    # Motivo: Equatorial emite fatura 5-10 dias DEPOIS da leitura, entao
    # leituras recentes (passadas) ja tem fatura disponivel no portal.
    # Inclui +3 dias pra antecipar quem esta prestes a fechar a leitura.
    hoje = date.today()
    de_default  = hoje - timedelta(days=10)
    ate_default = hoje + timedelta(days=3)
    de   = _parse_br(request.args.get("de"),  de_default)
    ate  = _parse_br(request.args.get("ate"), ate_default)

    # Carrega clientes com proxima_leitura no intervalo
    clientes = _db().select("tb_clientes", order="proxima_leitura.asc")
    no_intervalo = []
    for c in clientes:
        pl_raw = (c.get("proxima_leitura") or "").strip()
        if not pl_raw:
            continue
        try:
            pl = date.fromisoformat(pl_raw[:10])
        except Exception:
            continue
        if de <= pl <= ate:
            c["_proxima_leitura_dt"] = pl
            c["_proxima_leitura_br"] = pl.strftime("%d/%m/%Y")
            c["_dias_ate_leitura"]   = (pl - hoje).days
            no_intervalo.append(c)

    # Busca vinculos (uc -> nome_usina) para indicar se cliente tem usina vinculada
    from db import tb_mapa_uc_para_usina
    mapa_usina = tb_mapa_uc_para_usina()
    for c in no_intervalo:
        c["_nome_usina"] = mapa_usina.get(c.get("cod_uc"), "")

    # Busca status em tb_faturas pro mes_ref de cada cliente (mes da leitura)
    if no_intervalo:
        # Indexa faturas por (id_cliente, ano, mes)
        faturas = _db().select("tb_faturas")
        fat_por_chave = {}
        for f in faturas:
            chv = (f.get("id_cliente"), f.get("ano_referencia"), f.get("mes_referencia"))
            fat_por_chave[chv] = f
        for c in no_intervalo:
            pl = c["_proxima_leitura_dt"]
            # mes da leitura define mes da cobranca (Equatorial emite ~5-10 dias depois)
            chv = (c.get("id_cliente"), pl.year, pl.month)
            f = fat_por_chave.get(chv)
            if not f:
                c["_status"]       = "sem_fatura"
                c["_status_label"] = "Sem fatura"
                c["_status_icon"]  = "🚫"
                c["_status_color"] = "secondary"
            elif f.get("dt_pagamento"):
                c["_status"]       = "pago"
                c["_status_label"] = "Pago"
                c["_status_icon"]  = "💰"
                c["_status_color"] = "success"
            elif f.get("pdf_solev"):
                c["_status"]       = "cobranca"
                c["_status_label"] = "Cobranca gerada"
                c["_status_icon"]  = "✅"
                c["_status_color"] = "primary"
            elif f.get("pdf_equatorial"):
                c["_status"]       = "baixada"
                c["_status_label"] = "PDF baixado"
                c["_status_icon"]  = "📥"
                c["_status_color"] = "info"
            else:
                c["_status"]       = "pendente"
                c["_status_label"] = "Registrada"
                c["_status_icon"]  = "📭"
                c["_status_color"] = "warning"
            c["_id_fatura"] = f.get("id_fatura") if f else None
            c["_mes_ref"]   = f"{pl.month}/{pl.year}"

    return render_template(
        "cobrancas_dia.html",
        clientes_lista=no_intervalo,
        de_br=de.strftime("%d/%m/%Y"),
        ate_br=ate.strftime("%d/%m/%Y"),
        hoje_br=hoje.strftime("%d/%m/%Y"),
        total=len(no_intervalo),
    )


# ── DISPARA DOWNLOAD EM BACKGROUND PARA UCs SELECIONADAS ─────────────────────
@app.route("/cobrancas/dia/baixar", methods=["POST"])
def cobrancas_dia_baixar():
    """Recebe lista de UCs marcadas e dispara baixar_equatorial.py em background.
    O download e a geracao de cobranca rodam num subprocesso isolado.
    """
    import subprocess, sys as _sys
    ucs = request.form.getlist("ucs")
    mes_ref = request.form.get("mes_ref", "").strip()
    if not ucs:
        flash("Selecione pelo menos uma UC.", "warning")
        return redirect(url_for("cobrancas_dia",
                                de=request.form.get("de"),
                                ate=request.form.get("ate")))
    if not mes_ref:
        from datetime import date
        mes_ref = date.today().strftime("%m/%Y")

    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "baixar_equatorial.py")
    cmd = [_sys.executable, script_path,
           "--ucs", ",".join(ucs),
           "--mes", mes_ref,
           "--headless", "--forcar"]

    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs_download")
    os.makedirs(log_dir, exist_ok=True)
    from datetime import datetime as _dt
    log_path = os.path.join(log_dir, f"download_{_dt.now().strftime('%Y%m%d_%H%M%S')}.log")
    log_file = open(log_path, "w", encoding="utf-8")
    subprocess.Popen(
        cmd, stdout=log_file, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    logger.info(f"[COBRANCAS_DIA] Download iniciado: {len(ucs)} UCs, log={log_path}")
    flash(f"Download iniciado em background para {len(ucs)} UC(s) — mes {mes_ref}. "
          f"Recarregue a pagina em ~1 min para ver o progresso. Log: {os.path.basename(log_path)}",
          "info")
    return redirect(url_for("cobrancas_dia",
                            de=request.form.get("de"),
                            ate=request.form.get("ate")))


# ── SCEE da fatura (GET retorna JSON, POST salva) ────────────────────────────
@app.route("/cobrancas/dia/scee/<int:id_fatura>", methods=["GET", "POST"])
def cobrancas_dia_scee(id_fatura):
    """API JSON: visualizar e editar campos SCEE de uma fatura.
    Esses valores alimentam o rateio (nao recalculam o PDF da cobranca).
    """
    from db import _db
    if request.method == "GET":
        rows = _db().select("tb_faturas", filtros={"id_fatura": id_fatura})
        if not rows:
            return {"erro": "Fatura nao encontrada"}, 404
        f = rows[0]
        # usinas_geradoras pode vir como string JSON ou lista (depende do driver)
        ug = f.get("usinas_geradoras") or []
        if isinstance(ug, str):
            import json as _json
            try: ug = _json.loads(ug)
            except Exception: ug = []
        return {
            "id_fatura":              id_fatura,
            "id_cliente":             f.get("id_cliente"),
            "mes_referencia":         f.get("mes_referencia"),
            "ano_referencia":         f.get("ano_referencia"),
            "cod_uc_usina":           f.get("cod_uc_usina") or "",
            "desc_ciclo_geracao":    f.get("desc_ciclo_geracao") or "",
            "pct_rateio_scee":       f.get("pct_rateio_scee") or 0,
            "qtd_geracao_usina_kwh": f.get("qtd_geracao_usina_kwh") or 0,
            "qtd_excedente_kwh":     f.get("qtd_excedente_kwh") or 0,
            "qtd_credito_kwh":       f.get("qtd_credito_kwh") or 0,
            "qtd_saldo_kwh":         f.get("qtd_saldo_kwh") or 0,
            "qtd_saldo_exp_30d_kwh": f.get("qtd_saldo_exp_30d_kwh") or 0,
            "qtd_saldo_exp_60d_kwh": f.get("qtd_saldo_exp_60d_kwh") or 0,
            "usinas_geradoras":      ug,
        }
    # POST: atualiza os campos SCEE
    def _f(name):
        v = (request.form.get(name) or "").strip().replace(".", "").replace(",", ".")
        try:
            return float(v) if v else 0
        except ValueError:
            return 0

    def _num_str(s):
        s = (s or "").strip().replace(".", "").replace(",", ".")
        try:    return float(s) if s else 0.0
        except: return 0.0

    # Lista de usinas geradoras vinda como arrays paralelos (uc[], ger[], exc[])
    ucs_list  = request.form.getlist("usina_uc[]")
    gers_list = request.form.getlist("usina_ger[]")
    excs_list = request.form.getlist("usina_exc[]")
    usinas_lista = []
    soma_ger = soma_exc = 0.0
    for i, uc in enumerate(ucs_list):
        uc_clean = (uc or "").strip()
        if not uc_clean:
            continue  # ignora linhas com UC em branco
        ger = _num_str(gers_list[i]) if i < len(gers_list) else 0.0
        exc = _num_str(excs_list[i]) if i < len(excs_list) else 0.0
        usinas_lista.append({"uc": uc_clean, "geracao_kwh": ger, "excedente_kwh": exc})
        soma_ger += ger; soma_exc += exc

    dados = {
        "cod_uc_usina":          (request.form.get("cod_uc_usina") or "").strip() or None,
        "desc_ciclo_geracao":   (request.form.get("desc_ciclo_geracao") or "").strip() or None,
        "pct_rateio_scee":      _f("pct_rateio_scee"),
        "qtd_geracao_usina_kwh":_f("qtd_geracao_usina_kwh"),
        "qtd_excedente_kwh":    _f("qtd_excedente_kwh"),
        "qtd_credito_kwh":      _f("qtd_credito_kwh"),
        "qtd_saldo_kwh":        _f("qtd_saldo_kwh"),
        "qtd_saldo_exp_30d_kwh":_f("qtd_saldo_exp_30d_kwh"),
        "qtd_saldo_exp_60d_kwh":_f("qtd_saldo_exp_60d_kwh"),
    }
    # Se enviou lista de usinas, grava + sobrescreve somas (qtd_geracao_usina_kwh, qtd_excedente_kwh)
    # e UC principal = a com maior geração
    if usinas_lista:
        dados["usinas_geradoras"]      = usinas_lista
        dados["qtd_geracao_usina_kwh"] = round(soma_ger, 2)
        dados["qtd_excedente_kwh"]     = round(soma_exc, 2)
        principal = max(usinas_lista, key=lambda u: u.get("geracao_kwh", 0))
        dados["cod_uc_usina"] = principal["uc"]
    try:
        _db().patch("tb_faturas", {"id_fatura": id_fatura}, dados)
        return {"ok": True, "msg": f"Salvo. {len(usinas_lista)} usina(s) geradora(s)." if usinas_lista else "Salvo."}
    except Exception as e:
        logger.error(f"[COBRANCAS_DIA_SCEE] Erro salvando fatura {id_fatura}: {e}")
        return {"erro": str(e)}, 500


# GERAR COBRANCA (individual)
@app.route("/gerar", methods=["GET", "POST"])
def gerar():
    if request.method == "POST":
        if "pdf" not in request.files or request.files["pdf"].filename == "":
            logger.warning("[GERAR] Tentativa de gerar cobranca sem arquivo PDF")
            flash("Selecione um arquivo PDF!", "danger"); return redirect(url_for("gerar"))
        pdf = request.files["pdf"]
        pdf_path = os.path.join(UPLOAD_FOLDER, pdf.filename)
        pdf.save(pdf_path)
        uc_override = request.form.get("uc_override", "").strip() or None
        acao = request.form.get("acao", "gerar").strip().lower()

        logger.info(f"[GERAR] Iniciando geracao de cobranca - Arquivo: {pdf.filename}, UC override: {uc_override}, Acao: {acao}")

        # ── PREVIEW: extrai e mostra tela editavel (sem gerar PDF) ──
        if acao == "preview":
            ok, msg, dados, cliente, chave_real, equatorial = _montar_dados_de_pdf(pdf_path, uc_override)
            if not ok:
                logger.error(f"[GERAR] Erro ao montar dados do PDF {pdf.filename}: {msg}")
                flash(f"Erro: {msg}", "danger")
                return redirect(url_for("gerar"))
            calc = calcular(dados)
            logger.info(f"[GERAR] Preview montado com sucesso para cliente UC: {chave_real}")
            # Preview reutiliza o template manual; o "Confirmar" posta em /gerar/manual
            return render_template(
                "gerar_preview.html",
                dados=dados, calc=calc, cliente=cliente,
                chave_real=chave_real,
                origem="pdf",
                post_url=url_for("gerar_manual"),
                band_am=dados.get("_band_am_kwh", 0),
                band_vm=dados.get("_band_vm_kwh", 0),
                desconto_pct_input=(float(dados.get("desconto_pct", 0.20)) * 100),
                economia_acum_input="",
                equatorial_pdf_path=pdf_path,
            )

        # Fluxo padrao: gera direto
        ok, msg, dados_calc = _gerar_uma_cobranca(pdf_path, uc_override)
        if ok:
            output_path = dados_calc.get("output_path", "desconhecido") if dados_calc else "desconhecido"
            logger.info(f"[GERAR] Cobranca gerada com sucesso - {msg} - Arquivo: {output_path}")
            flash(f"Cobranca gerada! {msg}", "success")
            # Redireciona para download
            if dados_calc and dados_calc.get("output_path"):
                return redirect(url_for("resultado", pdf=os.path.basename(dados_calc["output_path"])))
            return redirect(url_for("faturas"))
        else:
            logger.error(f"[GERAR] Erro ao gerar cobranca - {msg}")
            flash(f"Erro: {msg}", "danger")
            return redirect(url_for("gerar"))
    from db import tb_carregar_clientes
    # Dropdown: prioriza novas tabelas, fallback para legado
    tb_cli = {c["cod_uc"]: {
                  "nome": c.get("desc_nome", c["cod_uc"]),
                  "desconto_pct": float(c.get("pct_desconto") or 0.20),
              } for c in tb_carregar_clientes()}
    leg_cli = {uc: c for uc, c in carregar_clientes().items() if uc not in tb_cli}
    clientes_dropdown = {**tb_cli, **leg_cli}
    return render_template("gerar.html", clientes=clientes_dropdown)

# ── API: Busca cliente por UC (AJAX) ────────────────────────
@app.route("/api/cliente/<path:uc>")
def api_cliente(uc):
    logger.debug(f"[API_CLIENTE] Busca de cliente UC: {uc}")
    try:
        chave_real, cli = _carregar_cliente_hibrido(uc)
        if cli:
            logger.debug(f"[API_CLIENTE] Cliente encontrado para UC: {uc}")
            resp = dict(cli)
            resp["uc"] = chave_real
            return jsonify(resp)
        logger.warning(f"[API_CLIENTE] Cliente nao encontrado para UC: {uc}")
        return jsonify({"erro": f"Cliente UC {uc} nao encontrado. Cadastre primeiro."})
    except Exception as e:
        import traceback; traceback.print_exc()
        logger.error(f"[API_CLIENTE] Erro ao buscar cliente UC {uc}: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"erro": f"Erro ao buscar cliente: {e}"}), 500

# ── API: Reconciliação SCEE ─────────────────────────────────
@app.route("/api/scee-reconciliacao")
def api_scee_reconciliacao():
    """Busca dados de reconciliação SCEE para uma combinação
    (UC cliente + UC usina + ciclo). Retorna o que o banco já tem:

    - geracao_real_usina: kWh totais da usina naquele ciclo
      (de tb_faturas onde a usina é o cliente, ou tb_geracao_mensal)
    - pct_rateio_cadastrado: % cadastrado em tb_cliente_usina

    A "verdade matemática" (excedente ÷ geração) é calculada no front-end.
    """
    uc_cliente = (request.args.get("uc_cliente") or "").strip()
    uc_usina   = (request.args.get("uc_usina")   or "").strip()
    ciclo      = (request.args.get("ciclo")      or "").strip()  # "MM/AAAA"

    resultado = {
        "geracao_real_usina":      None,
        "pct_rateio_cadastrado":   None,
        "fonte_geracao":           None,
        "fonte_rateio":            None,
        "uc_cliente":              uc_cliente,
        "uc_usina":                uc_usina,
        "ciclo":                   ciclo,
    }

    # 1) Buscar geração real da usina — múltiplas fontes em ordem de prioridade:
    #    a) tb_usinas (cadastro da usina, campo qtd_geracao_media_mensal)
    #    b) tb_faturas (fatura registrada da própria usina, qtd_geracao_usina_kwh)
    if uc_usina and ciclo and "/" in ciclo:
        try:
            from db import _resolver_id_cliente_por_uc, _db as _dbf
            import re as _re_norm
            # Normalização: remove pontos/hífens e zeros à esquerda pra comparação
            def _norm_uc(s):
                return _re_norm.sub(r"\D", "", str(s or "")).lstrip("0")
            alvo_uc = _norm_uc(uc_usina)

            # a) Busca em tb_usinas — fonte mais confiável (cadastro humano)
            usinas = _dbf().select("tb_usinas",
                                   columns="id_usina,desc_nome,cod_uc_geradora,qtd_geracao_media_mensal")
            for u in usinas:
                if _norm_uc(u.get("cod_uc_geradora")) == alvo_uc:
                    ger = u.get("qtd_geracao_media_mensal") or 0
                    if ger and float(ger) > 0:
                        resultado["geracao_real_usina"] = float(ger)
                        resultado["fonte_geracao"] = f"cadastro usina '{u.get('desc_nome','')}' (id={u.get('id_usina')})"
                        # Guarda também o id_usina pra próxima etapa do rateio
                        resultado["_id_usina_match"] = u.get("id_usina")
                    break

            # b) Fallback: fatura da própria usina em tb_faturas (caso seja cadastrada como cliente)
            if not resultado["geracao_real_usina"]:
                id_cli_usina = _resolver_id_cliente_por_uc(uc_usina)
                if id_cli_usina:
                    m, y = ciclo.split("/")
                    mes_int, ano_int = int(m), int(y)
                    rows = _dbf().select("tb_faturas", filtros={
                        "id_cliente":     id_cli_usina,
                        "ano_referencia": ano_int,
                        "mes_referencia": mes_int,
                    })
                    if rows:
                        f0 = rows[0]
                        ger = (f0.get("qtd_geracao_usina_kwh") or 0)
                        if ger and float(ger) > 0:
                            resultado["geracao_real_usina"] = float(ger)
                            resultado["fonte_geracao"] = f"fatura usina (id_fatura={f0.get('id_fatura')})"
        except Exception as _e:
            app.logger.warning(f"[scee-reconciliacao] geração: {_e}")

    # 2) Buscar pct_rateio cadastrado em tb_cliente_usina
    if uc_cliente and uc_usina:
        try:
            from db import (_resolver_id_cliente_por_uc, _db as _dbf,
                            tb_get_usinas_do_cliente)
            id_cli = _resolver_id_cliente_por_uc(uc_cliente)
            if id_cli:
                vincs = tb_get_usinas_do_cliente(id_cli)
                # Cruza id_usina → tb_usinas.cod_uc para casar com uc_usina
                if vincs:
                    import re as _re
                    digits_alvo = _re.sub(r"\D", "", uc_usina).lstrip("0")
                    for v in vincs:
                        id_u = v.get("id_usina")
                        if not id_u: continue
                        uros = _dbf().select("tb_usinas",
                                             filtros={"id_usina": id_u},
                                             columns="cod_uc")
                        if uros:
                            cod_u = _re.sub(r"\D", "", str(uros[0].get("cod_uc") or "")).lstrip("0")
                            if cod_u and cod_u == digits_alvo:
                                pct = v.get("pct_rateio")
                                if pct is not None:
                                    resultado["pct_rateio_cadastrado"] = float(pct)
                                    resultado["fonte_rateio"] = "tb_cliente_usina"
                                    break
        except Exception as _e:
            app.logger.warning(f"[scee-reconciliacao] rateio: {_e}")

    return jsonify(resultado)


# ── API: Busca clientes por UC (antiga ou nova) ou nome ─────
@app.route("/api/extrair-fatura-equatorial", methods=["POST"])
def api_extrair_fatura_equatorial():
    """Recebe PDF da fatura Equatorial e retorna os dados extraidos
    com pos-processamento: padroniza mes_referencia, sobrescreve tarifa
    pela cadastrada quando consumo totalmente compensado, normaliza datas."""
    if "pdf" not in request.files:
        return jsonify({"erro": "PDF nao enviado"}), 400
    f = request.files["pdf"]
    if not f or not f.filename:
        return jsonify({"erro": "Arquivo invalido"}), 400
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"erro": "Envie um arquivo PDF"}), 400

    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix="extracao_")
    try:
        f.save(tmp.name)
        tmp.close()
        from extrair_equatorial import extrair_equatorial
        dados = extrair_equatorial(tmp.name)

        # ── Pos-processamento ────────────────────────────────────────────
        # 1) Padroniza mes_referencia para MM/AAAA (extrator pode devolver "5/2026")
        mes_ref = (dados.get("mes_referencia") or "").strip()
        if "/" in mes_ref:
            partes = mes_ref.split("/")
            if len(partes) == 2 and partes[0].isdigit() and partes[1].isdigit():
                mes_ref = f"{int(partes[0]):02d}/{partes[1]}"
                dados["mes_referencia"] = mes_ref

        # 2) Tarifa Equatorial cadastrada — sobrescreve quando consumo
        #    totalmente compensado (caso em que a fatura Equatorial mostra
        #    tarifa SCEE reduzida, que nao deve ser usada para SEM SOLEV)
        consumo   = float(dados.get("consumo_kwh") or 0)
        compensado = float(dados.get("compensado_kwh") or 0)
        nao_comp  = float(dados.get("nao_comp_kwh") or 0)
        totalmente_compensado = (consumo > 0 and abs(consumo - compensado) < 0.5 and nao_comp < 0.5)

        cadastrada = None
        if mes_ref:
            try:
                from utils import obter_tarifa_mes
                cadastrada = obter_tarifa_mes(mes_ref)
            except Exception as _e:
                app.logger.warning(f"[api_extrair_fatura] obter_tarifa_mes falhou: {_e}")

        if cadastrada:
            # Sempre devolve a tarifa cadastrada (cliente espera ver a tarifa cheia
            # da Equatorial no SEM SOLEV, mesmo quando parcialmente compensado).
            # Override apenas se cadastrada > 0; senao mantem o extraido.
            if float(cadastrada.get("tarifa_sem") or 0) > 0:
                dados["tarifa_sem"]  = cadastrada["tarifa_sem"]
                dados["tarifa_scee"] = cadastrada["tarifa_sem"]
            dados["_tarifa_origem"] = "cadastrada"
        else:
            dados["_tarifa_origem"] = "extraida_fatura"

        # Bandeira — FONTE ÚNICA (utils.resolver_tarifa_bandeira): tarifa real do
        # PDF (adc_R$ / qtd_kWh) com fallback no tb_tarifas. Antes este endpoint
        # usava SEMPRE a cadastrada (ex.: 0,018053 velho), ignorando o adc/qtd do
        # PDF — era a origem do bug que reaparecia ao "Extrair dados da fatura".
        from utils import resolver_tarifa_bandeira
        _ba_st = float((cadastrada or {}).get("bandeira_amarela", 0) or 0)
        _bv_st = float((cadastrada or {}).get("bandeira_vermelha", 0) or 0)
        _ba, _bv, _binfo = resolver_tarifa_bandeira(dados, _ba_st, _bv_st)
        dados["bandeira_amarela"]  = _ba
        dados["bandeira_vermelha"] = _bv

        # 3) Datas: garantir que aliases apontem para as DATAS, nao para
        #    o numero do medidor (extrair_equatorial.py:40 tem alias errado)
        if dados.get("data_leitura_anterior"):
            dados["anterior_leitura"] = dados["data_leitura_anterior"]
        if dados.get("data_leitura_atual"):
            dados["data_leitura"] = dados["data_leitura_atual"]

        # 4) Tipo de fornecimento: limpa encoding ruim (ex.: MONOF�SICO)
        tf = (dados.get("tipo_fornecimento") or "").upper()
        if tf.startswith("MONO"):
            dados["tipo_fornecimento"] = "Monofásico"
        elif tf.startswith("BIF") or tf.startswith("BI"):
            dados["tipo_fornecimento"] = "Bifásico"
        elif tf.startswith("TRI"):
            dados["tipo_fornecimento"] = "Trifásico"

        dados["_totalmente_compensado"] = totalmente_compensado

        # ── Reconciliação SCEE (busca dados auxiliares do banco) ──
        try:
            uc_cli   = (dados.get("uc") or dados.get("unidade_consumidora") or "").strip()
            uc_usina = (dados.get("scee_uc_geradora") or "").strip()
            ciclo    = (dados.get("scee_ciclo_mes")   or dados.get("ciclo_geracao_mes") or "").strip()
            if uc_usina and ciclo:
                from db import _resolver_id_cliente_por_uc, _db as _dbf, tb_get_usinas_do_cliente
                import re as _re_norm2
                def _norm_uc(s):
                    return _re_norm2.sub(r"\D", "", str(s or "")).lstrip("0")
                alvo_uc = _norm_uc(uc_usina)

                rec = {"geracao_real_usina": None, "pct_rateio_cadastrado": None,
                       "fonte_geracao": None, "fonte_rateio": None}

                # 1a) Geração real da usina — busca em tb_usinas (cadastro humano)
                usinas_db = _dbf().select("tb_usinas",
                                          columns="id_usina,desc_nome,cod_uc_geradora,qtd_geracao_media_mensal")
                for u in usinas_db:
                    if _norm_uc(u.get("cod_uc_geradora")) == alvo_uc:
                        ger = u.get("qtd_geracao_media_mensal") or 0
                        if ger and float(ger) > 0:
                            rec["geracao_real_usina"] = float(ger)
                            rec["fonte_geracao"] = f"cadastro usina '{u.get('desc_nome','')}'"
                        break

                # 1b) Fallback: fatura da própria usina em tb_faturas
                if not rec["geracao_real_usina"]:
                    id_cli_us = _resolver_id_cliente_por_uc(uc_usina)
                    if id_cli_us and "/" in ciclo:
                        m, y = ciclo.split("/"); mes_int, ano_int = int(m), int(y)
                        rows_u = _dbf().select("tb_faturas", filtros={
                            "id_cliente": id_cli_us,
                            "ano_referencia": ano_int,
                            "mes_referencia": mes_int,
                        })
                        if rows_u:
                            ger = rows_u[0].get("qtd_geracao_usina_kwh") or 0
                            if ger and float(ger) > 0:
                                rec["geracao_real_usina"] = float(ger)
                                rec["fonte_geracao"] = f"fatura usina id={rows_u[0].get('id_fatura')}"
                # 2) Rateio cadastrado (cliente x usina)
                if uc_cli:
                    id_cli = _resolver_id_cliente_por_uc(uc_cli)
                    if id_cli:
                        vincs = tb_get_usinas_do_cliente(id_cli)
                        import re as _re_rec
                        digits_alvo = _re_rec.sub(r"\D", "", uc_usina).lstrip("0")
                        for v in vincs:
                            id_u = v.get("id_usina")
                            if not id_u: continue
                            uros = _dbf().select("tb_usinas",
                                                 filtros={"id_usina": id_u},
                                                 columns="cod_uc")
                            if uros:
                                cod_u = _re_rec.sub(r"\D", "", str(uros[0].get("cod_uc") or "")).lstrip("0")
                                if cod_u == digits_alvo:
                                    pct = v.get("pct_rateio")
                                    if pct is not None:
                                        rec["pct_rateio_cadastrado"] = float(pct)
                                        rec["fonte_rateio"] = "tb_cliente_usina"
                                    break
                dados["_scee_reconciliacao"] = rec
        except Exception as _e:
            app.logger.warning(f"[api_extrair_fatura] reconciliacao: {_e}")

        return jsonify(dados)
    except Exception as e:
        import traceback
        app.logger.error(f"[api_extrair_fatura] Falha: {e}")
        app.logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"erro": f"Falha na extracao: {e}"}), 500
    finally:
        try: os.unlink(tmp.name)
        except Exception: pass


@app.route("/api/clientes/busca")
def api_clientes_busca():
    """Autocomplete: casa por nome, UC antiga (cod_uc) E UC nova (cod_uc).
    Normaliza pontos/hifens para que '2026.034.798.403-00' bata com '202603479840300'."""
    try:
        import re as _re_b
        q = request.args.get("q", "").strip().lower()
        logger.debug(f"[API_CLIENTES_BUSCA] Busca autocomplete: query='{q}'")
        if not q or len(q) < 2:
            return jsonify([])

        # Versao so com digitos para casar UCs em qualquer formato
        q_norm = _re_b.sub(r'[.\-\s]', '', q)

        def _matches_uc(uc_val: str) -> bool:
            if not uc_val:
                return False
            v = str(uc_val).lower()
            if q in v:
                return True
            v_norm = _re_b.sub(r'[.\-\s]', '', v)
            return bool(q_norm) and q_norm in v_norm

        from db import tb_carregar_clientes
        resultados = []
        seen = set()

        for c in tb_carregar_clientes():
            uc     = (c.get("cod_uc") or "").strip()
            uc_alt = (c.get("cod_uc") or "").strip()
            nome   = (c.get("desc_nome") or "").strip()
            if q in nome.lower() or _matches_uc(uc) or _matches_uc(uc_alt):
                resultados.append({
                    "uc":           uc,
                    "uc_alt":       uc_alt,
                    "uc_alt_fmt":   _fmt_uc15(uc_alt),
                    "nome":         nome,
                    "desconto_pct": float(c.get("pct_desconto") or 0.20),
                })
                seen.add(uc)

        # Fallback legado (clientes que ainda nao estao em tb_clientes)
        for uc, c in carregar_clientes().items():
            if uc in seen:
                continue
            uc_alt = (c.get("cod_uc") or "").strip()
            nome   = (c.get("nome") or "").strip()
            if q in nome.lower() or _matches_uc(uc) or _matches_uc(uc_alt):
                resultados.append({
                    "uc":           uc,
                    "uc_alt":       uc_alt,
                    "uc_alt_fmt":   _fmt_uc15(uc_alt),
                    "nome":         nome,
                    "desconto_pct": c.get("desconto_pct", 0.20),
                })

        logger.debug(f"[API_CLIENTES_BUSCA] Retornando {len(resultados[:12])} resultados para query '{q}'")
        return jsonify(resultados[:12])
    except Exception as e:
        import traceback; traceback.print_exc()
        logger.error(f"[API_CLIENTES_BUSCA] Erro na busca autocomplete: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"erro": str(e)}), 500

# ── API: Busca tarifa do mes (AJAX) ─────────────────────────
@app.route("/api/validar-pix-uc/<path:uc>")
def api_validar_pix_uc(uc):
    """
    Antes de gerar cobranca, valida se a UC tem QR Code PIX disponivel.

    Retornos possiveis (sempre HTTP 200):
      { "status": "ok",        "recebedor": "Nome PIX" }
      { "status": "sem_pix",   "id_usina": 12, "nome_usina": "USTrindade",
                                "id_investidor": 34 }   # usina vinculada SEM PIX
      { "status": "sem_usina", "id_cliente": 56, "nome_cliente": "FULANO" }
      { "status": "sem_cliente" }
    """
    from db import (
        tb_get_cliente_por_uc as _cli,
        tb_get_usinas_do_cliente as _vinc,
        tb_get_pix_da_usina as _pix,
        tb_get_usina as _usi,
    )
    cli = _cli(uc)
    if not cli:
        return jsonify({"status": "sem_cliente"})

    vinculos = _vinc(cli["id_cliente"])
    if not vinculos:
        return jsonify({
            "status":       "sem_usina",
            "id_cliente":   cli["id_cliente"],
            "nome_cliente": cli.get("desc_nome", ""),
        })

    id_usina = vinculos[0]["id_usina"]
    usina    = _usi(id_usina) or {}
    rec      = _pix(id_usina)
    if not rec:
        return jsonify({
            "status":        "sem_pix",
            "id_usina":      id_usina,
            "nome_usina":    usina.get("desc_nome", ""),
            "id_investidor": usina.get("id_investidor"),
        })

    return jsonify({
        "status":    "ok",
        "recebedor": rec.get("desc_nome_pix") or rec.get("desc_nome", ""),
    })


# ── GERAR COBRANCA MANUAL ───────────────────────────────────
@app.route("/gerar/manual", methods=["GET", "POST"])
def gerar_manual():
    if request.method == "POST":
        try:
            acao = request.form.get("acao", "gerar").strip().lower()  # 'preview' ou 'gerar'

            uc = request.form["uc"].strip()
            chave_real, cliente = _carregar_cliente_hibrido(uc)
            if not cliente:
                flash(f"Cliente UC {uc} nao encontrado!", "danger")
                return redirect(url_for("gerar_manual"))
            chave_real = chave_real or uc

            def _p(field, default=0):
                v = request.form.get(field, str(default)).strip()
                if not v: return default
                # BR-aware:
                #  - "14.143,00"  → ambos: "." milhar, "," decimal
                #  - "0,75"       → só ",":  decimal BR
                #  - "1.135823"   → só "." com >3 dígitos após: decimal US (tarifa)
                #  - "14.143"     → só "." com exatamente 3 dígitos após: milhar BR
                #  - "100.000.50" → vários ".": todos milhar (não acontece normalmente)
                if "." in v and "," in v:
                    v = v.replace(".", "").replace(",", ".")
                elif "," in v:
                    v = v.replace(",", ".")
                elif "." in v:
                    partes = v.split(".")
                    # Múltiplos pontos OU 1 ponto seguido de exatamente 3 dígitos → milhar BR
                    if len(partes) > 2 or (len(partes) == 2 and len(partes[1]) == 3 and partes[0]):
                        v = v.replace(".", "")
                try: return float(v)
                except: return default

            consumo = _p("consumo_kwh")
            tarifa = _p("tarifa")
            # COM SOLEV: split entre compensado/nao-comp vem dos campos *_com do formulario
            # Fallback: campos antigos sem sufixo (para retrocompat com gerar_auto / API)
            compensado = _p("consumo_compensado_com", _p("consumo_compensado", consumo))
            nao_comp   = _p("consumo_nao_comp_com",   _p("consumo_nao_comp", 0))
            ilum = _p("iluminacao_publica")
            multa = _p("multa")
            juros = _p("juros")
            band_am = _p("bandeira_amarela")
            band_vm = _p("bandeira_vermelha")
            mes_ref = request.form.get("mes_referencia", "").strip()
            venc_solev = request.form.get("vencimento_solev", "").strip()

            # ── Novos campos manuais (COM SOLEV) ──
            multa_com_manual     = _p("multa_com", 0)
            juros_com_manual     = _p("juros_com", 0)
            difci_manual         = _p("difci", 0)
            ecnisenta_manual     = _p("ecnisenta", 0)
            ajuste_valor_manual  = _p("ajuste_valor", 0)
            correcao_ipca_manual = _p("correcao_ipca", 0)
            economia_acum_manual = request.form.get("economia_acumulada", "").strip()

            # ── Campos SCEE (geração solar) ──
            scee_ciclo_mes     = request.form.get("scee_ciclo_mes", "").strip()
            scee_uc_geradora   = request.form.get("scee_uc_geradora", "").strip()
            scee_pct_rateio         = _p("scee_pct_rateio", 0)
            scee_geracao_usina_kwh  = _p("scee_geracao_usina_kwh", 0)   # calculado pelo JS (excedente ÷ % rateio)
            scee_excedente_kwh      = _p("scee_excedente_kwh", 0)
            scee_credito_kwh   = _p("scee_credito_kwh", 0)
            scee_saldo_30d     = _p("scee_saldo_exp_30d", 0)
            scee_saldo_60d     = _p("scee_saldo_exp_60d", 0)

            if not mes_ref or not venc_solev:
                faltando = []
                if not mes_ref:    faltando.append("Mes de referencia")
                if not venc_solev: faltando.append("Vencimento SOLEV")
                flash(f"Obrigatorio: {', '.join(faltando)}", "danger")
                return redirect(url_for("gerar_manual"))

            # Se tarifa nao informada, busca do cadastro
            if tarifa <= 0:
                tm = obter_tarifa_mes(mes_ref)
                if tm:
                    tarifa = tm.get("tarifa_sem", 0) or 0
                if tarifa <= 0:
                    flash("Tarifa nao encontrada. Informe manualmente ou cadastre em Tarifas.", "danger")
                    return redirect(url_for("gerar_manual"))

            # Desconto: aceita override do preview, senao usa do cliente
            desconto_override = request.form.get("desconto_pct_override", "").strip()
            if desconto_override:
                try:
                    desconto = float(desconto_override.replace(",", "."))
                except ValueError:
                    desconto = cliente.get("desconto_pct", 0.20)
            else:
                desconto = cliente.get("desconto_pct", 0.20)
            if desconto > 1: desconto = desconto / 100

            # Endereco: campo unico ou legado
            endereco = cliente.get("endereco", "")
            if not endereco:
                l1 = cliente.get("endereco_linha1", "")
                l2 = cliente.get("endereco_linha2", "")
                l3 = cliente.get("endereco_linha3", "")
                endereco = ", ".join(p for p in [l1, l2, l3] if p)

            # ── Fatura Equatorial em anexo (sem extracao) ──
            equatorial_pdf_path = None
            if "equatorial_pdf" in request.files:
                f = request.files["equatorial_pdf"]
                if f and f.filename:
                    fname = f"{mes_ref.replace('/', '')}-EQUATORIAL-{chave_real}.pdf"
                    equatorial_pdf_path = os.path.join(UPLOAD_FOLDER, fname)
                    f.save(equatorial_pdf_path)
            # Path persistido vindo do preview (preserva anexo entre preview→confirmar)
            if not equatorial_pdf_path:
                persisted = request.form.get("_equatorial_pdf_path", "").strip()
                if persisted and os.path.exists(persisted):
                    equatorial_pdf_path = persisted

            # ── Economia acumulada: override manual ou valor do cadastro ──
            if economia_acum_manual:
                eco_acum_anterior = float(economia_acum_manual.replace(",", "."))
            else:
                eco_acum_anterior = max(0, cliente.get("economia_acumulada_anterior", 0) or 0)
                # Idempotencia: se JA existe fatura deste mes (regeracao), o
                # acumulado do cadastro ja contem a economia dela. Desconta para
                # o PDF nao duplicar a economia ao regerar a mesma cobranca.
                if cliente.get("_fonte") == "tb_clientes" and cliente.get("_id_cliente"):
                    import re as _re_eco
                    _mm = _re_eco.match(r"^\s*(\d{1,2})/(\d{4})\s*$", mes_ref or "")
                    if _mm:
                        from db import tb_economia_mes_fatura
                        _eco_ja = tb_economia_mes_fatura(
                            cliente["_id_cliente"], _mm.group(2), _mm.group(1))
                        eco_acum_anterior = max(0.0, eco_acum_anterior - _eco_ja)

            dados = {
                "nome": cliente["nome"],
                "cpf": cliente.get("cpf", ""),
                "endereco": endereco,
                "endereco_linha1": cliente.get("endereco_linha1", endereco[:50] if endereco else ""),
                "endereco_linha2": cliente.get("endereco_linha2", ""),
                "endereco_linha3": cliente.get("endereco_linha3", ""),
                "desconto_pct": desconto,
                "tarifa_sem": tarifa,
                "modo_bandeira": cliente.get("modo_bandeira", "com_bandeira"),
                "valor_cobranca_anterior": cliente.get("valor_cobranca_anterior", 0) or 0,
                "venc_solev_anterior": cliente.get("venc_solev_anterior", ""),
                "data_pagamento_anterior": cliente.get("data_pagamento_anterior", ""),
                "economia_acumulada_anterior": eco_acum_anterior,
                "codigo_barras": cliente.get("codigo_barras", "CODIGO DE BARRA EM DESENVOLVIMENTO"),
                "linha_digitavel": cliente.get("linha_digitavel", "XXXX.XXXX  XXXXX.XXXXX  XXXXX.XXXXX  X  XXXXXXXXXXXXXX"),
                "pix_payload": cliente.get("pix_payload", ""),
                "unidade_consumidora": cliente.get("cod_uc") or chave_real,
                "tipo_fornecimento": request.form.get("tipo_fornecimento", "Bifasico"),
                "mes_referencia": mes_ref,
                "anterior_leitura": request.form.get("anterior_leitura", ""),
                "data_leitura": request.form.get("data_leitura", ""),
                "proxima_leitura": request.form.get("proxima_leitura", ""),
                "n_dias": request.form.get("n_dias", ""),
                "venc_equatorial": request.form.get("venc_equatorial", ""),
                "consumo_kwh": consumo,
                "consumo_compensado": compensado,
                "consumo_nao_comp": nao_comp,
                "iluminacao_publica": ilum,
                "multa": multa, "juros": juros,
                "correcao_ipca": correcao_ipca_manual,
                "bandeira_amarela": band_am * consumo if band_am > 0 else 0,
                "bandeira_vermelha": band_vm * consumo if band_vm > 0 else 0,
                # Bandeiras — campos novos pro calculator (R$/kWh + ADC do PDF + modo)
                "bandeira_tarifa_amar":   band_am,
                "bandeira_tarifa_verm":   band_vm,
                "adc_bandeira_amarela":   0,  # manual: nao tem ADC do PDF
                "adc_bandeira_vermelha":  0,
                "modo_bandeira":          cliente.get("modo_bandeira", "com_bandeira"),
                "vencimento_solev": venc_solev,
                "equatorial_pdf": equatorial_pdf_path,
                # ── Overrides manuais para COM SOLEV ──
                "multa_com_override": multa_com_manual,
                "juros_com_override": juros_com_manual,
                "difci":              difci_manual,
                "ecnisenta":          ecnisenta_manual,
                "ajuste_valor":       ajuste_valor_manual,
            }

            # ── PREVIEW: calcula sem gerar PDF e mostra tela editavel ──
            if acao == "preview":
                dados_calc_preview = calcular(dados)
                return render_template(
                    "gerar_preview.html",
                    dados=dados, calc=dados_calc_preview,
                    cliente=cliente, chave_real=chave_real,
                    origem="manual",
                    post_url=url_for("gerar_manual"),
                    band_am=band_am, band_vm=band_vm,
                    desconto_pct_input=(desconto * 100),
                    economia_acum_input=economia_acum_manual,
                    equatorial_pdf_path=equatorial_pdf_path or "",
                )

            # QR Code PIX: apenas se cliente vinculado a usina com recebedor configurado
            dados_calc_pre = calcular(dados)
            _total = dados_calc_pre.get("_total_com", 0)
            _qr = None
            try:
                _id_cliente = cliente.get("_id_cliente")
                if _id_cliente:
                    from db import tb_get_usinas_do_cliente, tb_get_pix_da_usina
                    _vinculos = tb_get_usinas_do_cliente(_id_cliente)
                    if _vinculos:
                        _rec = tb_get_pix_da_usina(_vinculos[0]["id_usina"])
                        if _rec:
                            _qr = gerar_qrcode_pix(
                                _total,
                                chave_pix=_rec.get("desc_pix"),
                                nome_pix=_rec.get("desc_nome_pix") or _rec.get("desc_nome"),
                                cidade_pix=_rec.get("desc_cidade_pix"),
                            )
                            dados["pix_chave_display"] = _formatar_chave_pix_display(
                                _rec.get("desc_pix"))
            except Exception as _e:
                app.logger.warning(f"[pix manual] Falha ao buscar recebedor: {_e}")
            # Sem fallback global — QR so aparece se usina vinculada tiver recebedor
            if _qr:
                dados["pix_qr_path"] = _qr

            # Resolve id_cliente (nome do arquivo) e id_fatura (texto no PDF)
            try:
                from db import _resolver_id_cliente_por_uc, tb_reservar_id_fatura
                _id_cli_pdf_m = _resolver_id_cliente_por_uc(chave_real)
                if _id_cli_pdf_m:
                    dados["id_cliente"] = _id_cli_pdf_m
                    import re as _re_mr_pdf_m
                    _mm_m = _re_mr_pdf_m.match(r"^(\d{1,2})/(\d{4})$", str(mes_ref).strip())
                    if _mm_m:
                        dados["id_fatura"] = tb_reservar_id_fatura(
                            _id_cli_pdf_m, int(_mm_m.group(2)), int(_mm_m.group(1)))
            except Exception as _e_res_m:
                app.logger.warning(f"[gerar_manual] resolver id_cliente/id_fatura falhou: {_e_res_m}")

            gerar_cobranca(dados)
            dados_calc = calcular(dados)

            # Write-back pos-cobranca: tb_clientes ou legado JSON
            _total_com  = round(dados_calc.get("_total_com", 0), 2)
            _eco_acum   = round(dados_calc.get("_economia_acum", eco_acum_anterior), 2)
            if cliente.get("_fonte") == "tb_clientes" and cliente.get("_id_cliente"):
                from db import tb_writeback_pos_cobranca
                tb_writeback_pos_cobranca(cliente["_id_cliente"], _total_com,
                                          venc_solev, _eco_acum)
            else:
                clientes = carregar_clientes()
                if chave_real in clientes:
                    clientes[chave_real]["valor_cobranca_anterior"]    = _total_com
                    clientes[chave_real]["venc_solev_anterior"]      = venc_solev
                    clientes[chave_real]["data_pagamento_anterior"]     = ""
                    clientes[chave_real]["economia_acumulada_anterior"] = _eco_acum
                    salvar_clientes(clientes)

            # Upload de ambos os PDFs ao Supabase Storage
            _pdf_url_m = ""
            _pdf_eq_url_m = ""
            _output_path_m = dados_calc.get("output_path", "")
            try:
                from db import storage_ensure_bucket, storage_upload_pdf
                storage_ensure_bucket("faturas")
                if _output_path_m and os.path.exists(_output_path_m):
                    _pdf_url_m = storage_upload_pdf(_output_path_m, os.path.basename(_output_path_m), "faturas")
                if equatorial_pdf_path and os.path.exists(equatorial_pdf_path):
                    _pdf_eq_url_m = storage_upload_pdf(equatorial_pdf_path, os.path.basename(equatorial_pdf_path), "faturas")
            except Exception as _se:
                app.logger.warning(f"[storage manual] Upload falhou: {_se}")

            from db import inserir_fatura as _inserir_hist_m
            _venc_eq_m = ""
            _saldo_eq_m = 0
            _multa_eq_m = 0
            _juros_eq_m = 0
            _total_eq_m = 0
            _fio_b_m    = 0
            _ilum_m     = 0
            _eq_m_scee = {}   # dados SCEE extraídos do PDF (se houver)
            if equatorial_pdf_path:
                try:
                    from extrair_equatorial import extrair_equatorial as _extr
                    _eq_m = _extr(equatorial_pdf_path, verbose=False)
                    _venc_eq_m  = _eq_m.get("venc_equatorial", "")
                    _saldo_eq_m = _eq_m.get("saldo_kwh", 0)
                    _multa_eq_m = _eq_m.get("multa", 0)
                    _juros_eq_m = _eq_m.get("juros", 0)
                    _total_eq_m = _eq_m.get("total_fatura", 0)
                    _fio_b_m    = _eq_m.get("valor_parc_injet", 0)
                    _ilum_m     = _eq_m.get("iluminacao_publica", 0)
                    _eq_m_scee  = _eq_m   # guarda para fallback SCEE
                except Exception:
                    pass

            # SCEE: prioriza form (digitado/corrigido pelo operador), depois extrator
            def _scee_val(form_key, extr_key, default=0):
                v = request.form.get(form_key, "").strip()
                if v:
                    try: return float(v.replace(",", "."))
                    except ValueError: pass
                return _eq_m_scee.get(extr_key, default) or default

            _inserir_hist_m(
                uc=chave_real,
                nome=cliente["nome"],
                mes_ref=mes_ref,
                total_sem=round(dados_calc.get("_total_sem", 0), 2),
                total_com=round(dados_calc.get("_total_com", 0), 2),
                economia_mes=round(dados_calc.get("_economia_mes", 0), 2),
                economia_acum=round(dados_calc.get("_economia_acum", 0), 2),
                venc=venc_solev,
                pdf_path=_output_path_m,
                consumo_kwh=consumo,
                compensado_kwh=compensado,
                data_leitura_atual=request.form.get("data_leitura", ""),
                pdf_url=_pdf_url_m,
                pdf_equatorial=equatorial_pdf_path or "",
                pdf_equatorial_url=_pdf_eq_url_m,
                venc_equatorial=_venc_eq_m,
                saldo_kwh=_saldo_eq_m,
                multa_equatorial=_multa_eq_m,
                juros_equatorial=_juros_eq_m,
                multa_mes=dados_calc.get("_multa_com", 0),
                juros_mes=dados_calc.get("_juros_com", 0),
                fatura_equatorial=_total_eq_m,
                fio_b=_fio_b_m,
                ilum_publica=_ilum_m,
                band_amar_equatorial=dados_calc.get("_band_amar_equatorial", 0),
                band_verm_equatorial=dados_calc.get("_band_verm_equatorial", 0),
                band_amar_solev=dados_calc.get("_band_amar_solev", 0),
                band_verm_solev=dados_calc.get("_band_verm_solev", 0),
                ajuste_valor=dados_calc.get("ajuste_valor", 0),
                difci=dados_calc.get("difci", 0),
                ecnisenta=dados_calc.get("ecnisenta", 0),
                anterior_leitura=request.form.get("anterior_leitura", ""),
                proxima_leitura=request.form.get("proxima_leitura", "") or _eq_m_scee.get("proxima_leitura", ""),
                n_dias=int(request.form.get("n_dias", 0) or 0),
                # SCEE
                scee_ciclo_mes   = scee_ciclo_mes   or _eq_m_scee.get("scee_ciclo_mes", "") or _eq_m_scee.get("ciclo_geracao_mes", ""),
                scee_uc_geradora = scee_uc_geradora or _eq_m_scee.get("scee_uc_geradora", ""),
                scee_pct_rateio        = scee_pct_rateio or _scee_val("scee_pct_rateio", "scee_pct_rateio"),
                # Geração da usina: valor enviado pelo JS (excedente ÷ pct),
                # fallback: calcular aqui também se tiver os dados
                scee_geracao_usina_kwh = scee_geracao_usina_kwh or (
                    round(_scee_val("scee_excedente_kwh", "excedente_recebido_kwh") /
                          ((_scee_val("scee_pct_rateio", "scee_pct_rateio") or scee_pct_rateio) / 100), 2)
                    if (_scee_val("scee_excedente_kwh", "excedente_recebido_kwh") > 0 and
                        (_scee_val("scee_pct_rateio", "scee_pct_rateio") or scee_pct_rateio) > 0)
                    else 0
                ),
                scee_excedente_kwh     = scee_excedente_kwh or _scee_val("scee_excedente_kwh", "excedente_recebido_kwh"),
                scee_credito_kwh       = scee_credito_kwh   or _scee_val("scee_credito_kwh",   "credito_recebido_kwh"),
                scee_saldo_exp_30d_kwh = scee_saldo_30d     or _scee_val("scee_saldo_exp_30d", "saldo_expirar_30d_kwh"),
                scee_saldo_exp_60d_kwh = scee_saldo_60d     or _scee_val("scee_saldo_exp_60d", "saldo_expirar_60d_kwh"),
            )

            # ── Salva histórico de consumo (12 meses) para futuras predições de rateio ──
            try:
                from db import salvar_historico_consumo, _resolver_id_cliente_por_uc
                _hist = (_eq_m_scee or {}).get("historico_meses") or []
                if _hist:
                    _idc = _resolver_id_cliente_por_uc(chave_real)
                    if _idc:
                        n = salvar_historico_consumo(_idc, mes_ref, _hist,
                                                     origem=f"fatura_{mes_ref.replace('/','_')}")
                        if n > 0:
                            app.logger.info(f"[gerar_manual] {n} meses de histórico salvos para cliente {_idc}")
            except Exception as _he:
                app.logger.warning(f"[gerar_manual] histórico de consumo: {_he}")

            flash(f"Cobranca manual gerada para {cliente['nome']}!", "success")
            if dados_calc.get("output_path"):
                return redirect(url_for("resultado", pdf=os.path.basename(dados_calc["output_path"])))
            return redirect(url_for("faturas"))
        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            traceback.print_exc()
            app.logger.error(f"[gerar_manual] ERRO COMPLETO:\n{tb_str}")
            flash(f"Erro: {e!r} | {type(e).__name__} | {tb_str.splitlines()[-2] if tb_str else ''}", "danger")
            return redirect(url_for("gerar_manual"))
    from db import tb_carregar_clientes
    tb_cli  = {c["cod_uc"]: {
                   "nome": c.get("desc_nome", c["cod_uc"]),
                   "desconto_pct": float(c.get("pct_desconto") or 0.20),
               } for c in tb_carregar_clientes()}
    leg_cli = {uc: c for uc, c in carregar_clientes().items() if uc not in tb_cli}
    return render_template("gerar_manual.html", clientes={**tb_cli, **leg_cli})

# ─── GERAR COBRANCAS AUTOMATICO ────────────────────────────────────────────
@app.route("/gerar/auto", methods=["GET", "POST"])
def gerar_auto():
    from baixar_equatorial import (
        _primeiro_ultimo, _camel_case, _sanitizar_nome, BASE_PASTA_USINAS,
        gerar_cobranca_cliente,
    )

    mes_ref = request.values.get("mes", datetime.now().strftime("%m/%Y")).strip()
    try:
        datetime.strptime(mes_ref, "%m/%Y")
    except ValueError:
        mes_ref = datetime.now().strftime("%m/%Y")
    import glob as _glob
    from baixar_equatorial import _mes_para_yyyymm
    mes_str = mes_ref.replace("/", "")   # legado MMYYYY
    yyyymm  = _mes_para_yyyymm(mes_ref)  # novo YYYYMM

    # ── POST: gerar cobrancas para UCs selecionadas ──────────────────────────
    if request.method == "POST" and request.form.get("acao") == "gerar":
        ucs_gerar = request.form.getlist("uc_sel")
        clientes_all = carregar_clientes()
        ok_count = 0; err_msgs = []
        for uc in ucs_gerar:
            c = clientes_all.get(uc, {})
            nome = c.get("nome", uc)
            nome_camel = _camel_case(_primeiro_ultimo(nome))
            uc_nova = c.get("cod_uc") or uc
            # buscar usina via vinculos (ja importados no escopo local)
            from db import tb_carregar_todas_vinculacoes, carregar_usinas as _usinasDB
            vinculos = tb_carregar_todas_vinculacoes()
            usinas_map = {str(uid): u for uid, u in _usinasDB().items()}
            id_cli = c.get("_id_cliente")
            nome_usina = ""
            if id_cli and vinculos.get(id_cli):
                id_usina = str(vinculos[id_cli][0].get("id_usina", ""))
                u_data = usinas_map.get(id_usina, {})
                nome_usina = u_data.get("nome") or u_data.get("desc_nome", "")
            pasta_cli = os.path.join(
                BASE_PASTA_USINAS, nome_usina,
                _sanitizar_nome(f"{nome_camel}-{uc_nova}"),
            )
            # Busca PDF Equatorial: novo (com sufixo UC), legado (sem sufixo) ou glob
            from utils import uc_sufixo as _uc_suf
            _suf = _uc_suf(uc)
            pdf_eq = None
            for _cand in [
                os.path.join(pasta_cli, f"{yyyymm}-Equatorial{nome_camel}{_suf}.pdf"),
                os.path.join(pasta_cli, f"{yyyymm}-Equatorial{nome_camel}.pdf"),
                os.path.join(pasta_cli, f"{mes_str}-Equatorial{nome_camel}{_suf}.pdf"),
                os.path.join(pasta_cli, f"{mes_str}-Equatorial{nome_camel}.pdf"),
            ]:
                if os.path.exists(_cand):
                    pdf_eq = _cand; break
            if not pdf_eq:
                for _m in _glob.glob(os.path.join(pasta_cli, f"*Equatorial*{nome_camel}*.pdf")):
                    if os.path.basename(_m).startswith((yyyymm, mes_str)):
                        pdf_eq = _m; break
            if not pdf_eq:
                err_msgs.append(f"{nome}: fatura Equatorial nao encontrada")
                continue
            try:
                out = gerar_cobranca_cliente(pdf_eq, pasta_cli, mes_str, nome_camel, uc)
                if out:
                    ok_count += 1
                else:
                    err_msgs.append(f"{nome}: erro ao gerar")
            except Exception as exc:
                err_msgs.append(f"{nome}: {exc}")
        total_sel = len(ucs_gerar)
        if ok_count:
            flash(f"{ok_count} de {total_sel} cobrancas geradas com sucesso.", "success")
        for e in err_msgs[:5]:
            flash(e, "warning")
        return redirect(url_for("gerar_auto", mes=mes_ref))

    # ── GET: montar tabela com status de cada cliente ────────────────────────
    clientes_all = carregar_clientes()
    try:
        from db import tb_carregar_todas_vinculacoes, carregar_usinas as _usinasDB
        vinculos_todos = tb_carregar_todas_vinculacoes()   # {id_cliente: [vinculos]}
        usinas_todas   = _usinasDB()                       # {str(id_usina): dados}
        usina_map = {str(uid): (u.get("nome") or u.get("desc_nome", ""))
                     for uid, u in usinas_todas.items()}
    except Exception:
        vinculos_todos = {}; usina_map = {}

    rows = []
    for uc, c in clientes_all.items():
        nome      = c.get("nome", uc)
        nome_camel = _camel_case(_primeiro_ultimo(nome))
        uc_nova   = c.get("cod_uc") or uc
        titular   = c.get("titular_fatura", "")
        id_cli    = c.get("_id_cliente")

        nome_usina = ""
        if id_cli and vinculos_todos.get(id_cli):
            id_usina  = str(vinculos_todos[id_cli][0].get("id_usina", ""))
            nome_usina = usina_map.get(id_usina, "")

        pasta_cli = os.path.join(
            BASE_PASTA_USINAS, nome_usina,
            _sanitizar_nome(f"{nome_camel}-{uc_nova}"),
        )
        # Procura PDF Equatorial: novo (com sufixo UC), legado (sem sufixo) ou glob
        from utils import uc_sufixo as _uc_suf
        _suf = _uc_suf(uc)
        pdf_eq = None
        for _cand in [
            os.path.join(pasta_cli, f"{yyyymm}-Equatorial{nome_camel}{_suf}.pdf"),
            os.path.join(pasta_cli, f"{yyyymm}-Equatorial{nome_camel}.pdf"),
            os.path.join(pasta_cli, f"{mes_str}-Equatorial{nome_camel}{_suf}.pdf"),
            os.path.join(pasta_cli, f"{mes_str}-Equatorial{nome_camel}.pdf"),
        ]:
            if os.path.exists(_cand):
                pdf_eq = _cand; break
        if not pdf_eq:
            _matches = _glob.glob(os.path.join(pasta_cli, f"*-Equatorial{nome_camel}*.pdf"))
            for _m in _matches:
                if os.path.basename(_m).startswith((yyyymm, mes_str)):
                    pdf_eq = _m; break
        # Procura cobranca SOLEV: novo (com sufixo UC) primeiro, depois legados
        pdf_co = None
        for _cand in [
            os.path.join(pasta_cli, f"{yyyymm}-SoLev{nome_camel}{_suf}.pdf"),  # novo padrão
            os.path.join(pasta_cli, f"{yyyymm}-SoLev{nome_camel}.pdf"),        # canonico sem sufixo
            os.path.join(pasta_cli, f"{yyyymm}-ContaLev{nome_camel}.pdf"),     # legado v1
            os.path.join(pasta_cli, f"{yyyymm}-Contalev{nome_camel}.pdf"),     # legado v1
            os.path.join(pasta_cli, f"{yyyymm}-SOLEV{nome_camel}.pdf"),        # legado v1
            os.path.join(pasta_cli, f"{mes_str}-{nome_camel}Contalev.pdf"),    # legado antigo
            os.path.join(pasta_cli, f"{yyyymm}-{nome_camel}Contalev.pdf"),     # legado antigo
        ]:
            if os.path.exists(_cand):
                pdf_co = _cand; break
        if not pdf_co:
            for _m in _glob.glob(os.path.join(pasta_cli, f"*SoLev*.pdf")):
                if os.path.basename(_m).startswith((yyyymm, mes_str)):
                    pdf_co = _m; break
        if not pdf_co:
            for _m in _glob.glob(os.path.join(pasta_cli, f"*ContaLev*.pdf")):
                if os.path.basename(_m).startswith((yyyymm, mes_str)):
                    pdf_co = _m; break
        if not pdf_co:
            for _m in _glob.glob(os.path.join(pasta_cli, f"*Contalev*.pdf")):
                if os.path.basename(_m).startswith((yyyymm, mes_str)):
                    pdf_co = _m; break
        eq_ok  = pdf_eq is not None
        co_ok  = pdf_co is not None

        rows.append({
            "uc":       uc,
            "nome":     nome,
            "uc_nova":  uc_nova,
            "usina":    nome_usina,
            "titular":  titular,
            "eq_ok":    eq_ok,
            "co_ok":    co_ok,
            "pdf_co":   pdf_co or "",
        })

    rows.sort(key=lambda r: r["nome"])
    usinas_opts   = sorted({r["usina"]   for r in rows if r["usina"]})
    titulares_opts = sorted({r["titular"] for r in rows if r["titular"]})

    return render_template(
        "gerar_auto.html",
        rows          = rows,
        mes_ref       = mes_ref,
        usinas_opts   = usinas_opts,
        titulares_opts = titulares_opts,
        total         = len(rows),
        com_equatorial = sum(1 for r in rows if r["eq_ok"]),
        com_solev  = sum(1 for r in rows if r["co_ok"]),
    )


@app.route("/gerar/auto/download")
def gerar_auto_download():
    path = request.args.get("path", "").strip()
    if not path or not os.path.exists(path):
        flash("Arquivo nao encontrado.", "danger")
        return redirect(url_for("gerar_auto"))
    return send_file(path, as_attachment=True,
                     download_name=os.path.basename(path),
                     mimetype="application/pdf")


# ─── JOBS ASSINCRONOS (download + geracao em background) ────────────────────
import uuid as _uuid
_jobs: dict = {}   # {job_id: {tipo, total, done, ok, erros, log, running}}

def _job_novo(tipo: str, total: int) -> str:
    jid = _uuid.uuid4().hex[:8]
    _jobs[jid] = {"tipo": tipo, "total": total, "done": 0,
                  "ok": 0, "erros": [], "avisos": [], "log": [],
                  "running": True}
    return jid


def _job_aviso(jid: str, msg: str):
    """Adiciona um aviso nao-bloqueante (ex: UC sem PIX)."""
    if jid in _jobs:
        _jobs[jid]["avisos"].append(msg)


def _checar_pix_uc(uc: str, nome_cli: str = "") -> str | None:
    """
    Retorna mensagem de aviso se a UC NAO tem PIX configurado.
    Retorna None se esta OK.
    """
    try:
        from db import (
            tb_get_cliente_por_uc, tb_get_usinas_do_cliente,
            tb_get_pix_da_usina, tb_get_usina,
        )
        cli = tb_get_cliente_por_uc(uc)
        if not cli:
            return None  # sem cliente em tb_clientes — silencia
        vinc = tb_get_usinas_do_cliente(cli["id_cliente"])
        if not vinc:
            return f"{nome_cli or uc}: sem usina vinculada → cobranca sai sem QR PIX"
        id_us = vinc[0]["id_usina"]
        if not tb_get_pix_da_usina(id_us):
            usi = tb_get_usina(id_us) or {}
            return (f"{nome_cli or uc}: usina '{usi.get('desc_nome', '')}' sem chave PIX "
                    f"→ cobranca sai sem QR PIX")
    except Exception:
        pass
    return None

def _job_log(jid: str, msg: str):
    if jid in _jobs:
        _jobs[jid]["log"].append(msg)

def _job_fim(jid: str):
    if jid in _jobs:
        _jobs[jid]["running"] = False


@app.route("/gerar/auto/progresso/<jid>")
def gerar_auto_progresso(jid):
    job = _jobs.get(jid)
    if not job:
        return jsonify({"erro": "Job nao encontrado"}), 404
    return jsonify(job)


@app.route("/gerar/auto/baixar", methods=["POST"])
def gerar_auto_baixar():
    """Inicia download das faturas Equatorial em background via Playwright."""
    ucs    = request.form.getlist("uc_sel")
    mes_ref = request.form.get("mes", datetime.now().strftime("%m/%Y")).strip()
    if not ucs:
        return jsonify({"erro": "Nenhuma UC selecionada"}), 400

    jid = _job_novo("baixar", len(ucs))

    def _run():
        # Garante UTF-8 na thread (prints com emojis do baixar_equatorial)
        for _s in (sys.stdout, sys.stderr):
            if _s and hasattr(_s, 'reconfigure'):
                try: _s.reconfigure(encoding='utf-8', errors='replace')
                except Exception: pass
        try:
            from baixar_equatorial import (
                processar_uc, buscar_uc_nova, buscar_credenciais_usina,
                _camel_case, _primeiro_ultimo, ja_baixado,
            )
            from playwright.sync_api import sync_playwright
            import time as _time

            clientes_all = carregar_clientes()
            _job_log(jid, f"Iniciando download de {len(ucs)} fatura(s) — {mes_ref}")

            with sync_playwright() as pw:
                for i, uc in enumerate(ucs, 1):
                    c   = clientes_all.get(uc, {})
                    nome = c.get("nome", uc)
                    _job_log(jid, f"[{i}/{len(ucs)}] {nome}…")
                    # Aviso se UC sem PIX (cobranca gerada apos download sai sem QR)
                    _avp = _checar_pix_uc(uc, nome)
                    if _avp:
                        _job_aviso(jid, _avp)
                        _job_log(jid, f"  ⚠ {_avp}")
                    try:
                        result = processar_uc(pw, uc, c, mes_ref, headless=False)
                        if result:
                            _jobs[jid]["ok"] += 1
                            _job_log(jid, f"  ✓ Baixado: {os.path.basename(result)}")
                        else:
                            _jobs[jid]["erros"].append(nome)
                            _job_log(jid, f"  ✗ Falhou")
                    except Exception as exc:
                        _jobs[jid]["erros"].append(f"{nome}: {exc}")
                        _job_log(jid, f"  ✗ Erro: {exc}")
                    _jobs[jid]["done"] += 1
                    if i < len(ucs):
                        _time.sleep(2)
        except Exception as exc:
            _job_log(jid, f"Erro fatal: {exc}")
        finally:
            _job_fim(jid)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"job_id": jid})


@app.route("/gerar/auto/gerar-job", methods=["POST"])
def gerar_auto_gerar_job():
    """Gera cobrancas SOLEV em background para as UCs selecionadas."""
    ucs     = request.form.getlist("uc_sel")
    mes_ref = request.form.get("mes", datetime.now().strftime("%m/%Y")).strip()
    if not ucs:
        return jsonify({"erro": "Nenhuma UC selecionada"}), 400

    jid = _job_novo("gerar", len(ucs))

    def _run():
        try:
            import glob as _glob
            from baixar_equatorial import (
                _camel_case, _primeiro_ultimo, _sanitizar_nome,
                _mes_para_yyyymm, BASE_PASTA_USINAS, gerar_cobranca_cliente,
            )
            from db import tb_carregar_todas_vinculacoes, carregar_usinas as _usinasDB

            yyyymm  = _mes_para_yyyymm(mes_ref)          # ex: '202604'
            mes_str = mes_ref.replace("/", "")             # ex: '042026' (legado)
            clientes_all = carregar_clientes()
            vinculos = tb_carregar_todas_vinculacoes()
            usinas_map = {str(uid): (u.get("nome") or u.get("desc_nome", ""))
                          for uid, u in _usinasDB().items()}

            _job_log(jid, f"Iniciando geracao de {len(ucs)} cobranca(s) — {mes_ref}")

            for i, uc in enumerate(ucs, 1):
                c    = clientes_all.get(uc, {})
                nome = c.get("nome", uc)
                nome_camel = _camel_case(_primeiro_ultimo(nome))
                uc_nova    = c.get("cod_uc") or uc
                id_cli     = c.get("_id_cliente")
                nome_usina = ""
                if id_cli and vinculos.get(id_cli):
                    id_usina   = str(vinculos[id_cli][0].get("id_usina", ""))
                    nome_usina = usinas_map.get(id_usina, "")

                pasta_cli = os.path.join(
                    BASE_PASTA_USINAS, nome_usina,
                    _sanitizar_nome(f"{nome_camel}-{uc_nova}"),
                )

                # Busca o PDF Equatorial: novo (com sufixo UC), legado (sem sufixo) ou glob
                from utils import uc_sufixo as _uc_suf
                _suf = _uc_suf(uc)
                pdf_eq = None
                for _candidato in [
                    os.path.join(pasta_cli, f"{yyyymm}-Equatorial{nome_camel}{_suf}.pdf"),
                    os.path.join(pasta_cli, f"{yyyymm}-Equatorial{nome_camel}.pdf"),
                    os.path.join(pasta_cli, f"{mes_str}-Equatorial{nome_camel}{_suf}.pdf"),
                    os.path.join(pasta_cli, f"{mes_str}-Equatorial{nome_camel}.pdf"),
                ]:
                    if os.path.exists(_candidato):
                        pdf_eq = _candidato
                        break
                if not pdf_eq:
                    for _m in _glob.glob(os.path.join(pasta_cli, f"*Equatorial*{nome_camel}*.pdf")):
                        _base = os.path.basename(_m)
                        if _base.startswith(yyyymm) or _base.startswith(mes_str):
                            pdf_eq = _m
                            break

                _job_log(jid, f"[{i}/{len(ucs)}] {nome}…")

                # Aviso se UC sem PIX (cobranca sera gerada sem QR)
                _avp = _checar_pix_uc(uc, nome)
                if _avp:
                    _job_aviso(jid, _avp)
                    _job_log(jid, f"  ⚠ {_avp}")

                if not pdf_eq:
                    _jobs[jid]["erros"].append(f"{nome}: fatura Equatorial nao encontrada")
                    _job_log(jid, f"  ✗ Fatura Equatorial nao encontrada")
                    _jobs[jid]["done"] += 1
                    continue
                try:
                    out = gerar_cobranca_cliente(pdf_eq, pasta_cli, mes_str, nome_camel, uc)
                    if out:
                        _jobs[jid]["ok"] += 1
                        _job_log(jid, f"  ✓ Gerado: {os.path.basename(out)}")
                    else:
                        _jobs[jid]["erros"].append(nome)
                        _job_log(jid, f"  ✗ Falhou")
                except Exception as exc:
                    _jobs[jid]["erros"].append(f"{nome}: {exc}")
                    _job_log(jid, f"  ✗ Erro: {exc}")
                _jobs[jid]["done"] += 1
        except Exception as exc:
            _job_log(jid, f"Erro fatal: {exc}")
        finally:
            _job_fim(jid)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"job_id": jid})


# RESULTADO — Tela de download apos gerar
@app.route("/resultado")
def resultado():
    pdf_name = request.args.get("pdf", "")
    return render_template("resultado.html", pdf_name=pdf_name, fmt=_fmt_brl)

# GERAR EM LOTE
@app.route("/lote", methods=["GET", "POST"])
def gerar_lote():
    if request.method == "POST":
        pdfs = request.files.getlist("pdfs")
        if not pdfs or pdfs[0].filename == "":
            flash("Selecione pelo menos um PDF!", "danger"); return redirect(url_for("gerar_lote"))
        resultados = []
        for pdf in pdfs:
            pdf_path = os.path.join(UPLOAD_FOLDER, pdf.filename)
            pdf.save(pdf_path)
            ok, msg, _ = _gerar_uma_cobranca(pdf_path)
            resultados.append({"arquivo": pdf.filename, "ok": ok, "msg": msg})
        return render_template("lote_resultado.html", resultados=resultados)
    return render_template("lote.html")

# VER PDF INLINE (abre no browser em nova aba)
@app.route("/ver/<path:filename>")
def ver_pdf(filename):
    """Abre o PDF da cobranca SOLEV inline no browser (sem forcar download)."""
    fname = os.path.basename(filename)
    # 1. Filesystem primeiro (arquivo gerado localmente — mais confiavel)
    for folder in [_DIR, UPLOAD_FOLDER]:
        fpath = os.path.join(folder, fname)
        if os.path.exists(fpath):
            return send_file(fpath, mimetype="application/pdf")
    # 2. Storage (arquivo migrado para Supabase)
    try:
        item = _buscar_fatura_por_pdf(fname)
        if item and item.get("pdf_url"):
            from db import storage_signed_url
            return redirect(storage_signed_url(item["pdf_url"], expires_in=3600))
    except Exception as _e:
        print(f"[ver_pdf] Storage lookup falhou: {_e}")
    flash(f"Arquivo nao encontrado: {fname}", "danger")
    return redirect(url_for("faturas"))


@app.route("/ver-equatorial/<item_id>")
def ver_equatorial(item_id):
    """Abre a fatura Equatorial inline no browser a partir do id_fatura (int)."""
    item = _buscar_fatura_compat(item_id)
    if not item:
        flash("Registro nao encontrado.", "danger")
        return redirect(url_for("faturas"))
    # 1. Storage
    if item.get("pdf_equatorial_url"):
        try:
            from db import storage_signed_url
            return redirect(storage_signed_url(item["pdf_equatorial_url"], expires_in=3600))
        except Exception as _e:
            print(f"[ver_equatorial] Storage falhou: {_e}")
    # 2. Filesystem — procura por nome salvo
    fname = item.get("pdf_equatorial", "")
    BASE_USINAS_PATH = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", "Usinas")
    if fname:
        for root, dirs, files in os.walk(BASE_USINAS_PATH):
            if fname in files:
                return send_file(os.path.join(root, fname), mimetype="application/pdf")
    # 3. Fallback: busca PDF da Equatorial na pasta do cliente (qualquer PDF que nao seja SOLEV)
    #    Usa o nome do PDF SOLEV para localizar a pasta do cliente no OneDrive
    pdf_solev = item.get("pdf", "")
    if pdf_solev and os.path.exists(BASE_USINAS_PATH):
        for root, dirs, files in os.walk(BASE_USINAS_PATH):
            if pdf_solev in files:
                # Encontrou a pasta — pega o primeiro PDF que nao seja SOLEV nem de investidor
                pdfs_eq = [
                    f for f in files
                    if f.lower().endswith(".pdf")
                    and "solev" not in f.lower()
                    and "contrato" not in f.lower()
                ]
                if pdfs_eq:
                    return send_file(os.path.join(root, pdfs_eq[0]), mimetype="application/pdf")
    flash("Fatura Equatorial nao encontrada. Faca o download novamente pelo portal.", "warning")
    return redirect(url_for("faturas"))


# DOWNLOAD PDF
@app.route("/download/<path:filename>")
def download_pdf(filename):
    fname = os.path.basename(filename)

    # 1. Filesystem primeiro (arquivo gerado localmente — mais confiavel)
    for folder in [_DIR, UPLOAD_FOLDER]:
        fpath = os.path.join(folder, fname)
        if os.path.exists(fpath):
            return send_file(fpath, as_attachment=True,
                             download_name=fname,
                             mimetype="application/pdf")

    # 2. Storage (arquivo migrado para Supabase)
    try:
        item = _buscar_fatura_por_pdf(fname)
        if item and item.get("pdf_url"):
            from db import storage_signed_url
            signed = storage_signed_url(item["pdf_url"], expires_in=3600)
            return redirect(signed)
    except Exception as _e:
        print(f"[download_pdf] Storage lookup falhou: {_e}")

    # 3. Tenta nas pastas das usinas (OneDrive)
    BASE_USINAS = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", "Usinas")
    for root, dirs, files in os.walk(BASE_USINAS):
        if fname in files:
            return send_file(os.path.join(root, fname), as_attachment=True,
                             download_name=fname, mimetype="application/pdf")

    flash(f"Arquivo nao encontrado: {fname}", "danger")
    return redirect(url_for("faturas"))

# FATURA — Acesso curto ao PDF assinado (rota nova /luz/ + alias /fatura/)
@app.route("/luz/<code>")
@app.route("/fatura/<code>")
def fatura_redirect(code):
    """Redireciona para o link assinado do PDF (30 dias).
    Aceita short_code base62 (6 chars) ou id_fatura (int)."""
    item = _buscar_fatura_compat(code)
    if not item or not item.get("pdf_url"):
        flash("Fatura nao encontrada", "danger")
        return redirect(url_for("faturas"))
    try:
        from db import storage_signed_url
        pdf_link = storage_signed_url(item["pdf_url"], expires_in=2592000)
        return redirect(pdf_link)
    except Exception as _e:
        app.logger.warning(f"[fatura] Falha ao gerar link: {_e}")
        flash("Erro ao acessar fatura", "danger")
        return redirect(url_for("faturas"))

# SOLECONOMIA — Pagina unificada (fatura + PIX + branding)
# Tambem responde em /pix/ e /pagar/ como aliases (backward compat).
@app.route("/soleconomia/<code>")
@app.route("/pix/<code>")
@app.route("/pagar/<code>")
def pagar_pix(code):
    """Pagina unificada com fatura PDF + QR PIX + bancos.
    Aceita short_code base62 (6 chars) ou id_fatura (int)."""
    item = _buscar_fatura_compat(code)
    if not item:
        return "Cobranca nao encontrada", 404

    # UC pode estar em "uc" (legado) ou "_uc_nova" (15 digitos novo formato).
    # Tenta ambos para encontrar o cliente em tb_clientes.
    uc_legado = item.get("uc", "")
    uc_nova   = item.get("_uc_nova", "")
    nome  = item.get("nome", "Cliente")
    # valor pode vir como string do historico - converte para float
    try:
        valor = float(item.get("total_com", 0) or 0)
    except (ValueError, TypeError):
        valor = 0.0
    mes   = item.get("mes_referencia", "")

    # Busca PIX da usina - tenta UC nova primeiro, fallback UC legada
    pix_payload = ""
    pix_chave = ""
    nome_recebedor = ""
    try:
        from db import (
            tb_get_cliente_por_uc as _tc,
            tb_get_usinas_do_cliente as _tu,
            tb_get_pix_da_usina as _tp,
        )
        c_tb = None
        for uc_try in (uc_nova, uc_legado):
            if uc_try:
                c_tb = _tc(uc_try)
                if c_tb:
                    app.logger.info(f"[pagar] cliente encontrado por UC '{uc_try}': id_cliente={c_tb.get('id_cliente')}")
                    break
        if not c_tb:
            app.logger.warning(f"[pagar] cliente NAO encontrado em tb_clientes - UC nova='{uc_nova}' UC legada='{uc_legado}'")
        if c_tb and c_tb.get("id_cliente"):
            vinc = _tu(c_tb["id_cliente"])
            app.logger.info(f"[pagar] vinculacoes encontradas: {len(vinc) if vinc else 0}")
            if vinc:
                # Procura a primeira usina que tem PIX configurado
                rec = None
                for v in vinc:
                    r = _tp(v.get("id_usina"))
                    if r and r.get("desc_pix"):
                        rec = r
                        app.logger.info(f"[pagar] PIX encontrado em usina id={v.get('id_usina')}")
                        break
                if rec:
                    pix_chave = rec.get("desc_pix", "")
                    nome_recebedor = rec.get("desc_nome_pix") or rec.get("desc_nome", "")
                    pix_payload = _build_pix_payload(
                        valor,
                        chave_pix=pix_chave,
                        nome_pix=nome_recebedor,
                        cidade_pix=rec.get("desc_cidade_pix"),
                    )
                else:
                    app.logger.warning(f"[pagar] nenhuma das {len(vinc)} usinas vinculadas tem desc_pix configurado")
    except Exception as _e:
        app.logger.warning(f"[pagar] Falha ao gerar PIX: {_e}")

    # Gera QR code como data URI base64 (para embedar no HTML)
    qr_base64 = ""
    if pix_payload:
        try:
            import qrcode, io, base64
            qr_obj = qrcode.QRCode(
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=10, border=2,
            )
            qr_obj.add_data(pix_payload)
            qr_obj.make(fit=True)
            img = qr_obj.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            qr_base64 = f"data:image/png;base64,{b64}"
        except Exception as _e:
            app.logger.warning(f"[pagar] Falha ao gerar QR: {_e}")

    return render_template("soleconomia.html",
        code=code,
        nome=nome,
        mes=mes,
        valor=valor,
        valor_fmt=_fmt_brl(valor),
        vencimento=item.get("vencimento", ""),
        tem_pdf=bool(item.get("pdf_url") or item.get("pdf")),
        pix_payload=pix_payload,
        pix_chave=pix_chave,
        nome_recebedor=nome_recebedor,
        qr_base64=qr_base64)

# ENVIAR POR WHATSAPP
@app.route("/whatsapp/<path:filename>")
def enviar_whatsapp(filename):
    """Abre WhatsApp pre-preenchido para o cliente: contato + valor +
    link curto do PDF + link curto do PIX."""
    fname = os.path.basename(filename)
    # Prioriza busca pelo id_fatura (evita conflito quando dois clientes tem o mesmo nome)
    item_id = request.args.get("id", "").strip()
    item = None
    if item_id:
        item = _buscar_fatura_compat(item_id)
    if not item:
        item = _buscar_fatura_por_pdf(fname)
    if not item:
        # Fallback: mensagem generica de simulacao
        msg = "Ola! Segue sua simulacao SOLEV."
        return redirect(f"https://wa.me/?text={urllib.parse.quote(msg)}")

    nome  = item.get("nome", "Cliente")
    mes   = item.get("mes_referencia", "")
    valor = item.get("total_com", 0) or 0
    venc  = item.get("vencimento", "")
    uc    = item.get("uc", "")
    item_id = item.get("id", "")

    # 1. Telefone do cliente — busca em tb_clientes
    telefone_digits = ""
    try:
        from db import tb_get_cliente_por_uc
        c_tb = tb_get_cliente_por_uc(uc)
        if c_tb:
            tel_raw = (c_tb.get("desc_telefone") or "").strip()
            telefone_digits = "".join(filter(str.isdigit, tel_raw))
            if telefone_digits and not telefone_digits.startswith("55"):
                telefone_digits = "55" + telefone_digits
    except Exception as _e:
        app.logger.warning(f"[whatsapp] Falha ao buscar telefone: {_e}")

    # 2. Verifica se tem PIX para mostrar link de pagamento
    tem_pix = False
    try:
        from db import (
            tb_get_cliente_por_uc as _tc,
            tb_get_usinas_do_cliente as _tu,
            tb_get_pix_da_usina as _tp,
        )
        c_tb = _tc(uc)
        if c_tb and c_tb.get("id_cliente"):
            vinc = _tu(c_tb["id_cliente"])
            if vinc:
                rec = _tp(vinc[0]["id_usina"])
                tem_pix = bool(rec and rec.get("desc_pix"))
    except Exception as _e:
        app.logger.warning(f"[whatsapp] Falha ao verificar PIX: {_e}")

    # 3. Monta mensagem
    BULLET  = "\u25b8"       # \u25b8

    nome_curto = nome.split()[0] if nome else "Cliente"

    # Link do portal do cliente (rota /c/<token>). Se nao tiver token, omite.
    token = item.get("token_acesso") or ""
    link_portal = url_for("portal_cliente", token=token, _external=True) if token else ""

    # Acentos em \u escape para evitar problemas de encoding cp1252 no Windows
    linhas = [
        f"Ol\u00e1! *{nome_curto}*",
        "",
        "Sua fatura da SOLEV ENERGIA j\u00e1 est\u00e1 dispon\u00edvel.",
        "",
        f"{BULLET} Valor: *{_fmt_brl(valor)}*",
    ]
    if venc:
        linhas.append(f"{BULLET} Vencimento: {venc}")

    if link_portal:
        linhas.append("")
        linhas.append("Acesse o link abaixo para visualizar o detalhamento, "
                      "baixar o PDF e copiar o PIX:")
        linhas.append("")
        linhas.append(link_portal)

    linhas.append("")
    linhas.append("Qualquer d\u00favida, \u00e9 s\u00f3 responder esta mensagem.")
    linhas.append("SOLEV ENERGIA")

    msg = "\n".join(linhas)

    # 4. URL wa.me - quote com encoding UTF-8 explicito para garantir emojis
    msg_quoted = urllib.parse.quote(msg, safe="", encoding="utf-8")
    if telefone_digits:
        url = f"https://wa.me/{telefone_digits}?text={msg_quoted}"
    else:
        url = f"https://wa.me/?text={msg_quoted}"
    return redirect(url)


# ENVIAR CHAVE PIX POR WHATSAPP (mensagem separada — facil de copiar, nao expira)
@app.route("/whatsapp-pix/<int:id_fatura>")
def enviar_whatsapp_pix(id_fatura):
    """Abre WhatsApp pre-preenchido apenas com a chave PIX (UUID).

    Por que so a chave (e nao BRCode com valor):
    - A chave PIX nao expira (so deixa de funcionar se o titular deletar)
    - Alguns bancos tem timeout interno no BRCode, gerando reclamacao apos dias
    - Cliente cola na opcao "Chave Aleatoria" do banco e digita o valor
    """
    item = _buscar_fatura_compat(id_fatura)
    if not item:
        flash("Fatura nao encontrada.", "danger")
        return redirect(url_for("faturas"))

    uc = item.get("uc", "") or item.get("_cod_uc", "")

    # Telefone do cliente
    telefone_digits = ""
    try:
        from db import tb_get_cliente_por_uc
        c_tb = tb_get_cliente_por_uc(uc)
        if c_tb:
            tel_raw = (c_tb.get("desc_telefone") or "").strip()
            telefone_digits = "".join(filter(str.isdigit, tel_raw))
            if telefone_digits and not telefone_digits.startswith("55"):
                telefone_digits = "55" + telefone_digits
    except Exception as _e:
        app.logger.warning(f"[whatsapp-pix] Falha ao buscar telefone: {_e}")

    # Buscar chave PIX dinamicamente do banco por usina
    pix_chave = "f6189239-d8ae-4edb-9d62-99299de54fc3"  # fallback padrão
    try:
        from db import tb_get_pix_da_usina
        id_cliente = item.get("id_cliente")
        if id_cliente:
            # Buscar primeira usina ativa do cliente
            from db import _db as _get_db
            vinc_rows = _get_db().select(
                "tb_cliente_usina",
                columns="id_usina",
                filtros={"id_cliente": id_cliente},
                raw_params={"dt_fim": "is.null"},
                limit=1
            )
            if vinc_rows:
                id_usina = vinc_rows[0].get("id_usina")
                pix_data = tb_get_pix_da_usina(id_usina)
                if pix_data and pix_data.get("desc_pix"):
                    pix_chave = pix_data["desc_pix"]
                    app.logger.info(f"[whatsapp-pix] Usina {id_usina} PIX: {pix_chave[:4]}...")
    except Exception as _e:
        app.logger.warning(f"[whatsapp-pix] Falha ao buscar PIX da usina: {_e}")

    # Mensagem com APENAS a chave PIX — long-press > Copy copia exatamente isto
    msg_quoted = urllib.parse.quote(pix_chave, safe="", encoding="utf-8")
    if telefone_digits:
        url = f"https://wa.me/{telefone_digits}?text={msg_quoted}"
    else:
        url = f"https://wa.me/?text={msg_quoted}"
    return redirect(url)


# PAGAMENTO
@app.route("/pagamento", methods=["GET", "POST"])
def pagamento():
    """Lista faturas pendentes (de tb_faturas) e registra pagamento.

    Fonte primaria: tb_faturas (estrutura nova normalizada).
    Mirror nas tabelas legadas (historico, clientes.json) ate a etapa 7."""
    from db import (tb_get_faturas_pendentes_ordenadas, tb_marcar_fatura_pago,
                    _resolver_id_cliente_por_uc, _db as _get_db,
                    tb_get_cliente_por_uc)

    if request.method == "POST":
        uc          = request.form["uc"].strip()
        data_pgto   = request.form["data_pagamento"].strip()  # dd/mm/aaaa

        try:
            dt_pgto_obj = datetime.strptime(data_pgto, "%d/%m/%Y")
            data_pgto_iso = dt_pgto_obj.strftime("%Y-%m-%d")
        except ValueError:
            flash("Data invalida! Use dd/mm/aaaa", "danger")
            return redirect(url_for("pagamento"))

        nome_cli = uc
        venc_iso = None
        valor    = 0.0
        fatura_id = None

        id_cliente = _resolver_id_cliente_por_uc(uc)
        if id_cliente:
            cli = tb_get_cliente_por_uc(uc)
            if cli:
                nome_cli = cli.get("desc_nome") or uc

            rows = _get_db().select(
                "tb_faturas",
                filtros={"id_cliente": id_cliente, "status": "pendente"},
                order="dt_venc_solev.asc.nullslast",
            )
            if rows:
                fatura    = rows[0]
                fatura_id = fatura.get("id_fatura")
                valor     = float(fatura.get("vlr_total_com") or 0)
                venc_iso  = fatura.get("dt_venc_solev")

        multa_proxima = 0.0; juros_proxima = 0.0; dias_atraso = 0
        if venc_iso and valor > 0:
            try:
                dt_venc = datetime.strptime(venc_iso, "%Y-%m-%d")
                dias_atraso = (dt_pgto_obj - dt_venc).days
                if dias_atraso > 0:
                    multa_proxima = round(valor * 0.02, 2)
                    juros_proxima = round(valor * 0.001627 * dias_atraso, 2)
            except ValueError:
                pass

        if fatura_id:
            try:
                tb_marcar_fatura_pago(
                    fatura_id, data_pgto_iso,
                    vlr_pago=round(valor, 2),
                    vlr_multa_proxima=multa_proxima,
                    vlr_juros_proxima=juros_proxima,
                )
            except Exception as e:
                app.logger.warning(f"[pagamento] falha tb_faturas: {e}")

        # Mirror legacy clientes.json (necessario para geracao de PDF
        # ainda usar data_pagamento_anterior). A tabela historico NAO
        # eh mais espelhada desde 7B.2.
        clientes = carregar_clientes()
        chave_real, _cli = _buscar_cliente_por_uc(uc, clientes)
        if chave_real:
            clientes[chave_real]["data_pagamento_anterior"] = data_pgto
            salvar_clientes(clientes)
            if not nome_cli or nome_cli == uc:
                nome_cli = clientes[chave_real].get("nome", uc)

        msg = f"Pagamento registrado para {nome_cli}!"
        if multa_proxima > 0 or juros_proxima > 0:
            total_proxima = round(multa_proxima + juros_proxima, 2)
            msg += (f" Atraso de {dias_atraso} dia(s). "
                    f"Multa {_fmt_brl(multa_proxima)} + Juros {_fmt_brl(juros_proxima)} "
                    f"= {_fmt_brl(total_proxima)} serao cobrados na proxima fatura.")
        elif venc_iso:
            msg += " Pagamento em dia!"
        flash(msg, "success")
        return redirect(url_for("faturas"))

    faturas_pendentes = tb_get_faturas_pendentes_ordenadas()
    for f in faturas_pendentes:
        if f.get("dt_venc_solev"):
            try:
                f["_venc_br"] = datetime.strptime(
                    f["dt_venc_solev"], "%Y-%m-%d").strftime("%d/%m/%Y")
            except ValueError:
                f["_venc_br"] = f["dt_venc_solev"]
        else:
            f["_venc_br"] = ""
        f["_cod_uc_fmt"] = _fmt_uc15(f.get("_cod_uc") or "")

    clientes = carregar_clientes()
    return render_template("pagamento.html",
                           clientes=clientes,
                           faturas_pendentes=faturas_pendentes,
                           fmt=_fmt_brl)

# FATURAS  (le de tb_faturas)
@app.route("/historico")
def historico_redirect():
    """Compatibilidade: /historico era a URL antiga. Redireciona para /faturas
    preservando query string (busca, mes, status, page, per_page)."""
    qs = request.query_string.decode("utf-8")
    target = url_for("faturas") + (("?" + qs) if qs else "")
    return redirect(target, code=301)


@app.route("/faturas")
def faturas():
    from db import tb_get_faturas_paginado, tb_mapa_uc_para_usina

    page = max(1, int(request.args.get("page", 1)))
    try:
        per_page = int(request.args.get("per_page", 20))
        if per_page not in [20, 50, 100]:
            per_page = 20
    except (ValueError, TypeError):
        per_page = 20
    busca  = request.args.get("q", "").strip()
    mes_br = request.args.get("mes", "").strip()
    status = request.args.get("status", "todos").strip()

    status_map = {"nao_pago": "pendente", "vencidos": "vencido"}
    status_db  = status_map.get(status, status)
    if status_db not in ("todos", "pendente", "pago", "cancelado", "vencido"):
        status_db = "todos"

    ano_filtro = None; mes_filtro = None
    if mes_br:
        import re as _re_mes
        m = _re_mes.match(r"^(\d{1,2})/(\d{4})$", mes_br)
        if m:
            mes_filtro = int(m.group(1))
            ano_filtro = int(m.group(2))

    rows, total = tb_get_faturas_paginado(
        page=page, per_page=per_page, busca=busca,
        ano=ano_filtro, mes=mes_filtro, status=status_db,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)

    try:
        mapa_usina = tb_mapa_uc_para_usina()
    except Exception:
        mapa_usina = {}

    for r in rows:
        if r.get("status") == "pago":
            r["_status_classe"] = "pago"
        elif r.get("_vencido"):
            r["_status_classe"] = "vencido"
        elif r.get("status") == "cancelado":
            r["_status_classe"] = "cancelado"
        else:
            r["_status_classe"] = "aguardando"

        for chave_iso, chave_br in (("dt_geracao", "_data_br"),
                                    ("dt_venc_solev", "_venc_br"),
                                    ("dt_venc_equatorial", "_venc_eq_br"),
                                    ("dt_pagamento", "_pgto_br")):
            v = r.get(chave_iso)
            if v:
                try:
                    if "T" in str(v) or " " in str(v):
                        dt = datetime.fromisoformat(str(v).replace("Z", "").split("+")[0][:19])
                    else:
                        dt = datetime.fromisoformat(str(v))
                    r[chave_br] = dt.strftime("%d/%m/%Y %H:%M") \
                        if chave_iso == "dt_geracao" else dt.strftime("%d/%m/%Y")
                except (ValueError, TypeError):
                    r[chave_br] = str(v)
            else:
                r[chave_br] = ""

        r["_usina"] = mapa_usina.get(str(r.get("_cod_uc") or ""), "") or \
                      mapa_usina.get(str(r.get("_cod_uc") or ""), "")
        r["_pdf_legado"] = r.get("pdf_solev") or ""

    # ── Detecta faturas consolidáveis (modelo FIXO) ──
    try:
        from consolidar_fixo import detectar_consolidaveis as _det_cons
        for r in rows:
            id_c = r.get("id_cliente")
            mes_r = r.get("mes_referencia")
            ano_r = r.get("ano_referencia")
            if id_c and mes_r and ano_r:
                irmaos = _det_cons(id_c, int(ano_r), int(mes_r))
                if irmaos and len(irmaos) >= 2:
                    r["_pode_consolidar"] = True
                    r["_consolidar_count"] = len(irmaos)
                else:
                    r["_pode_consolidar"] = False
            else:
                r["_pode_consolidar"] = False
    except Exception as _e:
        app.logger.warning(f"[faturas] detecção FIXO falhou: {_e}")
        for r in rows:
            r["_pode_consolidar"] = False

    return render_template("faturas.html",
        faturas=rows, total=total,
        page=page, total_pages=total_pages,
        per_page=per_page, busca=busca, mes=mes_br, status=status,
        fmt=_fmt_brl)


# ============================================================
#  Cobrança consolidada FIXO
# ============================================================
@app.route("/fatura/consolidar-fixo/<int:id_fatura>", methods=["POST"])
def fatura_consolidar_fixo(id_fatura):
    """Gera o PDF consolidado FIXO para a fatura dada (e suas irmãs)."""
    from db import _db as _get_db
    from consolidar_fixo import detectar_consolidaveis, gerar_pdf

    db = _get_db()
    fats = db.select("tb_faturas", filtros={"id_fatura": id_fatura})
    if not fats:
        flash("Fatura não encontrada.", "danger")
        return redirect(url_for("faturas"))
    f = fats[0]
    id_c = f.get("id_cliente")
    ano  = int(f.get("ano_referencia") or 0)
    mes  = int(f.get("mes_referencia") or 0)

    irmaos = detectar_consolidaveis(id_c, ano, mes)
    if not irmaos:
        flash("Esta fatura não tem irmãos FIXO consolidáveis no mesmo mês.", "warning")
        return redirect(url_for("faturas"))

    try:
        result = gerar_pdf(irmaos, ano, mes)
        flash(
            f"Cobrança consolidada gerada: {len(irmaos)} UCs · "
            f"Total {_fmt_brl(result['total_com'])} · Economia {_fmt_brl(result['total_sem'] - result['total_com'])}",
            "success"
        )
    except Exception as e:
        app.logger.exception(f"[consolidar] {e}")
        flash(f"Erro ao gerar consolidada: {e}", "danger")

    return redirect(url_for("faturas"))


# ============================================================
#  Endpoints novos para acoes em fatura individual (tb_faturas)
# ============================================================
@app.route("/fatura/baixa/<int:id_fatura>", methods=["POST"])
def fatura_baixa(id_fatura):
    """Da baixa em uma fatura de tb_faturas + mirror em historico legado."""
    from db import (tb_get_fatura_por_id, tb_marcar_fatura_pago,
                    _db as _get_db)

    fatura = tb_get_fatura_por_id(id_fatura)
    if not fatura:
        flash("Fatura nao encontrada!", "danger")
        return redirect(url_for("faturas"))

    data_pgto_br = request.form.get("data_pagamento", "").strip()
    if not data_pgto_br:
        data_pgto_br = datetime.now().strftime("%d/%m/%Y")

    try:
        dt_pgto_obj = datetime.strptime(data_pgto_br, "%d/%m/%Y")
    except ValueError:
        flash("Data invalida! Use dd/mm/aaaa", "danger")
        return redirect(url_for("faturas"))

    valor    = float(fatura.get("vlr_total_com") or 0)
    venc_iso = fatura.get("dt_venc_solev")
    multa_proxima = juros_proxima = 0.0; dias = 0
    if venc_iso and valor > 0:
        try:
            dt_venc = datetime.strptime(str(venc_iso), "%Y-%m-%d")
            dias = (dt_pgto_obj - dt_venc).days
            if dias > 0:
                multa_proxima = round(valor * 0.02, 2)
                juros_proxima = round(valor * 0.001627 * dias, 2)
        except ValueError:
            pass

    tb_marcar_fatura_pago(
        id_fatura, dt_pgto_obj.strftime("%Y-%m-%d"),
        vlr_pago=round(valor, 2),
        vlr_multa_proxima=multa_proxima,
        vlr_juros_proxima=juros_proxima,
    )

    # Mirror legacy clientes.json (para PDF que ainda usa
    # data_pagamento_anterior). Tabela historico nao mais espelhada.
    uc = fatura.get("_cod_uc") or ""
    if uc:
        try:
            clientes = carregar_clientes()
            chave_real, _cli = _buscar_cliente_por_uc(uc, clientes)
            if chave_real:
                clientes[chave_real]["data_pagamento_anterior"] = data_pgto_br
                salvar_clientes(clientes)
        except Exception as e:
            app.logger.warning(f"[fatura_baixa] mirror clientes.json falhou: {e}")

    nome = fatura.get("_nome") or uc
    msg = f"Baixa registrada — {nome}!"
    if multa_proxima > 0 or juros_proxima > 0:
        total_proxima = round(multa_proxima + juros_proxima, 2)
        msg += (f" Atraso de {dias} dia(s). Multa {_fmt_brl(multa_proxima)} + "
                f"Juros {_fmt_brl(juros_proxima)} = {_fmt_brl(total_proxima)} "
                f"serao cobrados na proxima fatura.")
    elif venc_iso:
        msg += " Pagamento em dia!"
    flash(msg, "success")
    return redirect(url_for("faturas"))


@app.route("/fatura/excluir/<int:id_fatura>")
def fatura_excluir(id_fatura):
    """Exclui fatura de tb_faturas + mirror em historico + reverte cliente."""
    from db import (tb_get_fatura_por_id, tb_delete_fatura,
                    _db as _get_db, tb_get_cliente_por_uc)

    fatura = tb_get_fatura_por_id(id_fatura)
    if not fatura:
        flash("Fatura nao encontrada!", "danger")
        return redirect(url_for("faturas"))

    nome     = fatura.get("_nome") or ""
    mes_ref  = f"{int(fatura.get('mes_referencia') or 0):02d}/{int(fatura.get('ano_referencia') or 0)}"
    uc       = fatura.get("_cod_uc") or ""
    eco_mes  = float(fatura.get("vlr_economia_mes") or 0)

    pdf = fatura.get("pdf_solev") or ""
    if pdf:
        pdf_path = os.path.join(_DIR, pdf)
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except OSError:
                pass

    # Guarda dt_leitura_atual da fatura antes de deletar (para restaurar proxima_leitura)
    dt_leitura_fatura = fatura.get("dt_leitura_atual") or ""

    try:
        c_tb = tb_get_cliente_por_uc(uc)
        if c_tb:
            eco_tb = c_tb.get("qtd_economia_acumulada", 0) or 0
            patch_data = {
                "qtd_economia_acumulada": round(max(0, eco_tb - eco_mes), 2),
                "vlr_cobranca_anterior":  0,
                "dt_venc_anterior":       None,   # None, NUNCA "" (coluna date rejeita string vazia)
                "dt_ultimo_pagamento":    None,
            }
            # Restaura proxima_leitura para a data de leitura da fatura excluída,
            # para que o cliente reapareça em Cobranças do Dia com o intervalo correto
            if dt_leitura_fatura:
                patch_data["proxima_leitura"] = dt_leitura_fatura
            _get_db().patch("tb_clientes", {"id_cliente": c_tb["id_cliente"]}, patch_data)
    except Exception as e:
        app.logger.warning(f"[fatura_excluir] reverter cliente falhou: {e}")

    tb_delete_fatura(id_fatura)

    flash(f"Cobranca de {nome} ({mes_ref}) excluida.", "warning")

    next_url = request.args.get("next", "").strip()
    if next_url:
        from urllib.parse import unquote
        return redirect(unquote(next_url))

    # Se veio de Cobranças do Dia e há data de leitura, redireciona com intervalo ampliado
    if dt_leitura_fatura:
        try:
            from datetime import date as _date, timedelta as _td
            _leit = _date.fromisoformat(dt_leitura_fatura[:10])
            _de  = (_leit - _td(days=2)).strftime("%d/%m/%Y")
            _ate = (_leit + _td(days=5)).strftime("%d/%m/%Y")
            return redirect(url_for("cobrancas_dia", de=_de, ate=_ate))
        except Exception:
            pass

    return redirect(url_for("faturas"))


# RELATORIO MENSAL  (le de tb_faturas)
# ══════════════════════════════════════════════════════════════
#  RELATÓRIOS — índice (extensível para novos relatórios)
# ══════════════════════════════════════════════════════════════
@app.route("/relatorios")
def relatorios_index():
    """Página índice listando todos os relatórios disponíveis."""
    return render_template("relatorios_index.html")


@app.route("/relatorios/comercializacao")
def relatorio_comercializacao():
    """Resumo de comercialização: geração total, vendido e disponível.

    Quebras:
      - Modo A (Consumo Médio): vendido = SUM(cliente.consumo_medio × pct_rateio)
      - Modo B (Capacidade Reservada): reservado = SUM(usina.geracao × pct_rateio)
      - Categoria FIXO vs Normal (FIXO = vínculo com desc_saldo_obs='FIXO')

    Query params:
      ?considerar_saldo=1  → desconta saldo do consumo médio no Modo A
                            (cliente "coberto pelo saldo" ocupa 0 kWh)
    """
    from db import _db
    db = _db()

    considerar_saldo = request.args.get("considerar_saldo") in ("1", "true", "on")

    # 1. Carrega usinas e clientes
    usinas   = db.select("tb_usinas")
    clientes = db.select("tb_clientes")
    vincs    = db.select("tb_cliente_usina", raw_params={"dt_fim": "is.null"})

    # Indexa
    usinas_by_id   = {u["id_usina"]: u for u in usinas}
    clientes_by_id = {c["id_cliente"]: c for c in clientes}

    # Saldo efetivo por cliente: prioriza vínculo ativo; fallback saldo_inicial do cadastro
    saldo_por_cliente = {}
    for v in vincs:
        id_c = v.get("id_cliente")
        s = float(v.get("qtd_saldo_kwh") or 0)
        if id_c and s > 0:
            saldo_por_cliente[id_c] = saldo_por_cliente.get(id_c, 0) + s
    for c in clientes:
        id_c = c["id_cliente"]
        if id_c not in saldo_por_cliente:
            saldo_por_cliente[id_c] = float(c.get("qtd_saldo_inicial_kwh") or 0)

    # 2. Geração total (estimada) e por usina
    ger_total = 0.0
    ger_por_usina = {}
    for u in usinas:
        g = float(u.get("qtd_geracao_media_mensal") or 0)
        ger_por_usina[u["id_usina"]] = g
        ger_total += g

    # 3. Processa vínculos: separa FIXO de normal, acumula por usina
    #    Para cada vínculo: contribui com (pct × geração) — capacidade reservada
    #                       e (consumo_medio × pct/100) — consumo médio esperado
    cap_fixo_por_usina   = {}  # capacidade reservada FIXO por usina
    cap_normal_por_usina = {}  # capacidade reservada normal por usina
    cons_fixo_por_usina   = {}  # consumo médio esperado FIXO por usina
    cons_normal_por_usina = {}  # consumo médio esperado normal por usina
    n_clientes_fixo = 0
    n_clientes_normal = 0
    ids_fixos_set = set()
    ids_normal_set = set()

    for v in vincs:
        id_u = v.get("id_usina")
        id_c = v.get("id_cliente")
        if not id_u or not id_c:
            continue
        pct = float(v.get("pct_rateio") or 0) / 100.0
        if pct <= 0:
            continue
        is_fixo = (v.get("desc_saldo_obs") or "").upper() == "FIXO"
        ger_u = ger_por_usina.get(id_u, 0)
        cli   = clientes_by_id.get(id_c, {})
        consumo_med = float(cli.get("qtd_consumo_medio_kwh") or 0)

        cap_alocada  = pct * ger_u
        # Modo A — consumo médio (com ou sem saldo):
        # Saldo é POR CLIENTE (não por vínculo); então ratiamos pelo pct também.
        if considerar_saldo:
            saldo_cli = saldo_por_cliente.get(id_c, 0)
            consumo_liq = max(0, consumo_med - saldo_cli)
            cons_alocado = pct * consumo_liq
        else:
            cons_alocado = pct * consumo_med

        alvo_cap  = cap_fixo_por_usina  if is_fixo else cap_normal_por_usina
        alvo_cons = cons_fixo_por_usina if is_fixo else cons_normal_por_usina
        alvo_cap[id_u]  = alvo_cap.get(id_u, 0)  + cap_alocada
        alvo_cons[id_u] = alvo_cons.get(id_u, 0) + cons_alocado

        if is_fixo:
            ids_fixos_set.add(id_c)
        else:
            ids_normal_set.add(id_c)

    n_clientes_fixo   = len(ids_fixos_set)
    n_clientes_normal = len(ids_normal_set)

    # 4. Agrega totais
    cap_fixo_total    = sum(cap_fixo_por_usina.values())
    cap_normal_total  = sum(cap_normal_por_usina.values())
    cap_vendida_total = cap_fixo_total + cap_normal_total
    cap_disponivel    = max(0, ger_total - cap_vendida_total)

    cons_fixo_total    = sum(cons_fixo_por_usina.values())
    cons_normal_total  = sum(cons_normal_por_usina.values())
    cons_esperado_total = cons_fixo_total + cons_normal_total
    cons_disponivel    = max(0, ger_total - cons_esperado_total)

    pct_cap_uso   = (cap_vendida_total  / ger_total * 100) if ger_total > 0 else 0
    pct_cons_uso  = (cons_esperado_total / ger_total * 100) if ger_total > 0 else 0

    # 5. Breakdown POR CLIENTE — TODOS os clientes ativos cadastrados:
    #    - Clientes com vínculo: 1 linha por vínculo ativo
    #    - Clientes sem vínculo: 1 linha marcada como "sem usina" (capacidade=0)
    # Mapeia vínculos ativos por id_cliente
    vincs_por_cliente = {}
    for v in vincs:
        id_vc = v.get("id_cliente")
        if id_vc:
            vincs_por_cliente.setdefault(id_vc, []).append(v)

    n_sem_vinculo = 0
    clientes_breakdown = []
    for cli in clientes:
        # Pula inativos
        if str(cli.get("STATUS") or "").upper() == "INATIVO" or cli.get("STATUS") is False:
            continue
        id_c = cli["id_cliente"]
        consumo_med = float(cli.get("qtd_consumo_medio_kwh") or 0)
        saldo_cli   = saldo_por_cliente.get(id_c, 0)
        cli_vincs   = vincs_por_cliente.get(id_c, [])

        if not cli_vincs:
            # Sem vínculo — consumo total fica como "demanda não alocada"
            cons_bruto = consumo_med
            cons_liq   = max(0, consumo_med - saldo_cli)
            gap_capac  = 0 - (cons_liq if considerar_saldo else cons_bruto)
            clientes_breakdown.append({
                "id_cliente":  id_c,
                "id_usina":    None,
                "nome":        cli.get("desc_nome", "?"),
                "cod_uc":      cli.get("cod_uc", ""),
                "nome_usina":  "",
                "pct":         0,
                "consumo_med": consumo_med,
                "saldo":       saldo_cli,
                "cons_bruto":  cons_bruto,
                "cons_liq":    cons_liq,
                "cap_alocada": 0,
                "gap":         gap_capac,
                "is_fixo":     False,
                "sem_vinculo": True,
            })
            n_sem_vinculo += 1
        else:
            # Tem vínculo(s) — 1 linha por vínculo ativo
            for v in cli_vincs:
                id_u = v.get("id_usina")
                pct  = float(v.get("pct_rateio") or 0)
                if pct <= 0 or not id_u:
                    continue
                is_fixo = (v.get("desc_saldo_obs") or "").upper() == "FIXO"
                usina = usinas_by_id.get(id_u, {})
                ger_u = float(usina.get("qtd_geracao_media_mensal") or 0)
                cap_alocada = (pct / 100.0) * ger_u
                cons_bruto  = (pct / 100.0) * consumo_med
                cons_liq    = (pct / 100.0) * max(0, consumo_med - saldo_cli)
                gap_capac   = cap_alocada - (cons_liq if considerar_saldo else cons_bruto)
                clientes_breakdown.append({
                    "id_cliente":  id_c,
                    "id_usina":    id_u,
                    "nome":        cli.get("desc_nome", "?"),
                    "cod_uc":      cli.get("cod_uc", ""),
                    "nome_usina":  usina.get("desc_nome", ""),
                    "pct":         pct,
                    "consumo_med": consumo_med,
                    "saldo":       saldo_cli,
                    "cons_bruto":  cons_bruto,
                    "cons_liq":    cons_liq,
                    "cap_alocada": cap_alocada,
                    "gap":         gap_capac,
                    "is_fixo":     is_fixo,
                    "sem_vinculo": False,
                })
    # Ordena: sem-vínculo primeiro (mais urgente), depois FIXO, depois maiores consumos
    clientes_breakdown.sort(key=lambda x: (
        not x.get("sem_vinculo", False),
        not x.get("is_fixo", False),
        -x["cons_bruto"]
    ))

    # 6. Breakdown por usina (mantido)
    usinas_breakdown = []
    for u in usinas:
        id_u = u["id_usina"]
        g    = ger_por_usina.get(id_u, 0)
        if g <= 0:
            continue
        cf = cap_fixo_por_usina.get(id_u, 0)
        cn = cap_normal_por_usina.get(id_u, 0)
        usinas_breakdown.append({
            "id_usina":   id_u,
            "nome":       u.get("desc_nome", ""),
            "geracao":    g,
            "fixo":       cf,
            "normal":     cn,
            "vendido":    cf + cn,
            "disponivel": max(0, g - cf - cn),
            "pct":        ((cf + cn) / g * 100) if g > 0 else 0,
        })
    usinas_breakdown.sort(key=lambda x: -x["geracao"])

    return render_template("relatorio_comercializacao.html",
        considerar_saldo=considerar_saldo,
        ger_total=ger_total,
        n_usinas=len(usinas),
        # Modo A — Consumo Médio
        cons_esperado_total=cons_esperado_total,
        cons_disponivel=cons_disponivel,
        pct_cons_uso=pct_cons_uso,
        cons_fixo_total=cons_fixo_total,
        cons_normal_total=cons_normal_total,
        # Modo B — Capacidade Reservada
        cap_vendida_total=cap_vendida_total,
        cap_disponivel=cap_disponivel,
        pct_cap_uso=pct_cap_uso,
        cap_fixo_total=cap_fixo_total,
        cap_normal_total=cap_normal_total,
        # Contagens
        n_clientes_fixo=n_clientes_fixo,
        n_clientes_normal=n_clientes_normal,
        # Breakdown
        usinas_breakdown=usinas_breakdown,
        clientes_breakdown=clientes_breakdown,
        n_sem_vinculo=n_sem_vinculo,
    )


@app.route("/relatorio")
def relatorio():
    from db import tb_get_faturas_paginado, tb_carregar_clientes

    rows, total = tb_get_faturas_paginado(page=1, per_page=999999, status="todos")

    for r in rows:
        v = r.get("dt_pagamento")
        if v:
            try:
                r["_pgto_br"] = datetime.fromisoformat(str(v)).strftime("%d/%m/%Y")
            except (ValueError, TypeError):
                r["_pgto_br"] = str(v)
        else:
            r["_pgto_br"] = ""

    meses = {}
    for r in rows:
        ano = int(r.get("ano_referencia") or 0)
        mes = int(r.get("mes_referencia") or 0)
        key = f"{mes:02d}/{ano}" if ano and mes else "N/A"
        if key not in meses:
            meses[key] = {
                "registros": [],
                "total_sem": 0.0, "total_com": 0.0,
                "economia":  0.0, "compensacao_dic": 0.0,
                "qtd_total": 0, "qtd_pago": 0, "qtd_pendente": 0, "qtd_cancelado": 0,
                "vlr_pago": 0.0, "vlr_multa_juros": 0.0,
            }
        bucket = meses[key]
        bucket["registros"].append(r)
        bucket["total_sem"]       += float(r.get("vlr_total_sem") or 0)
        bucket["total_com"]       += float(r.get("vlr_total_com") or 0)
        bucket["economia"]        += float(r.get("vlr_economia_mes") or 0)
        bucket["compensacao_dic"] += float(r.get("vlr_compensacao_dic") or 0)
        bucket["qtd_total"]       += 1
        st = r.get("status") or "pendente"
        if st == "pago":
            bucket["qtd_pago"] += 1
            bucket["vlr_pago"] += float(r.get("vlr_pago") or r.get("vlr_total_com") or 0)
            bucket["vlr_multa_juros"] += float(r.get("vlr_multa") or 0) + float(r.get("vlr_juros") or 0)
        elif st == "cancelado":
            bucket["qtd_cancelado"] += 1
        else:
            bucket["qtd_pendente"] += 1

    total_clientes = len(tb_carregar_clientes())
    return render_template("relatorio.html",
                           meses=meses,
                           total_clientes=total_clientes,
                           fmt=_fmt_brl)


# ══════════════════════════════════════════════════════════════
# USINAS

# USINAS - Listar
@app.route("/usinas")
def usinas_lista():
    from db import tb_carregar_usinas, tb_carregar_todas_vinculacoes, tb_carregar_enderecos_usinas, tb_carregar_investidores
    usinas    = tb_carregar_usinas()
    vinculos  = tb_carregar_todas_vinculacoes()
    enderecos = tb_carregar_enderecos_usinas()
    investidores = tb_carregar_investidores()
    # Conta clientes vinculados a cada usina e enriquece com endereco
    contagem = {}
    for id_c, vlist in vinculos.items():
        for v in vlist:
            id_u = v["id_usina"]
            contagem[id_u] = contagem.get(id_u, 0) + 1
    # Conta usinas por investidor
    usinas_por_inv = {}
    for u in usinas:
        iid = u.get("id_investidor")
        if iid:
            usinas_por_inv[iid] = usinas_por_inv.get(iid, 0) + 1
    for u in usinas:
        u["_clientes_count"] = contagem.get(u["id_usina"], 0)
        end = enderecos.get(u["id_usina"], {})
        u["_cidade_uf"] = ", ".join(filter(None, [
            end.get("desc_cidade", ""),
            end.get("desc_estado", ""),
        ]))
    for inv in investidores:
        inv["_usinas_count"] = usinas_por_inv.get(inv["id_investidor"], 0)
    tab = request.args.get("tab", "usinas")
    return render_template("usinas.html", usinas=usinas, investidores=investidores, tab=tab, fmt=_fmt_brl)

# USINAS - Helper para extrair dados do form
def _usina_from_form():
    return {
        "nome": request.form.get("nome", "").strip(),
        "endereco": request.form.get("endereco", "").strip(),
        "cep": request.form.get("cep", "").strip(),
        "cidade_uf": request.form.get("cidade_uf", "").strip(),
        "potencia_kwp": float(request.form.get("potencia_kwp", "0").replace(",", ".") or "0"),
        "modulos_tipo": request.form.get("modulos_tipo", "").strip(),
        "modulos_qtd": int(request.form.get("modulos_qtd", "0") or "0"),
        "inversor": request.form.get("inversor", "").strip(),
        "estrutura": request.form.get("estrutura", "").strip(),
        "uc_geradora": request.form.get("uc_geradora", "").strip(),
        "titular_uc": request.form.get("titular_uc", "").strip(),
        "cpf_titular": request.form.get("cpf_titular", "").strip(),
        "data_comissionamento": request.form.get("data_comissionamento", "").strip(),
        "garantia_modulos": request.form.get("garantia_modulos", "25 anos").strip(),
        "garantia_inversor": request.form.get("garantia_inversor", "10 anos").strip(),
        "geracao_media_mensal": float(request.form.get("geracao_media_mensal", "0").replace(",", ".") or "0"),
        "geracao_prevista_diaria": float(request.form.get("geracao_prevista_diaria", "0").replace(",", ".") or "0"),
        "observacoes": request.form.get("observacoes", "").strip(),
        # ── Investidor ──
        "investidor_nome": request.form.get("investidor_nome", "").strip(),
        "investidor_cpf_cnpj": request.form.get("investidor_cpf_cnpj", "").strip(),
        "investidor_email": request.form.get("investidor_email", "").strip(),
        "investidor_telefone": request.form.get("investidor_telefone", "").strip(),
        "investidor_banco": request.form.get("investidor_banco", "").strip(),
        "investidor_agencia": request.form.get("investidor_agencia", "").strip(),
        "investidor_conta": request.form.get("investidor_conta", "").strip(),
        "investidor_pix": request.form.get("investidor_pix", "").strip(),
        "investidor_desagio_pct": float(request.form.get("investidor_desagio_pct", "0").replace(",", ".") or "0"),
        "investidor_dia_pagamento": request.form.get("investidor_dia_pagamento", "").strip(),
        "investidor_valor_minimo": float(request.form.get("investidor_valor_minimo", "0").replace(",", ".") or "0"),
    }


# USINAS - Nova
@app.route("/usinas/nova", methods=["GET", "POST"])
def usina_nova():
    if request.method == "POST":
        from db import (tb_save_usina, tb_save_investidor,
                        tb_save_titular, tb_save_endereco_usina)
        try:
            # Proprietário/Investidor: selecionar existente OU cadastrar novo inline
            id_investidor = None
            _rec_existente = request.form.get("id_investidor_existente", "").strip()
            if _rec_existente:
                id_investidor = int(_rec_existente)
            else:
                inv_nome = request.form.get("inv_desc_nome", "").strip()
                if inv_nome:
                    inv_dados = {
                        "desc_nome":         inv_nome,
                        "desc_cpf_cnpj":     request.form.get("inv_desc_cpf_cnpj", "").strip(),
                        "desc_email":        request.form.get("inv_desc_email", "").strip(),
                        "desc_telefone":     request.form.get("inv_desc_telefone", "").strip(),
                        "desc_banco":        request.form.get("inv_desc_banco", "").strip(),
                        "desc_agencia":      request.form.get("inv_desc_agencia", "").strip(),
                        "desc_conta":        request.form.get("inv_desc_conta", "").strip(),
                        "desc_pix":          request.form.get("inv_desc_pix", "").strip(),
                        "pct_desagio":       float(request.form.get("inv_pct_desagio", "0").replace(",", ".") or "0"),
                        "qtd_dia_pagamento": int(request.form.get("inv_qtd_dia_pagamento", "0") or "0") or None,
                        "vlr_minimo":        float(request.form.get("inv_vlr_minimo", "0").replace(",", ".") or "0"),
                    }
                    inv_salvo     = tb_save_investidor(inv_dados)
                    id_investidor = inv_salvo.get("id_investidor")

            # Titular UC: selecionar existente OU cadastrar novo inline
            id_titular = None
            _titular_existente = request.form.get("id_titular_existente", "").strip()
            if _titular_existente:
                id_titular = int(_titular_existente)
            else:
                titular_nome = request.form.get("desc_titular_uc", "").strip()
                if titular_nome:
                    titular_dados = {
                        "desc_nome":     titular_nome,
                        "desc_cpf_cnpj": request.form.get("desc_cpf_titular", "").strip() or None,
                        "desc_telefone": request.form.get("desc_telefone_titular", "").strip() or None,
                        "desc_email":    request.form.get("desc_email_titular", "").strip() or None,
                        "dt_nascimento": _data_br_para_iso(request.form.get("dt_nascimento_titular", "")) or None,
                    }
                    titular_salvo = tb_save_titular(titular_dados)
                    id_titular = titular_salvo.get("id_titular")

            # Usina
            # cod_uc_geradora: constraint tb_usinas_uc_15_digito exige exatos 15 dígitos sem formatação
            import re as _re_uc
            _uc_raw = request.form.get("cod_uc_geradora", "").strip()
            _uc_digitos = _re_uc.sub(r"\D", "", _uc_raw)
            usina_dados = {
                "desc_nome": request.form.get("desc_nome", "").strip(),
                "cod_uc_geradora": _uc_digitos,
                "desc_classe": request.form.get("desc_classe", "").strip() or None,
                "qtd_potencia_kwp": float(request.form.get("qtd_potencia_kwp", "0").replace(",", ".") or "0"),
                "desc_modulos_tipo": request.form.get("desc_modulos_tipo", "").strip(),
                "qtd_modulos": int(request.form.get("qtd_modulos", "0") or "0"),
                "desc_inversor": request.form.get("desc_inversor", "").strip(),
                "desc_estrutura": request.form.get("desc_estrutura", "").strip(),
                "dt_comissionamento": _data_br_para_iso(request.form.get("dt_comissionamento", "").strip()) or None,
                "desc_garantia_modulos": request.form.get("desc_garantia_modulos", "25 anos").strip(),
                "desc_garantia_inversor": request.form.get("desc_garantia_inversor", "10 anos").strip(),
                "qtd_geracao_media_mensal": float(request.form.get("qtd_geracao_media_mensal", "0").replace(",", ".") or "0"),
                "qtd_geracao_prevista_diaria": float(request.form.get("qtd_geracao_prevista_diaria", "0").replace(",", ".") or "0"),
                "desc_observacoes": request.form.get("desc_observacoes", "").strip(),
                "desc_pix_recebimento": request.form.get("desc_pix_recebimento", "").strip() or None,
            }
            # Ciclo de leitura — habitual + próxima exata
            _dia_leit = request.form.get("qtd_dia_leitura", "").strip()
            if _dia_leit:
                try:
                    d = int(_dia_leit)
                    if 1 <= d <= 31:
                        usina_dados["qtd_dia_leitura"] = d
                except ValueError:
                    pass
            _prox_leit = _data_br_para_iso(request.form.get("dt_proxima_leitura", "").strip())
            if _prox_leit:
                usina_dados["dt_proxima_leitura"] = _prox_leit
            if id_investidor:
                usina_dados["id_investidor"] = id_investidor
            if id_titular:
                usina_dados["id_titular"] = id_titular
            usina_salva = tb_save_usina(usina_dados)
            id_usina = usina_salva.get("id_usina")
            # Endereco
            if id_usina:
                end_dados = {
                    "desc_logradouro": request.form.get("desc_logradouro", "").strip(),
                    "desc_numero": request.form.get("desc_numero", "").strip(),
                    "desc_complemento": request.form.get("desc_complemento", "").strip(),
                    "desc_setor": request.form.get("desc_setor", "").strip(),
                    "desc_cidade": request.form.get("desc_cidade", "").strip(),
                    "desc_estado": request.form.get("desc_estado", "").strip(),
                    "cod_cep": request.form.get("cod_cep", "").strip(),
                }
                if any(v for v in end_dados.values()):
                    tb_save_endereco_usina(id_usina, end_dados)
            flash(f"Usina '{usina_dados['desc_nome']}' cadastrada!", "success")
            return redirect(url_for("usinas_lista"))
        except Exception as e:
            flash(f"Erro ao salvar: {e}", "danger")
    from db import tb_carregar_investidores, tb_carregar_titulares
    return render_template("usina_form.html", usina=None, endereco=None,
                           investidor=None, titular=None,
                           recebedores=tb_carregar_investidores(),
                           titulares=tb_carregar_titulares())

# USINAS - Editar
@app.route("/usinas/editar/<int:id_usina>", methods=["GET", "POST"])
def usina_editar(id_usina):
    from db import (tb_get_usina, tb_save_usina, tb_save_investidor,
                    tb_save_titular, tb_get_endereco_usina, tb_save_endereco_usina,
                    tb_get_investidor, tb_get_titular)
    usina = tb_get_usina(id_usina)
    if not usina:
        flash("Usina nao encontrada!", "danger"); return redirect(url_for("usinas_lista"))
    if request.method == "POST":
        try:
            # Proprietário/Investidor: selecionar existente OU manter/atualizar inline
            _rec_existente = request.form.get("id_investidor_existente", "").strip()
            if _rec_existente:
                id_investidor = int(_rec_existente)
            else:
                id_investidor = usina.get("id_investidor")
                inv_nome = request.form.get("inv_desc_nome", "").strip()
                if inv_nome:
                    inv_dados = {
                        "desc_nome":         inv_nome,
                        "desc_cpf_cnpj":     request.form.get("inv_desc_cpf_cnpj", "").strip(),
                        "desc_email":        request.form.get("inv_desc_email", "").strip(),
                        "desc_telefone":     request.form.get("inv_desc_telefone", "").strip(),
                        "desc_banco":        request.form.get("inv_desc_banco", "").strip(),
                        "desc_agencia":      request.form.get("inv_desc_agencia", "").strip(),
                        "desc_conta":        request.form.get("inv_desc_conta", "").strip(),
                        "desc_pix":          request.form.get("inv_desc_pix", "").strip(),
                        "pct_desagio":       float(request.form.get("inv_pct_desagio", "0").replace(",", ".") or "0"),
                        "qtd_dia_pagamento": int(request.form.get("inv_qtd_dia_pagamento", "0") or "0") or None,
                        "vlr_minimo":        float(request.form.get("inv_vlr_minimo", "0").replace(",", ".") or "0"),
                    }
                    if id_investidor:
                        inv_dados["id_investidor"] = id_investidor
                    inv_salvo     = tb_save_investidor(inv_dados)
                    id_investidor = inv_salvo.get("id_investidor")

            # Titular: selecionar existente OU manter/cadastrar/atualizar inline
            _titular_existente = request.form.get("id_titular_existente", "").strip()
            if _titular_existente:
                id_titular = int(_titular_existente)
            else:
                id_titular = usina.get("id_titular")
                titular_nome = request.form.get("desc_titular_uc", "").strip()
                if titular_nome:
                    titular_dados = {
                        "desc_nome":     titular_nome,
                        "desc_cpf_cnpj": request.form.get("desc_cpf_titular", "").strip() or None,
                        "desc_telefone": request.form.get("desc_telefone_titular", "").strip() or None,
                        "desc_email":    request.form.get("desc_email_titular", "").strip() or None,
                        "dt_nascimento": _data_br_para_iso(request.form.get("dt_nascimento_titular", "")) or None,
                    }
                    if id_titular:
                        titular_dados["id_titular"] = id_titular
                    titular_salvo = tb_save_titular(titular_dados)
                    id_titular = titular_salvo.get("id_titular")

            # Usina
            # cod_uc_geradora: constraint tb_usinas_uc_15_digito exige exatos 15 dígitos sem formatação
            import re as _re_uc
            _uc_raw = request.form.get("cod_uc_geradora", "").strip()
            _uc_digitos = _re_uc.sub(r"\D", "", _uc_raw)
            usina_dados = {
                "id_usina": id_usina,
                "desc_nome": request.form.get("desc_nome", "").strip(),
                "cod_uc_geradora": _uc_digitos,
                "desc_classe": request.form.get("desc_classe", "").strip() or None,
                "qtd_potencia_kwp": float(request.form.get("qtd_potencia_kwp", "0").replace(",", ".") or "0"),
                "desc_modulos_tipo": request.form.get("desc_modulos_tipo", "").strip(),
                "qtd_modulos": int(request.form.get("qtd_modulos", "0") or "0"),
                "desc_inversor": request.form.get("desc_inversor", "").strip(),
                "desc_estrutura": request.form.get("desc_estrutura", "").strip(),
                "dt_comissionamento": _data_br_para_iso(request.form.get("dt_comissionamento", "").strip()) or None,
                "desc_garantia_modulos": request.form.get("desc_garantia_modulos", "25 anos").strip(),
                "desc_garantia_inversor": request.form.get("desc_garantia_inversor", "10 anos").strip(),
                "qtd_geracao_media_mensal": float(request.form.get("qtd_geracao_media_mensal", "0").replace(",", ".") or "0"),
                "qtd_geracao_prevista_diaria": float(request.form.get("qtd_geracao_prevista_diaria", "0").replace(",", ".") or "0"),
                "desc_observacoes": request.form.get("desc_observacoes", "").strip(),
                "desc_pix_recebimento": request.form.get("desc_pix_recebimento", "").strip() or None,
            }
            # Ciclo de leitura — habitual + próxima exata
            _dia_leit = request.form.get("qtd_dia_leitura", "").strip()
            if _dia_leit:
                try:
                    d = int(_dia_leit)
                    if 1 <= d <= 31:
                        usina_dados["qtd_dia_leitura"] = d
                except ValueError:
                    pass
            _prox_leit = _data_br_para_iso(request.form.get("dt_proxima_leitura", "").strip())
            if _prox_leit:
                usina_dados["dt_proxima_leitura"] = _prox_leit
            if id_investidor:
                usina_dados["id_investidor"] = id_investidor
            if id_titular:
                usina_dados["id_titular"] = id_titular
            tb_save_usina(usina_dados)
            # Endereco
            end_dados = {
                "desc_logradouro": request.form.get("desc_logradouro", "").strip(),
                "desc_numero": request.form.get("desc_numero", "").strip(),
                "desc_complemento": request.form.get("desc_complemento", "").strip(),
                "desc_setor": request.form.get("desc_setor", "").strip(),
                "desc_cidade": request.form.get("desc_cidade", "").strip(),
                "desc_estado": request.form.get("desc_estado", "").strip(),
                "cod_cep": request.form.get("cod_cep", "").strip(),
            }
            tb_save_endereco_usina(id_usina, end_dados)
            flash("Usina atualizada!", "success")
            return redirect(url_for("usinas_lista"))
        except Exception as e:
            flash(f"Erro ao salvar: {e}", "danger")
    from db import tb_carregar_investidores, tb_carregar_titulares
    endereco   = tb_get_endereco_usina(id_usina) or {}
    investidor = tb_get_investidor(usina.get("id_investidor")) if usina.get("id_investidor") else {}
    titular    = tb_get_titular(usina.get("id_titular")) if usina.get("id_titular") else {}
    return render_template("usina_form.html", usina=usina, endereco=endereco,
                           investidor=investidor or {},
                           titular=titular or {},
                           recebedores=tb_carregar_investidores(),
                           titulares=tb_carregar_titulares())

# USINAS - Upload do documento pessoal do titular (anexado ao PDF de rateio)
@app.route("/usinas/upload_doc/<uid>", methods=["POST"])
def usina_upload_doc(uid):
    usinas = carregar_usinas()
    if uid not in usinas:
        flash("Usina nao encontrada!", "danger"); return redirect(url_for("usinas_lista"))
    if "documento" not in request.files:
        flash("Nenhum arquivo enviado!", "warning"); return redirect(url_for("usina_ver", uid=uid))
    f = request.files["documento"]
    if not f or not f.filename:
        flash("Nenhum arquivo enviado!", "warning"); return redirect(url_for("usina_ver", uid=uid))
    if not f.filename.lower().endswith(".pdf"):
        flash("Apenas arquivos PDF sao aceitos.", "danger"); return redirect(url_for("usina_ver", uid=uid))
    fname = f"doc_titular_{uid}.pdf"
    fpath = os.path.join(UPLOAD_FOLDER, fname)
    f.save(fpath)
    usinas[uid]["documento_titular_pdf"] = fpath
    salvar_usinas(usinas)
    flash("Documento do titular anexado! Sera incluido nos proximos PDFs de rateio.", "success")
    return redirect(url_for("usina_ver", uid=uid))

# USINAS - Remover documento pessoal
@app.route("/usinas/remover_doc/<uid>")
def usina_remover_doc(uid):
    usinas = carregar_usinas()
    if uid in usinas and "documento_titular_pdf" in usinas[uid]:
        try:
            if os.path.exists(usinas[uid]["documento_titular_pdf"]):
                os.remove(usinas[uid]["documento_titular_pdf"])
        except: pass
        del usinas[uid]["documento_titular_pdf"]
        salvar_usinas(usinas)
        flash("Documento removido.", "warning")
    return redirect(url_for("usina_ver", uid=uid))

# USINAS - Upload de documentos (CNH/RG, Procuracao, CNH/RG Procurador)
_DOCS_CONFIG = {
    "cnh_rg":       ("path_doc_cnh_rg",      "CNH/RG do titular"),
    "procuracao":   ("path_doc_procuracao",   "Procuracao"),
    "cnh_rg_proc":  ("path_doc_cnh_rg_proc",  "CNH/RG do procurador"),
}
_EXTS_PERMITIDAS = {".pdf", ".jpg", ".jpeg", ".png"}

@app.route("/usinas/upload_documento/<int:id_usina>/<tipo_doc>", methods=["POST"])
def usina_upload_documento(id_usina, tipo_doc):
    from db import tb_get_usina, tb_save_usina
    if tipo_doc not in _DOCS_CONFIG:
        flash("Tipo de documento invalido.", "danger")
        return redirect(url_for("usina_editar", id_usina=id_usina))
    campo_db, label = _DOCS_CONFIG[tipo_doc]
    if "documento" not in request.files:
        flash("Nenhum arquivo enviado!", "warning")
        return redirect(url_for("usina_editar", id_usina=id_usina))
    f = request.files["documento"]
    if not f or not f.filename:
        flash("Nenhum arquivo enviado!", "warning")
        return redirect(url_for("usina_editar", id_usina=id_usina))
    ext = os.path.splitext(f.filename.lower())[1]
    if ext not in _EXTS_PERMITIDAS:
        flash("Formato nao permitido. Use PDF, JPG ou PNG.", "danger")
        return redirect(url_for("usina_editar", id_usina=id_usina))
    fname = f"usina{id_usina}_{tipo_doc}{ext}"
    fpath = os.path.join(UPLOAD_FOLDER, fname)
    f.save(fpath)
    tb_save_usina({"id_usina": id_usina, campo_db: fpath})
    flash(f"{label} anexado com sucesso!", "success")
    return redirect(url_for("usina_editar", id_usina=id_usina))


@app.route("/usinas/remover_documento/<int:id_usina>/<tipo_doc>")
def usina_remover_documento(id_usina, tipo_doc):
    from db import tb_get_usina, tb_save_usina
    if tipo_doc not in _DOCS_CONFIG:
        flash("Tipo de documento invalido.", "danger")
        return redirect(url_for("usina_editar", id_usina=id_usina))
    campo_db, label = _DOCS_CONFIG[tipo_doc]
    usina = tb_get_usina(id_usina)
    if usina and usina.get(campo_db):
        try:
            if os.path.exists(usina[campo_db]):
                os.remove(usina[campo_db])
        except Exception:
            pass
        tb_save_usina({"id_usina": id_usina, campo_db: None})
    flash(f"{label} removido.", "warning")
    return redirect(url_for("usina_editar", id_usina=id_usina))


@app.route("/usinas/download_documento/<int:id_usina>/<tipo_doc>")
def usina_download_documento(id_usina, tipo_doc):
    from db import tb_get_usina
    from flask import send_file
    if tipo_doc not in _DOCS_CONFIG:
        flash("Tipo de documento invalido.", "danger")
        return redirect(url_for("usina_editar", id_usina=id_usina))
    campo_db, label = _DOCS_CONFIG[tipo_doc]
    usina = tb_get_usina(id_usina)
    fpath = usina.get(campo_db) if usina else None
    if not fpath or not os.path.exists(fpath):
        flash("Arquivo nao encontrado.", "danger")
        return redirect(url_for("usina_editar", id_usina=id_usina))
    return send_file(fpath, as_attachment=True)


# USINAS - Remover
@app.route("/usinas/remover/<int:id_usina>")
def usina_remover(id_usina):
    from db import tb_get_usina, tb_delete_usina, tb_delete_endereco_usina
    usina = tb_get_usina(id_usina)
    if usina:
        nome = usina.get("desc_nome", str(id_usina))
        try:
            tb_delete_endereco_usina(id_usina)
        except: pass
        tb_delete_usina(id_usina)
        flash(f"Usina '{nome}' removida!", "warning")
    return redirect(url_for("usinas_lista"))

# ──────────────────────────────────────────────────────────────────
# USINAS - Distribuição automática de clientes
# ──────────────────────────────────────────────────────────────────
def _dia_de(data_iso):
    """Extrai o dia do mês de uma data ISO (YYYY-MM-DD). Retorna None se inválida."""
    try:
        return int(str(data_iso)[8:10]) if data_iso and len(str(data_iso)) >= 10 else None
    except (ValueError, TypeError):
        return None


def _dias_apos(dia_usina: int, dia_cliente: int) -> int:
    """Quantos dias o cliente é lido após a usina (módulo 30). Negativo = antes."""
    return (dia_cliente - dia_usina) % 30


def _algoritmo_distribuicao(usinas: list, clientes: list,
                             kwh_fixo_por_usina: dict = None,
                             ignorar_saldo: bool = False,
                             janela_dias: int = 7,
                             excesso_pct: int = 5,
                             folga_pct: int = 0,
                             ordem: str = "maior",
                             permitir_split: bool = True) -> tuple:
    """
    Distribui clientes entre usinas respeitando filtros configuráveis.

    Args:
      kwh_fixo_por_usina: {id_usina: kwh_total_comprometido_via_fixo}
      ignorar_saldo:    True trata saldo como 0
      janela_dias:      compatibilidade leitura: 1 ≤ (dia_cli - dia_usina) mod 30 ≤ janela_dias
                        (cliente deve ler DEPOIS da usina, nunca no mesmo dia)
      excesso_pct:      até X% acima da geração que o algoritmo aceita ultrapassar (hard limit)
      folga_pct:        Y% da geração que o algoritmo PREFERE deixar livre (soft target)
                        Quando 0 e excesso=5 → comportamento legado (até 5% acima).
                        Quando folga=10 e excesso=0 → estrito, sempre deixa 10% livres.
                        Quando folga=5 e excesso=10 → tenta deixar 5%, aceita até +10% se necessário.
      ordem:            "maior" = clientes com maior demanda primeiro; "menor" = menor primeiro
      permitir_split:   True permite dividir cliente em 2 usinas
    Retorna:
      alocacao  = {id_usina: {'usina': {...}, 'itens': [...]}}
      sem_usina = [{'cliente': {...}, 'motivo': str}]
    """
    kwh_fixo_por_usina = kwh_fixo_por_usina or {}
    # Fatores: target = capacidade preferida (com folga); max = teto absoluto (com excesso)
    fator_target = max(0.10, 1.0 - folga_pct / 100.0)
    fator_max    = max(fator_target, 1.0 + excesso_pct / 100.0)

    def _ger_disp(u):
        ger_total = float(u.get("qtd_geracao_media_mensal") or 0)
        return max(0.0, ger_total - kwh_fixo_por_usina.get(u["id_usina"], 0.0))

    # Inclui apenas usinas com geração DISPONÍVEL > 0 (após descontar FIXO)
    usinas_ok = [u for u in usinas
                 if u.get("qtd_dia_leitura") and _ger_disp(u) > 0]

    alocacao = {
        u["id_usina"]: {
            "usina":        u,
            "itens":        [],
            "kwh_alocado":  0.0,    # soma dos kwh_efetivos (líquido de saldo)
            "kwh_geracao":  _ger_disp(u),                          # CAPACIDADE PARA ALOCAR (pós-FIXO)
            "kwh_geracao_total": float(u.get("qtd_geracao_media_mensal") or 0),  # bruta (display)
            "kwh_fixo":     kwh_fixo_por_usina.get(u["id_usina"], 0.0),
        }
        for u in usinas_ok
    }
    sem_usina = []

    def _compat(u_day, c_day):
        # Cliente deve ler ENTRE 1 e janela_dias APÓS a usina.
        # Dia 0 (mesma data) NÃO conta — créditos ainda não foram alocados
        # pela Equatorial (o ciclo de geração da usina não fechou).
        return 1 <= _dias_apos(u_day, c_day) <= janela_dias

    def _restante(id_u):
        return alocacao[id_u]["kwh_geracao"] - alocacao[id_u]["kwh_alocado"]

    def _registrar(id_u, cli, pct, kwh_bruto, saldo):
        kwh_efetivo = max(0.0, kwh_bruto * pct / 100 - saldo * pct / 100)
        coberto = (kwh_efetivo == 0)
        alocacao[id_u]["itens"].append({
            "cliente":      cli,
            "pct":          pct,
            "kwh_bruto":    kwh_bruto * pct / 100,
            "kwh_efetivo":  kwh_efetivo,
            "saldo":        saldo * pct / 100,
            "coberto_saldo": coberto,
        })
        alocacao[id_u]["kwh_alocado"] += kwh_efetivo

    # Ordena: por kwh_efetivo (maior ou menor primeiro conforme parâmetro)
    def _sort_key(c):
        bruto = float(c.get("qtd_consumo_medio_kwh") or 0)
        saldo = 0.0 if ignorar_saldo else float(c.get("_saldo_atual") or 0)
        ef = max(0.0, bruto - saldo)
        return -ef if ordem == "maior" else ef

    clientes_sorted = sorted(clientes, key=_sort_key)

    for cli in clientes_sorted:
        consumo_bruto = float(cli.get("qtd_consumo_medio_kwh") or 0)
        saldo         = 0.0 if ignorar_saldo else float(cli.get("_saldo_atual") or 0)
        kwh_efetivo   = max(0.0, consumo_bruto - saldo)

        if consumo_bruto <= 0:
            sem_usina.append({"cliente": cli, "motivo": "Consumo médio não preenchido"})
            continue

        dia_c = _dia_de(cli.get("proxima_leitura"))
        if not dia_c:
            sem_usina.append({"cliente": cli, "motivo": "Data de leitura não preenchida"})
            continue

        compat = [u for u in usinas_ok if _compat(u["qtd_dia_leitura"], dia_c)]
        if not compat:
            sem_usina.append({"cliente": cli,
                               "motivo": f"Nenhuma usina compatível (dia de leitura: {dia_c})"})
            continue

        # Ordena por restante desc
        compat_rest = sorted(compat, key=lambda u: -_restante(u["id_usina"]))

        if kwh_efetivo == 0:
            # Coberto pelo saldo: vincula à usina com mais restante (ocupa 0 kWh)
            _registrar(compat_rest[0]["id_usina"], cli, 100, consumo_bruto, saldo)
            continue

        # Tenta encaixar em 1 usina em 2 fases:
        # 1ª: respeitando folga (target = gen × (1 - folga%))
        # 2ª: usando excesso permitido (max = gen × (1 + excesso%))
        limite_target = kwh_efetivo / fator_target
        limite_max    = kwh_efetivo / fator_max
        candidato = next(
            (u for u in compat_rest if _restante(u["id_usina"]) >= limite_target),
            None
        )
        if not candidato:
            candidato = next(
                (u for u in compat_rest if _restante(u["id_usina"]) >= limite_max),
                None
            )
        if candidato:
            _registrar(candidato["id_usina"], cli, 100, consumo_bruto, saldo)
        elif permitir_split and len(compat_rest) >= 2:
            # Split entre as 2 com maior restante
            u1, u2 = compat_rest[0], compat_rest[1]
            r1 = max(_restante(u1["id_usina"]), 0)
            r2 = max(_restante(u2["id_usina"]), 0)
            total_r = r1 + r2
            if total_r > 0:
                pct1 = max(1, min(99, round(r1 / total_r * 100)))
            else:
                pct1 = 50
            pct2 = 100 - pct1
            _registrar(u1["id_usina"], cli, pct1, consumo_bruto, saldo)
            _registrar(u2["id_usina"], cli, pct2, consumo_bruto, saldo)
        else:
            # Não cabe em 1 e split desabilitado → marca como sem usina
            if not permitir_split:
                sem_usina.append({"cliente": cli,
                    "motivo": f"Sem capacidade em 1 usina (split desativado, demanda {int(kwh_efetivo)} kWh)"})
            else:
                # Só 1 usina compatível mesmo que cheia
                _registrar(compat_rest[0]["id_usina"], cli, 100, consumo_bruto, saldo)

    return alocacao, sem_usina


@app.route("/usinas/distribuir", methods=["GET", "POST"])
def usinas_distribuir():
    import json as _json
    from db import tb_carregar_usinas, tb_carregar_clientes, tb_carregar_enderecos_usinas, _db

    usinas   = tb_carregar_usinas()
    clientes = tb_carregar_clientes()
    # Todos os ativos (incluindo já vinculados)
    clientes = [c for c in clientes if str(c.get("STATUS") or "").upper() != "INATIVO"]

    if request.method == "POST":
        # ── CONFIRMAR ──────────────────────────────────────────
        from datetime import date
        hoje = date.today().isoformat()
        payload = request.form.get("payload_json", "")
        try:
            proposta = _json.loads(payload)  # [{id_cliente, id_usina, pct, saldo_kwh}]
        except Exception as e:
            flash(f"Erro ao interpretar proposta: {e}", "danger")
            return redirect(url_for("usinas_distribuir"))

        por_cliente: dict = {}
        for item in proposta:
            por_cliente.setdefault(item["id_cliente"], []).append(item)

        db = _db()
        # Identifica clientes com vínculos FIXO — não serão sobrescritos
        vincs_fixas_post = db.select("tb_cliente_usina",
            raw_params={"dt_fim": "is.null", "desc_saldo_obs": "eq.FIXO"})
        ids_fixos_post = {v["id_cliente"] for v in vincs_fixas_post}

        # IDs de clientes que DEVEM permanecer vinculados (vieram no payload)
        ids_no_payload = {int(k) for k in por_cliente.keys()}

        # ── PASSO 1: Limpa "lixo" — fecha vínculos ATIVOS de clientes que NÃO
        # estão no payload (clientes movidos pra "sem usina" perdem o vínculo).
        # FIXO sempre preservado.
        todos_ativos = db.select("tb_cliente_usina",
                                  raw_params={"dt_fim": "is.null"})
        removidos = 0
        for v in todos_ativos:
            if (v.get("desc_saldo_obs") or "").upper() == "FIXO":
                continue
            if v.get("id_cliente") not in ids_no_payload:
                try:
                    db.patch("tb_cliente_usina", {"id": v["id"]}, {"dt_fim": hoje})
                    removidos += 1
                except Exception as e:
                    app.logger.error(f"[distribuir-global] erro fechar v={v.get('id')}: {e}")

        # ── PASSO 2: Processa os clientes do payload
        salvos = erros = 0
        for id_c, items in por_cliente.items():
            if int(id_c) in ids_fixos_post:
                continue  # Vínculo FIXO — não sobrescrever
            try:
                # Fecha vínculos ativos antigos do cliente (mesmo cliente em outra usina)
                ativos = db.select("tb_cliente_usina",
                                   raw_params={"id_cliente": f"eq.{id_c}", "dt_fim": "is.null"})
                for a in ativos:
                    if (a.get("desc_saldo_obs") or "").upper() == "FIXO":
                        continue
                    db.patch("tb_cliente_usina", {"id": a["id"]}, {"dt_fim": hoje})
                # Cria novos vínculos — preserva saldo no novo vínculo
                for item in items:
                    row = {
                        "id_cliente": id_c,
                        "id_usina":   item["id_usina"],
                        "pct_rateio": item["pct"],
                        "dt_inicio":  hoje,
                    }
                    if item.get("saldo_kwh", 0) > 0:
                        row["qtd_saldo_kwh"] = item["saldo_kwh"]
                    db.upsert("tb_cliente_usina", row)
                salvos += 1
            except Exception as e:
                app.logger.error(f"[distribuir] cliente {id_c}: {e}")
                erros += 1

        msgs = [f"{salvos} cliente(s) vinculado(s)"]
        if removidos:
            msgs.append(f"{removidos} vínculo(s) antigo(s) fechado(s)")
        if erros:
            msgs.append(f"{erros} erro(s)")
        flash("Distribuição concluída! " + " · ".join(msgs),
              "warning" if erros else "success")
        return redirect(url_for("usinas_lista"))

    # ── GET: busca saldo atual e calcula preview ────────────────
    # Saldo atual = saldo da vinculação ativa OU saldo_inicial do cadastro
    vinculos_ativos = _db().select("tb_cliente_usina",
                                   raw_params={"dt_fim": "is.null"},
                                   columns="id_cliente,id_usina,qtd_saldo_kwh,desc_saldo_obs")
    saldo_por_cliente = {}
    for v in vinculos_ativos:
        id_c = v.get("id_cliente")
        saldo = float(v.get("qtd_saldo_kwh") or 0)
        if saldo > 0:
            saldo_por_cliente[id_c] = saldo_por_cliente.get(id_c, 0) + saldo

    # ── Clientes FIXO: vínculos pré-configurados, não entram na distribuição ──
    # Reload com pct_rateio para calcular kwh comprometido por usina
    vinculos_ativos_full = _db().select("tb_cliente_usina",
                                   raw_params={"dt_fim": "is.null"},
                                   columns="id_cliente,id_usina,pct_rateio,qtd_saldo_kwh,desc_saldo_obs")
    ids_fixos = {v["id_cliente"] for v in vinculos_ativos_full
                 if (v.get("desc_saldo_obs") or "").upper() == "FIXO"}
    usinas_map = {u["id_usina"]: u.get("desc_nome", "") for u in usinas}
    vincs_fixas_map: dict = {}
    for v in vinculos_ativos_full:
        if (v.get("desc_saldo_obs") or "").upper() == "FIXO":
            vincs_fixas_map.setdefault(v["id_cliente"], []).append(v)

    # kwh comprometido por usina via FIXO (= soma de pct × geração_usina)
    ger_por_usina = {u["id_usina"]: float(u.get("qtd_geracao_media_mensal") or 0) for u in usinas}
    kwh_fixo_por_usina: dict = {}
    for v in vinculos_ativos_full:
        if (v.get("desc_saldo_obs") or "").upper() != "FIXO":
            continue
        id_u = v.get("id_usina"); pct = float(v.get("pct_rateio") or 0) / 100.0
        if id_u and pct > 0:
            kwh_fixo_por_usina[id_u] = kwh_fixo_por_usina.get(id_u, 0.0) + pct * ger_por_usina.get(id_u, 0)

    clientes_fixos = []
    for c in clientes:
        if c["id_cliente"] in ids_fixos:
            vfs = vincs_fixas_map.get(c["id_cliente"], [])
            c["_vinculos_fixos"] = [
                {"nome_usina": usinas_map.get(v.get("id_usina"), str(v.get("id_usina"))),
                 "pct": v.get("pct_rateio") or 100}
                for v in vfs
            ]
            clientes_fixos.append(c)

    # Remove fixos da lista que entra na distribuição automática
    clientes = [c for c in clientes if c["id_cliente"] not in ids_fixos]

    for c in clientes:
        id_c = c["id_cliente"]
        # Prioridade: saldo da vinculação ativa; fallback: saldo_inicial do cadastro
        c["_saldo_atual"] = saldo_por_cliente.get(
            id_c, float(c.get("qtd_saldo_inicial_kwh") or 0)
        )

    enderecos = tb_carregar_enderecos_usinas()
    for u in usinas:
        end = enderecos.get(u["id_usina"], {})
        u["_cidade_uf"] = ", ".join(filter(None, [end.get("desc_cidade"), end.get("desc_estado")]))

    ignorar_saldo = request.args.get("ignorar_saldo") in ("1", "true", "on")
    try: janela_dias = max(1, min(30, int(request.args.get("janela_dias", "7"))))
    except Exception: janela_dias = 7
    try: excesso_pct = max(0, min(50, int(request.args.get("excesso_pct", "5"))))
    except Exception: excesso_pct = 5
    try: folga_pct   = max(0, min(50, int(request.args.get("folga_pct",   "0"))))
    except Exception: folga_pct = 0
    permitir_split = request.args.get("permitir_split", "1") in ("1", "true", "on")

    alocacao, sem_usina = _algoritmo_distribuicao(
        usinas, clientes, kwh_fixo_por_usina,
        ignorar_saldo=ignorar_saldo,
        janela_dias=janela_dias,
        excesso_pct=excesso_pct,
        folga_pct=folga_pct,
        permitir_split=permitir_split,
    )

    # Payload para confirmação (inclui saldo proporcional por vínculo)
    proposta = []
    for uid, bloco in alocacao.items():
        for item in bloco["itens"]:
            proposta.append({
                "id_cliente": item["cliente"]["id_cliente"],
                "id_usina":   uid,
                "pct":        item["pct"],
                "saldo_kwh":  round(item["saldo"], 2),
            })
    payload_json = _json.dumps(proposta)

    # Estatísticas
    ids_alocados = {item["cliente"]["id_cliente"]
                    for bloco in alocacao.values() for item in bloco["itens"]}
    total_alocados  = len(ids_alocados)
    total_sem_usina = len(sem_usina)
    splits          = len({item["cliente"]["id_cliente"]
                           for bloco in alocacao.values()
                           for item in bloco["itens"] if item["pct"] < 100})
    cobertos_saldo  = sum(1 for bloco in alocacao.values()
                          for item in bloco["itens"]
                          if item["coberto_saldo"] and item["pct"] == 100)

    return render_template("distribuir_preview.html",
                           alocacao=alocacao,
                           sem_usina=sem_usina,
                           payload_json=payload_json,
                           total_clientes=len(clientes) + len(clientes_fixos),
                           total_alocados=total_alocados,
                           total_sem_usina=total_sem_usina,
                           splits=splits,
                           cobertos_saldo=cobertos_saldo,
                           clientes_fixos=clientes_fixos,
                           total_fixos=len(clientes_fixos),
                           ignorar_saldo=ignorar_saldo,
                           janela_dias=janela_dias,
                           excesso_pct=excesso_pct,
                           folga_pct=folga_pct,
                           permitir_split=permitir_split)


# ============================================================
#  Confirmar distribuição de UMA usina específica
#  Permite finalizar usinas incrementalmente (próximas de leitura primeiro)
# ============================================================
@app.route("/usinas/distribuir/confirmar-usina/<int:id_usina>", methods=["POST"])
def usinas_distribuir_confirmar_usina(id_usina):
    import json as _json
    from datetime import date
    from db import _db

    payload = request.form.get("payload_json", "")
    try:
        proposta = _json.loads(payload)
    except Exception as e:
        flash(f"Erro ao interpretar proposta: {e}", "danger")
        return redirect(url_for("usinas_distribuir"))

    # Filtra só os itens da usina sendo confirmada
    itens_usina = [p for p in proposta if int(p.get("id_usina") or 0) == id_usina]
    if not itens_usina:
        flash("Nenhum cliente para confirmar nesta usina.", "warning")
        return redirect(url_for("usinas_distribuir"))

    db = _db()
    hoje = date.today().isoformat()

    # Identifica clientes FIXO (proteção extra — não sobrescrever)
    vincs_fixas = db.select("tb_cliente_usina",
        raw_params={"dt_fim": "is.null", "desc_saldo_obs": "eq.FIXO"})
    ids_fixos = {v["id_cliente"] for v in vincs_fixas}

    # IDs de clientes que DEVEM ficar vinculados a esta usina (vieram no payload)
    ids_novos = {int(p.get("id_cliente") or 0) for p in itens_usina}
    ids_novos.discard(0)

    # ── PASSO 1: Limpa "lixo" — fecha vínculos ATIVOS desta usina que NÃO estão
    # mais no payload (clientes removidos/movidos pra outra usina na tela).
    # Sem isto, clientes anteriores ficavam pendurados aqui, causando duplicação.
    vincs_existentes_usina = db.select("tb_cliente_usina",
        raw_params={"id_usina": f"eq.{id_usina}", "dt_fim": "is.null"})
    removidos = 0
    for v in vincs_existentes_usina:
        if (v.get("desc_saldo_obs") or "").upper() == "FIXO":
            continue  # nunca toca FIXO
        if v.get("id_cliente") not in ids_novos:
            try:
                db.patch("tb_cliente_usina", {"id": v["id"]}, {"dt_fim": hoje})
                removidos += 1
            except Exception as e:
                app.logger.error(f"[confirmar-usina {id_usina}] erro fechar v={v.get('id')}: {e}")

    # ── PASSO 2: Processa os clientes do payload
    salvos = erros = 0
    for item in itens_usina:
        id_c = int(item.get("id_cliente") or 0)
        if not id_c:
            continue
        if id_c in ids_fixos:
            continue  # FIXO: nunca sobrescrever
        try:
            # Fecha TODOS os vínculos ativos antigos do cliente (em qualquer usina)
            # Garante consistência mesmo quando confirmando 1 usina por vez:
            # se cliente foi movido da usina A pra B, ao confirmar B fecha o de A.
            ativos = db.select("tb_cliente_usina",
                               raw_params={"id_cliente": f"eq.{id_c}", "dt_fim": "is.null"})
            for a in ativos:
                # Não fecha vínculos FIXO (proteção extra)
                if (a.get("desc_saldo_obs") or "").upper() == "FIXO":
                    continue
                db.patch("tb_cliente_usina", {"id": a["id"]}, {"dt_fim": hoje})

            # Cria vínculo novo nesta usina
            row = {
                "id_cliente": id_c,
                "id_usina":   id_usina,
                "pct_rateio": item.get("pct", 100),
                "dt_inicio":  hoje,
            }
            if (item.get("saldo_kwh") or 0) > 0:
                row["qtd_saldo_kwh"] = item["saldo_kwh"]
            db.upsert("tb_cliente_usina", row)
            salvos += 1
        except Exception as e:
            app.logger.error(f"[confirmar-usina {id_usina}] cliente {id_c}: {e}")
            erros += 1

    msgs = []
    if salvos:
        msgs.append(f"{salvos} vinculado(s)")
    if removidos:
        msgs.append(f"{removidos} removido(s) (estavam aqui e não estão mais no payload)")
    if erros:
        msgs.append(f"{erros} erro(s)")

    if salvos or removidos:
        flash("Usina confirmada! " + " · ".join(msgs),
              "success" if not erros else "warning")
    else:
        flash("Nenhuma alteração aplicada." + (f" {erros} erro(s)." if erros else ""),
              "danger" if erros else "warning")

    # Redireciona pra tela de rateio dessa usina
    return redirect(url_for("rateio_dashboard", uid=id_usina))


# USINAS - Ver detalhes + geracao
@app.route("/usinas/ver/<uid>")
def usina_ver(uid):
    from db import (tb_get_usina, tb_get_usina_por_nome, tb_get_endereco_usina,
                    tb_get_clientes_da_usina, tb_carregar_clientes)

    # ── Resolve id_usina: inteiro (novo) ou uid legado (string) ──
    usinas_leg = carregar_usinas()
    try:
        id_usina = int(uid)
        usina_tb = tb_get_usina(id_usina)
    except ValueError:
        # uid legado → busca por nome na nova tabela
        nome     = usinas_leg.get(uid, {}).get("nome", "")
        usina_tb = tb_get_usina_por_nome(nome) if nome else None
        id_usina = usina_tb["id_usina"] if usina_tb else None

    if not usina_tb:
        flash("Usina nao encontrada!", "danger")
        return redirect(url_for("usinas_lista"))

    endereco = tb_get_endereco_usina(id_usina) or {}
    end_str  = " ".join(filter(None, [endereco.get("desc_logradouro", ""), endereco.get("desc_numero", "")]))
    cid_uf   = "/".join(filter(None, [endereco.get("desc_cidade", ""), endereco.get("desc_estado", "")]))

    # uid legado (string) para acessar geracao/rateio ainda nao migrados
    uid_leg = next((u for u, d in usinas_leg.items()
                    if d.get("nome") == usina_tb.get("desc_nome")), "")
    uid = uid_leg or str(id_usina)   # passado ao template para URLs legadas

    # Dict compativel com o template (nomes antigos → valores novos)
    usina = {
        "nome":                    usina_tb.get("desc_nome", ""),
        "potencia_kwp":            usina_tb.get("qtd_potencia_kwp", 0) or 0,
        "geracao_media_mensal":    usina_tb.get("qtd_geracao_media_mensal", 0) or 0,
        "geracao_prevista_diaria": usina_tb.get("qtd_geracao_prevista_diaria", 0) or 0,
        "uc_geradora":             usina_tb.get("cod_uc_geradora", ""),
        "titular_uc":              usina_tb.get("desc_titular_uc", ""),
        "modulos_tipo":            usina_tb.get("desc_modulos_tipo", ""),
        "modulos_qtd":             usina_tb.get("qtd_modulos", 0) or 0,
        "inversor":                usina_tb.get("desc_inversor", ""),
        "estrutura":               usina_tb.get("desc_estrutura", ""),
        "endereco":                end_str,
        "cidade_uf":               cid_uf,
        "cep":                     endereco.get("cod_cep", ""),
        "data_comissionamento":    usina_tb.get("dt_comissionamento", ""),
        "garantia_modulos":        usina_tb.get("desc_garantia_modulos", ""),
        "garantia_inversor":       usina_tb.get("desc_garantia_inversor", ""),
        "documento_titular_pdf":   usina_tb.get("desc_documento_titular_pdf", ""),
        # proxima_leitura: prefere nova tabela (ISO→BR), fallback para legado
        "proxima_leitura": (_iso_to_br(usina_tb.get("dt_proxima_leitura")) or
                            usinas_leg.get(uid_leg, {}).get("proxima_leitura", "")),
    }

    # ── Vinculados — novas tabelas ────────────────────────────
    vinculos_lista  = tb_get_clientes_da_usina(id_usina)
    todos_clientes  = tb_carregar_clientes()
    clientes_id_map = {c["id_cliente"]: c for c in todos_clientes}

    vinculados     = {}
    vinculados_ucs = set()
    for v in vinculos_lista:
        id_c = v.get("id_cliente")
        c_tb = clientes_id_map.get(id_c, {})
        uc   = c_tb.get("cod_uc", "")
        if uc:
            pct = v.get("pct_rateio", 0) or 0
            uc_alt = c_tb.get("cod_uc", "") or ""
            vinculados[uc] = {
                "nome":            c_tb.get("desc_nome", uc),
                "rateio_pct":      round(pct, 2),
                "proxima_leitura": v.get("dt_proxima_leitura", "") or "",
                "uc_display":      _fmt_uc15(uc_alt) if uc_alt else uc,
            }
            vinculados_ucs.add(uc)

    # Nao vinculados — usa legado para compatibilidade com route /vincular
    clientes_leg  = carregar_clientes()
    _uc_alt_map = {c["cod_uc"]: _fmt_uc15(c.get("cod_uc") or "") for c in todos_clientes}
    nao_vinculados = {
        uc: {**c, "uc_display": _uc_alt_map.get(uc) or uc}
        for uc, c in clientes_leg.items()
        if uc not in vinculados_ucs
    }

    # ── Geracao diaria (legado) ───────────────────────────────
    geracao = carregar_geracao()

    def _data_sort_key(r):
        try:
            d = r.get("data", ""); p = d.split("/")
            return f"{p[2]}-{p[1]}-{p[0]}"
        except Exception:
            return ""

    registros_usina = sorted(geracao.get(uid, []), key=_data_sort_key)

    total_kwh_periodo = sum((r.get("kwh", 0) or 0) for r in registros_usina)
    dias_registrados  = len(registros_usina)
    media_diaria      = total_kwh_periodo / dias_registrados if dias_registrados > 0 else 0
    prevista_diaria   = usina["geracao_prevista_diaria"]

    if registros_usina:
        datas              = [r.get("data", "") for r in registros_usina]
        data_inicio        = min(datas)
        data_fim           = max(datas)
        dias_restantes     = max(0, 30 - dias_registrados)
        estimativa_periodo = total_kwh_periodo + (media_diaria * dias_restantes)
    else:
        data_inicio = data_fim = ""
        dias_restantes     = 30
        estimativa_periodo = prevista_diaria * 30

    # ── Geracao mensal (legado) ───────────────────────────────
    geracao_mensal_all = carregar_geracao_mensal().get(uid, {})
    leituras_mensais   = []
    for mes_ref, dados in geracao_mensal_all.items():
        leituras_mensais.append({
            "mes_ref":               mes_ref,
            "kwh_gerado":            dados.get("kwh_gerado", 0) or 0,
            "saldo_kwh":             dados.get("saldo_kwh", 0) or 0,
            "excedente_kwh":         dados.get("excedente_kwh", 0) or 0,
            "data_leitura_anterior": dados.get("data_leitura_anterior", "") or "",
            "data_leitura_atual":    dados.get("data_leitura_atual", "") or "",
            "n_dias":                dados.get("n_dias", 0) or 0,
            "data_registro":         dados.get("data_registro", ""),
            "origem":                dados.get("origem", "manual"),
            "fatura_pdf":            dados.get("fatura_pdf", ""),
        })

    def _ord_key(item):
        try:
            p = item["mes_ref"].split("/")
            return int(p[1]) * 100 + int(p[0])
        except:
            return 0
    leituras_mensais.sort(key=_ord_key, reverse=True)
    total_kwh_mensal = sum(l["kwh_gerado"] for l in leituras_mensais)

    graf_recentes = registros_usina[-30:]
    graf_labels   = [r.get("data", "")[-5:] for r in graf_recentes]
    graf_valores  = [(r.get("kwh", 0) or 0) for r in graf_recentes]

    # ── Rateio ───────────────────────────────────────────────
    prox_leitura    = usina["proxima_leitura"]
    data_rateio     = ""
    dias_para_rateio = None
    status_rateio   = ""
    if prox_leitura:
        try:
            prox_date = datetime.strptime(prox_leitura, "%d/%m/%Y").date()
            hoje      = datetime.now().date()
            dr        = prox_date - timedelta(days=8)
            data_rateio      = dr.strftime("%d/%m/%Y")
            dias_para_rateio = (dr - hoje).days
            if   dias_para_rateio <= 0: status_rateio = "atrasado"
            elif dias_para_rateio <= 3: status_rateio = "urgente"
            elif dias_para_rateio <= 8: status_rateio = "proximo"
            else:                       status_rateio = "ok"
        except:
            pass

    total_rateio_pct  = sum((c.get("rateio_pct", 0) or 0) for c in vinculados.values())
    geracao_mensal_prev = usina["geracao_media_mensal"]

    # Base de kWh para rateio:
    #   Prioridade: fatura do ciclo atual > registros diarios > previsao mensal.
    #   A fatura "cobre" o ciclo atual se sua data_leitura_atual >= ultima data
    #   dos registros diarios (ex: fatura com leitura 13/04 cobre diarios ate 13/04).
    tem_fatura_usina = False
    mes_fatura_usina = ""
    geracao_real_kwh = 0

    if leituras_mensais:
        ultimo = leituras_mensais[0]
        geracao_real_kwh = ultimo.get("kwh_gerado", 0) or 0
        data_leit_atu_fatura = ultimo.get("data_leitura_atual", "")

        # Verifica se a fatura mais recente cobre o ciclo dos registros diarios
        fatura_cobre_ciclo = False
        if geracao_real_kwh > 0 and data_leit_atu_fatura and data_fim:
            try:
                dt_fatura = datetime.strptime(data_leit_atu_fatura, "%d/%m/%Y")
                dt_fim = datetime.strptime(data_fim, "%d/%m/%Y")
                fatura_cobre_ciclo = dt_fatura >= dt_fim
            except Exception:
                pass

        if fatura_cobre_ciclo:
            tem_fatura_usina = True
            mes_fatura_usina = ultimo.get("mes_ref", "")
            base_kwh_rateio = geracao_real_kwh
        elif dias_registrados > 0:
            base_kwh_rateio = total_kwh_periodo
        else:
            if geracao_real_kwh > 0:
                tem_fatura_usina = True
                mes_fatura_usina = ultimo.get("mes_ref", "")
                base_kwh_rateio = geracao_real_kwh
            else:
                base_kwh_rateio = geracao_mensal_prev
    elif dias_registrados > 0:
        base_kwh_rateio = total_kwh_periodo
    else:
        base_kwh_rateio = geracao_mensal_prev

    # Alocacao por cliente para o painel de rateio
    rateio_clientes = []
    for uc, c in vinculados.items():
        pct = c.get("rateio_pct", 0) or 0
        kwh_alocado = base_kwh_rateio * (pct / 100) if pct > 0 and base_kwh_rateio > 0 else 0
        rateio_clientes.append({
            "uc": uc, "nome": c.get("nome", ""), "rateio_pct": pct,
            "kwh_alocado": round(kwh_alocado, 2),
            "proxima_leitura": c.get("proxima_leitura", ""),
        })
    rateio_clientes.sort(key=lambda x: -x["rateio_pct"])

    return render_template("usina_detalhe.html",
        usina=usina, uid=uid, id_usina=id_usina,
        vinculados=vinculados, nao_vinculados=nao_vinculados,
        registros=registros_usina,
        total_kwh=total_kwh_periodo, dias_registrados=dias_registrados,
        media_diaria=media_diaria, estimativa_periodo=estimativa_periodo,
        data_inicio=data_inicio, data_fim=data_fim,
        leituras_mensais=leituras_mensais,
        total_kwh_mensal=total_kwh_mensal,
        graf_labels=json.dumps(graf_labels), graf_valores=json.dumps(graf_valores),
        prox_leitura=prox_leitura, data_rateio=data_rateio,
        dias_para_rateio=dias_para_rateio, status_rateio=status_rateio,
        total_rateio_pct=round(total_rateio_pct, 2),
        geracao_mensal_prev=geracao_mensal_prev,
        base_kwh_rateio=round(base_kwh_rateio, 1),
        tem_fatura_usina=tem_fatura_usina,
        mes_fatura_usina=mes_fatura_usina,
        rateio_clientes=rateio_clientes,
        fmt=_fmt_brl
    )

# USINAS - Registrar geracao diaria
@app.route("/usinas/geracao/<uid>", methods=["POST"])
def registrar_geracao(uid):
    geracao = carregar_geracao()
    if uid not in geracao:
        geracao[uid] = []
    data = request.form.get("data", "").strip()
    kwh = float(request.form.get("kwh", "0").replace(",", "."))
    obs = request.form.get("obs", "").strip()
    if not data or kwh <= 0:
        flash("Data e kWh sao obrigatorios!", "danger")
        return redirect(url_for("usina_ver", uid=uid))
    # Evita duplicata
    for r in geracao[uid]:
        if r.get("data") == data:
            r["kwh"] = kwh
            r["obs"] = obs
            salvar_geracao(geracao)
            flash(f"Geracao de {data} atualizada: {kwh:.1f} kWh", "success")
            return redirect(url_for("usina_ver", uid=uid))
    geracao[uid].append({"data": data, "kwh": kwh, "obs": obs})
    salvar_geracao(geracao)
    flash(f"Geracao registrada: {data} — {kwh:.1f} kWh", "success")
    return redirect(url_for("usina_ver", uid=uid))

# USINAS - Remover registro de geracao
@app.route("/usinas/geracao/<uid>/remover/<path:data>")
def remover_geracao(uid, data):
    geracao = carregar_geracao()
    if uid in geracao:
        geracao[uid] = [r for r in geracao[uid] if r.get("data") != data]
        salvar_geracao(geracao)
        flash(f"Registro de {data} removido.", "warning")
    return redirect(url_for("usina_ver", uid=uid))

# USINAS - Registrar geracao mensal (a partir da fatura da unidade geradora)
@app.route("/usinas/geracao_mensal/<uid>", methods=["POST"])
def registrar_geracao_mensal(uid):
    usinas = carregar_usinas()
    # Aceita tanto uid legado quanto id_usina inteiro (novo)
    if uid not in usinas:
        try:
            int(uid)   # uid numerico e valido (nova usina)
        except ValueError:
            flash("Usina nao encontrada!", "danger"); return redirect(url_for("usinas_lista"))

    # Upload da fatura (obrigatorio para extracao automatica)
    pdf_path = ""
    if "fatura_pdf" in request.files:
        f = request.files["fatura_pdf"]
        if f and f.filename:
            # Salva temporariamente para extrair dados
            fname_tmp = f"usina_{uid}_fatura_tmp.pdf"
            pdf_path = os.path.join(UPLOAD_FOLDER, fname_tmp)
            f.save(pdf_path)

    if not pdf_path:
        flash("Anexe a fatura em PDF!", "danger")
        return redirect(url_for("usina_ver", uid=uid))

    # Extrai todos os dados do PDF automaticamente
    kwh = 0
    data_ant = ""
    data_atu = ""
    n_dias = 0
    mes_ref = ""

    try:
        extraido = extrair_equatorial(pdf_path, verbose=False)
        # Para usinas: prioriza GERACAO CICLO (geracao real da usina)
        # Se nao houver, usa consumo_kwh como fallback
        kwh_geracao = extraido.get("geracao_ciclo_kwh", 0) or 0
        kwh_consumo = extraido.get("consumo_kwh", 0) or 0
        kwh = kwh_geracao if kwh_geracao > 0 else kwh_consumo
        data_ant = extraido.get("data_leitura_anterior", "") or ""
        data_atu = extraido.get("data_leitura_atual", "") or ""
        n_dias = extraido.get("n_dias", 0) or 0
        mes_ref = _norm_mes(extraido.get("mes_referencia", "") or "")
        saldo_kwh = extraido.get("saldo_kwh", 0) or 0
        excedente_kwh = extraido.get("excedente_recebido_kwh", 0) or 0

        # Salva proxima leitura e saldo — legado e nova tabela
        _prox_ext = extraido.get("proxima_leitura", "")
        _prox_ext_iso = None
        if _prox_ext:
            # Converte para ISO se vem em DD/MM/YYYY do PDF
            try:
                _prox_ext_iso = _data_br_para_iso(_prox_ext)
            except Exception:
                _prox_ext_iso = None  # descarta se nao conseguiu converter

        if uid in usinas:
            if _prox_ext:
                usinas[uid]["proxima_leitura"] = _prox_ext
            usinas[uid]["saldo_kwh"] = saldo_kwh
            salvar_usinas(usinas)
        # Persiste tambem em tb_usinas (para usinas novas e futuras)
        try:
            from db import tb_get_usina_por_nome, tb_save_usina
            _nome_u = usinas.get(uid, {}).get("nome", "")
            _tb_u   = tb_get_usina_por_nome(_nome_u) if _nome_u else None
            if not _tb_u:
                # uid numerico → busca direta
                from db import tb_get_usina
                try: _tb_u = tb_get_usina(int(uid))
                except: pass
            if _tb_u:
                _upd = {"id_usina": _tb_u["id_usina"], "qtd_saldo_kwh": saldo_kwh}
                if _prox_ext_iso:
                    _upd["dt_proxima_leitura"] = _prox_ext_iso
                tb_save_usina(_upd)
        except Exception as _e:
            app.logger.warning(f"[geracao_mensal] Falha ao salvar tb_usinas: {_e}")

        _src = "Geracao Ciclo" if kwh_geracao > 0 else "Consumo"
        flash(f"Dados extraidos: {mes_ref} — {_src}: {kwh:,.0f} kWh, Saldo: {saldo_kwh:,.2f} kWh, {n_dias} dias", "success")
    except Exception as e:
        flash(f"Nao foi possivel extrair do PDF: {e}", "danger")
        return redirect(url_for("usina_ver", uid=uid))

    if not mes_ref:
        flash("Mes de referencia nao encontrado no PDF!", "danger")
        return redirect(url_for("usina_ver", uid=uid))

    # Renomeia arquivo para nome definitivo com mes
    fname_final = f"usina_{uid}_geracao_{mes_ref.replace('/', '')}.pdf"
    pdf_final = os.path.join(UPLOAD_FOLDER, fname_final)
    try:
        if pdf_path != pdf_final:
            shutil.move(pdf_path, pdf_final)
            pdf_path = pdf_final
    except:
        pass

    # Calcula nº de dias se nao veio da extracao
    if n_dias == 0:
        try:
            if data_ant and data_atu:
                d1 = datetime.strptime(data_ant, "%d/%m/%Y")
                d2 = datetime.strptime(data_atu, "%d/%m/%Y")
                n_dias = (d2 - d1).days
        except:
            pass

    geracao = carregar_geracao_mensal()
    if uid not in geracao:
        geracao[uid] = {}

    entrada = {
        "kwh_gerado": kwh,
        "data_leitura_anterior": data_ant,
        "data_leitura_atual": data_atu,
        "n_dias": n_dias,
        "saldo_kwh": saldo_kwh,
        "excedente_kwh": excedente_kwh,
        "data_registro": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "origem": "extraido",
        "fatura_pdf": pdf_path,
    }

    geracao[uid][mes_ref] = entrada
    salvar_geracao_mensal(geracao)
    flash(f"Fatura de {mes_ref} registrada: {kwh:,.0f} kWh em {n_dias} dias | Saldo: {saldo_kwh:,.2f} kWh", "success")
    return redirect(url_for("usina_ver", uid=uid))

# USINAS - Atualizar proxima leitura manualmente
@app.route("/usinas/proxima_leitura/<uid>", methods=["POST"])
def usina_proxima_leitura(uid):
    from db import tb_get_usina_por_nome, tb_get_usina, tb_save_usina
    prox  = request.form.get("proxima_leitura", "").strip()
    usinas = carregar_usinas()

    # Atualiza legado (se uid existir no sistema antigo)
    if uid in usinas:
        if prox:
            usinas[uid]["proxima_leitura"] = prox
        else:
            usinas[uid].pop("proxima_leitura", None)
        salvar_usinas(usinas)

    # Converte DD/MM/YYYY → YYYY-MM-DD para o Supabase
    prox_iso = None
    if prox:
        try:
            from datetime import datetime as _dt
            prox_iso = _dt.strptime(prox, "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            try:
                prox_iso = _dt.strptime(prox, "%Y-%m-%d").strftime("%Y-%m-%d")
            except ValueError:
                pass

    # Atualiza tb_usinas (novas tabelas)
    try:
        tb_u = None
        try: tb_u = tb_get_usina(int(uid))
        except (ValueError, TypeError): pass
        if not tb_u:
            nome = usinas.get(uid, {}).get("nome", "")
            tb_u = tb_get_usina_por_nome(nome) if nome else None
        if tb_u:
            tb_save_usina({"id_usina": tb_u["id_usina"],
                           "dt_proxima_leitura": prox_iso})
        else:
            app.logger.warning(f"[proxima_leitura] Usina uid={uid} nao encontrada em tb_usinas")
    except Exception as e:
        app.logger.warning(f"[proxima_leitura] Falha ao salvar tb_usinas: {e}")
        flash(f"Erro ao salvar proxima leitura: {e}", "danger")
        return redirect(url_for("usina_ver", uid=uid))

    if prox:
        flash(f"Proxima leitura atualizada: {prox}", "success")
    else:
        flash("Proxima leitura removida.", "warning")
    return redirect(url_for("usina_ver", uid=uid))

# USINAS - Remover geracao mensal
@app.route("/usinas/geracao_mensal/<uid>/remover/<path:mes_ref>")
def remover_geracao_mensal(uid, mes_ref):
    mes_norm = _norm_mes(mes_ref)
    geracao = carregar_geracao_mensal()
    if uid in geracao and mes_norm in geracao[uid]:
        del geracao[uid][mes_norm]
        salvar_geracao_mensal(geracao)
        flash(f"Geracao mensal de {mes_norm} removida.", "warning")
    return redirect(url_for("usina_ver", uid=uid))

# USINAS - Vincular cliente COM RATEIO
@app.route("/usinas/vincular/<uid>", methods=["POST"])
def vincular_cliente(uid):
    from db import (tb_get_cliente_por_uc, tb_get_usina_por_nome,
                    tb_get_usina, tb_save_cliente_usina)
    uc = request.form.get("uc", "").strip()
    rateio = float(request.form.get("rateio_pct", "0").replace(",", ".") or "0")
    if not uc:
        flash("Selecione um cliente!", "danger")
        return redirect(url_for("usina_ver", uid=uid))

    pct_pct = rateio * 100 if rateio <= 1 else rateio

    # ── Resolve usina nas novas tabelas (int uid) ou via nome (legado) ──
    tb_usina = None
    try:
        tb_usina = tb_get_usina(int(uid))
    except (ValueError, TypeError):
        pass
    if not tb_usina:
        try:
            usinas_leg = carregar_usinas()
            nome_usina = usinas_leg.get(uid, {}).get("nome", "")
            if nome_usina:
                tb_usina = tb_get_usina_por_nome(nome_usina)
        except Exception as e:
            app.logger.warning(f"[vincular] Falha ao resolver usina legada: {e}")

    # ── Resolve cliente nas novas tabelas ──
    tb_cliente = tb_get_cliente_por_uc(uc)

    # ── Salva vinculo na tabela normalizada (principal) ──
    if tb_usina and tb_cliente:
        try:
            tb_save_cliente_usina(
                tb_cliente["id_cliente"],
                tb_usina["id_usina"],
                {"pct_rateio": round(pct_pct, 2)},
            )
        except Exception as e:
            flash(f"Erro ao vincular: {e}", "danger")
            app.logger.error(f"[vincular] tb_save_cliente_usina: {e}")
            return redirect(url_for("usina_ver", uid=uid))
    else:
        flash("Cliente ou usina nao encontrados no sistema!", "danger")
        return redirect(url_for("usina_ver", uid=uid))


    nome_cliente = (tb_cliente.get("desc_nome") or uc)
    flash(f"Cliente {nome_cliente} vinculado com {rateio}%!", "success")
    return redirect(url_for("rateio_dashboard", uid=uid))

# USINAS - Atualizar % de rateio
@app.route("/usinas/rateio/atualizar/<uid>", methods=["POST"])
def rateio_atualizar(uid):
    """Atualiza pct_rateio dos clientes vinculados a usina.

    Otimizado: antes fazia ~170 HTTP requests (PATCH em todos os 129 clientes
    + GET+PATCH por vinculado). Agora faz 1 SELECT inicial + 1 PATCH por
    vinculado alterado.
    """
    from db import (tb_get_clientes_da_usina, tb_get_usina_por_nome,
                    tb_get_usina, tb_carregar_clientes, _db)

    usinas_leg = carregar_usinas()
    nome_u = usinas_leg.get(uid, {}).get("nome", "")
    tb_u   = tb_get_usina_por_nome(nome_u) if nome_u else None
    if not tb_u:
        try: tb_u = tb_get_usina(int(uid))
        except: pass
    if not tb_u:
        flash("Usina nao encontrada", "error")
        return redirect(url_for("rateio_dashboard", uid=uid))

    id_usina    = tb_u["id_usina"]
    vinculos    = tb_get_clientes_da_usina(id_usina)
    clientes_tb = {c["id_cliente"]: c for c in tb_carregar_clientes()}

    total = 0.0
    atualizados = 0
    for v in vinculos:
        id_c = v.get("id_cliente")
        uc   = clientes_tb.get(id_c, {}).get("cod_uc", "")
        if not uc:
            continue
        novo_pct_raw = request.form.get(f"rateio_{uc}", "")
        if not novo_pct_raw:
            total += float(v.get("pct_rateio") or 0)
            continue
        pct = round(float(novo_pct_raw.replace(",", ".") or "0"), 2)
        total += pct
        # PATCH direto pelo id do vinculo — sem GET previo
        if abs(pct - float(v.get("pct_rateio") or 0)) > 0.001:
            _db().patch("tb_cliente_usina", {"id": v["id"]}, {"pct_rateio": pct})
            atualizados += 1

    if abs(total - 100) > 0.01:
        flash(f"Atencao: rateio soma {total:.2f}% (deveria ser 100%)", "warning")
    else:
        flash(f"Rateio atualizado ({atualizados} alteracoes). Total: 100%", "success")

    return redirect(url_for("rateio_dashboard", uid=uid))

# USINAS - Atualizar saldo de um cliente
# USINAS - Conferir saldo (saldo confirmado pelo usuario + observacao + data)
@app.route("/usinas/conferir_saldo/<uid>/<uc>", methods=["POST"])
def conferir_saldo(uid, uc):
    """Confirma manualmente o saldo de creditos de um cliente em uma usina.

    Salva em tb_cliente_usina:
      - qtd_saldo_kwh         = valor conferido
      - dt_saldo_conferido    = data de hoje
      - desc_saldo_obs        = observacao livre
    """
    from db import (tb_get_cliente_por_uc, tb_get_usina_por_nome,
                    tb_get_usina, tb_save_cliente_usina)
    from datetime import date as _date
    saldo_conferido = float(
        request.form.get("saldo_conferido", "0").replace(",", ".") or "0"
    )
    obs = (request.form.get("obs", "") or "").strip()[:500]

    try:
        usinas_leg = carregar_usinas()
        nome_u = usinas_leg.get(uid, {}).get("nome", "")
        tb_u   = tb_get_usina_por_nome(nome_u) if nome_u else None
        if not tb_u:
            try: tb_u = tb_get_usina(int(uid))
            except: pass
        tb_c = tb_get_cliente_por_uc(uc)
        if tb_u and tb_c:
            tb_save_cliente_usina(
                tb_c["id_cliente"], tb_u["id_usina"],
                {
                    "qtd_saldo_kwh":      saldo_conferido,
                    "dt_saldo_conferido": _date.today().isoformat(),
                    "desc_saldo_obs":     obs,
                },
            )
            flash(f"Saldo de {tb_c.get('desc_nome', uc)} conferido em "
                  f"{saldo_conferido:.1f} kWh", "success")
        else:
            flash("Cliente ou usina nao encontrado!", "danger")
    except Exception as e:
        app.logger.warning(f"[conferir_saldo] Falha: {e}")
        flash(f"Erro ao salvar conferencia: {e}", "danger")

    mes_q = request.form.get("mes_sel", "")
    return redirect(
        url_for("rateio_dashboard", uid=uid) + (f"?mes={mes_q}" if mes_q else "")
    )


@app.route("/usinas/saldo/<uid>/<uc>", methods=["POST"])
def atualizar_saldo(uid, uc):
    from db import (tb_get_cliente_por_uc, tb_get_usina_por_nome,
                    tb_get_usina, tb_save_cliente_usina)
    saldo = float(request.form.get("saldo_kwh", "0").replace(",", ".") or "0")
    kwh_real = float(request.form.get("kwh_real", "0").replace(",", ".") or "0")
    # Legado
    clientes = carregar_clientes()
    if uc in clientes:
        clientes[uc]["saldo_kwh"] = saldo
        clientes[uc]["kwh_creditado_real"] = kwh_real
        salvar_clientes(clientes)
        flash(f"Saldo de {clientes[uc].get('nome', uc)} atualizado!", "success")
    # Novas tabelas
    try:
        usinas_leg = carregar_usinas()
        nome_u = usinas_leg.get(uid, {}).get("nome", "")
        tb_u   = tb_get_usina_por_nome(nome_u) if nome_u else None
        if not tb_u:
            try: tb_u = tb_get_usina(int(uid))
            except: pass
        tb_c = tb_get_cliente_por_uc(uc)
        if tb_u and tb_c:
            tb_save_cliente_usina(tb_c["id_cliente"], tb_u["id_usina"],
                                  {"qtd_saldo_kwh": saldo,
                                   "qtd_kwh_creditado": kwh_real})
    except Exception as e:
        app.logger.warning(f"[atualizar_saldo] Falha tb_: {e}")
    return redirect(url_for("rateio_dashboard", uid=uid))

# ══════════════════════════════════════════════════════════════
# RATEIO CONSOLIDADO — visao agregada de todas as usinas
# ══════════════════════════════════════════════════════════════
def _calcular_resumo_rateio_consolidado(mes_sel: str = ""):
    """Para um mes de referencia, calcula uma linha de resumo por usina
    (geracao, compensado, saldo, n_clientes, status, risco) e identifica
    clientes 'fora da curva' (top excecoes).

    Reaproveita a mesma logica de rateio_dashboard para que os numeros
    da tela consolidada batam com a tela individual da usina.
    """
    from db import tb_get_clientes_da_usina, tb_carregar_clientes

    usinas = carregar_usinas()
    todos_clientes = tb_carregar_clientes()
    clientes_id_map = {c["id_cliente"]: c for c in todos_clientes}
    geracao_mensal_all = carregar_geracao_mensal()
    geracao_diaria_all = carregar_geracao()
    historico = carregar_faturas()
    rateios_all = carregar_rateios_mensais()

    # Lista de meses disponiveis = uniao de todos os meses com geracao + mes atual + proximo mes
    _now = datetime.now()
    mes_atual = f"{_now.month}/{_now.year}"
    _prox_n   = _now.month + 1 if _now.month < 12 else 1
    _prox_ano = _now.year if _now.month < 12 else _now.year + 1
    prox_mes  = f"{_prox_n}/{_prox_ano}"
    meses_set = {mes_atual, prox_mes}
    for _uid, _meses in geracao_mensal_all.items():
        meses_set.update(_meses.keys())

    def _sort_mes(m):
        try:
            p = m.split("/")
            return int(p[1]) * 100 + int(p[0])
        except Exception:
            return 0
    meses_disponiveis = sorted(meses_set, key=_sort_mes, reverse=True)

    if not mes_sel:
        mes_sel = mes_atual
    mes_norm = _norm_mes(mes_sel)

    def _norm_mes_cmp(m):
        if not m or "/" not in m:
            return ""
        p = m.split("/")
        return f"{int(p[0])}/{p[1]}"

    def _prox_mes(m):
        if not m or "/" not in m:
            return m
        p = m.split("/")
        mes_n, ano_n = int(p[0]), int(p[1])
        return f"1/{ano_n+1}" if mes_n == 12 else f"{mes_n+1}/{ano_n}"

    linhas = []
    excecoes = []
    total_geracao = 0.0
    total_compensado = 0.0
    total_clientes = 0
    n_alerta_falta = 0
    n_alerta_sobra = 0
    n_balanceado = 0
    n_estimativa = 0
    n_protocolo_ok = 0

    # Tolerancia (kWh) para considerar saldo equilibrado
    TOL_FALTA = 50    # compensado pode ser ate +50 kWh acima da geracao
    TOL_SOBRA_PCT = 80  # se compensado < 80% da geracao = sobra cronica

    for uid, u in usinas.items():
        try:
            id_usina = int(uid)
        except (ValueError, TypeError):
            continue

        # Vinculos ativos
        vinculos = tb_get_clientes_da_usina(id_usina)
        clientes_da_usina = []
        rateio_total = 0.0
        for v in vinculos:
            id_c = v.get("id_cliente")
            c_tb = clientes_id_map.get(id_c, {})
            cod_uc = c_tb.get("cod_uc", "")
            if not cod_uc:
                continue
            pct = v.get("pct_rateio", 0) or 0
            rateio_total += pct
            clientes_da_usina.append({
                "id_cliente": id_c, "uc": cod_uc,
                "nome": c_tb.get("desc_nome", cod_uc),
                "rateio_pct": pct,
            })

        # Geracao do mes (real ou estimada)
        dados_ger = geracao_mensal_all.get(uid, {}).get(mes_sel, {}) or \
                    geracao_mensal_all.get(uid, {}).get(mes_norm, {})
        kwh_gerado_real = dados_ger.get("kwh_gerado", 0) or 0
        saldo_acumulado = dados_ger.get("saldo_kwh", 0) or 0
        data_leitura_usina = dados_ger.get("data_leitura_atual", "") or ""
        tem_geracao_real = kwh_gerado_real > 0

        registros_diarios = geracao_diaria_all.get(uid, [])
        total_diario = sum((r.get("kwh", 0) or 0) for r in registros_diarios)
        dias_reg = len(registros_diarios)
        ger_diaria_prev = u.get("geracao_prevista_diaria", 0) or 0
        media_diaria = total_diario / dias_reg if dias_reg > 0 else ger_diaria_prev
        estimativa_30d = media_diaria * 30
        ger_prev_mensal = u.get("geracao_media_mensal", 0) or 0

        if tem_geracao_real:
            base_kwh = kwh_gerado_real
        elif dias_reg > 0:
            base_kwh = estimativa_30d
        else:
            base_kwh = ger_prev_mensal

        # Confrontacao por cliente
        compensado_total = 0.0
        n_com_fatura = 0
        for cli in clientes_da_usina:
            # REGRA: fatura que compensa = leitura POSTERIOR a leitura da usina (1a apos)
            kwh_compensado = 0
            tem_fatura = False
            def _dia_br_c(s):
                s = str(s or "").strip()
                for _f in ("%d/%m/%Y", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(s[:10], _f).date()
                    except ValueError:
                        continue
                return None
            _leit_u = _dia_br_c(data_leitura_usina)
            _uc_lst = str(cli["uc"]).lstrip("0")
            _cands = []
            for item in historico:
                if str(item.get("uc", "")).lstrip("0") != _uc_lst:
                    continue
                _dl = _dia_br_c(item.get("data_leitura_atual", ""))
                if _leit_u and _dl and _dl > _leit_u:
                    _cands.append((_dl, item))
            if _cands:
                _cands.sort(key=lambda x: x[0])
                kwh_compensado = _cands[0][1].get("compensado_kwh", 0) or 0
                tem_fatura = True

            if tem_fatura:
                n_com_fatura += 1
                compensado_total += kwh_compensado

            # Excecao: cliente fora da curva (>= 20% acima/abaixo do esperado)
            kwh_esperado = base_kwh * (cli["rateio_pct"] / 100) if cli["rateio_pct"] > 0 else 0
            if tem_fatura and kwh_esperado > 0:
                diferenca = kwh_compensado - kwh_esperado
                pct_dif = abs(diferenca) / kwh_esperado * 100
                if pct_dif >= 20:
                    excecoes.append({
                        "uc": cli["uc"], "nome": cli["nome"],
                        "usina_uid": uid, "usina_nome": u.get("nome", ""),
                        "rateio_pct": round(cli["rateio_pct"], 2),
                        "kwh_esperado": round(kwh_esperado, 1),
                        "kwh_compensado": round(kwh_compensado, 1),
                        "diferenca": round(diferenca, 1),
                        "pct_dif": round(pct_dif, 1),
                        "tipo": "excedente" if diferenca > 0 else "deficit",
                    })

        saldo_mes = base_kwh - compensado_total

        # Ciclo
        if not tem_geracao_real:
            ciclo_status = "estimativa"
            n_estimativa += 1
        elif n_com_fatura == 0:
            ciclo_status = "aguardando"
        elif n_com_fatura < len(clientes_da_usina):
            ciclo_status = "parcial"
        else:
            ciclo_status = "completo"

        # Risco do saldo
        risco = "ok"
        if rateio_total > 0 and abs(rateio_total - 100) > 0.5:
            risco = "rateio_invalido"
        elif tem_geracao_real and n_com_fatura > 0 and base_kwh > 0:
            if compensado_total > base_kwh + TOL_FALTA:
                risco = "falta"
                n_alerta_falta += 1
            elif n_com_fatura == len(clientes_da_usina):
                pct_uso = (compensado_total / base_kwh) * 100
                if pct_uso < TOL_SOBRA_PCT:
                    risco = "sobra"
                    n_alerta_sobra += 1
                else:
                    risco = "ok"
                    n_balanceado += 1
            else:
                risco = "ok"

        # Protocolo
        rateio_mes = rateios_all.get(uid, {}).get(mes_norm, {})
        tem_protocolo = bool(rateio_mes.get("protocolo", ""))
        if tem_protocolo:
            n_protocolo_ok += 1

        linhas.append({
            "uid": uid,
            "nome": u.get("nome", uid),
            "uc_geradora": u.get("uc_geradora", ""),
            "base_kwh": round(base_kwh, 1),
            "tem_geracao_real": tem_geracao_real,
            "kwh_gerado_real": round(kwh_gerado_real, 1),
            "compensado_total": round(compensado_total, 1),
            "saldo_mes": round(saldo_mes, 1),
            "saldo_acumulado": round(saldo_acumulado, 1),
            "n_clientes": len(clientes_da_usina),
            "n_com_fatura": n_com_fatura,
            "rateio_total_pct": round(rateio_total, 2),
            "ciclo_status": ciclo_status,
            "risco": risco,
            "tem_protocolo": tem_protocolo,
            "protocolo": rateio_mes.get("protocolo", ""),
            "data_leitura": data_leitura_usina,
        })

        total_geracao += base_kwh
        total_compensado += compensado_total
        total_clientes += len(clientes_da_usina)

    # Ordenacao: cadastro invalido primeiro, depois falta, depois sobra, depois ok
    _ordem = {"rateio_invalido": 0, "falta": 1, "sobra": 2, "ok": 3}
    linhas.sort(key=lambda x: (_ordem.get(x["risco"], 9), x["nome"]))

    excecoes.sort(key=lambda e: -e["pct_dif"])
    excecoes = excecoes[:8]

    return {
        "mes_sel": mes_sel,
        "meses_disponiveis": meses_disponiveis,
        "linhas": linhas,
        "totais": {
            "geracao": round(total_geracao, 1),
            "compensado": round(total_compensado, 1),
            "saldo_mes": round(total_geracao - total_compensado, 1),
            "n_usinas": len(linhas),
            "n_clientes": total_clientes,
            "n_alerta_falta": n_alerta_falta,
            "n_alerta_sobra": n_alerta_sobra,
            "n_balanceado": n_balanceado,
            "n_estimativa": n_estimativa,
            "n_protocolo_ok": n_protocolo_ok,
        },
        "excecoes": excecoes,
    }


@app.route("/rateio")
def rateio_consolidado():
    """Visao consolidada de rateio: todas as usinas em uma so tabela."""
    mes_sel = request.args.get("mes", "")
    resumo = _calcular_resumo_rateio_consolidado(mes_sel)
    return render_template("rateio_consolidado.html", **resumo)


# ══════════════════════════════════════════════════════════════
# RATEIO PLANEJAR — previsao de consumo + montagem assistida do %
# ══════════════════════════════════════════════════════════════
def _historico_consumo_cliente(uc, historico, n_meses=6):
    """Retorna lista dos ultimos N meses de consumo de um cliente.
    Cada item: {mes, mes_ord, consumo, compensado, nao_compensado}.
    Ordenada do mais recente pro mais antigo.
    """
    uc_norm = str(uc).lstrip("0")
    out = []
    for item in historico:
        h_uc = str(item.get("uc", "")).lstrip("0")
        if h_uc != uc_norm:
            continue
        mes = (item.get("mes_referencia", "") or "").strip()
        if not mes or "/" not in mes:
            continue
        try:
            p = mes.split("/")
            mes_ord = int(p[1]) * 100 + int(p[0])
        except Exception:
            continue
        out.append({
            "mes": mes,
            "mes_ord": mes_ord,
            "consumo": float(item.get("consumo_kwh", 0) or 0),
            "compensado": float(item.get("compensado_kwh", 0) or 0),
            "nao_compensado": float(item.get("nao_compensado_kwh", 0) or 0),
        })
    out.sort(key=lambda c: -c["mes_ord"])
    # Deduplica por mes (caso haja varias faturas do mesmo mes)
    visto = set()
    final = []
    for c in out:
        if c["mes_ord"] in visto:
            continue
        visto.add(c["mes_ord"])
        final.append(c)
    return final[:n_meses]


def _prever_consumo(consumos, modo="max3m", n_std=1.0, margem_pct=10.0):
    """Calcula previsao de consumo do cliente para o proximo mes.

    Args:
        consumos: lista do _historico_consumo_cliente (mais recente primeiro)
        modo: 'max3m' (maximo dos ultimos 3 meses)
              | 'avg_std' (media + N * desvio padrao)
        n_std: numero de desvios padrao a somar (so usado em avg_std)
        margem_pct: margem de seguranca em % (10 = +10%)

    Returns:
        dict {previsao, base, media, maximo, std, qtd_meses, modo}
    """
    valores = [c["consumo"] for c in consumos[:3 if modo == "max3m" else 6]
               if c["consumo"] > 0]
    if not valores:
        return {"previsao": 0.0, "base": 0.0, "media": 0.0, "maximo": 0.0,
                "std": 0.0, "qtd_meses": 0, "modo": modo}

    n = len(valores)
    media = sum(valores) / n
    maximo = max(valores)
    if n >= 2:
        var = sum((v - media) ** 2 for v in valores) / (n - 1)
        std = var ** 0.5
    else:
        std = 0.0

    if modo == "max3m":
        base = maximo
    elif modo == "avg_std":
        base = media + n_std * std
    else:
        base = media  # fallback

    previsao = base * (1 + margem_pct / 100.0)
    return {
        "previsao":  round(previsao, 1),
        "base":      round(base, 1),
        "media":     round(media, 1),
        "maximo":    round(maximo, 1),
        "std":       round(std, 1),
        "qtd_meses": n,
        "modo":      modo,
    }


# ══════════════════════════════════════════════════════════════
# RATEIO PLANEJAR — assistente de montagem de rateio para proximo mes
# ══════════════════════════════════════════════════════════════
@app.route("/usinas/rateio/<uid>/planejar")
def rateio_planejar(uid):
    return redirect(url_for("rateio_dashboard", uid=uid))

def rateio_planejar_old(uid):
    """Tela de planejamento do rateio do proximo mes.

    Para cada cliente vinculado a usina:
      - Carrega historico dos ultimos 6 meses de consumo
      - Sugere previsao de consumo (max3m | avg_std) + margem de seguranca
      - Calcula % rateio sugerido (previsao / soma_previsoes)
    Usuario ajusta valores e clica em "Aplicar rateio" para salvar.
    """
    from db import (tb_get_usina, tb_get_usina_por_nome,
                    tb_get_clientes_da_usina, tb_carregar_clientes)

    # Resolve usina (igual ao rateio_dashboard)
    usinas_leg = carregar_usinas()
    try:
        id_usina = int(uid)
        usina_tb = tb_get_usina(id_usina)
    except ValueError:
        nome_u = usinas_leg.get(uid, {}).get("nome", "")
        usina_tb = tb_get_usina_por_nome(nome_u) if nome_u else None
        id_usina = usina_tb["id_usina"] if usina_tb else None
    if not usina_tb:
        if uid not in usinas_leg:
            flash("Usina nao encontrada!", "danger"); return redirect(url_for("usinas_lista"))
        usina_tb = {}
    uid_leg = next((u for u, d in usinas_leg.items()
                    if d.get("nome") == usina_tb.get("desc_nome")), uid)
    usina = {
        "id_usina":             usina_tb.get("id_usina"),
        "nome":                 usina_tb.get("desc_nome", usinas_leg.get(uid_leg, {}).get("nome", "")),
        "uc_geradora":          usina_tb.get("cod_uc_geradora", usinas_leg.get(uid_leg, {}).get("uc_geradora", "")),
        "geracao_media_mensal": usina_tb.get("qtd_geracao_media_mensal") or usinas_leg.get(uid_leg, {}).get("geracao_media_mensal", 0) or 0,
        "qtd_dia_leitura":      usina_tb.get("qtd_dia_leitura"),
        "dt_proxima_leitura":   usina_tb.get("dt_proxima_leitura"),
    }

    # ── Calcula deadline (D-7 antes da próxima leitura) ──
    from datetime import date as _date_t, timedelta as _td_t
    _hoje = _date_t.today()
    dt_prox_leitura_obj = None
    if usina["dt_proxima_leitura"]:
        try:
            dt_prox_leitura_obj = _date_t.fromisoformat(str(usina["dt_proxima_leitura"])[:10])
        except (ValueError, TypeError):
            pass
    if not dt_prox_leitura_obj and usina.get("qtd_dia_leitura"):
        # Fallback: usa qtd_dia_leitura do mês corrente ou próximo
        try:
            dia = int(usina["qtd_dia_leitura"])
            ano_t, mes_t = _hoje.year, _hoje.month
            try:
                cand = _date_t(ano_t, mes_t, dia)
                if cand < _hoje:
                    # passou — vai pro próximo mês
                    if mes_t == 12: ano_t += 1; mes_t = 1
                    else: mes_t += 1
                    cand = _date_t(ano_t, mes_t, dia)
                dt_prox_leitura_obj = cand
            except ValueError:
                pass
        except (ValueError, TypeError):
            pass
    dt_deadline_obj = dt_prox_leitura_obj - _td_t(days=7) if dt_prox_leitura_obj else None
    dias_para_deadline = (dt_deadline_obj - _hoje).days if dt_deadline_obj else None
    dt_proxima_leitura_br = dt_prox_leitura_obj.strftime("%d/%m/%Y") if dt_prox_leitura_obj else None
    dt_deadline_br        = dt_deadline_obj.strftime("%d/%m/%Y") if dt_deadline_obj else None

    # Mes alvo (default: proximo mes)
    def _prox_mes(m):
        if not m or "/" not in m: return m
        p = m.split("/")
        try:
            mn, an = int(p[0]), int(p[1])
        except Exception:
            return m
        return f"1/{an + 1}" if mn == 12 else f"{mn + 1}/{an}"

    mes_atual = f"{datetime.now().month}/{datetime.now().year}"
    mes_alvo  = request.args.get("mes", "") or _prox_mes(mes_atual)

    # Params de previsao (via query string)
    algo = request.args.get("algo", "max3m")
    if algo not in ("max3m", "avg_std"):
        algo = "max3m"
    try:
        n_std = max(0.0, min(3.0, float(request.args.get("n_std", "1").replace(",", "."))))
    except Exception:
        n_std = 1.0
    try:
        margem = max(0.0, min(100.0, float(request.args.get("margem", "10").replace(",", "."))))
    except Exception:
        margem = 10.0

    # Vinculos ativos
    vinculos_lista = tb_get_clientes_da_usina(id_usina) if id_usina else []
    todos_clientes = tb_carregar_clientes()
    clientes_id_map = {c["id_cliente"]: c for c in todos_clientes}

    # Geracao prevista da usina (input)
    geracao_mensal_all = carregar_geracao_mensal().get(uid, {})
    # default: media mensal cadastrada na usina; se nao tem, usa ultimo mes registrado
    if usina.get("geracao_media_mensal") and float(usina["geracao_media_mensal"]) > 0:
        ger_default = float(usina["geracao_media_mensal"])
    else:
        ultimos = sorted(geracao_mensal_all.items(),
                         key=lambda kv: int(kv[0].split("/")[1]) * 100 + int(kv[0].split("/")[0])
                         if "/" in kv[0] else 0, reverse=True)
        ger_default = float((ultimos[0][1].get("kwh_gerado", 0) if ultimos else 0) or 0)
    try:
        geracao_prevista = float(request.args.get("ger", "").replace(",", "."))
    except Exception:
        geracao_prevista = ger_default
    if geracao_prevista <= 0:
        geracao_prevista = ger_default

    # Historico de todos os clientes
    historico = carregar_historico()

    # ── Saldo mais recente por cliente (de tb_faturas) ──
    # Fonte primária: última fatura do cliente naquela usina/uc.
    # Fallback: tb_cliente_usina.qtd_saldo_kwh (manual).
    saldo_recente_por_id = {}
    try:
        from db import _db as _dbf
        ids_clientes_vinc = [v.get("id_cliente") for v in vinculos_lista if v.get("id_cliente")]
        if ids_clientes_vinc:
            # Busca faturas dos clientes vinculados (apenas as colunas necessárias)
            for id_c_v in ids_clientes_vinc:
                fats = _dbf().select(
                    "tb_faturas",
                    filtros={"id_cliente": id_c_v},
                    order="ano_referencia.desc,mes_referencia.desc",
                    columns="id_fatura,ano_referencia,mes_referencia,qtd_saldo_kwh",
                )
                if fats:
                    saldo_recente_por_id[id_c_v] = {
                        "saldo": float(fats[0].get("qtd_saldo_kwh") or 0),
                        "mes":   f"{fats[0].get('mes_referencia',0):02d}/{fats[0].get('ano_referencia',0)}",
                    }
    except Exception as _e:
        app.logger.warning(f"[rateio_planejar] saldo recente: {_e}")

    # Monta linha por cliente
    clientes = []
    soma_previsao = 0.0
    soma_necessidade = 0.0
    for v in vinculos_lista:
        id_c = v.get("id_cliente")
        c_tb = clientes_id_map.get(id_c, {})
        cod_uc = c_tb.get("cod_uc", "")
        if not cod_uc:
            continue
        consumos = _historico_consumo_cliente(cod_uc, historico, n_meses=6)
        prev = _prever_consumo(consumos, modo=algo, n_std=n_std, margem_pct=margem)

        # Saldo: prioriza fatura mais recente, fallback tb_cliente_usina
        _saldo_fat = saldo_recente_por_id.get(id_c)
        saldo_kwh   = _saldo_fat["saldo"] if _saldo_fat else round(v.get("qtd_saldo_kwh", 0) or 0, 1)
        saldo_fonte = ("fatura " + _saldo_fat["mes"]) if _saldo_fat else "conferência manual"

        # ── Custo de disponibilidade (kWh sempre não-compensáveis) ──
        tp_forn   = c_tb.get("tp_fornecimento") or ""
        cd_kwh    = _cd_kwh(tp_forn)
        # Parte da previsão que PODE ser compensada por crédito SCEE
        parte_compensavel = max(0.0, prev["previsao"] - cd_kwh)
        # Necessidade líquida = (parte_compensavel) − saldo, mínimo 0
        # Saldo cobre primeiro a parte compensável; se sobra saldo, vira excesso ocioso
        necessidade = max(0.0, parte_compensavel - saldo_kwh)

        # Próxima leitura do cliente + proximidade da leitura da usina
        prox_leit_cli = c_tb.get("proxima_leitura") or ""
        proximidade_dias = None
        prox_leit_cli_br = ""
        if prox_leit_cli and dt_prox_leitura_obj:
            try:
                pl_obj = _date_t.fromisoformat(str(prox_leit_cli)[:10])
                proximidade_dias = abs((pl_obj - dt_prox_leitura_obj).days)
                prox_leit_cli_br = pl_obj.strftime("%d/%m/%Y")
            except (ValueError, TypeError):
                pass

        clientes.append({
            "id_cliente":      id_c,
            "uc":              cod_uc,
            "uc_display":      _fmt_uc15(c_tb.get("cod_uc") or "") or cod_uc,
            "nome":            c_tb.get("desc_nome", cod_uc),
            "pct_atual":       round(v.get("pct_rateio", 0) or 0, 2),
            "saldo_kwh":       round(saldo_kwh, 1),
            "saldo_fonte":     saldo_fonte,
            "tp_fornecimento": tp_forn or "—",
            "cd_kwh":          cd_kwh,
            "parte_compensavel": round(parte_compensavel, 1),
            "necessidade":     round(necessidade, 1),
            "consumos":        consumos,
            "previsao":        prev["previsao"],
            "previsao_base":   prev["base"],
            "media":           prev["media"],
            "maximo":          prev["maximo"],
            "std":             prev["std"],
            "qtd_meses":       prev["qtd_meses"],
            "prox_leitura_cli_br": prox_leit_cli_br,
            "proximidade_dias":    proximidade_dias,
        })
        soma_previsao    += prev["previsao"]
        soma_necessidade += necessidade

    # Calcula % sugerido:
    # 1) Se soma_necessidade > 0 — usa necessidade líquida (já considera saldo)
    # 2) Fallback: usa previsão pura (caso todos tenham saldo suficiente)
    base_para_sugestao = "necessidade" if soma_necessidade > 0 else "previsao"
    for c in clientes:
        if base_para_sugestao == "necessidade" and soma_necessidade > 0:
            c["pct_sugerido"] = round((c["necessidade"] / soma_necessidade) * 100, 2) if c["necessidade"] > 0 else 0.0
        elif soma_previsao > 0 and c["previsao"] > 0:
            c["pct_sugerido"] = round((c["previsao"] / soma_previsao) * 100, 2)
        else:
            c["pct_sugerido"] = 0.0
        c["alocado"] = round(geracao_prevista * c["pct_sugerido"] / 100, 1)
        c["saldo_projetado"] = round(c["saldo_kwh"] + c["alocado"] - c["previsao"], 1)

    # Ordena por previsao desc (clientes maiores primeiro)
    clientes.sort(key=lambda c: -c["previsao"])

    soma_pct_sugerido = round(sum(c["pct_sugerido"] for c in clientes), 2)
    soma_pct_atual    = round(sum(c["pct_atual"]    for c in clientes), 2)

    return render_template("rateio_planejar.html",
        usina=usina, uid=uid_leg, id_usina=id_usina,
        mes_alvo=mes_alvo,
        algo=algo, n_std=n_std, margem=margem,
        geracao_prevista=round(geracao_prevista, 1),
        geracao_default=round(ger_default, 1),
        clientes=clientes,
        soma_previsao=round(soma_previsao, 1),
        soma_necessidade=round(soma_necessidade, 1),
        base_para_sugestao=base_para_sugestao,
        soma_pct_sugerido=soma_pct_sugerido,
        soma_pct_atual=soma_pct_atual,
        dt_proxima_leitura_br=dt_proxima_leitura_br,
        dt_deadline_br=dt_deadline_br,
        dias_para_deadline=dias_para_deadline,
    )


# RATEIO PLANEJAR - Aplicar rateio (salva pct em tb_cliente_usina)
@app.route("/usinas/rateio/<uid>/aplicar_rateio", methods=["POST"])
def rateio_aplicar(uid):
    """Salva os percentuais de rateio definidos no planejamento.

    Form: rateio_<uc> = pct para cada cliente vinculado.
          mes_alvo  = mes que sera passado pro redirect.
    Valida que a soma esteja entre 99.5 e 100.5 (margem de arredondamento).
    """
    from db import (tb_get_cliente_por_uc, tb_get_usina_por_nome,
                    tb_get_usina, tb_save_cliente_usina,
                    tb_get_clientes_da_usina)

    mes_alvo = request.form.get("mes_alvo", "")
    rateios = {}
    soma = 0.0
    for key, val in request.form.items():
        if not key.startswith("rateio_"):
            continue
        uc = key[len("rateio_"):]
        try:
            pct = float((val or "0").replace(",", "."))
        except ValueError:
            pct = 0
        rateios[uc] = pct
        soma += pct

    if abs(soma - 100) > 0.5:
        flash(f"Soma do rateio = {soma:.2f}%. Deve estar entre 99.5% e 100.5% para aplicar.",
              "danger")
        # mantem params na URL para o usuario continuar editando
        return redirect(url_for("rateio_planejar", uid=uid) +
                        f"?mes={mes_alvo}" if mes_alvo else "")

    # Resolve usina
    try:
        id_usina_int = int(uid)
        tb_u = tb_get_usina(id_usina_int)
    except (ValueError, TypeError):
        usinas_leg = carregar_usinas()
        nome_u = usinas_leg.get(uid, {}).get("nome", "")
        tb_u = tb_get_usina_por_nome(nome_u) if nome_u else None

    if not tb_u:
        flash("Usina nao encontrada para aplicar rateio.", "danger")
        return redirect(url_for("rateio_dashboard", uid=uid))

    # Salva cada vinculo. Recupera lista atual para nao perder vinculos com 0%.
    atual = {c.get("id_cliente"): c for c in tb_get_clientes_da_usina(tb_u["id_usina"])}
    n_ok = 0
    for uc, pct in rateios.items():
        tb_c = tb_get_cliente_por_uc(uc)
        if not tb_c:
            continue
        tb_save_cliente_usina(
            tb_c["id_cliente"], tb_u["id_usina"],
            {"pct_rateio": round(pct, 2)}
        )
        n_ok += 1

    flash(f"Rateio aplicado em {n_ok} clientes (total {soma:.2f}%).", "success")
    redir = url_for("rateio_dashboard", uid=uid)
    if mes_alvo:
        redir += f"?mes={mes_alvo}"
    return redirect(redir)


# RATEIO - Dashboard (por mes de referencia)
# ── EDIT INLINE: saldo manual + consumo medio direto na tela de rateio ──────
@app.route("/usinas/rateio/<int:id_usina>/cliente/<int:id_cliente>/edit", methods=["POST"])
def rateio_editar_base(id_usina, id_cliente):
    """Atualiza qtd_saldo_kwh (tb_cliente_usina) e qtd_consumo_medio_kwh (tb_clientes).
    Aceita apenas os campos enviados (parcial). Retorna JSON."""
    from db import _db, tb_get_vinculo_ativo_do_cliente
    def _num(name):
        v = (request.form.get(name) or "").strip()
        if not v:
            return None
        # Só interpreta como BR ('1.234,56') se houver vírgula.
        # '125.5' (US) é interpretado direto pelo float().
        if "," in v:
            v = v.replace(".", "").replace(",", ".")
        elif v.count(".") > 1:
            v = v.replace(".", "")  # '1.234' (BR sem decimais) → 1234
        try:
            return float(v)
        except ValueError:
            return None

    saldo   = _num("saldo_kwh")
    consumo = _num("consumo_medio_kwh")
    if saldo is None and consumo is None:
        return {"erro": "Nada para salvar"}, 400

    try:
        if saldo is not None:
            vinc = tb_get_vinculo_ativo_do_cliente(id_cliente)
            if not vinc or vinc.get("id_usina") != id_usina:
                return {"erro": "Vinculo ativo nao encontrado para essa usina"}, 404
            from datetime import date as _d
            _db().patch("tb_cliente_usina",
                        {"id": vinc["id"]},
                        {"qtd_saldo_kwh": round(saldo, 2),
                         "dt_saldo_conferido": _d.today().isoformat()})
        if consumo is not None:
            _db().patch("tb_clientes",
                        {"id_cliente": id_cliente},
                        {"qtd_consumo_medio_kwh": round(consumo, 1)})
        return {"ok": True}
    except Exception as e:
        logger.error(f"[RATEIO_EDIT] id_usina={id_usina} id_cliente={id_cliente}: {e}")
        return {"erro": str(e)}, 500


@app.route("/usinas/rateio/<uid>")
def rateio_dashboard(uid):
    from db import (tb_get_usina, tb_get_usina_por_nome,
                    tb_get_clientes_da_usina, tb_carregar_clientes)

    # ── Resolve usina (novo ou legado) ───────────────────────
    usinas_leg = carregar_usinas()
    try:
        id_usina = int(uid)
        usina_tb = tb_get_usina(id_usina)
    except ValueError:
        nome_u   = usinas_leg.get(uid, {}).get("nome", "")
        usina_tb = tb_get_usina_por_nome(nome_u) if nome_u else None
        id_usina = usina_tb["id_usina"] if usina_tb else None

    if not usina_tb:
        # fallback para legado puro (usina antiga sem equivalente tb_)
        if uid not in usinas_leg:
            flash("Usina nao encontrada!", "danger"); return redirect(url_for("usinas_lista"))
        usina_tb = {}

    uid_leg = next((u for u, d in usinas_leg.items()
                    if d.get("nome") == usina_tb.get("desc_nome")), uid)

    # Dict compativel com o template (nomes antigos)
    usina = {
        "nome":                    usina_tb.get("desc_nome", usinas_leg.get(uid_leg, {}).get("nome", "")),
        "uc_geradora":             usina_tb.get("cod_uc_geradora", usinas_leg.get(uid_leg, {}).get("uc_geradora", "")),
        "geracao_prevista_diaria": usina_tb.get("qtd_geracao_prevista_diaria") or usinas_leg.get(uid_leg, {}).get("geracao_prevista_diaria", 0) or 0,
        "geracao_media_mensal":    usina_tb.get("qtd_geracao_media_mensal") or usinas_leg.get(uid_leg, {}).get("geracao_media_mensal", 0) or 0,
    }

    # ── Vinculados — novas tabelas ────────────────────────────
    vinculos_lista  = tb_get_clientes_da_usina(id_usina) if id_usina else []
    todos_clientes  = tb_carregar_clientes()
    clientes_id_map = {c["id_cliente"]: c for c in todos_clientes}

    vinculados     = {}
    vinculados_ucs = set()
    for v in vinculos_lista:
        id_c = v.get("id_cliente")
        c_tb = clientes_id_map.get(id_c, {})
        uc   = c_tb.get("cod_uc", "")
        if uc:
            pct = v.get("pct_rateio", 0) or 0
            uc_alt = c_tb.get("cod_uc", "") or ""
            vinculados[uc] = {
                "nome":              c_tb.get("desc_nome", uc),
                "rateio_pct":        round(pct, 2),
                "saldo_kwh":         v.get("qtd_saldo_kwh", 0) or 0,
                "dt_saldo_conferido": v.get("dt_saldo_conferido", "") or "",
                "desc_saldo_obs":    v.get("desc_saldo_obs", "") or "",
                "uc_display":        _fmt_uc15(uc_alt) if uc_alt else uc,
            }
            vinculados_ucs.add(uc)

    # Nao vinculados — legado para compatibilidade com form /vincular
    clientes_leg  = carregar_clientes()
    _uc_alt_map = {c["cod_uc"]: _fmt_uc15(c.get("cod_uc") or "") for c in todos_clientes}
    nao_vinculados = {
        uc: {**c, "uc_display": _uc_alt_map.get(uc) or uc}
        for uc, c in clientes_leg.items()
        if uc not in vinculados_ucs
    }

    # ── Mes de referencia ──────────────────────────────────
    geracao_mensal_all = carregar_geracao_mensal().get(uid, {})
    historico = carregar_faturas()

    # Mes atual (proxima leitura / ciclo em andamento)
    mes_atual = f"{datetime.now().month}/{datetime.now().year}"

    # Meses disponiveis: meses com fatura/geracao + mes atual + meses com rateio registrado
    from db import tb_get_rateios_usina
    rateios_usina = tb_get_rateios_usina(id_usina) if id_usina else {}
    meses_set = set(geracao_mensal_all.keys())
    meses_set.add(mes_atual)
    meses_set.update(rateios_usina.keys())  # inclui meses que tem rateio registrado (ex: 5/2026)
    def _sort_mes(m):
        try:
            p = m.split("/")
            return int(p[1]) * 100 + int(p[0])
        except Exception:
            return 0
    meses_disponiveis = sorted(meses_set, key=_sort_mes, reverse=True)

    mes_sel = request.args.get("mes", "")
    if not mes_sel:
        # Padrão: mês mais recente com geração real; senão mês com rateio; senão mês atual
        if geracao_mensal_all:
            mes_sel = max(geracao_mensal_all.keys(), key=_sort_mes)
        elif rateios_usina:
            mes_sel = max(rateios_usina.keys(), key=_sort_mes)
        else:
            mes_sel = mes_atual

    # ── Estimativa diaria (geracao em andamento) ──────────
    geracao_diaria = carregar_geracao()
    registros_diarios = geracao_diaria.get(uid, [])
    total_kwh_periodo = sum((r.get("kwh", 0) or 0) for r in registros_diarios)
    dias_registrados = len(registros_diarios)
    geracao_prevista_diaria = usina.get("geracao_prevista_diaria", 0) or 0
    media_diaria = total_kwh_periodo / dias_registrados if dias_registrados > 0 else geracao_prevista_diaria
    estimativa_30d = media_diaria * 30

    # ── Dados da geracao real do mes (da fatura da usina) ──
    dados_geracao = geracao_mensal_all.get(mes_sel, {})
    kwh_gerado_real = dados_geracao.get("kwh_gerado", 0) or 0
    saldo_usina = dados_geracao.get("saldo_kwh", 0) or 0
    data_leitura_usina = dados_geracao.get("data_leitura_atual", "") or ""
    tem_geracao_real = kwh_gerado_real > 0

    # Base para calculo:
    #   1) Se tem fatura real → usa geracao real
    #   2) Se tem registros diarios → usa estimativa 30d
    #   3) Fallback → previsao mensal da usina
    geracao_prevista = usina.get("geracao_media_mensal", 0) or 0
    if tem_geracao_real:
        base_kwh = kwh_gerado_real
    elif dias_registrados > 0:
        base_kwh = estimativa_30d
    else:
        base_kwh = geracao_prevista

    # ── Normaliza mes para comparacao com historico ────────
    def _norm_mes_cmp(m):
        """Normaliza '03/2026' e '3/2026' para comparacao."""
        if not m or "/" not in m:
            return ""
        p = m.split("/")
        return f"{int(p[0])}/{p[1]}"

    mes_norm = _norm_mes_cmp(mes_sel)

    # ── Helper: proximo mes (ex: '3/2026' → '4/2026') ────
    def _prox_mes(m):
        if not m or "/" not in m:
            return m
        p = m.split("/")
        mes_n, ano_n = int(p[0]), int(p[1])
        if mes_n == 12:
            return f"1/{ano_n + 1}"
        return f"{mes_n + 1}/{ano_n}"

    # ── Indexa o saldo Equatorial mais recente por UC (ultima fatura do historico)
    # Usado para comparar com o saldo conferido pelo usuario (qtd_saldo_kwh).
    saldo_eq_por_uc = {}  # {uc_lstripped: {saldo_kwh, data_leitura, mes_referencia}}
    def _data_para_ord(item):
        """Para ordenacao: prioriza data_leitura_atual, fallback para mes_referencia."""
        dl = item.get("data_leitura_atual", "") or ""
        if dl and "/" in dl:
            try:
                p = dl.split("/")
                return (int(p[2]), int(p[1]), int(p[0]))
            except Exception: pass
        m = item.get("mes_referencia", "") or ""
        if m and "/" in m:
            try:
                p = m.split("/")
                return (int(p[1]), int(p[0]), 0)
            except Exception: pass
        return (0, 0, 0)
    for item in historico:
        h_uc = str(item.get("uc", "")).lstrip("0")
        if not h_uc: continue
        atual = saldo_eq_por_uc.get(h_uc)
        if atual is None or _data_para_ord(item) > _data_para_ord(atual):
            saldo_eq_por_uc[h_uc] = item

    # ── Confrontacao: alocacao esperada vs fatura do cliente ─
    total_rateio = sum((c.get("rateio_pct", 0) or 0) for c in vinculados.values())
    # Mapeia uc → id_cliente pra incluir no dict de alocacao (necessario pro
    # endpoint AJAX de edicao manual de saldo/consumo)
    _uc_para_id_cliente = {}
    for v in vinculos_lista:
        id_c = v.get("id_cliente")
        c_tb = clientes_id_map.get(id_c, {})
        if id_c and c_tb.get("cod_uc"):
            _uc_para_id_cliente[c_tb["cod_uc"]] = id_c

    alocacoes = []
    for uc, c in vinculados.items():
        pct = c.get("rateio_pct", 0) or 0
        kwh_esperado = base_kwh * (pct / 100) if pct > 0 else 0

        # Busca fatura do cliente neste mes (compensado = kWh creditado real)
        # REGRA: a fatura que COMPENSA esta geracao e a do cliente cuja leitura e
        # POSTERIOR a leitura da usina (a primeira apos). Faturas de leitura anterior
        # compensam o ciclo anterior, nao esta geracao.
        kwh_compensado = 0
        consumo_cliente = 0
        saldo_cliente = c.get("saldo_kwh", 0) or 0
        tem_fatura = False

        def _dia_br(s):
            s = str(s or "").strip()
            for _f in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    return datetime.strptime(s[:10], _f).date()
                except ValueError:
                    continue
            return None

        leit_usina = _dia_br(data_leitura_usina)
        uc_lst = str(uc).lstrip("0")
        candidatas = []
        for item in historico:
            if str(item.get("uc", "")).lstrip("0") != uc_lst:
                continue
            dl = _dia_br(item.get("data_leitura_atual", ""))
            if leit_usina and dl and dl > leit_usina:
                candidatas.append((dl, item))
        if candidatas:
            candidatas.sort(key=lambda x: x[0])  # a 1a leitura posterior a da usina
            item = candidatas[0][1]
            kwh_compensado = item.get("compensado_kwh", 0) or 0
            consumo_cliente = item.get("consumo_kwh", 0) or 0
            tem_fatura = True

        diferenca = kwh_compensado - kwh_esperado if tem_fatura and kwh_compensado > 0 else 0

        # Status
        if not tem_geracao_real:
            status = "estimativa"
        elif not tem_fatura:
            status = "aguardando"
        elif abs(diferenca) < 1:
            status = "ok"
        elif diferenca > 0:
            status = "excedente"
        else:
            status = "deficit"

        # Saldo Equatorial: vem da fatura mais recente do cliente
        item_eq = saldo_eq_por_uc.get(str(uc).lstrip("0"))
        saldo_equatorial = (item_eq or {}).get("saldo_kwh", 0) or 0
        data_saldo_eq    = (item_eq or {}).get("data_leitura_atual", "") or (item_eq or {}).get("mes_referencia", "") or ""
        # Divergencia: tolera ate 1 kWh de diferenca para arredondamento
        divergencia_saldo = round(saldo_cliente - saldo_equatorial, 1)
        tem_divergencia = abs(divergencia_saldo) >= 1

        alocacoes.append({
            "uc": uc, "uc_display": c.get("uc_display", uc), "nome": c["nome"], "rateio_pct": pct,
            "id_cliente": _uc_para_id_cliente.get(uc),
            "kwh_esperado": round(kwh_esperado, 1),
            "kwh_compensado": round(kwh_compensado, 1),
            "consumo_cliente": round(consumo_cliente, 1),
            "saldo_kwh": round(saldo_cliente, 1),
            "saldo_equatorial": round(saldo_equatorial, 1),
            "data_saldo_eq": data_saldo_eq,
            "divergencia_saldo": divergencia_saldo,
            "tem_divergencia": tem_divergencia,
            "dt_saldo_conferido": c.get("dt_saldo_conferido", ""),
            "desc_saldo_obs":     c.get("desc_saldo_obs", ""),
            "diferenca": round(diferenca, 1),
            "tem_fatura": tem_fatura,
            "status": status,
        })
    alocacoes.sort(key=lambda x: -x["rateio_pct"])

    # ── Enriquece alocacoes com dados de planejamento ──────────
    _uc_tp_map      = {}
    _uc_med_map     = {}  # consumo_medio_kwh por uc
    _uc_saldo_ini   = {}  # saldo_inicial_kwh por uc
    for v in vinculos_lista:
        id_c = v.get("id_cliente")
        c_tb = clientes_id_map.get(id_c, {})
        uc_c = c_tb.get("cod_uc", "")
        if uc_c:
            _uc_tp_map[uc_c]    = c_tb.get("tp_fornecimento", "") or ""
            _uc_med_map[uc_c]   = float(c_tb.get("qtd_consumo_medio_kwh") or 0)
            _uc_saldo_ini[uc_c] = float(c_tb.get("qtd_saldo_inicial_kwh") or 0)

    for a in alocacoes:
        tp_forn  = _uc_tp_map.get(a["uc"], "")
        consumos = _historico_consumo_cliente(a["uc"], historico, n_meses=6)
        # Fallback: sem histórico → usa consumo médio do cadastro
        if not consumos:
            med = _uc_med_map.get(a["uc"], 0)
            if med > 0:
                consumos = [{"mes": "estimado", "mes_ord": 0, "consumo": med,
                             "compensado": 0, "nao_compensado": med}]
        prev       = _prever_consumo(consumos, modo="max3m", margem_pct=10.0)
        cd         = _cd_kwh(tp_forn)
        parte_comp = max(0.0, prev["previsao"] - cd)
        # Saldo: tb_cliente_usina > saldo_inicial do cadastro
        saldo_efetivo = a["saldo_kwh"] if a["saldo_kwh"] != 0 else _uc_saldo_ini.get(a["uc"], 0)
        nec = max(0.0, parte_comp - saldo_efetivo)
        a.update({
            "previsao":       round(prev["previsao"], 1),
            "media_consumo":  round(prev["media"], 1),
            "qtd_meses":      prev["qtd_meses"],
            "necessidade":    round(nec, 1),
            "pct_sugerido":   0.0,
            "saldo_kwh":      round(saldo_efetivo, 1),
        })

    _soma_nec  = sum(a["necessidade"] for a in alocacoes)
    _soma_prev = sum(a["previsao"]    for a in alocacoes)
    for a in alocacoes:
        if _soma_nec > 0:
            a["pct_sugerido"] = round(a["necessidade"] / _soma_nec * 100, 2) if a["necessidade"] > 0 else 0.0
        elif _soma_prev > 0:
            a["pct_sugerido"] = round(a["previsao"] / _soma_prev * 100, 2)

    # ── Sugestao de rateio para o proximo mes ──────────────
    # Baseado na diferenca: quem recebeu mais do que deveria, reduz;
    # quem recebeu menos, aumenta. So sugere se tem dados reais.
    sugestoes = []
    todas_faturas = all(a["tem_fatura"] for a in alocacoes) and tem_geracao_real and len(alocacoes) > 0
    if todas_faturas:
        # Calcula consumo total dos clientes para redistribuir proporcionalmente
        consumo_total = sum(a["consumo_cliente"] for a in alocacoes)
        for a in alocacoes:
            if consumo_total > 0:
                # Sugere baseado no consumo real do cliente
                pct_sugerido = (a["consumo_cliente"] / consumo_total) * total_rateio
            else:
                pct_sugerido = a["rateio_pct"]
            delta = round(pct_sugerido - a["rateio_pct"], 2)
            sugestoes.append({
                "uc": a["uc"], "nome": a["nome"],
                "pct_atual": a["rateio_pct"],
                "pct_sugerido": round(pct_sugerido, 2),
                "delta": delta,
            })

    _rateios_all = carregar_rateios_mensais()
    _mes_key = _norm_mes(mes_sel)
    rateio_mes = _rateios_all.get(uid_leg, {}).get(_mes_key, {}) or _rateios_all.get(str(id_usina), {}).get(_mes_key, {})
    protocolo_info = {
        "protocolo":      rateio_mes.get("protocolo", ""),
        "via_envio":      rateio_mes.get("via_envio", ""),
        "data_protocolo": rateio_mes.get("data_protocolo", ""),
    }
    # Snapshot do rateio registrado (tb_rateios_mensais) para exibir como controle
    rateio_registrado = rateios_usina.get(_mes_key) or rateios_usina.get(mes_sel) or {}

    return render_template("rateio.html",
        usina=usina, uid=uid_leg, id_usina=id_usina, alocacoes=alocacoes,
        nao_vinculados=nao_vinculados,
        total_rateio=round(total_rateio, 2),
        total_kwh_gerado=round(total_kwh_periodo, 1),
        estimativa_30d=round(estimativa_30d, 1),
        geracao_mensal=round(geracao_prevista, 1),
        base_kwh=round(base_kwh, 1),
        kwh_gerado_real=round(kwh_gerado_real, 1),
        saldo_usina=round(saldo_usina, 2),
        data_leitura_usina=data_leitura_usina,
        tem_geracao_real=tem_geracao_real,
        dias_registrados=dias_registrados, media_diaria=round(media_diaria, 1),
        mes_sel=mes_sel, meses_disponiveis=meses_disponiveis,
        sugestoes=sugestoes, todas_faturas=todas_faturas,
        protocolo_info=protocolo_info, rateio_registrado=rateio_registrado,
        soma_necessidade=round(_soma_nec, 1),
        base_para_sugestao="necessidade" if _soma_nec > 0 else "previsao",
        fmt=_fmt_brl,
        now_str=datetime.now().strftime("%Y%m%d"),
    )

# RATEIO - Registrar protocolo
@app.route("/usinas/rateio/protocolo/<uid>", methods=["POST"])
def rateio_registrar_protocolo(uid):
    mes_ref  = _norm_mes(request.form.get("mes_ref", "").strip())
    protocolo = request.form.get("protocolo", "").strip()
    via_envio = request.form.get("via_envio", "email")
    if not mes_ref or not protocolo:
        flash("Numero do protocolo e obrigatorio!", "danger")
        return redirect(url_for("rateio_dashboard", uid=uid))
    rateios = carregar_rateios_mensais()
    if uid not in rateios:
        rateios[uid] = {}
    if mes_ref not in rateios[uid]:
        rateios[uid][mes_ref] = {"data_registro": datetime.now().strftime("%d/%m/%Y %H:%M"), "soma_percentual": 0, "beneficiarios": []}
    rateios[uid][mes_ref]["protocolo"]      = protocolo
    rateios[uid][mes_ref]["via_envio"]      = via_envio
    rateios[uid][mes_ref]["data_protocolo"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    salvar_rateios_mensais(rateios)
    flash(f"Protocolo {protocolo} registrado para {mes_ref}!", "success")
    return redirect(url_for("rateio_dashboard", uid=uid) + f"?mes={mes_ref}")


# RATEIO - Aplicar sugestao de rateio do proximo mes
@app.route("/usinas/rateio/aplicar_sugestao/<uid>", methods=["POST"])
def aplicar_sugestao_rateio(uid):
    from db import (tb_get_clientes_da_usina, tb_get_usina_por_nome,
                    tb_get_usina, tb_save_cliente_usina, tb_carregar_clientes)
    usinas_leg = carregar_usinas()
    clientes   = carregar_clientes()

    # Vinculados legado (para compatibilidade)
    vinculados_leg = {uc: c for uc, c in clientes.items() if c.get("usina_id") == uid}
    alterados = 0
    for uc in vinculados_leg:
        valor = request.form.get(f"rateio_{uc}", "")
        if valor:
            try:
                novo_pct = round(float(valor.replace(",", ".")), 2)
                if novo_pct != clientes[uc].get("rateio_pct", 0):
                    clientes[uc]["rateio_pct"] = novo_pct
                    alterados += 1
            except (ValueError, TypeError):
                pass
    if alterados > 0:
        salvar_clientes(clientes)
        flash(f"Rateio atualizado para {alterados} cliente(s)!", "success")
    else:
        flash("Nenhuma alteracao no rateio.", "info")

    # Novas tabelas
    try:
        nome_u = usinas_leg.get(uid, {}).get("nome", "")
        tb_u   = tb_get_usina_por_nome(nome_u) if nome_u else None
        if not tb_u:
            try: tb_u = tb_get_usina(int(uid))
            except: pass
        if tb_u:
            id_usina = tb_u["id_usina"]
            vinculos = tb_get_clientes_da_usina(id_usina)
            clientes_tb = {c["id_cliente"]: c for c in tb_carregar_clientes()}
            for v in vinculos:
                id_c = v.get("id_cliente")
                c_tb = clientes_tb.get(id_c, {})
                uc_tb = c_tb.get("cod_uc", "")
                valor = request.form.get(f"rateio_{uc_tb}", "")
                if valor:
                    try:
                        pct = round(float(valor.replace(",", ".")), 2)
                        # Armazena como percentual (ex: 10.57) para preservar os decimais
                        tb_save_cliente_usina(id_c, id_usina, {"pct_rateio": pct})
                    except: pass
    except Exception as e:
        app.logger.warning(f"[aplicar_sugestao] Falha tb_: {e}")

    mes = request.form.get("mes_sel", "")
    return redirect(url_for("rateio_dashboard", uid=uid, mes=mes))

# TESTE - Verificar se este servidor esta rodando
@app.route("/teste-versao")
def teste_versao():
    return "SERVIDOR ATUALIZADO - v2026-04-13 OK", 200

# ── SUPABASE — Sincronizacao (obsoleta: tudo ja esta no Supabase) ──
@app.route("/sync")
@app.route("/sync/push", methods=["GET", "POST"])
@app.route("/sync/pull", methods=["GET", "POST"])
def sync_page():
    flash("Sincronizacao nao e mais necessaria — todos os dados ja estao no Supabase.", "info")
    return redirect(url_for("dashboard"))


@app.route("/admin/sync_leituras", methods=["POST"])
def admin_sync_leituras():
    """Popula proxima_leitura em tb_clientes a partir de tb_faturas."""
    from db import tb_sync_proxima_leitura_por_fatura
    try:
        resultado = tb_sync_proxima_leitura_por_fatura()
        flash(
            f"Datas sincronizadas: {resultado['atualizados']} clientes atualizados"
            + (f", {resultado['erros']} erros" if resultado['erros'] else "") + ".",
            "success" if not resultado['erros'] else "warning"
        )
    except Exception as e:
        flash(f"Erro ao sincronizar datas: {e}", "danger")
    return redirect(request.referrer or url_for("clientes"))

# RATEIO - Gerar PDF formulario Equatorial
@app.route("/usinas/rateio/pdf/<uid>")
def rateio_gerar_pdf(uid):
    from db import (tb_get_usina, tb_get_usina_por_nome, tb_get_endereco_usina,
                    tb_get_investidor, tb_get_clientes_da_usina, tb_carregar_clientes,
                    tb_get_titular)
    try:
        usina = None
        vinculados = []

        # ── Resolve id_usina: inteiro (novo) ou uid legado (string) ──
        usinas_leg = carregar_usinas()
        try:
            id_usina = int(uid)
            usina_tb = tb_get_usina(id_usina)
        except (ValueError, TypeError):
            # uid legado → busca por nome na nova tabela (mesmo que rateio_dashboard)
            nome     = usinas_leg.get(uid, {}).get("nome", "")
            usina_tb = tb_get_usina_por_nome(nome) if nome else None
            id_usina = usina_tb["id_usina"] if usina_tb else None

        if usina_tb:
            end_tb = tb_get_endereco_usina(id_usina) or {}
            # fallback legado por uid string ou por nome
            _leg = usinas_leg.get(uid, {})
            if not _leg:
                _nome_tb = usina_tb.get("desc_nome", "")
                _leg = next((v for v in usinas_leg.values() if v.get("nome") == _nome_tb), {})
            _cidade = end_tb.get("desc_cidade", "")
            if _cidade and end_tb.get("desc_estado"):
                _cidade += f"/{end_tb['desc_estado']}"
            _end_parts = [
                end_tb.get("desc_logradouro", ""), end_tb.get("desc_numero", ""),
                end_tb.get("desc_complemento", ""), end_tb.get("desc_setor", ""),
            ]
            _end_str = ", ".join(p for p in _end_parts if p).strip() or _leg.get("endereco", "")

            # ── Dados do TITULAR ──────────────────────────────────────
            # Os campos legados desc_titular_uc / desc_cpf_titular / etc. em
            # tb_usinas ficaram NULL após a migração — agora vivem em tb_titulares
            # referenciado por id_titular. Buscar lá primeiro, com fallback nos legados.
            _titular_nome  = (usina_tb.get("desc_titular_uc") or "").strip()
            _titular_cpf   = (usina_tb.get("desc_cpf_titular") or "").strip()
            _titular_tel   = (usina_tb.get("desc_telefone_titular") or "").strip()
            _titular_email = (usina_tb.get("desc_email_titular") or "").strip()
            _id_titular = usina_tb.get("id_titular")
            if _id_titular and not all([_titular_nome, _titular_cpf, _titular_tel, _titular_email]):
                _tit = tb_get_titular(_id_titular) or {}
                if not _titular_nome:  _titular_nome  = (_tit.get("desc_nome")     or "").strip()
                if not _titular_cpf:   _titular_cpf   = (_tit.get("desc_cpf_cnpj") or "").strip()
                if not _titular_tel:   _titular_tel   = (_tit.get("desc_telefone") or "").strip()
                if not _titular_email: _titular_email = (_tit.get("desc_email")    or "").strip()

            usina = {
                "nome":              usina_tb.get("desc_nome", uid),
                "uc_geradora":       _fmt_uc15(usina_tb.get("cod_uc_geradora", "") or _leg.get("uc_geradora", "")),
                "classe":            usina_tb.get("desc_classe", "") or _leg.get("classe", ""),
                "titular_uc":        _titular_nome or _leg.get("titular_uc", ""),
                "cpf_titular":       _fmt_cpf_cnpj(_titular_cpf or _leg.get("cpf_titular", "")),
                "telefone":          _titular_tel or _leg.get("telefone", ""),
                "email_titular":     _titular_email or _leg.get("email", ""),
                "endereco":          _end_str,
                "cep":               _fmt_cep(end_tb.get("cod_cep", "") or _leg.get("cep", "")),
                "cidade_uf":         _cidade or _leg.get("cidade_uf", ""),
                "path_doc_cnh_rg":   usina_tb.get("path_doc_cnh_rg", ""),
                "path_doc_procuracao": usina_tb.get("path_doc_procuracao", ""),
                "path_doc_cnh_rg_proc": usina_tb.get("path_doc_cnh_rg_proc", ""),
            }
            # Vinculados de tb_cliente_usina — mesma fonte que a tela de rateio
            vinculos   = tb_get_clientes_da_usina(id_usina)
            tb_cli_map = {c["id_cliente"]: c for c in tb_carregar_clientes() if c.get("id_cliente")}
            for v in vinculos:
                c_tb   = tb_cli_map.get(v.get("id_cliente")) or {}
                pct    = v.get("pct_rateio", 0) or 0
                uc     = c_tb.get("cod_uc", str(v.get("id_cliente", "")))
                uc_alt = c_tb.get("cod_uc", "") or ""
                vinculados.append((
                    uc,
                    {"nome": c_tb.get("desc_nome", ""), "rateio_pct": round(pct, 2),
                     "uc_display": _fmt_uc15(uc_alt) if uc_alt else uc},
                ))
            vinculados.sort(key=lambda x: -(x[1].get("rateio_pct", 0) or 0))

        # ── Fallback: sistema legado (uid sem correspondencia nas novas tabelas) ──
        if usina is None:
            if uid not in usinas_leg:
                flash("Usina nao encontrada!", "danger"); return redirect(url_for("usinas_lista"))
            usina = usinas_leg[uid]
            clientes = carregar_clientes()
            vinculados = [(uc, c) for uc, c in clientes.items() if c.get("usina_id") == uid]
            vinculados.sort(key=lambda x: -(x[1].get("rateio_pct", 0) or 0))

        _mes_ref_rat = request.args.get("mes", "")
        pdf_path = gerar_pdf_rateio(usina, uid, vinculados, mes_ref=_mes_ref_rat)
        nome_download = os.path.basename(pdf_path)
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={nome_download}"}
        )
    except Exception as e:
        return f"Erro ao gerar rateio: {e}", 500

# RATEIO - Enviar por e-mail para Equatorial
EMAIL_CONFIG_JSON = os.path.join(_DIR, "email_config.json")

def _carregar_email_config():
    if os.path.exists(EMAIL_CONFIG_JSON):
        with open(EMAIL_CONFIG_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

@app.route("/usinas/rateio/email/<uid>", methods=["POST"])
def rateio_enviar_email(uid):
    import smtplib
    from email.message import EmailMessage
    usinas = carregar_usinas()
    cfg = _carregar_email_config()
    senha = cfg.get("senha_app", "")
    if not senha or senha == "COLE_AQUI_SUA_SENHA_DE_APP":
        flash("Configure a senha de app em email_config.json antes de enviar.", "danger")
        return redirect(url_for("rateio_dashboard", uid=uid))

    # Resolve usina: tenta novo sistema (id numerico) e legado (string)
    from db import (tb_get_usina, tb_get_usina_por_nome, tb_get_endereco_usina,
                    tb_get_clientes_da_usina, tb_carregar_clientes)
    try:
        id_usina = int(uid)
        usina_tb = tb_get_usina(id_usina)
    except (ValueError, TypeError):
        nome     = usinas.get(uid, {}).get("nome", "")
        usina_tb = tb_get_usina_por_nome(nome) if nome else None
        id_usina = usina_tb["id_usina"] if usina_tb else None

    if not usina_tb and uid not in usinas:
        flash("Usina nao encontrada!", "danger")
        return redirect(url_for("usinas_lista"))

    vinculados = []
    if usina_tb:
        end_tb = tb_get_endereco_usina(id_usina) or {}
        _leg = usinas.get(uid, {})
        if not _leg:
            _nome_tb = usina_tb.get("desc_nome", "")
            _leg = next((v for v in usinas.values() if v.get("nome") == _nome_tb), {})
        _cidade = end_tb.get("desc_cidade", "")
        if _cidade and end_tb.get("desc_estado"):
            _cidade += f"/{end_tb['desc_estado']}"
        _end_parts2 = [
            end_tb.get("desc_logradouro", ""), end_tb.get("desc_numero", ""),
            end_tb.get("desc_complemento", ""), end_tb.get("desc_setor", ""),
        ]
        _end_str2 = ", ".join(p for p in _end_parts2 if p).strip() or _leg.get("endereco", "")
        usina = {
            "nome":               usina_tb.get("desc_nome", uid),
            "uc_geradora":        _fmt_uc15(usina_tb.get("cod_uc_geradora", "") or _leg.get("uc_geradora", "")),
            "classe":             usina_tb.get("desc_classe", "") or _leg.get("classe", ""),
            "titular_uc":         usina_tb.get("desc_titular_uc", "") or _leg.get("titular_uc", ""),
            "cpf_titular":        _fmt_cpf_cnpj(usina_tb.get("desc_cpf_titular", "") or _leg.get("cpf_titular", "")),
            "telefone":           usina_tb.get("desc_telefone_titular", "") or _leg.get("telefone", ""),
            "email_titular":      usina_tb.get("desc_email_titular", "") or _leg.get("email", ""),
            "endereco":           _end_str2,
            "cep":                end_tb.get("cod_cep", "") or _leg.get("cep", ""),
            "cidade_uf":          _cidade or _leg.get("cidade_uf", ""),
            "path_doc_cnh_rg":    usina_tb.get("path_doc_cnh_rg", ""),
            "path_doc_procuracao": usina_tb.get("path_doc_procuracao", ""),
            "path_doc_cnh_rg_proc": usina_tb.get("path_doc_cnh_rg_proc", ""),
        }
        vinculos   = tb_get_clientes_da_usina(id_usina)
        tb_cli_map = {c["id_cliente"]: c for c in tb_carregar_clientes() if c.get("id_cliente")}
        for v in vinculos:
            c_tb   = tb_cli_map.get(v.get("id_cliente")) or {}
            pct    = v.get("pct_rateio", 0) or 0
            uc     = c_tb.get("cod_uc", str(v.get("id_cliente", "")))
            uc_alt = c_tb.get("cod_uc", "") or ""
            vinculados.append((uc, {"nome": c_tb.get("desc_nome", ""), "rateio_pct": round(pct, 2),
                                    "uc_display": _fmt_uc15(uc_alt) if uc_alt else uc}))
        vinculados.sort(key=lambda x: -(x[1].get("rateio_pct", 0) or 0))
    else:
        usina = usinas.get(uid, {})
        clientes = carregar_clientes()
        vinculados = [(uc, c) for uc, c in clientes.items() if c.get("usina_id") == uid]
        vinculados.sort(key=lambda x: -(x[1].get("rateio_pct", 0) or 0))

    try:
        _mes_ref_email = request.args.get("mes", "")
        pdf_path = gerar_pdf_rateio(usina, uid, vinculados, mes_ref=_mes_ref_email)
    except Exception as e:
        flash(f"Erro ao gerar PDF: {e}", "danger")
        return redirect(url_for("rateio_dashboard", uid=uid))

    uc_ger = usina.get("uc_geradora", uid)
    data_inv = datetime.now().strftime("%Y%m%d")
    assunto = f"UC {uc_ger} {data_inv}"

    corpo = (
        f"Bom dia!\n\n"
        f"Venho por meio deste solicitar atualizacao do rateio de geracao distribuida "
        f"da unidade {uc_ger}.\n\n"
        f"Segue anexo o formulario do rateio e documentos.\n\n"
        f"Certo do pronto atendimento, desde ja agradeco."
    )

    remetente = cfg.get("remetente", "")
    destinatario = cfg.get("destinatario_padrao", "gd.goias@equatorialenergia.com.br")
    smtp_host = cfg.get("smtp_host", "smtp.gmail.com")
    smtp_port = cfg.get("smtp_port", 587)

    msg = EmailMessage()
    msg["From"] = remetente
    msg["To"] = destinatario
    msg["Subject"] = assunto
    msg.set_content(corpo)

    with open(pdf_path, "rb") as fp:
        msg.add_attachment(fp.read(), maintype="application", subtype="pdf",
                           filename=os.path.basename(pdf_path))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(remetente, senha)
            server.send_message(msg)
        flash(f"E-mail enviado para {destinatario} com assunto: {assunto}", "success")
    except Exception as e:
        flash(f"Erro ao enviar e-mail: {e}", "danger")

    return redirect(url_for("rateio_dashboard", uid=uid))

# USINAS - Desvincular cliente
@app.route("/usinas/rateio/<uid>/desvincular/<uc>", methods=["POST"])
def rateio_desvincular_cliente(uid, uc):
    """Desvincula um cliente da usina diretamente pela tela de Rateio
    (atalho que evita ter que voltar pra tela de Distribuir).
    Após desvincular, volta pra mesma tela de rateio."""
    from db import (tb_get_cliente_por_uc, tb_get_usina, tb_get_usina_por_nome,
                    tb_delete_cliente_usina)
    nome_exibir = uc
    try:
        try:
            id_usina = int(uid)
            tb_usina = tb_get_usina(id_usina)
        except (ValueError, TypeError):
            usinas_leg = carregar_usinas()
            nome_usina = usinas_leg.get(uid, {}).get("nome", "")
            tb_usina = tb_get_usina_por_nome(nome_usina) if nome_usina else None

        tb_cliente = tb_get_cliente_por_uc(uc)
        if not tb_usina or not tb_cliente:
            flash("Cliente ou usina não encontrados.", "danger")
            return redirect(url_for("rateio_dashboard", uid=uid))

        # Bloqueia exclusão de vínculo FIXO (consistência com toda a regra FIXO)
        from db import tb_get_usinas_do_cliente
        vincs = tb_get_usinas_do_cliente(tb_cliente["id_cliente"])
        for v in vincs:
            if v.get("id_usina") == tb_usina["id_usina"] and (v.get("desc_saldo_obs") or "").upper() == "FIXO":
                flash(f"Cliente {tb_cliente.get('desc_nome','?')} está como vínculo FIXO — não pode ser desvinculado aqui.", "warning")
                return redirect(url_for("rateio_dashboard", uid=uid))

        tb_delete_cliente_usina(tb_cliente["id_cliente"], tb_usina["id_usina"])
        nome_exibir = tb_cliente.get("desc_nome", nome_exibir)
        flash(f"Cliente {nome_exibir} desvinculado da usina.", "warning")
    except Exception as e:
        app.logger.warning(f"[rateio-desvincular] Falha: {e}")
        flash(f"Erro ao desvincular: {e}", "danger")
    return redirect(url_for("rateio_dashboard", uid=uid))


@app.route("/usinas/desvincular/<uid>/<uc>")
def desvincular_cliente(uid, uc):
    from db import (tb_get_cliente_por_uc, tb_get_usina, tb_get_usina_por_nome,
                    tb_delete_cliente_usina)
    nome_exibir = uc


    # Remove das tabelas normalizadas — independente de estar no legado
    try:
        try:
            id_usina = int(uid)
            tb_usina = tb_get_usina(id_usina)
        except (ValueError, TypeError):
            usinas_leg = carregar_usinas()
            nome_usina = usinas_leg.get(uid, {}).get("nome", "")
            tb_usina = tb_get_usina_por_nome(nome_usina) if nome_usina else None

        tb_cliente = tb_get_cliente_por_uc(uc)
        if tb_usina and tb_cliente:
            tb_delete_cliente_usina(tb_cliente["id_cliente"], tb_usina["id_usina"])
            nome_exibir = tb_cliente.get("desc_nome", nome_exibir)
    except Exception as e:
        app.logger.warning(f"[desvincular] Falha ao remover tb_cliente_usina: {e}")

    flash(f"Cliente {nome_exibir} desvinculado.", "warning")
    return redirect(url_for("usina_ver", uid=uid))

# USINAS - Zerar periodo (nova leitura)
@app.route("/usinas/zerar/<uid>")
def zerar_periodo(uid):
    from db import tb_get_usina, tb_save_usina
    total = 0

    # Sistema legado: zera geracao diaria
    geracao = carregar_geracao()
    total = sum((r.get("kwh", 0) or 0) for r in geracao.get(uid, []))
    geracao[uid] = []
    salvar_geracao(geracao)

    # Sistema novo: zera qtd_saldo_kwh em tb_usinas (se uid for inteiro)
    try:
        id_usina = int(uid)
        usina_tb = tb_get_usina(id_usina)
        if usina_tb:
            if total == 0:
                # uid e inteiro mas nao havia nada no legado — pega total do tb_
                total = usina_tb.get("qtd_saldo_kwh", 0) or 0
            tb_save_usina({"id_usina": id_usina, "qtd_saldo_kwh": 0})
    except (ValueError, TypeError):
        pass

    flash(f"Periodo zerado! Total anterior: {total:.1f} kWh", "success")
    return redirect(url_for("usina_ver", uid=uid))

# ══════════════════════════════════════════════════════════════
# CONCILIACAO MENSAL — Geracao × Rateio × Credito Real
# ══════════════════════════════════════════════════════════════
def carregar_rateios_mensais():
    """Le rateios de tb_rateios_mensais (Supabase)."""
    from db import tb_get_todos_rateios
    return tb_get_todos_rateios()

def salvar_rateios_mensais(r):
    """Grava rateios em tb_rateios_mensais (Supabase)."""
    from db import tb_save_rateio_mes
    for uid_str, meses in r.items():
        try:
            id_usina = int(uid_str)
        except (ValueError, TypeError):
            logging.warning(f"[salvar_rateios_mensais] uid '{uid_str}' nao e inteiro, ignorado.")
            continue
        for mes_ref, dados in meses.items():
            tb_save_rateio_mes(
                id_usina, mes_ref,
                dados.get("beneficiarios", []),
                dados.get("soma_percentual", 0),
                dados.get("data_registro", ""),
            )

def _norm_mes(mes_ref):
    """Normaliza 'MM/YYYY' para 'M/YYYY' (sem zero a esquerda)."""
    if not mes_ref: return ""
    p = mes_ref.split("/")
    if len(p) == 2:
        try: return f"{int(p[0])}/{p[1]}"
        except: pass
    return mes_ref

def obter_rateio_mes(uid, mes_ref):
    rateios = carregar_rateios_mensais()
    return rateios.get(uid, {}).get(_norm_mes(mes_ref))

def obter_geracao_mes(uid, mes_ref):
    geracao = carregar_geracao_mensal()
    return geracao.get(uid, {}).get(_norm_mes(mes_ref))

def _esperado_total_cliente(uc, mes_ref):
    """Soma o kWh esperado para um cliente em TODAS as usinas em que participa naquele mes."""
    mes_norm = _norm_mes(mes_ref)
    rateios = carregar_rateios_mensais()
    geracao_all = carregar_geracao_mensal()
    total = 0
    usinas_participa = []
    for uid, meses in rateios.items():
        rat = meses.get(mes_norm)
        if not rat: continue
        for b in rat.get("beneficiarios", []):
            if b.get("uc", "").lstrip("0") == uc.lstrip("0"):
                ger = geracao_all.get(uid, {}).get(mes_norm, {})
                kwh_g = ger.get("kwh_gerado", 0) or 0
                pct = b.get("percentual", 0) or 0
                esperado_aqui = kwh_g * pct / 100
                total += esperado_aqui
                usinas_participa.append({"uid": uid, "percentual": pct, "esperado": round(esperado_aqui, 2)})
                break
    return round(total, 2), usinas_participa

def calcular_conciliacao(uid, mes_ref):
    """Calcula a conciliacao entre rateio esperado × credito real recebido.
    Considera o caso multi-usina: cliente pode receber de varias usinas no mesmo mes."""
    mes_norm = _norm_mes(mes_ref)
    rateio = obter_rateio_mes(uid, mes_ref)
    geracao = obter_geracao_mes(uid, mes_ref)
    historico = carregar_faturas()
    clientes = carregar_clientes()

    # Cache de nomes tb_clientes (carrega sob demanda)
    _cache_nomes_tb = {}
    def _nome_cliente(uc):
        if uc in clientes:
            return clientes[uc].get("nome", "")
        if uc in _cache_nomes_tb:
            return _cache_nomes_tb[uc]
        try:
            from db import tb_get_cliente_por_uc
            c_tb = tb_get_cliente_por_uc(uc)
            nome = c_tb.get("desc_nome", "") if c_tb else ""
        except Exception:
            nome = ""
        _cache_nomes_tb[uc] = nome
        return nome

    kwh_gerado = (geracao or {}).get("kwh_gerado", 0) or 0
    beneficiarios = (rateio or {}).get("beneficiarios", [])

    linhas = []
    for b in beneficiarios:
        uc = b.get("uc", "")
        pct = b.get("percentual", 0) or 0
        kwh_esperado_aqui = round(kwh_gerado * pct / 100, 2)

        nome = _nome_cliente(uc)
        # kwh_real: total compensado no historico (vem da fatura unica do cliente)
        kwh_real = 0
        for h in historico:
            h_uc = h.get("uc", "")
            if h_uc.lstrip("0") == uc.lstrip("0") and _norm_mes(h.get("mes_referencia", "")) == mes_norm:
                kwh_real = h.get("compensado_kwh", 0) or 0
                break

        # Esperado TOTAL do cliente (somando todas as usinas que ele participa neste mes)
        esperado_total, usinas_participa = _esperado_total_cliente(uc, mes_ref)
        n_usinas = len(usinas_participa)

        # A diferenca real (cliente-level) usa o total
        diff = round(kwh_real - esperado_total, 2)
        if kwh_real == 0:
            status = "pendente"
        elif abs(diff) < 0.01:
            status = "ok"
        else:
            status = "divergente"

        linhas.append({
            "uc": uc, "nome": nome, "percentual": pct,
            "kwh_esperado": kwh_esperado_aqui,           # esperado desta usina
            "kwh_esperado_total": esperado_total,        # esperado de todas as usinas
            "kwh_real": kwh_real,                         # total recebido na fatura
            "diferenca": diff,                            # real - total esperado
            "status": status,
            "n_usinas": n_usinas,                         # quantas usinas o cliente participa
            "multi_usina": n_usinas > 1,
        })

    soma_pct = round(sum(l["percentual"] for l in linhas), 2)
    soma_esperado = round(sum(l["kwh_esperado"] for l in linhas), 2)
    soma_real = round(sum(l["kwh_real"] for l in linhas), 2)
    diff_total = round(soma_real - soma_esperado, 2)

    return {
        "kwh_gerado": kwh_gerado,
        "soma_pct": soma_pct,
        "soma_esperado": soma_esperado,
        "soma_real": soma_real,
        "diff_total": diff_total,
        "linhas": linhas,
        "rateio": rateio,
        "geracao": geracao,
    }


@app.route("/api/usina/<int:id_usina>")
def api_usina(id_usina):
    try:
        from db import tb_get_usina
        u = tb_get_usina(id_usina)
        if u:
            return jsonify(u)
        return jsonify({"erro": "Usina nao encontrada"}), 404
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# ── MAIN ─────────────────────────────────────────────────────
if __name__ == "__main__":
    # Verifica se as variáveis de ambiente foram carregadas
    if SUPABASE_TOKEN:
        logger.info("✓ Token Supabase carregado do .env")
    else:
        logger.warning("✗ Aviso: Token Supabase nao encontrado no .env")

    import os as _os
    _port = int(_os.environ.get("PORT", "5001"))
    logger.info("=" * 50)
    logger.info("SOLEV — Sistema de Cobranca")
    logger.info(f"http://localhost:{_port}")
    logger.info("=" * 50)
    logger.info("Servidor Flask iniciando...")
    app.run(debug=False, host='0.0.0.0', port=_port, threaded=True)

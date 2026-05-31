"""
Blueprint: inter
Rotas de integração com o Banco Inter.

  POST /inter/webhook             — recebe notificações de pagamento do Inter
  POST /inter/emitir/<id_fatura>  — emite boleto/PIX para uma fatura (admin)
  GET  /inter/status/<id_fatura>  — consulta status atual no Inter
  POST /inter/setup-webhook       — registra a URL de webhook no Inter (setup único)

Segurança do webhook:
  O Inter chama o endpoint sem assinatura HMAC. Protegemos com um token secreto
  na query string: /inter/webhook?token=<INTER_WEBHOOK_TOKEN>
  Defina INTER_WEBHOOK_TOKEN no .env e no Railway.
"""
import os
import logging
from datetime import date, datetime

from flask import Blueprint, request, jsonify, flash, redirect, url_for

from db import _db, tb_marcar_fatura_pago

bp = Blueprint("inter", __name__, url_prefix="/inter")
log = logging.getLogger(__name__)


def _webhook_token_ok() -> bool:
    esperado = os.getenv("INTER_WEBHOOK_TOKEN", "")
    if not esperado:
        log.warning("[inter/webhook] INTER_WEBHOOK_TOKEN não definido — endpoint desprotegido!")
        return True
    return request.args.get("token", "") == esperado


# ── Webhook (chamado pelo Inter quando uma cobrança é paga) ─────────────────

@bp.route("/webhook", methods=["POST"])
def webhook():
    """Recebe notificação de pagamento do Banco Inter e marca a fatura como paga."""
    if not _webhook_token_ok():
        log.warning(f"[inter/webhook] token inválido — IP: {request.remote_addr}")
        return jsonify({"erro": "Não autorizado"}), 401

    data = request.get_json(silent=True) or {}
    log.info(f"[inter/webhook] payload recebido: {data}")

    evento = data.get("evento", "")
    if evento != "COBRANCA_LIQUIDADA":
        # Inter envia outros eventos (ex: COBRANCA_EMITIDA) — ignoramos
        return jsonify({"ok": True, "ignorado": evento}), 200

    nosso_numero = data.get("nossoNumero", "")
    if not nosso_numero:
        return jsonify({"erro": "nossoNumero ausente"}), 400

    # Busca a fatura pelo nossoNumero salvo no momento da emissão
    rows = _db().select(
        "tb_faturas",
        columns="id_fatura,status,vlr_total_com",
        filtros={"inter_nosso_numero": nosso_numero},
    )
    if not rows:
        log.warning(f"[inter/webhook] nossoNumero {nosso_numero} não encontrado em tb_faturas")
        return jsonify({"erro": "fatura não encontrada"}), 404

    fatura = rows[0]
    if fatura.get("status") == "pago":
        log.info(f"[inter/webhook] fatura {fatura['id_fatura']} já estava paga — ignorando")
        return jsonify({"ok": True, "ja_pago": True}), 200

    dt_pgto   = data.get("dataPagamento") or date.today().isoformat()
    vlr_pago  = float(data.get("valorPago") or fatura.get("vlr_total_com") or 0)

    tb_marcar_fatura_pago(
        id_fatura=int(fatura["id_fatura"]),
        dt_pagamento=dt_pgto,
        vlr_pago=vlr_pago,
    )

    # Atualiza status Inter na própria fatura
    _db().patch(
        "tb_faturas",
        {"id_fatura": fatura["id_fatura"]},
        {"inter_status": "PAGO"},
    )

    log.info(f"[inter/webhook] fatura {fatura['id_fatura']} marcada como PAGA "
             f"(vlr={vlr_pago}, dt={dt_pgto})")
    return jsonify({"ok": True}), 200


# ── Emitir boleto para uma fatura ───────────────────────────────────────────

@bp.route("/emitir/<int:id_fatura>", methods=["POST"])
def emitir(id_fatura: int):
    """Emite boleto + PIX no Inter para uma fatura já existente em tb_faturas.

    Salva nossoNumero, linhaDigitavel e pixCopiaECola na fatura.
    Redireciona de volta com flash de sucesso ou erro.
    """
    import inter_api

    # Carrega fatura
    rows = _db().select("tb_faturas", filtros={"id_fatura": id_fatura})
    if not rows:
        flash("Fatura não encontrada.", "danger")
        return redirect(request.referrer or url_for("faturas"))
    fat = rows[0]

    if fat.get("inter_nosso_numero"):
        flash(f"Boleto já emitido: nossoNumero {fat['inter_nosso_numero']}", "warning")
        return redirect(request.referrer or url_for("faturas"))

    # Carrega cliente
    cli_rows = _db().select("tb_clientes", filtros={"id_cliente": fat.get("id_cliente")})
    if not cli_rows:
        flash("Cliente não encontrado.", "danger")
        return redirect(request.referrer or url_for("faturas"))
    cli = cli_rows[0]

    nome     = cli.get("desc_nome", "Cliente SOLEV")
    cpf_cnpj = cli.get("desc_cpf") or cli.get("cpf") or "00000000000"
    valor    = float(fat.get("vlr_total_com") or 0)
    venc     = str(fat.get("dt_venc_solev") or "")[:10]   # YYYY-MM-DD
    mes      = int(fat.get("mes_referencia") or 0)
    ano      = int(fat.get("ano_referencia") or 0)

    if not venc:
        flash("Fatura sem data de vencimento — preencha antes de emitir.", "danger")
        return redirect(request.referrer or url_for("faturas"))

    meses_br = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    mes_label = f"{meses_br[mes]}/{ano}" if 1 <= mes <= 12 else f"{mes}/{ano}"
    descricao = f"Energia solar SOLEV {mes_label}"
    seu_numero = f"SOLEV-{id_fatura}"

    try:
        resultado = inter_api.criar_cobranca(
            valor=valor,
            vencimento_iso=venc,
            nome_pagador=nome,
            cpf_cnpj=cpf_cnpj,
            seu_numero=seu_numero,
            descricao=descricao,
        )
    except Exception as e:
        log.exception(f"[inter/emitir] erro ao emitir fatura {id_fatura}")
        flash(f"Erro ao emitir no Inter: {e}", "danger")
        return redirect(request.referrer or url_for("faturas"))

    nosso_numero   = resultado.get("nossoNumero", "")
    linha_digitavel = resultado.get("linhaDigitavel", "")
    pix_copia      = resultado.get("pixCopiaECola", "")

    _db().patch(
        "tb_faturas",
        {"id_fatura": id_fatura},
        {
            "inter_nosso_numero": nosso_numero,
            "inter_seu_numero":   seu_numero,
            "inter_linha_dig":    linha_digitavel,
            "inter_pix_copia":    pix_copia,
            "inter_status":       "EMABERTO",
            "inter_dt_emissao":   datetime.now().date().isoformat(),
        },
    )

    flash(f"Boleto emitido! nossoNumero: {nosso_numero}", "success")
    return redirect(request.referrer or url_for("faturas"))


# ── Consultar status no Inter ────────────────────────────────────────────────

@bp.route("/status/<int:id_fatura>", methods=["GET"])
def status(id_fatura: int):
    """Consulta status atualizado de uma cobrança diretamente no Inter."""
    import inter_api

    rows = _db().select(
        "tb_faturas",
        columns="id_fatura,inter_nosso_numero,inter_status,status",
        filtros={"id_fatura": id_fatura},
    )
    if not rows:
        return jsonify({"erro": "fatura não encontrada"}), 404

    fat = rows[0]
    nosso_numero = fat.get("inter_nosso_numero")
    if not nosso_numero:
        return jsonify({"erro": "boleto ainda não emitido para esta fatura"}), 404

    try:
        inter_data = inter_api.get_cobranca(nosso_numero)
    except Exception as e:
        return jsonify({"erro": str(e)}), 502

    return jsonify({
        "id_fatura":      id_fatura,
        "nosso_numero":   nosso_numero,
        "status_solev":   fat.get("status"),
        "status_inter":   inter_data.get("situacao"),
        "valor_pago":     inter_data.get("valorTotalRecebido"),
        "data_pagamento": inter_data.get("dataPagamento"),
    })


# ── Setup do webhook (executar uma vez) ────────────────────────────────────

@bp.route("/setup-webhook", methods=["POST"])
def setup_webhook():
    """Registra a URL de webhook no Inter. Executar uma vez após o deploy."""
    import inter_api

    webhook_token = os.getenv("INTER_WEBHOOK_TOKEN", "")
    base_url = request.host_url.rstrip("/")
    url = f"{base_url}/inter/webhook"
    if webhook_token:
        url += f"?token={webhook_token}"

    try:
        resultado = inter_api.configurar_webhook(url)
    except Exception as e:
        flash(f"Erro ao configurar webhook: {e}", "danger")
        return redirect(request.referrer or "/")

    flash(f"Webhook registrado: {url}", "success")
    return redirect(request.referrer or "/")

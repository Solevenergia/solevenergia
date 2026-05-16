"""
Blueprint: WhatsApp
Rotas: /whatsapp/config, /whatsapp/enviar_rateio, /api/alertas_rateio,
       /api/whatsapp/check_e_enviar
"""
import json
import os
import urllib.parse
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

from db import carregar_usinas, carregar_clientes

bp = Blueprint('whatsapp', __name__)

# Placeholders para evitar import circular na inicializacao
_carregar_rateios_mensais_fn = None
_norm_mes_fn = None

def _inicializar_funcoes():
    """Inicializa funcoes de app.py apos o modulo estar carregado."""
    global _carregar_rateios_mensais_fn, _norm_mes_fn
    if _carregar_rateios_mensais_fn is None:
        try:
            from app import carregar_rateios_mensais, _norm_mes
            _carregar_rateios_mensais_fn = carregar_rateios_mensais
            _norm_mes_fn = _norm_mes
        except ImportError:
            pass

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WHATSAPP_CONFIG_JSON = os.path.join(_PROJECT_DIR, "whatsapp_config.json")


def _carregar_whatsapp_config():
    if os.path.exists(WHATSAPP_CONFIG_JSON):
        with open(WHATSAPP_CONFIG_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"telefone": "", "ativo": False}


def _salvar_whatsapp_config(cfg):
    with open(WHATSAPP_CONFIG_JSON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


def _calcular_alertas_rateio():
    """Calcula alertas de rateio para todas as usinas.
    Rateio deve acontecer 8 dias antes da proxima leitura."""
    # Inicializa funcoes de app.py se ainda nao foram carregadas
    _inicializar_funcoes()
    if _carregar_rateios_mensais_fn is None or _norm_mes_fn is None:
        return []  # Retorna vazio se ainda nao conseguiu importar

    usinas = carregar_usinas()
    clientes = carregar_clientes()
    hoje = datetime.now().date()
    alertas = []
    rateios_todos = _carregar_rateios_mensais_fn()
    mes_atual_key = _norm_mes_fn(f"{hoje.month}/{hoje.year}")

    for uid, u in usinas.items():
        prox = u.get("proxima_leitura", "")
        if not prox:
            continue
        try:
            prox_date = datetime.strptime(prox, "%d/%m/%Y").date()
        except Exception:
            continue

        if rateios_todos.get(uid, {}).get(mes_atual_key, {}).get("protocolo"):
            continue

        data_rateio = prox_date - timedelta(days=8)
        dias_restantes = (data_rateio - hoje).days

        vinculados = {uc: c for uc, c in clientes.items() if c.get("usina_id") == uid}
        total_rateio = sum((c.get("rateio_pct", 0) or 0) for c in vinculados.values())

        status = "ok"
        if dias_restantes <= 0:
            status = "atrasado"
        elif dias_restantes <= 3:
            status = "urgente"
        elif dias_restantes <= 8:
            status = "proximo"

        alertas.append({
            "uid": uid,
            "nome": u.get("nome", uid),
            "uc_geradora": u.get("uc_geradora", ""),
            "proxima_leitura": prox,
            "proxima_leitura_date": prox_date,
            "data_rateio": data_rateio.strftime("%d/%m/%Y"),
            "data_rateio_date": data_rateio,
            "dias_restantes": dias_restantes,
            "status": status,
            "total_clientes": len(vinculados),
            "total_rateio_pct": round(total_rateio, 2),
            "geracao_media": u.get("geracao_media_mensal", 0) or 0,
        })

    alertas.sort(key=lambda x: x["dias_restantes"])
    return alertas


def _gerar_msg_whatsapp_rateio(alertas):
    """Gera mensagem de texto para alertas de rateio via WhatsApp."""
    if not alertas:
        return ""
    linhas = ["*SOLEV - Alertas de Rateio*", ""]
    for a in alertas:
        icon = "🔴" if a["status"] == "atrasado" else "🟡" if a["status"] == "urgente" else "🟢"
        linhas.append(f"{icon} *{a['nome']}*")
        linhas.append(f"   UC: {a['uc_geradora']}")
        linhas.append(f"   Prox. Leitura: {a['proxima_leitura']}")
        linhas.append(f"   Rateio ate: {a['data_rateio']}")
        if a["dias_restantes"] <= 0:
            linhas.append(f"   ATRASADO {abs(a['dias_restantes'])} dia(s)")
        else:
            linhas.append(f"   Faltam {a['dias_restantes']} dia(s)")
        linhas.append(f"   Clientes: {a['total_clientes']} | Rateio: {a['total_rateio_pct']}%")
        linhas.append("")
    linhas.append(f"_Enviado em {datetime.now().strftime('%d/%m/%Y %H:%M')}_")
    return "\n".join(linhas)


@bp.route("/whatsapp/config", methods=["GET", "POST"])
def whatsapp_config():
    cfg = _carregar_whatsapp_config()
    if request.method == "POST":
        cfg["telefone"] = request.form.get("telefone", "").strip()
        cfg["ativo"] = request.form.get("ativo") == "1"
        _salvar_whatsapp_config(cfg)
        flash("Configuracao do WhatsApp salva!", "success")
        return redirect(url_for(".whatsapp_config"))
    alertas = _calcular_alertas_rateio()
    return render_template("whatsapp_config.html", cfg=cfg, alertas=alertas)


@bp.route("/whatsapp/enviar_rateio")
def whatsapp_enviar_rateio():
    cfg = _carregar_whatsapp_config()
    telefone = cfg.get("telefone", "")
    if not telefone:
        flash("Configure o numero do WhatsApp primeiro!", "warning")
        return redirect(url_for(".whatsapp_config"))
    alertas = _calcular_alertas_rateio()
    ativos = [a for a in alertas if a["status"] in ("atrasado", "urgente", "proximo")]
    if not ativos:
        ativos = alertas
    msg = _gerar_msg_whatsapp_rateio(ativos)
    tel_limpo = telefone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not tel_limpo.startswith("+"):
        tel_limpo = "+55" + tel_limpo
    url_wa = f"https://wa.me/{tel_limpo.replace('+', '')}?text={urllib.parse.quote(msg)}"
    return redirect(url_wa)


@bp.route("/api/alertas_rateio")
def api_alertas_rateio():
    """API que retorna alertas de rateio em JSON.
    Pode ser chamada por agendador externo (Task Scheduler, cron)."""
    alertas = _calcular_alertas_rateio()
    ativos = [a for a in alertas if a["status"] in ("atrasado", "urgente", "proximo")]
    for a in alertas:
        a.pop("proxima_leitura_date", None)
        a.pop("data_rateio_date", None)
    return jsonify({
        "total": len(alertas),
        "ativos": len(ativos),
        "alertas": alertas,
    })


@bp.route("/api/whatsapp/check_e_enviar")
def api_whatsapp_check():
    """Endpoint para verificacao automatica.
    Use com agendador para automatizar (ex: curl http://localhost:5000/api/whatsapp/check_e_enviar)."""
    cfg = _carregar_whatsapp_config()
    if not cfg.get("ativo"):
        return jsonify({"ok": False, "msg": "WhatsApp desativado nas configuracoes."})
    telefone = cfg.get("telefone", "")
    if not telefone:
        return jsonify({"ok": False, "msg": "Telefone nao configurado."})
    alertas = _calcular_alertas_rateio()
    ativos = [a for a in alertas if a["status"] in ("atrasado", "urgente", "proximo")]
    if not ativos:
        return jsonify({"ok": True, "msg": "Sem alertas de rateio no momento.", "alertas": 0})
    msg = _gerar_msg_whatsapp_rateio(ativos)
    tel_limpo = telefone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not tel_limpo.startswith("+"):
        tel_limpo = "+55" + tel_limpo
    url_wa = f"https://wa.me/{tel_limpo.replace('+', '')}?text={urllib.parse.quote(msg)}"
    return jsonify({
        "ok": True,
        "msg": f"{len(ativos)} alerta(s) de rateio encontrado(s).",
        "alertas": len(ativos),
        "whatsapp_url": url_wa,
        "mensagem": msg,
    })

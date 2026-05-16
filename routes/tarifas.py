"""
Blueprint: Tarifas
Rotas: /tarifas, /tarifas/nova, /tarifas/editar, /tarifas/remover, /api/tarifa
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from db import carregar_tarifas, salvar_tarifas, salvar_tarifa_mes
from contalev_cobranca_v2_padrao import _fmt_brl
from utils import obter_tarifa_mes

bp = Blueprint('tarifas', __name__)


@bp.route("/api/tarifa/<path:mes>")
def api_tarifa(mes):
    t = obter_tarifa_mes(mes)
    if t:
        return jsonify({
            "tarifa": t.get("tarifa_sem", 0) or 0,
            "bandeira_amarela": t.get("bandeira_amarela", 0) or 0,
            "bandeira_vermelha": t.get("bandeira_vermelha", 0) or 0,
            "fio_b": t.get("fio_b", 0) or 0,
            "origem": "tarifas.json",
        })
    return jsonify({"tarifa": None, "origem": "nao cadastrada"})


@bp.route("/tarifas")
def tarifas_lista():
    tarifas = carregar_tarifas()
    def _sort_key(k):
        parts = k.split("/")
        if len(parts) == 2:
            try:
                return int(parts[1]) * 100 + int(parts[0])
            except ValueError:
                return 0
        return 0
    tarifas_ord = sorted(tarifas.items(), key=lambda x: _sort_key(x[0]), reverse=True)
    return render_template("tarifas.html", tarifas=tarifas_ord, fmt=_fmt_brl)


@bp.route("/tarifas/nova", methods=["GET", "POST"])
def tarifa_nova():
    if request.method == "POST":
        mes_ref = request.form.get("mes_referencia", "").strip()
        if not mes_ref:
            flash("Mes de referencia e obrigatorio!", "danger")
            return redirect(url_for(".tarifa_nova"))
        tarifas = carregar_tarifas()
        tarifas[mes_ref] = {
            "tarifa_sem":       float(request.form.get("tarifa_sem", "0").replace(",", ".") or "0"),
            "bandeira_amarela": float(request.form.get("bandeira_amarela", "0").replace(",", ".") or "0"),
            "bandeira_vermelha":float(request.form.get("bandeira_vermelha", "0").replace(",", ".") or "0"),
            "fio_b":            float(request.form.get("fio_b", "0").replace(",", ".") or "0"),
            "observacao":       request.form.get("observacao", "").strip(),
        }
        salvar_tarifas(tarifas)
        flash(f"Tarifa {mes_ref} salva!", "success")
        return redirect(url_for(".tarifas_lista"))
    return render_template("tarifa_form.html", tarifa=None, mes_ref="")


@bp.route("/tarifas/editar/<path:mes_ref>", methods=["GET", "POST"])
def tarifa_editar(mes_ref):
    tarifas = carregar_tarifas()
    if mes_ref not in tarifas:
        flash("Tarifa nao encontrada!", "danger")
        return redirect(url_for(".tarifas_lista"))
    if request.method == "POST":
        novo_mes = request.form.get("mes_referencia", mes_ref).strip()
        dados = {
            "tarifa_sem":       float(request.form.get("tarifa_sem", "0").replace(",", ".") or "0"),
            "bandeira_amarela": float(request.form.get("bandeira_amarela", "0").replace(",", ".") or "0"),
            "bandeira_vermelha":float(request.form.get("bandeira_vermelha", "0").replace(",", ".") or "0"),
            "fio_b":            float(request.form.get("fio_b", "0").replace(",", ".") or "0"),
            "observacao":       request.form.get("observacao", "").strip(),
        }
        salvar_tarifa_mes(novo_mes, dados, mes_ref_antigo=mes_ref)
        flash(f"Tarifa {novo_mes} atualizada!", "success")
        return redirect(url_for(".tarifas_lista"))
    return render_template("tarifa_form.html", tarifa=tarifas[mes_ref], mes_ref=mes_ref)


@bp.route("/tarifas/remover/<path:mes_ref>")
def tarifa_remover(mes_ref):
    tarifas = carregar_tarifas()
    if mes_ref in tarifas:
        del tarifas[mes_ref]
        salvar_tarifas(tarifas)
        flash(f"Tarifa {mes_ref} removida!", "warning")
    return redirect(url_for(".tarifas_lista"))

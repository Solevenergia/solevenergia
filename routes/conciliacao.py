"""
Blueprint: Conciliacao
Rotas: /conciliacao, /conciliacao/<uid>, /conciliacao/<uid>/geracao,
       /conciliacao/<uid>/rateio, /conciliacao/<uid>/copiar_rateio

Helpers (calcular_conciliacao, obter_rateio_mes, obter_geracao_mes,
_norm_mes, carregar_rateios_mensais, salvar_rateios_mensais) ainda
ficam em app.py — serao movidos com usinas/rateio na Fase 2c.
"""
import os
import logging
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash

from extrair_equatorial import extrair_equatorial
from contalev_cobranca_v2_padrao import _fmt_brl
from utils import _fmt_uc15
from db import (
    carregar_usinas, carregar_clientes,
    carregar_geracao_mensal, salvar_geracao_mensal,
)

bp = Blueprint('conciliacao', __name__)

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_FOLDER = os.path.join(_PROJECT_DIR, "uploads")


@bp.route("/conciliacao")
def conciliacao_lista():
    from app import _norm_mes, calcular_conciliacao

    usinas = carregar_usinas()
    try:
        from db import tb_carregar_usinas
        for u in tb_carregar_usinas():
            uid_str = str(u["id_usina"])
            if uid_str not in usinas:
                usinas[uid_str] = {"nome": u.get("desc_nome", uid_str)}
    except Exception as _e:
        logging.error(f"[conciliacao_lista] tb_usinas: {_e}")

    mes_atual = f"{datetime.now().month}/{datetime.now().year}"
    mes_filtro = _norm_mes(request.args.get("mes", mes_atual))

    overview = []
    for uid, u in usinas.items():
        conc = calcular_conciliacao(uid, mes_filtro)
        rateio_existe = conc["rateio"] is not None
        geracao_existe = conc["geracao"] is not None

        if not rateio_existe and not geracao_existe:
            status = "sem_dados"
        elif not rateio_existe or not geracao_existe:
            status = "incompleto"
        else:
            divergentes = sum(1 for l in conc["linhas"] if l["status"] == "divergente")
            pendentes = sum(1 for l in conc["linhas"] if l["status"] == "pendente")
            if pendentes > 0:
                status = "pendente"
            elif divergentes > 0:
                status = "divergente"
            else:
                status = "ok"

        overview.append({
            "uid": uid, "nome": u.get("nome", uid),
            "kwh_gerado": conc["kwh_gerado"],
            "soma_esperado": conc["soma_esperado"],
            "soma_real": conc["soma_real"],
            "diff": conc["diff_total"],
            "status": status,
            "n_beneficiarios": len(conc["linhas"]),
        })

    return render_template("conciliacao_lista.html",
        overview=overview, mes_filtro=mes_filtro, fmt=_fmt_brl)


@bp.route("/conciliacao/<uid>", methods=["GET"])
def conciliacao_detalhe(uid):
    from app import (_norm_mes, calcular_conciliacao,
                     obter_rateio_mes, obter_geracao_mes,
                     carregar_rateios_mensais)

    usinas = carregar_usinas()
    try:
        from db import tb_carregar_usinas as _tbu
        for u in _tbu():
            uid_str = str(u["id_usina"])
            if uid_str not in usinas:
                usinas[uid_str] = {"nome": u.get("desc_nome", uid_str)}
    except Exception:
        pass

    usina = usinas.get(uid)
    if usina is None:
        flash("Usina nao encontrada!", "danger")
        return redirect(url_for(".conciliacao_lista"))

    mes_atual = f"{datetime.now().month}/{datetime.now().year}"
    mes_ref = _norm_mes(request.args.get("mes", mes_atual))

    # ── Lista de todos os clientes (legado + tb_clientes) ──
    clientes = carregar_clientes()
    todos_clientes = [{"uc": uc, "uc_display": uc, "nome": c.get("nome", "")} for uc, c in clientes.items()]
    try:
        from db import tb_carregar_clientes as _tbc
        ucs_vistos = {c["uc"] for c in todos_clientes}
        for c_tb in _tbc():
            uc_tb = c_tb.get("cod_uc", "")
            if uc_tb and uc_tb not in ucs_vistos:
                uc_alt = c_tb.get("cod_uc", "") or ""
                todos_clientes.append({
                    "uc":         uc_tb,
                    "uc_display": _fmt_uc15(uc_alt) if uc_alt else uc_tb,
                    "nome":       c_tb.get("desc_nome", ""),
                })
                ucs_vistos.add(uc_tb)
    except Exception as _e:
        logging.error(f"[conciliacao_detalhe] tb_clientes: {_e}")
    todos_clientes.sort(key=lambda x: x["nome"])

    rateio = obter_rateio_mes(uid, mes_ref)
    geracao = obter_geracao_mes(uid, mes_ref)
    conc = calcular_conciliacao(uid, mes_ref)

    pct_map = {}
    if rateio:
        for b in rateio.get("beneficiarios", []):
            pct_map[b["uc"]] = b.get("percentual", 0) or 0

    outras_usinas_map = {}
    todos_rateios = carregar_rateios_mensais()
    for outro_uid, meses in todos_rateios.items():
        if outro_uid == uid:
            continue
        rat_outro = meses.get(mes_ref)
        if not rat_outro:
            continue
        nome_outra = usinas.get(outro_uid, {}).get("nome", outro_uid)
        for b in rat_outro.get("beneficiarios", []):
            uc_b = b.get("uc", "")
            outras_usinas_map.setdefault(uc_b, []).append({
                "uid": outro_uid, "nome": nome_outra,
                "percentual": b.get("percentual", 0) or 0,
            })

    rateios_all = todos_rateios.get(uid, {})
    meses_disponiveis = sorted(rateios_all.keys(),
        key=lambda m: (int(m.split("/")[1]), int(m.split("/")[0])) if "/" in m else (0, 0),
        reverse=True)

    return render_template("conciliacao.html",
        usina=usina, uid=uid, mes_ref=mes_ref,
        todos_clientes=todos_clientes, rateio=rateio, geracao=geracao,
        conciliacao=conc, pct_map=pct_map,
        outras_usinas_map=outras_usinas_map,
        meses_disponiveis=meses_disponiveis, fmt=_fmt_brl)


@bp.route("/conciliacao/<uid>/geracao", methods=["POST"])
def conciliacao_salvar_geracao(uid):
    from app import _norm_mes

    mes_ref = _norm_mes(request.form.get("mes_ref", "").strip())
    if not mes_ref:
        flash("Mes de referencia e obrigatorio!", "danger")
        return redirect(url_for(".conciliacao_detalhe", uid=uid))

    try:
        kwh = float(request.form.get("kwh_gerado", "0").replace(",", ".") or "0")
    except Exception:
        kwh = 0

    pdf_path = ""
    if "geracao_pdf" in request.files:
        f = request.files["geracao_pdf"]
        if f and f.filename:
            fname = f"usina_{uid}_geracao_{mes_ref.replace('/', '')}.pdf"
            pdf_path = os.path.join(UPLOAD_FOLDER, fname)
            f.save(pdf_path)

    if request.form.get("extrair") == "1" and pdf_path:
        try:
            extraido = extrair_equatorial(pdf_path, verbose=False)
            kwh_ext = extraido.get("consumo_kwh", 0) or 0
            if kwh_ext > 0:
                kwh = kwh_ext
                flash(f"Geracao extraida do PDF: {kwh} kWh", "info")
        except Exception as e:
            flash(f"Nao foi possivel extrair do PDF ({e}). Use entrada manual.", "warning")

    geracao = carregar_geracao_mensal()
    if uid not in geracao:
        geracao[uid] = {}

    entrada = {
        "kwh_gerado": kwh,
        "data_registro": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "origem": "extraido" if request.form.get("extrair") == "1" else "manual",
    }
    if pdf_path:
        entrada["fatura_pdf"] = pdf_path
    elif geracao.get(uid, {}).get(mes_ref, {}).get("fatura_pdf"):
        entrada["fatura_pdf"] = geracao[uid][mes_ref]["fatura_pdf"]

    geracao[uid][mes_ref] = entrada
    salvar_geracao_mensal(geracao)
    flash(f"Geracao de {mes_ref} salva: {kwh} kWh", "success")
    return redirect(url_for(".conciliacao_detalhe", uid=uid, mes=mes_ref))


@bp.route("/conciliacao/<uid>/rateio", methods=["POST"])
def conciliacao_salvar_rateio(uid):
    from app import _norm_mes, carregar_rateios_mensais, salvar_rateios_mensais

    mes_ref = _norm_mes(request.form.get("mes_ref", "").strip())
    if not mes_ref:
        flash("Mes de referencia e obrigatorio!", "danger")
        return redirect(url_for(".conciliacao_detalhe", uid=uid))

    clientes = carregar_clientes()
    todos_ucs = set(clientes.keys())
    try:
        from db import tb_carregar_clientes as _tbc
        for c_tb in _tbc():
            if c_tb.get("cod_uc"):
                todos_ucs.add(c_tb["cod_uc"])
    except Exception as _e:
        logging.error(f"[conciliacao_salvar_rateio] tb_clientes: {_e}")

    beneficiarios = []
    for uc in todos_ucs:
        pct_str = request.form.get(f"pct_{uc}", "0").replace(",", ".")
        try:
            pct = float(pct_str or "0")
        except Exception:
            pct = 0
        if pct > 0:
            beneficiarios.append({"uc": uc, "percentual": round(pct, 4)})

    soma = round(sum(b["percentual"] for b in beneficiarios), 2)

    rateios = carregar_rateios_mensais()
    if uid not in rateios:
        rateios[uid] = {}
    existente = rateios[uid].get(mes_ref, {})
    rateios[uid][mes_ref] = {
        "data_registro": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "soma_percentual": soma,
        "beneficiarios": beneficiarios,
        **{k: existente[k] for k in ("protocolo", "via_envio", "data_protocolo") if k in existente},
    }
    salvar_rateios_mensais(rateios)

    if abs(soma - 100) > 0.01:
        flash(f"Rateio salvo, mas atencao: soma e {soma}% (deveria ser 100%)", "warning")
    else:
        flash(f"Rateio de {mes_ref} salvo: 100% distribuido entre {len(beneficiarios)} clientes", "success")
    return redirect(url_for(".conciliacao_detalhe", uid=uid, mes=mes_ref))


@bp.route("/conciliacao/<uid>/copiar_rateio", methods=["POST"])
def conciliacao_copiar_rateio(uid):
    from app import _norm_mes, carregar_rateios_mensais, salvar_rateios_mensais

    mes_destino = _norm_mes(request.form.get("mes_ref", "").strip())
    mes_origem  = _norm_mes(request.form.get("mes_origem", "").strip())
    if not mes_destino or not mes_origem:
        flash("Selecione o mes de origem!", "danger")
        return redirect(url_for(".conciliacao_detalhe", uid=uid))
    rateios = carregar_rateios_mensais()
    origem = rateios.get(uid, {}).get(mes_origem)
    if not origem:
        flash(f"Nao ha rateio em {mes_origem} para copiar.", "warning")
        return redirect(url_for(".conciliacao_detalhe", uid=uid, mes=mes_destino))
    if uid not in rateios:
        rateios[uid] = {}
    rateios[uid][mes_destino] = {
        "data_registro": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "soma_percentual": origem.get("soma_percentual", 0) or 0,
        "beneficiarios": [dict(b) for b in origem.get("beneficiarios", [])],
    }
    salvar_rateios_mensais(rateios)
    flash(f"Rateio copiado de {mes_origem} -> {mes_destino}", "success")
    return redirect(url_for(".conciliacao_detalhe", uid=uid, mes=mes_destino))

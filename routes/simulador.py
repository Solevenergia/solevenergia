"""
Blueprint: Simulador
Rotas: /simulador, /simulador/excluir/<id_sim>, /simulador/importar/<id_sim>
"""
import json
import os
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash

from extrair_equatorial import extrair_equatorial
from contalev_cobranca_v2_padrao import _fmt_brl
from utils import obter_tarifa_mes
from db import (
    carregar_tarifas,
    carregar_simulacoes as _db_carregar_simulacoes,
    salvar_simulacao as _db_salvar_simulacao,
    atualizar_simulacao as _db_atualizar_simulacao,
    deletar_simulacao as _db_deletar_simulacao,
)

bp = Blueprint('simulador', __name__)

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_FOLDER = os.path.join(_PROJECT_DIR, "uploads")


def carregar_simulacoes():
    return _db_carregar_simulacoes()


@bp.route("/simulador", methods=["GET", "POST"])
def simulador():
    resultado = None
    pdf_name = None
    if request.method == "POST":
        modo = request.form.get("modo", "manual")

        if modo == "pdf":
            # ── Modo PDF: extrai da fatura Equatorial ──
            if "pdf_equatorial" not in request.files or request.files["pdf_equatorial"].filename == "":
                flash("Selecione um PDF!", "danger")
                return redirect(url_for(".simulador"))
            pdf = request.files["pdf_equatorial"]
            pdf_path = os.path.join(UPLOAD_FOLDER, pdf.filename)
            pdf.save(pdf_path)
            try:
                equatorial = extrair_equatorial(pdf_path, verbose=False)
            except Exception as e:
                flash(f"Erro ao extrair: {e}", "danger")
                return redirect(url_for(".simulador"))

            nome = equatorial.get("nome", "").upper().strip()
            if not nome:
                nome = request.form.get("nome_pdf", "CLIENTE").strip().upper()
            telefone = request.form.get("telefone_pdf", "").strip()
            desconto = float(request.form.get("desconto_pdf", "20").replace(",", ".") or "20")
            if desconto > 1:
                desconto = desconto / 100

            consumo = equatorial.get("consumo_kwh", 0) or 0
            mes_ref = equatorial.get("mes_referencia", "") or ""

            # Prioridade: tarifas cadastradas > extraida do PDF > fallback
            tarifa_mes = obter_tarifa_mes(mes_ref)
            if tarifa_mes:
                tarifa = tarifa_mes["tarifa_sem"]
                _stored_am = tarifa_mes.get("bandeira_amarela", 0) or 0
                _stored_vm = tarifa_mes.get("bandeira_vermelha", 0) or 0
            else:
                tarifa = equatorial.get("tarifa_scee", 0) or 1.125214
                _stored_am = _stored_vm = 0
            # Bandeira — FONTE ÚNICA: tarifa REAL do PDF (adc/qtd) > tb_tarifas.
            # Antes multiplicava o consumo pelo tb_tarifas velho (0,018053),
            # ignorando o adc/qtd do PDF — mesmo bug que foi corrigido nas telas.
            from utils import resolver_tarifa_bandeira
            _ba, _bv, _ = resolver_tarifa_bandeira(equatorial, _stored_am, _stored_vm)
            band_am = _ba * consumo
            band_vm = _bv * consumo

            compensado = equatorial.get("compensado_kwh", consumo) or consumo
            ilum = equatorial.get("iluminacao_publica", 0) or 0
            multa = equatorial.get("multa", 0) or 0
            juros = equatorial.get("juros", 0) or 0
            email = ""
            endereco = equatorial.get("endereco", "")
            uc = equatorial.get("uc", "")
            cpf = equatorial.get("cpf", "")
            tipo_forn = equatorial.get("tipo_fornecimento", "")
            anterior_leitura = equatorial.get("leitura_anterior", "")
            data_leitura = equatorial.get("data_leitura_atual", "")
            proxima_leitura = equatorial.get("proxima_leitura", "")
            n_dias = equatorial.get("n_dias", "")
            nao_comp = equatorial.get("nao_comp_kwh", 0) or 0
        else:
            # ── Modo manual ──
            nome = request.form.get("nome", "Cliente").strip().upper()
            consumo = float(request.form.get("consumo", "0").replace(",", ".") or "0")
            tarifa = float(request.form.get("tarifa", "1.135823").replace(",", ".") or "1.135823")
            desconto = float(request.form.get("desconto", "20").replace(",", ".") or "20")
            if desconto > 1:
                desconto = desconto / 100
            ilum = float(request.form.get("iluminacao", "0").replace(",", ".") or "0")
            compensado = float(request.form.get("compensado", str(consumo)).replace(",", ".") or str(consumo))
            band_am = float(request.form.get("bandeira_amarela", "0").replace(",", ".") or "0") * consumo
            band_vm = float(request.form.get("bandeira_vermelha", "0").replace(",", ".") or "0") * consumo
            multa = float(request.form.get("multa", "0").replace(",", ".") or "0")
            juros = float(request.form.get("juros", "0").replace(",", ".") or "0")
            mes_ref = request.form.get("mes_referencia", "03/2026").strip()
            telefone = request.form.get("telefone", "").strip()
            email = request.form.get("email", "").strip()
            endereco = request.form.get("endereco", "").strip()
            uc = request.form.get("uc_sim", "").strip()
            cpf = request.form.get("cpf_sim", "").strip()
            tipo_forn = request.form.get("tipo_forn", "").strip()
            anterior_leitura = request.form.get("anterior_leitura", "").strip()
            data_leitura = request.form.get("data_leitura", "").strip()
            proxima_leitura = request.form.get("proxima_leitura", "").strip()
            n_dias = request.form.get("n_dias", "").strip()
            nao_comp = max(0, consumo - compensado)

        modo_bandeira = request.form.get("modo_bandeira", request.form.get("modo_bandeira_pdf", "com_bandeira"))

        nao_comp = max(0, consumo - compensado)
        energia_sem = consumo * tarifa
        total_sem = energia_sem + band_am + band_vm + ilum + multa + juros

        v_band = band_am + band_vm
        bkwh = v_band / consumo if consumo > 0 else 0
        total_kwh = tarifa + bkwh

        tarifa_com = tarifa * (1 - desconto)
        energia_com = consumo * tarifa_com

        if v_band > 0:
            if modo_bandeira == "com_bandeira":
                total_com = energia_com + ilum + multa + juros
                desconto_mostrado = round((total_kwh - tarifa_com) / total_kwh * 100, 2) if total_kwh > 0 else round(desconto * 100, 2)
            else:
                total_com = energia_com + v_band + ilum + multa + juros
                desconto_mostrado = round(desconto * 100, 2)
            desconto_efetivo = (total_kwh - tarifa_com) / total_kwh if total_kwh > 0 else desconto
        else:
            total_com = energia_com + ilum + multa + juros
            desconto_efetivo = desconto
            desconto_mostrado = round(desconto * 100, 2)

        economia_mes = total_sem - total_com
        economia_anual = economia_mes * 12
        desconto_real_pct = (economia_mes / total_sem * 100) if total_sem > 0 else 0

        resultado = {
            "nome": nome, "consumo": consumo, "tarifa": tarifa, "tarifa_com": tarifa_com,
            "desconto": desconto * 100, "desconto_mostrado": desconto_mostrado,
            "desconto_real": round(desconto_real_pct, 1),
            "desconto_efetivo": round(desconto_efetivo * 100, 2),
            "modo_bandeira": modo_bandeira,
            "ilum": ilum,
            "compensado": compensado, "nao_comp": round(nao_comp, 2),
            "band_am": band_am, "band_vm": band_vm,
            "multa": round(multa, 2), "juros": round(juros, 2),
            "mes_referencia": mes_ref, "telefone": telefone, "email": email,
            "endereco": endereco,
            "uc": uc, "cpf": cpf, "tipo_fornecimento": tipo_forn,
            "anterior_leitura": anterior_leitura, "data_leitura": data_leitura,
            "proxima_leitura": proxima_leitura, "n_dias": n_dias,
            "total_sem": round(total_sem, 2), "total_com": round(total_com, 2),
            "economia_mes": round(economia_mes, 2), "economia_anual": round(economia_anual, 2),
        }

        resultado["data"] = datetime.now().strftime("%d/%m/%Y %H:%M")
        resultado["status"] = "Pendente"
        resultado["pdf"] = ""
        sim_id = _db_salvar_simulacao(resultado)

        if request.form.get("gerar_pdf") == "1":
            try:
                from contalev_simulador_web import gerar_simulacao_web
                sim_data = {
                    "nome": nome, "consumo_kwh": consumo, "tarifa_sem": tarifa,
                    "iluminacao_publica": ilum, "bandeira_amarela": band_am,
                    "bandeira_vermelha": band_vm, "mes_referencia": mes_ref,
                    "desconto_pct": desconto, "multa": multa, "juros": juros,
                    "modo_bandeira": modo_bandeira,
                    "uc": uc, "cpf": cpf, "tipo_fornecimento": tipo_forn,
                    "endereco": endereco,
                    "anterior_leitura": anterior_leitura, "data_leitura": data_leitura,
                    "proxima_leitura": proxima_leitura, "n_dias": n_dias,
                    "compensado": compensado, "nao_comp": nao_comp,
                }
                pdf_path = gerar_simulacao_web(sim_data)
                pdf_name = os.path.basename(pdf_path)
                if sim_id:
                    _db_atualizar_simulacao(sim_id, pdf=pdf_name)
                flash(f"Simulacao PDF gerada para {nome}!", "success")
            except Exception as e:
                import traceback
                traceback.print_exc()
                flash(f"Erro ao gerar PDF: {e}", "danger")

    simulacoes = carregar_simulacoes()
    return render_template("simulador.html", resultado=resultado, pdf_name=pdf_name,
                           simulacoes=simulacoes[:20], fmt=_fmt_brl,
                           tarifas_json=json.dumps(carregar_tarifas()))


@bp.route("/simulador/excluir/<int:id_sim>")
def simulacao_excluir(id_sim):
    sims = carregar_simulacoes()
    sim = next((s for s in sims if s.get("id") == id_sim), None)
    if sim:
        nome = sim.get("nome", "")
        pdf = sim.get("pdf", "")
        if pdf:
            p = os.path.join(_PROJECT_DIR, pdf)
            if os.path.exists(p):
                os.remove(p)
        _db_deletar_simulacao(id_sim)
        flash(f"Simulacao de {nome} excluida.", "warning")
    return redirect(url_for(".simulador"))


@bp.route("/simulador/importar/<int:id_sim>", methods=["GET", "POST"])
def simulacao_importar(id_sim):
    from db import (tb_save_cliente, tb_save_endereco, tb_save_cliente_usina,
                    tb_carregar_usinas)
    sims = carregar_simulacoes()
    sim = next((s for s in sims if s.get("id") == id_sim), None)
    if not sim:
        flash("Simulacao nao encontrada!", "danger")
        return redirect(url_for(".simulador"))

    tb_usinas_lst = [u for u in tb_carregar_usinas() if u.get("STATUS") is not False]

    if request.method == "POST":
        uc = request.form.get("uc", "").strip()
        if not uc:
            flash("UC e obrigatoria!", "danger")
            return render_template("simulacao_importar.html", sim=sim, usinas=tb_usinas_lst)

        desc = sim.get("desconto", 20)
        if desc > 1:
            desc = desc / 100

        try:
            cli_dados = {
                "cod_uc":           uc,
                "desc_nome":        sim.get("nome", "").upper(),
                "desc_cpf":         request.form.get("cpf", "").strip(),
                "desc_telefone":    sim.get("telefone", ""),
                "desc_email":       sim.get("email", ""),
                "pct_desconto":     desc,
                "tp_fornecimento":  request.form.get("tipo_fornecimento", "MONOFASICO"),
                "tp_bandeira":      "com_bandeira",
            }
            cli_salvo  = tb_save_cliente(cli_dados)
            id_cliente = cli_salvo.get("id_cliente")

            if id_cliente:
                end_raw = request.form.get("endereco_linha1", sim.get("endereco", "")).strip()
                if end_raw:
                    tb_save_endereco(id_cliente, {"desc_logradouro": end_raw})

            id_usina_sel = request.form.get("id_usina", "").strip()
            rateio = float(request.form.get("rateio_pct", "0").replace(",", ".") or "0")
            if id_cliente and id_usina_sel:
                pct_pct = rateio * 100 if rateio <= 1 else rateio
                tb_save_cliente_usina(id_cliente, int(id_usina_sel),
                                      {"pct_rateio": round(pct_pct, 2)})

            _db_atualizar_simulacao(id_sim, status="Convertido")

            flash(f"Cliente {sim.get('nome', '')} cadastrado com UC {uc}!", "success")
            return redirect(url_for("clientes_lista"))
        except Exception as e:
            flash(f"Erro ao cadastrar: {e}", "danger")

    return render_template("simulacao_importar.html", sim=sim, usinas=tb_usinas_lst)

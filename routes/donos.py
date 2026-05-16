"""
Blueprint: Donos das Usinas
Rotas: /donos, /donos/novo, /donos/editar, /donos/excluir
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash

bp = Blueprint('donos', __name__)


def _extrair_dados_dono(form) -> dict:
    """Extrai campos do formulario de dono."""
    from utils import _data_br_para_iso
    return {
        "desc_nome":     form.get("desc_nome", "").strip(),
        "desc_cpf_cnpj": form.get("desc_cpf_cnpj", "").strip() or None,
        "desc_telefone": form.get("desc_telefone", "").strip() or None,
        "desc_email":    form.get("desc_email", "").strip() or None,
        "dt_nascimento": _data_br_para_iso(form.get("dt_nascimento", "")) or None,
    }


@bp.route("/donos")
def donos_lista():
    from db import tb_carregar_donos, tb_carregar_usinas
    donos = tb_carregar_donos()
    usinas = tb_carregar_usinas()
    for d in donos:
        d["_usinas"] = [
            {"id_usina": u.get("id_usina"), "desc_nome": u.get("desc_nome")}
            for u in usinas if u.get("id_dono") == d.get("id_dono")
        ]
        d["_usinas_count"] = len(d["_usinas"])
    return render_template("donos.html", donos=donos)


@bp.route("/donos/novo", methods=["GET", "POST"])
def dono_novo():
    from db import tb_save_dono
    if request.method == "POST":
        try:
            nome = request.form.get("desc_nome", "").strip()
            if not nome:
                flash("Informe o nome do dono!", "danger")
                return redirect(url_for(".dono_novo"))
            dados = _extrair_dados_dono(request.form)
            tb_save_dono(dados)
            flash("Dono cadastrado!", "success")
            return redirect(url_for(".donos_lista"))
        except Exception as e:
            flash(f"Erro ao salvar: {e}", "danger")
    return render_template("dono_form.html", dono=None)


@bp.route("/donos/editar/<int:id_dono>", methods=["GET", "POST"])
def dono_editar(id_dono):
    from db import tb_get_dono, tb_save_dono
    dono = tb_get_dono(id_dono)
    if not dono:
        flash("Dono nao encontrado!", "danger")
        return redirect(url_for(".donos_lista"))
    if request.method == "POST":
        try:
            nome = request.form.get("desc_nome", "").strip()
            if not nome:
                flash("Informe o nome do dono!", "danger")
                return redirect(url_for(".dono_editar", id_dono=id_dono))
            dados = _extrair_dados_dono(request.form)
            dados["id_dono"] = id_dono
            tb_save_dono(dados)
            flash("Dono atualizado!", "success")
            return redirect(url_for(".donos_lista"))
        except Exception as e:
            flash(f"Erro ao salvar: {e}", "danger")
    return render_template("dono_form.html", dono=dono)


@bp.route("/donos/excluir/<int:id_dono>")
def dono_excluir(id_dono):
    from db import tb_carregar_usinas, tb_delete_dono
    usinas = tb_carregar_usinas()
    em_uso = any(u.get("id_dono") == id_dono for u in usinas)
    if em_uso:
        flash("Nao e possivel excluir: este dono esta vinculado a uma ou mais usinas.", "danger")
        return redirect(url_for(".donos_lista"))
    tb_delete_dono(id_dono)
    flash("Dono excluido.", "warning")
    return redirect(url_for(".donos_lista"))

"""
Blueprint: Titulares das UCs (das usinas)
Rotas: /titulares, /titulares/novo, /titulares/editar, /titulares/excluir
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash

bp = Blueprint('titulares', __name__)


def _extrair_dados_titular(form) -> dict:
    """Extrai campos do formulario de titular."""
    from utils import _data_br_para_iso
    return {
        "desc_nome":     form.get("desc_nome", "").strip(),
        "desc_cpf_cnpj": form.get("desc_cpf_cnpj", "").strip() or None,
        "desc_telefone": form.get("desc_telefone", "").strip() or None,
        "desc_email":    form.get("desc_email", "").strip() or None,
        "dt_nascimento": _data_br_para_iso(form.get("dt_nascimento", "")) or None,
    }


@bp.route("/titulares")
def titulares_lista():
    from db import tb_carregar_titulares, tb_carregar_usinas
    titulares = tb_carregar_titulares()
    usinas = tb_carregar_usinas()
    for t in titulares:
        t["_usinas"] = [
            {"id_usina": u.get("id_usina"), "desc_nome": u.get("desc_nome")}
            for u in usinas if u.get("id_titular") == t.get("id_titular")
        ]
        t["_usinas_count"] = len(t["_usinas"])
    return render_template("titulares.html", titulares=titulares)


@bp.route("/titulares/novo", methods=["GET", "POST"])
def titular_novo():
    from db import tb_save_titular
    if request.method == "POST":
        try:
            nome = request.form.get("desc_nome", "").strip()
            if not nome:
                flash("Informe o nome do titular!", "danger")
                return redirect(url_for(".titular_novo"))
            dados = _extrair_dados_titular(request.form)
            tb_save_titular(dados)
            flash("Titular cadastrado!", "success")
            return redirect(url_for(".titulares_lista"))
        except Exception as e:
            flash(f"Erro ao salvar: {e}", "danger")
    return render_template("titular_form.html", titular=None)


@bp.route("/titulares/editar/<int:id_titular>", methods=["GET", "POST"])
def titular_editar(id_titular):
    from db import tb_get_titular, tb_save_titular
    titular = tb_get_titular(id_titular)
    if not titular:
        flash("Titular nao encontrado!", "danger")
        return redirect(url_for(".titulares_lista"))
    if request.method == "POST":
        try:
            nome = request.form.get("desc_nome", "").strip()
            if not nome:
                flash("Informe o nome do titular!", "danger")
                return redirect(url_for(".titular_editar", id_titular=id_titular))
            dados = _extrair_dados_titular(request.form)
            dados["id_titular"] = id_titular
            tb_save_titular(dados)
            flash("Titular atualizado!", "success")
            return redirect(url_for(".titulares_lista"))
        except Exception as e:
            flash(f"Erro ao salvar: {e}", "danger")
    return render_template("titular_form.html", titular=titular)


@bp.route("/titulares/excluir/<int:id_titular>")
def titular_excluir(id_titular):
    from db import tb_carregar_usinas, tb_delete_titular
    usinas = tb_carregar_usinas()
    em_uso = any(u.get("id_titular") == id_titular for u in usinas)
    if em_uso:
        flash("Nao e possivel excluir: este titular esta vinculado a uma ou mais usinas.", "danger")
        return redirect(url_for(".titulares_lista"))
    tb_delete_titular(id_titular)
    flash("Titular excluido.", "warning")
    return redirect(url_for(".titulares_lista"))

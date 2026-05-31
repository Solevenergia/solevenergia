"""
Blueprint: Recebedores PIX
Rotas: /recebedores, /recebedores/novo, /recebedores/editar, /recebedores/excluir
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash

bp = Blueprint('recebedores', __name__)


def _extrair_dados_recebedor(form) -> dict:
    """Extrai e normaliza campos do formulario de recebedor."""
    nome_completo = form.get("desc_nome", "").strip()
    return {
        "desc_nome":         nome_completo,
        "desc_cpf_cnpj":     form.get("desc_cpf_cnpj", "").strip(),
        "desc_email":        form.get("desc_email", "").strip(),
        "desc_telefone":     form.get("desc_telefone", "").strip(),
        "desc_banco":        form.get("desc_banco", "").strip(),
        "desc_agencia":      form.get("desc_agencia", "").strip(),
        "desc_conta":        form.get("desc_conta", "").strip(),
        "desc_pix":          form.get("desc_pix", "").strip(),
        "pct_desagio":       float(form.get("pct_desagio", "0").replace(",", ".") or "0"),
        "qtd_dia_pagamento": int(form.get("qtd_dia_pagamento", "0") or "0") or None,
        "vlr_minimo":        float(form.get("vlr_minimo", "0").replace(",", ".") or "0"),
    }


_VOLTA = "/usinas?tab=proprietarios"


@bp.route("/recebedores")
def recebedores_lista():
    return redirect(_VOLTA)


@bp.route("/recebedores/novo", methods=["GET", "POST"])
def recebedor_novo():
    from db import tb_save_investidor
    if request.method == "POST":
        try:
            dados = _extrair_dados_recebedor(request.form)
            tb_save_investidor(dados)
            flash("Proprietário cadastrado com sucesso!", "success")
            return redirect(_VOLTA)
        except Exception as e:
            flash(f"Erro ao salvar: {e}", "danger")
    return render_template("recebedor_form.html", rec=None)


@bp.route("/recebedores/editar/<int:id_investidor>", methods=["GET", "POST"])
def recebedor_editar(id_investidor):
    from db import tb_get_investidor, tb_save_investidor
    rec = tb_get_investidor(id_investidor)
    if not rec:
        flash("Proprietário não encontrado!", "danger")
        return redirect(_VOLTA)
    if request.method == "POST":
        try:
            dados = _extrair_dados_recebedor(request.form)
            dados["id_investidor"] = id_investidor
            tb_save_investidor(dados)
            flash("Proprietário atualizado!", "success")
            return redirect(_VOLTA)
        except Exception as e:
            flash(f"Erro ao salvar: {e}", "danger")
    return render_template("recebedor_form.html", rec=rec)


@bp.route("/recebedores/excluir/<int:id_investidor>")
def recebedor_excluir(id_investidor):
    from db import tb_carregar_usinas, tb_delete_investidor
    usinas = tb_carregar_usinas()
    em_uso = any(u.get("id_investidor") == id_investidor for u in usinas)
    if em_uso:
        flash("Não é possível excluir: este proprietário está vinculado a uma ou mais usinas.", "danger")
        return redirect(_VOLTA)
    tb_delete_investidor(id_investidor)
    flash("Proprietário excluído.", "warning")
    return redirect(_VOLTA)

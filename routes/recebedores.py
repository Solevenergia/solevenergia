"""
Blueprint: Recebedores PIX
Rotas: /recebedores, /recebedores/novo, /recebedores/editar, /recebedores/excluir
"""
import unicodedata
from flask import Blueprint, render_template, request, redirect, url_for, flash

bp = Blueprint('recebedores', __name__)


def _extrair_dados_recebedor(form) -> dict:
    """Extrai e normaliza campos do formulario de recebedor."""
    def _ascii(s):
        return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").upper()
    nome_completo  = form.get("desc_nome", "").strip()
    nome_pix_raw   = form.get("desc_nome_pix", "").strip() or nome_completo
    cidade_pix_raw = form.get("desc_cidade_pix", "").strip()
    return {
        "desc_nome":         nome_completo,
        "desc_cpf_cnpj":     form.get("desc_cpf_cnpj", "").strip(),
        "desc_email":        form.get("desc_email", "").strip(),
        "desc_telefone":     form.get("desc_telefone", "").strip(),
        "desc_banco":        form.get("desc_banco", "").strip(),
        "desc_agencia":      form.get("desc_agencia", "").strip(),
        "desc_conta":        form.get("desc_conta", "").strip(),
        "desc_pix":          form.get("desc_pix", "").strip(),
        "desc_nome_pix":     _ascii(nome_pix_raw)[:25],
        "desc_cidade_pix":   _ascii(cidade_pix_raw)[:15] if cidade_pix_raw else None,
        "pct_desagio":       float(form.get("pct_desagio", "0").replace(",", ".") or "0"),
        "qtd_dia_pagamento": int(form.get("qtd_dia_pagamento", "0") or "0") or None,
        "vlr_minimo":        float(form.get("vlr_minimo", "0").replace(",", ".") or "0"),
    }


@bp.route("/recebedores")
def recebedores_lista():
    from db import tb_carregar_investidores, tb_carregar_usinas
    recebedores = tb_carregar_investidores()
    usinas = tb_carregar_usinas()
    for r in recebedores:
        r["_usinas_count"] = sum(
            1 for u in usinas if u.get("id_investidor") == r.get("id_investidor")
        )
    return render_template("recebedores.html", recebedores=recebedores)


@bp.route("/recebedores/novo", methods=["GET", "POST"])
def recebedor_novo():
    from db import tb_save_investidor
    if request.method == "POST":
        try:
            dados = _extrair_dados_recebedor(request.form)
            tb_save_investidor(dados)
            flash("Recebedor cadastrado com sucesso!", "success")
            return redirect(url_for(".recebedores_lista"))
        except Exception as e:
            flash(f"Erro ao salvar: {e}", "danger")
    return render_template("recebedor_form.html", rec=None)


@bp.route("/recebedores/editar/<int:id_investidor>", methods=["GET", "POST"])
def recebedor_editar(id_investidor):
    from db import tb_get_investidor, tb_save_investidor
    rec = tb_get_investidor(id_investidor)
    if not rec:
        flash("Recebedor nao encontrado!", "danger")
        return redirect(url_for(".recebedores_lista"))
    if request.method == "POST":
        try:
            dados = _extrair_dados_recebedor(request.form)
            dados["id_investidor"] = id_investidor
            tb_save_investidor(dados)
            flash("Recebedor atualizado!", "success")
            return redirect(url_for(".recebedores_lista"))
        except Exception as e:
            flash(f"Erro ao salvar: {e}", "danger")
    return render_template("recebedor_form.html", rec=rec)


@bp.route("/recebedores/excluir/<int:id_investidor>")
def recebedor_excluir(id_investidor):
    from db import tb_carregar_usinas, tb_delete_investidor
    usinas = tb_carregar_usinas()
    em_uso = any(u.get("id_investidor") == id_investidor for u in usinas)
    if em_uso:
        flash("Nao e possivel excluir: este recebedor esta vinculado a uma ou mais usinas.", "danger")
        return redirect(url_for(".recebedores_lista"))
    tb_delete_investidor(id_investidor)
    flash("Recebedor excluido.", "warning")
    return redirect(url_for(".recebedores_lista"))

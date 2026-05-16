"""
Blueprint: Contrato
Rotas: /contrato, /contrato/visualizar, /contrato/assets/<filename>
"""
import os
from flask import Blueprint, render_template, request, send_file

bp = Blueprint('contrato', __name__)

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@bp.route("/contrato/assets/<filename>")
def contrato_assets(filename):
    folder = os.path.join(_PROJECT_DIR, "design_handoff_contrato_contalev", "assets")
    filepath = os.path.join(folder, filename)
    if os.path.exists(filepath):
        return send_file(filepath)
    return "", 404


@bp.route("/contrato", methods=["GET"])
def contrato_form():
    from db import tb_carregar_clientes, tb_carregar_usinas
    clientes = tb_carregar_clientes()
    usinas = tb_carregar_usinas()
    return render_template("contrato_form.html", clientes=clientes, usinas=usinas)


@bp.route("/contrato/visualizar", methods=["POST"])
def contrato_visualizar():
    class _D:
        def __getattr__(self, name):
            return request.form.get(name, "")
    return render_template("contrato_pdf.html", d=_D())

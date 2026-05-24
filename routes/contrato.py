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
    folder = os.path.join(_PROJECT_DIR, "design_handoff_solev_brand", "assets")
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


@bp.route("/contrato/cliente/<path:uc>", methods=["GET"])
def contrato_cliente(uc):
    from db import tb_get_cliente_por_uc, tb_get_endereco_cliente, tb_carregar_usinas
    cliente = tb_get_cliente_por_uc(uc)
    if not cliente:
        return {"error": "Cliente não encontrado"}, 404

    id_cliente = cliente["id_cliente"]
    endereco = tb_get_endereco_cliente(id_cliente) or {}
    usinas = tb_carregar_usinas()

    # Pré-preenche com dados do cliente
    cliente_data = {
        "nome_cliente": cliente.get("desc_nome", ""),
        "cpf_cnpj": cliente.get("desc_cpf", ""),
        "email": cliente.get("desc_email", ""),
        "telefone": cliente.get("desc_telefone", ""),
        "endereco": endereco.get("desc_logradouro", ""),
        "numero": endereco.get("desc_numero", ""),
        "complemento": endereco.get("desc_complemento", ""),
        "bairro": endereco.get("desc_setor", ""),
        "cidade": endereco.get("desc_cidade", ""),
        "estado": endereco.get("desc_estado", ""),
        "cep": endereco.get("cod_cep", ""),
    }

    return render_template("contrato_form.html", clientes=[cliente], usinas=usinas,
                           cliente_data=cliente_data, uc_cliente=uc)


@bp.route("/contrato/visualizar", methods=["POST"])
def contrato_visualizar():
    class _D:
        def __getattr__(self, name):
            return request.form.get(name, "")
    return render_template("contrato_pdf.html", d=_D())


@bp.route("/contrato/gerar_pdf", methods=["POST"])
def contrato_gerar_pdf():
    """Gera PDF do contrato via Playwright e salva no Supabase Storage."""
    import os, re, tempfile, unicodedata
    from datetime import datetime
    from flask import current_app, flash, redirect
    from db import (tb_get_cliente_por_uc, tb_save_documento_cliente,
                    storage_upload_pdf, storage_ensure_bucket)

    uc_cliente = request.form.get("uc_cliente", "").strip()

    class _D:
        def __getattr__(self, name):
            return request.form.get(name, "")

    html_str = render_template("contrato_pdf.html", d=_D())

    try:
        from contalev_cobranca_v2_padrao import _html_para_pdf
        pdf_bytes = _html_para_pdf(html_str)
    except Exception as e:
        flash(f"Erro ao gerar PDF: {e}", "danger")
        return redirect("/clientes/ver/" + uc_cliente if uc_cliente else "/contrato")

    nome_raw = request.form.get("nome_cliente", "cliente").strip()
    nome_seguro = re.sub(
        r"[^a-zA-Z0-9_-]", "_",
        unicodedata.normalize("NFKD", nome_raw).encode("ascii", "ignore").decode(),
    )
    nome_arquivo = f"Contrato_{nome_seguro}_{datetime.now().strftime('%Y%m%d')}.pdf"

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    storage_path = None
    try:
        storage_ensure_bucket("documentos")
        storage_path = storage_upload_pdf(tmp_path, nome_arquivo, bucket="documentos")
    except Exception:
        import shutil
        upload_folder = current_app.config.get("UPLOAD_FOLDER", "uploads")
        local_path = os.path.join(upload_folder, nome_arquivo)
        shutil.copy(tmp_path, local_path)
        storage_path = f"local/{nome_arquivo}"
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    if uc_cliente:
        try:
            cliente = tb_get_cliente_por_uc(uc_cliente)
            if cliente:
                tb_save_documento_cliente(
                    id_cliente=cliente["id_cliente"],
                    nome_arquivo=nome_arquivo,
                    tipo_doc="contrato",
                    storage_path=storage_path,
                )
        except Exception as e:
            flash(f"PDF gerado, mas erro ao salvar referência: {e}", "warning")

    flash("Contrato gerado e salvo com sucesso!", "success")
    return redirect(f"/clientes/ver/{uc_cliente}?aba=documentos" if uc_cliente else "/contrato")

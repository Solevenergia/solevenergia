"""
consolidar_fixo.py
Módulo reutilizável para geração de cobranças SOLEV consolidadas
(modelo FIXO — Luiz Camilo e similares).

API pública:
  detectar_consolidaveis(id_cliente_referencia, ano, mes) -> list[int] | None
      Retorna os id_clientes que devem ser consolidados juntos
      (mesmo CPF + todos FIXO + todos com fatura no mesmo mês).
      Retorna None se não há grupo consolidável.

  gerar_pdf(id_clientes, ano, mes) -> dict
      Gera o PDF consolidado e devolve {'path_local', 'storage_key'}.
"""
import os, shutil, tempfile, re
from datetime import datetime
import httpx

from extrair_equatorial import extrair_equatorial
from gerar_cobranca_auto import montar_dados, gerar_qrcode_pix
from contalev_cobranca_v2_padrao import gerar_cobranca
from db import (
    _db, carregar_clientes, storage_upload_pdf, _storage_cfg,
    tb_get_usinas_do_cliente, tb_get_pix_da_usina,
)
from utils import _fmt_uc15

# ─── CONFIG DE FALLBACK ────────────────────────────────────────────────────────
# Para usinas que ainda não têm os PDFs Equatorial no Storage, mantemos um
# mapeamento manual por (id_usina, "MM/YYYY") → caminho local. À medida que o
# fluxo de download de usinas amadurecer, isto vai sair daqui.
PDF_USINA_LOCAL = {
    (23, "03/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USjoseOliveira88-0003.954.137.012-88\202603-EquatorialUCJoseOliveira88.pdf",
    (23, "04/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USjoseOliveira88-0003.954.137.012-88\202604-EquatorialUCJoseOliveira88.pdf",
    (23, "05/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USjoseOliveira88-0003.954.137.012-88\202605-EquatorialUCJoseOliveira88.pdf",
    (22, "03/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USJoseOliveira93-0004.322.044.012-93\202603-EquatorialUCJoseOliveira93.pdf",
    (22, "04/2026"): r"C:\Users\danil\OneDrive\Desktop\Usinas\Todos\USJoseOliveira93-0004.322.044.012-93\202604-EquatorialUCJoseOliveira93.pdf",
}


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _fmt_kwh(v):
    return f"{v:,.2f} kWh".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _norm_mes(s):
    if not s or "/" not in s:
        return s
    m, a = s.split("/")
    return f"{int(m):02d}/{a}"


def _camel(nome: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", nome)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    partes = re.sub(r"[^a-zA-Z0-9 ]", "", s).split()
    return "".join(p.capitalize() for p in partes)


def _baixar_storage_para_tempfile(storage_key: str) -> str | None:
    """Baixa um arquivo do Supabase Storage e retorna o caminho temporário local."""
    if not storage_key:
        return None
    url, key = _storage_cfg()
    parts = storage_key.split("/", 1)
    bucket = parts[0]
    path   = parts[1] if len(parts) > 1 else storage_key
    r = httpx.get(
        f"{url}/storage/v1/object/{bucket}/{path}",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=30,
    )
    if r.status_code != 200:
        return None
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.write(r.content)
    tmp.close()
    return tmp.name


def _resolver_pdf_consumidor(id_cliente: int, ano: int, mes: int) -> str | None:
    """Tenta achar o PDF Equatorial do consumidor: Storage primeiro, depois pdf_equatorial local."""
    db = _db()
    fats = db.select("tb_faturas", raw_params={
        "id_cliente":     f"eq.{id_cliente}",
        "ano_referencia": f"eq.{ano}",
        "mes_referencia": f"eq.{mes}",
    })
    if not fats:
        return None
    f = fats[0]

    # 1) Storage
    storage_key = f.get("pdf_equatorial_url") or ""
    if storage_key:
        # pode estar como "faturas/arquivo.pdf" ou só "arquivo.pdf"
        if "/" not in storage_key:
            storage_key = f"faturas/{storage_key}"
        path = _baixar_storage_para_tempfile(storage_key)
        if path and os.path.exists(path):
            return path

    # 2) Local (pdf_equatorial)
    local = f.get("pdf_equatorial") or ""
    if local and os.path.exists(local):
        return local

    return None


def _resolver_pdf_usina(id_usina: int, ciclo: str) -> str | None:
    """Resolve PDF Equatorial da usina.
    1º) Storage: faturas/usinas/<id_usina>/<YYYYMM>.pdf
    2º) Mapeamento local (fallback dev)
    """
    if not ciclo or "/" not in ciclo:
        return None
    mes, ano = ciclo.split("/")
    yyyymm = f"{ano}{int(mes):02d}"
    storage_key = f"faturas/usinas/{id_usina}/{yyyymm}.pdf"
    p = _baixar_storage_para_tempfile(storage_key)
    if p and os.path.exists(p):
        return p
    # fallback local
    p = PDF_USINA_LOCAL.get((id_usina, ciclo))
    if p and os.path.exists(p):
        return p
    return None


# ─── API PÚBLICA ──────────────────────────────────────────────────────────────

def detectar_consolidaveis(id_cliente_referencia: int, ano: int, mes: int) -> list[int] | None:
    """
    Dado um cliente, retorna a lista de id_clientes que devem ser consolidados
    com ele (incluindo o próprio).

    Critério:
      - Mesmo desc_cpf
      - Todos têm pelo menos 1 vínculo FIXO ativo
      - Todos têm fatura para (ano, mes)

    Retorna None se não há grupo consolidável (precisa pelo menos 2 clientes).
    """
    db = _db()

    # 1) CPF do cliente de referência
    cli_rows = db.select("tb_clientes", filtros={"id_cliente": id_cliente_referencia})
    if not cli_rows:
        return None
    cpf = (cli_rows[0].get("desc_cpf") or "").strip()
    if not cpf:
        return None

    # 2) Clientes do mesmo CPF
    irmaos = db.select("tb_clientes", filtros={"desc_cpf": cpf})
    ids_mesmo_cpf = [c["id_cliente"] for c in irmaos]

    if len(ids_mesmo_cpf) < 2:
        return None

    # 3) Filtra os que têm vínculo FIXO ativo
    fixos = []
    for id_c in ids_mesmo_cpf:
        vincs = db.select("tb_cliente_usina", raw_params={
            "id_cliente":     f"eq.{id_c}",
            "dt_fim":         "is.null",
            "desc_saldo_obs": "eq.FIXO",
        })
        if vincs:
            fixos.append(id_c)

    if len(fixos) < 2:
        return None

    # 4) Todos têm fatura no mesmo (ano, mes)?
    com_fatura = []
    for id_c in fixos:
        fats = db.select("tb_faturas", raw_params={
            "id_cliente":     f"eq.{id_c}",
            "ano_referencia": f"eq.{ano}",
            "mes_referencia": f"eq.{mes}",
            "status":         "neq.cancelado",
        })
        if fats:
            com_fatura.append(id_c)

    if len(com_fatura) < 2:
        return None

    return sorted(com_fatura)


def gerar_pdf(id_clientes: list[int], ano: int, mes: int) -> dict:
    """
    Gera o PDF consolidado FIXO. Retorna {'path_local', 'storage_key', 'total_com'}.
    Lança RuntimeError em caso de falha.
    """
    db = _db()
    if len(id_clientes) < 2:
        raise RuntimeError("consolidação requer pelo menos 2 clientes")

    detalhamento_uc = []
    total_ger = total_sem = total_com = total_fio_b_ded = 0.0
    peso_tarifa = 0.0
    consumer_ref = None
    cli_ref = None
    pdf_cons_ref = None
    pdfs_usinas_anexar = []   # PDFs únicos das usinas, ordem estável, para anexar ao final
    temps_remover = []        # arquivos temporários a remover ao final

    for id_cli in id_clientes:
        cli_rows = db.select("tb_clientes", filtros={"id_cliente": id_cli})
        if not cli_rows:
            raise RuntimeError(f"cliente {id_cli} não encontrado")
        cli_db = cli_rows[0]
        if cli_ref is None:
            cli_ref = cli_db
        desconto = float(cli_db.get("pct_desconto") or 0)

        vincs = db.select("tb_cliente_usina", raw_params={
            "id_cliente":     f"eq.{id_cli}",
            "dt_fim":         "is.null",
            "desc_saldo_obs": "eq.FIXO",
        })
        if not vincs:
            raise RuntimeError(f"cliente {id_cli} sem vínculos FIXO")

        pdf_cons = _resolver_pdf_consumidor(id_cli, ano, mes)
        if not pdf_cons:
            raise RuntimeError(f"PDF Equatorial do consumidor {id_cli} ({ano}-{mes:02d}) não encontrado")
        if pdf_cons.startswith(tempfile.gettempdir()):
            temps_remover.append(pdf_cons)

        cons = extrair_equatorial(pdf_cons, verbose=False)
        if consumer_ref is None:
            consumer_ref = cons
            pdf_cons_ref = pdf_cons
        tarifa_fio_b = float(cons.get("tarifa_nao_comp", 0) or 0)
        ciclo = _norm_mes(cons.get("ciclo_geracao_mes", ""))

        ger_cli = valor_sem_cli = valor_com_cli = 0.0
        for v in vincs:
            id_usina = v.get("id_usina")
            pct      = float(v.get("pct_rateio") or 0) / 100.0
            pdf_us   = _resolver_pdf_usina(id_usina, ciclo)
            if not pdf_us:
                raise RuntimeError(f"PDF da usina id={id_usina} ciclo {ciclo} não localizado")
            if pdf_us.startswith(tempfile.gettempdir()):
                temps_remover.append(pdf_us)
            # Acumula para anexar ao final (deduplica por (id_usina, ciclo))
            _key_us = (id_usina, ciclo)
            if not any(k == _key_us for k, _ in pdfs_usinas_anexar):
                pdfs_usinas_anexar.append((_key_us, pdf_us))
            usina = extrair_equatorial(pdf_us, verbose=False)
            ger_us_total = float(usina.get("geracao_ciclo_kwh", 0) or 0)
            tarifa_us    = float(usina.get("tarifa_convencional", 0) or 0)
            ger_aplic    = pct * ger_us_total
            valor_sem    = ger_aplic * tarifa_us
            valor_com    = ger_aplic * (tarifa_us * (1 - desconto) - tarifa_fio_b)

            ger_cli       += ger_aplic
            valor_sem_cli += valor_sem
            valor_com_cli += valor_com
            peso_tarifa   += ger_aplic * tarifa_us
            total_fio_b_ded += ger_aplic * tarifa_fio_b

        total_ger += ger_cli
        total_sem += valor_sem_cli
        total_com += valor_com_cli
        detalhamento_uc.append({
            "id_cliente": id_cli,
            "label":      _fmt_uc15(cli_db.get("cod_uc")),
            "uc":         cli_db.get("cod_uc"),
            "ger_aplic":  ger_cli,
            "valor_sem":  valor_sem_cli,
            "valor_com":  valor_com_cli,
        })

    if total_ger <= 0:
        raise RuntimeError("geração total = 0")

    tarifa_sem_pond = peso_tarifa / total_ger

    # ── Monta equatorial base (a partir do primeiro consumidor) ──
    equatorial = dict(consumer_ref)
    equatorial["consumo_kwh"]           = round(total_ger, 2)
    equatorial["compensado_kwh"]        = round(total_ger, 2)
    equatorial["consumo_compensado"]    = round(total_ger, 2)
    equatorial["nao_comp_kwh"]          = 0.0
    equatorial["consumo_nao_comp"]      = 0.0
    equatorial["consumo_nao_comp_kwh"]  = 0.0
    equatorial["valor_parc_injet"]      = 0.0
    equatorial["total_fatura"]          = 0.0

    # Cliente legado
    clientes_legado = carregar_clientes()
    uc_ref = cli_ref.get("cod_uc")
    cliente = clientes_legado.get(uc_ref)
    if not cliente:
        for k, v in clientes_legado.items():
            if k.lstrip("0") == str(uc_ref).lstrip("0"):
                cliente = v
                break
    if not cliente:
        raise RuntimeError(f"cliente UC {uc_ref} não encontrado em carregar_clientes()")

    dados = montar_dados(equatorial, cliente, uc_ref, pdf_cons_ref, tarifa_override=tarifa_sem_pond)
    dados["fio_b_deducao"] = total_fio_b_ded
    # Desabilita anexo da Equatorial do CONSUMIDOR — a consolidada anexa
    # os PDFs das USINAS depois (manualmente via pypdf).
    dados["equatorial_pdf"] = ""

    # Economia anterior = SOMA das economias de meses < (ano, mes) de todos os clientes
    prior_eco = 0.0
    for id_c in id_clientes:
        fats_ant = db.select("tb_faturas", raw_params={
            "id_cliente": f"eq.{id_c}",
            "status":     "neq.cancelado",
        })
        for f in fats_ant:
            f_mes = int(f.get("mes_referencia") or 0)
            f_ano = int(f.get("ano_referencia") or 0)
            if (f_ano, f_mes) < (ano, mes):
                prior_eco += float(f.get("vlr_economia_mes") or 0)
    dados["economia_acumulada_anterior"] = round(prior_eco, 2)

    # Lista de UCs para o template
    dados["consumo_por_uc"] = [
        {
            "label":         d["label"],
            "uc":            d["uc"],
            "ger_fmt":       _fmt_kwh(d["ger_aplic"]),
            "valor_sem_fmt": _fmt_brl(d["valor_sem"]),
            "valor_com_fmt": _fmt_brl(d["valor_com"]),
        }
        for d in detalhamento_uc
    ]
    dados["unidade_consumidora"] = " + ".join(d["uc"] for d in detalhamento_uc if d.get("uc"))

    # PIX
    try:
        _vinc_db = tb_get_usinas_do_cliente(id_clientes[0])
        if _vinc_db:
            _rec = tb_get_pix_da_usina(_vinc_db[0]["id_usina"])
            if _rec and _rec.get("desc_pix"):
                qr = gerar_qrcode_pix(
                    total_com,
                    chave_pix=_rec.get("desc_pix"),
                    nome_recebedor=_rec.get("desc_nome_pix") or _rec.get("desc_nome"),
                    cidade=_rec.get("desc_cidade_pix"),
                )
                if qr:
                    dados["pix_qr_path"] = qr
    except Exception:
        pass

    dados["id_cliente"] = id_clientes[0]

    # Gera PDF
    gerar_cobranca(dados)
    arquivo_gerado = dados.get("output_path", "")
    if not arquivo_gerado or not os.path.exists(arquivo_gerado):
        raise RuntimeError(f"arquivo não encontrado: {arquivo_gerado}")

    # Nome final
    yyyymm = f"{ano}{mes:02d}"
    nome_camel = _camel(cli_ref.get("desc_nome") or "Cliente")
    nome_arq = f"{yyyymm}-SoLev{nome_camel}-Consolidada.pdf"

    # Pasta de destino: Desktop\Usinas\Consolidadas\<NomeClienteCamel>\
    # (evita usar pasta temp quando o PDF do consumidor foi baixado do Storage)
    base_consolidadas = os.path.join(
        os.path.expanduser("~"), "OneDrive", "Desktop", "Usinas", "Consolidadas", nome_camel
    )
    os.makedirs(base_consolidadas, exist_ok=True)
    destino = os.path.join(base_consolidadas, nome_arq)
    shutil.move(arquivo_gerado, destino)

    # ── Mescla PDFs das USINAS após a página da cobrança SOLEV ──
    # Page 1: SOLEV cobrança consolidada
    # Pages 2+: cada usina, APENAS página 1 + overlay SoLev (cobre boleto/cobrança)
    if pdfs_usinas_anexar:
        try:
            from pypdf import PdfReader, PdfWriter
            from contalev_cobranca_v2_padrao import _criar_overlay_pdf
            import io as _io

            writer = PdfWriter()
            # Lê SOLEV (já está em destino)
            for pg in PdfReader(destino).pages:
                writer.add_page(pg)
            # Adiciona página 1 de cada usina com overlay SoLev (oculta boleto)
            for (_id_us, _ciclo), caminho_us in pdfs_usinas_anexar:
                _r_us = PdfReader(caminho_us)
                _pg_us = _r_us.pages[0]
                _pw = float(_pg_us.mediabox.width)
                _ph = float(_pg_us.mediabox.height)
                _ov_bytes = _criar_overlay_pdf(_pw, _ph)
                _ov_page = PdfReader(_io.BytesIO(_ov_bytes)).pages[0]
                _pg_us.merge_page(_ov_page)
                writer.add_page(_pg_us)
            # Reescreve destino com tudo
            with open(destino, "wb") as f_out:
                writer.write(f_out)
            print(f"  📎 Anexadas {len(pdfs_usinas_anexar)} fatura(s) Equatorial (pag.1 + overlay SoLev)")
        except Exception as _e:
            print(f"  ⚠️ Falha ao anexar PDFs das usinas: {_e}")

    # Upload Storage
    storage_key = ""
    try:
        storage_key = storage_upload_pdf(destino, nome_arq, bucket="faturas")
    except Exception:
        pass

    # Limpa temporários (consumidor + usina)
    for t in temps_remover:
        try:
            os.remove(t)
        except Exception:
            pass

    return {
        "path_local":  destino,
        "storage_key": storage_key,
        "total_com":   round(total_com, 2),
        "total_sem":   round(total_sem, 2),
        "total_ger":   round(total_ger, 2),
        "fio_b_ded":   round(total_fio_b_ded, 2),
        "id_clientes": id_clientes,
    }

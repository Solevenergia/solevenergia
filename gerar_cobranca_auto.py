"""
=============================================================
  CONTALEV — Gerador Automatico de Cobranca v3
=============================================================
  Fluxo:
    1. Recebe o PDF da fatura Equatorial
    2. Extrai dados automaticamente (consumo, datas, etc.)
    3. Busca dados do cliente no clientes.json
    4. Resolve tarifa (tarifas.json > fatura > SCEE×1.454759)
    5. Monta o dict DADOS e chama gerar_cobranca()
    6. Gera QR Code PIX dinamico com o valor da cobranca
    7. Apos gerar, atualiza clientes.json

  Uso:
    python gerar_cobranca_auto.py <fatura_equatorial.pdf>
    python gerar_cobranca_auto.py <fatura.pdf> --uc <numero>
=============================================================
"""

import json
import os
import sys
import shutil
import tempfile
from datetime import datetime, timedelta

# Garante que o Python rode na pasta onde os scripts estao
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Modulos CONTALEV
from extrair_equatorial import extrair_equatorial
from contalev_cobranca_v2_padrao import gerar_cobranca, calcular, _fmt_brl

# ── Configuracao ─────────────────────────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENTES_JSON = os.path.join(_DIR, "clientes.json")
TARIFAS_JSON  = os.path.join(_DIR, "tarifas.json")

# ══════════════════════════════════════════════════════════════
#  CHAVE PIX — Configure aqui os dados da sua conta Inter
# ══════════════════════════════════════════════════════════════
PIX_CHAVE        = ""           # CPF, e-mail, telefone ou chave aleatoria
PIX_NOME         = "SOLEV ENERGIA"
PIX_CIDADE       = "GOIANIA"


# ── Helpers de JSON ──────────────────────────────────────────

def carregar_clientes():
    """Carrega o banco de clientes do JSON."""
    if not os.path.exists(CLIENTES_JSON):
        print(f"⚠️  Arquivo {CLIENTES_JSON} nao encontrado. Criando vazio...")
        with open(CLIENTES_JSON, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4, ensure_ascii=False)
        return {}
    with open(CLIENTES_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar_clientes(clientes):
    """Salva o banco de clientes no JSON."""
    with open(CLIENTES_JSON, "w", encoding="utf-8") as f:
        json.dump(clientes, f, indent=4, ensure_ascii=False)
    print(f"💾 Banco de clientes atualizado: {CLIENTES_JSON}")


def adicionar_fatura(uc, nome, mes_ref, total_sem, total_com,
                     economia_mes, economia_acum, venc, pdf_path,
                     consumo_kwh=0, compensado_kwh=0,
                     data_leitura_atual="", saldo_kwh=0,
                     multa_equatorial=0, juros_equatorial=0,
                     multa_mes=0, juros_mes=0,
                     fatura_equatorial=0, fio_b=0, ilum_publica=0,
                     band_amar_equatorial=0, band_verm_equatorial=0,
                     band_amar_solev=0,   band_verm_solev=0,
                     ajuste_valor=0,
                     difci=0, ecnisenta=0,
                     anterior_leitura="", n_dias=0):
    """Insere uma fatura em tb_faturas via db.inserir_fatura.

    Renomeada de adicionar_historico() na etapa 7B.5.
    """
    from db import inserir_fatura as _db_inserir
    _db_inserir(
        uc=uc, nome=nome, mes_ref=mes_ref,
        total_sem=total_sem, total_com=total_com,
        economia_mes=economia_mes, economia_acum=economia_acum,
        venc=venc, pdf_path=pdf_path,
        consumo_kwh=consumo_kwh, compensado_kwh=compensado_kwh,
        data_leitura_atual=data_leitura_atual,
        saldo_kwh=saldo_kwh,
        multa_equatorial=multa_equatorial,
        juros_equatorial=juros_equatorial,
        multa_mes=multa_mes,
        juros_mes=juros_mes,
        fatura_equatorial=fatura_equatorial,
        fio_b=fio_b,
        ilum_publica=ilum_publica,
        band_amar_equatorial=band_amar_equatorial,
        band_verm_equatorial=band_verm_equatorial,
        band_amar_solev=band_amar_solev,
        band_verm_solev=band_verm_solev,
        ajuste_valor=ajuste_valor,
        difci=difci,
        ecnisenta=ecnisenta,
        anterior_leitura=anterior_leitura,
        n_dias=n_dias,
    )


def carregar_tarifas():
    """Carrega tarifas do Supabase (via db.py)."""
    from db import carregar_tarifas as _db_tarifas
    return _db_tarifas()


def buscar_cliente(uc, clientes):
    """Busca cliente pela UC (exata ou sem zeros a esquerda)."""
    if uc in clientes:
        return uc, clientes[uc]
    uc_limpo = uc.lstrip("0")
    for key in clientes:
        if key.lstrip("0") == uc_limpo:
            return key, clientes[key]
    return None, None


# ── Resolver Tarifa ──────────────────────────────────────────

def _normalizar_mes(mes_referencia: str) -> list:
    """Retorna lista de variantes do mes para lookup (com e sem zero a esquerda).
    Ex: '4/2026' → ['4/2026', '04/2026'] | '04/2026' → ['04/2026', '4/2026']"""
    partes = mes_referencia.split("/")
    if len(partes) != 2:
        return [mes_referencia]
    m, a = partes
    m_int = int(m)
    return [f"{m_int}/{a}", f"{m_int:02d}/{a}"]


def resolver_tarifa(mes_referencia, equatorial=None):
    """
    Resolve a tarifa R$/kWh com prioridade:
      1. Supabase — tabela tarifas (campo tarifa_sem)
      2. Fatura Equatorial — campo tarifa_scee × 1,454759 (consumo 100% compensado)

    Returns:
        tuple: (tarifa_valor, origem_str)
    """
    # 1. Supabase
    tarifas = carregar_tarifas()
    for mes_fmt in _normalizar_mes(mes_referencia):
        if mes_fmt in tarifas:
            t = tarifas[mes_fmt]
            val = t.get("tarifa_sem", t.get("tarifa", 0))
            if val and val > 0:
                return val, f"Supabase ({mes_fmt})"

    # 2. Fatura Equatorial
    if equatorial:
        tarifa_fatura = equatorial.get("tarifa", 0)
        if tarifa_fatura and tarifa_fatura > 0:
            return tarifa_fatura, "fatura Equatorial"

        # 3. Consumo 100% compensado → SCEE × 1,454759
        nao_comp = equatorial.get("consumo_nao_comp", 0)
        tarifa_scee = equatorial.get("tarifa_scee", 0)
        if nao_comp == 0 and tarifa_scee and tarifa_scee > 0:
            calc = round(tarifa_scee * 1.454759, 6)
            return calc, "SCEE × 1,454759"

        # 4. Fallback: tarifa_convencional extraida do PDF (linha CONSUMO NAO COMPENSADO
        # ou CONSUMO kWh). Usada quando cliente nao tem GD e Supabase nao tem tarifa.
        tarifa_conv = equatorial.get("tarifa_convencional", 0)
        if tarifa_conv and tarifa_conv > 0:
            return tarifa_conv, "fatura Equatorial (convencional)"

    return 0, "nao encontrada"


def resolver_bandeiras(mes_referencia):
    """Busca bandeiras tarifarias do Supabase."""
    tarifas = carregar_tarifas()
    for mes_fmt in _normalizar_mes(mes_referencia):
        if mes_fmt in tarifas:
            t = tarifas[mes_fmt]
            return t.get("bandeira_amarela", 0), t.get("bandeira_vermelha", 0)
    return 0, 0


# ── QR Code PIX ──────────────────────────────────────────────

def gerar_qrcode_pix(valor, chave_pix=None, nome_recebedor=None,
                     cidade=None, txid="***"):
    """
    Gera QR Code PIX (BRCode) com valor dinamico.

    Returns:
        str: caminho do PNG, ou None se falhar
    """
    from utils import _normalizar_chave_pix
    chave = _normalizar_chave_pix(chave_pix or PIX_CHAVE)
    nome = nome_recebedor or PIX_NOME
    cid = cidade or PIX_CIDADE

    if not chave:
        return None

    def _tlv(tag, value):
        return f"{tag:02d}{len(value):02d}{value}"

    def _crc16(data):
        crc = 0xFFFF
        for byte in data.encode('utf-8'):
            crc ^= byte << 8
            for _ in range(8):
                crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
                crc &= 0xFFFF
        return f"{crc:04X}"

    try:
        import qrcode
        payload = _tlv(0, "01")
        payload += _tlv(26, _tlv(0, "br.gov.bcb.pix") + _tlv(1, chave[:77]))
        payload += _tlv(52, "0000")
        payload += _tlv(53, "986")
        payload += _tlv(54, f"{valor:.2f}")
        payload += _tlv(58, "BR")
        payload += _tlv(59, nome[:25])
        payload += _tlv(60, cid[:15].upper())
        payload += _tlv(62, _tlv(5, txid[:25]))
        payload += "6304"
        payload += _crc16(payload)

        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10, border=2)
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        tmp = tempfile.NamedTemporaryFile(
            suffix=".png", delete=False, prefix="pix_qr_")
        img.save(tmp.name)
        return tmp.name
    except Exception as e:
        print(f"⚠️ Erro ao gerar QR Code PIX: {e}")
        return None


# ── Endereco (compatibilidade) ───────────────────────────────

def _resolver_endereco(cliente):
    """Retorna endereco do cliente (formato novo ou legado)."""
    end = cliente.get("endereco", "")
    if end:
        return end
    # Fallback: formato antigo (3 linhas)
    l1 = cliente.get("endereco_linha1", "")
    l2 = cliente.get("endereco_linha2", "")
    l3 = cliente.get("endereco_linha3", "")
    return ", ".join(p for p in [l1, l2, l3] if p)


# ── Montar Dados ─────────────────────────────────────────────

def montar_dados(equatorial, cliente, chave_uc, pdf_equatorial, tarifa_override=None):
    """
    Monta o dicionario DADOS combinando:
      - dados do cadastro do cliente (clientes.json)
      - dados extraidos da fatura Equatorial
      - tarifa resolvida (tarifas.json > fatura > SCEE)
    """
    mr = equatorial.get("mes_referencia", "")

    # Resolve tarifa
    if tarifa_override and tarifa_override > 0:
        tarifa_val, tarifa_orig = tarifa_override, "informada manualmente"
    else:
        tarifa_val, tarifa_orig = resolver_tarifa(mr, equatorial)

    if tarifa_val <= 0:
        print("⚠️ Tarifa nao encontrada! Verifique tarifas.json ou informe manualmente.")

    # Resolve bandeiras — FONTE ÚNICA (utils.resolver_tarifa_bandeira):
    # tarifa REAL do PDF (adc/qtd) com fallback no tb_tarifas. Mesma função que
    # o endpoint /api/extrair e o calcular() consomem — nunca mais diverge.
    from utils import resolver_tarifa_bandeira
    ba_stored, bv_stored = resolver_bandeiras(mr)
    ba, bv, _binfo = resolver_tarifa_bandeira(equatorial, ba_stored, bv_stored)
    ba_real, bv_real = _binfo["ba_pdf"], _binfo["bv_pdf"]
    if ba_real is not None and abs(ba_real - ba_stored) > 0.00001:
        print(f"   Bandeira AM: tarifa do PDF = R$ {ba_real:.6f}/kWh — substitui tb_tarifas R$ {ba_stored:.6f}")
    if bv_real is not None and abs(bv_real - bv_stored) > 0.00001:
        print(f"   Bandeira VM: tarifa do PDF = R$ {bv_real:.6f}/kWh — substitui tb_tarifas R$ {bv_stored:.6f}")

    # Auto-aprendizado: atualiza tb_tarifas se a tarifa real do PDF for MAIOR
    # que a cadastrada (mantém sempre o maior valor observado como fallback).
    if ba_real or bv_real:
        try:
            from db import tarifa_atualizar_se_maior
            res = tarifa_atualizar_se_maior(mr, ba_real, bv_real)
            if res.get("atualizado"):
                print(f"   📌 tb_tarifas[{res.get('mes', mr)}] atualizado com valores do PDF")
            elif res.get("criado"):
                print(f"   📌 tb_tarifas[{res.get('mes', mr)}] criado com valores do PDF")
        except Exception as _e:
            print(f"   ⚠️ Falha ao auto-atualizar tb_tarifas: {_e}")

    # Endereco
    endereco = _resolver_endereco(cliente)
    if not endereco:
        endereco = equatorial.get("endereco", "")

    # CPF: sempre do cadastro
    cpf = cliente.get("cpf", "")

    # Desconto
    desc = cliente.get("desconto_pct", 0.20)
    if desc > 1:
        desc = desc / 100

    # Modo bandeira
    modo = cliente.get("modo_bandeira", "com_bandeira")

    # Consumo
    consumo = equatorial.get("consumo_kwh", 0) or 0
    # ATENCAO: NAO usar "or consumo" como fallback de compensado.
    # Para clientes sem GD, compensado_kwh=0 (correto) — o fallback "or consumo"
    # causava double-count: comp=consumo E nao_comp=consumo simultaneamente.
    compensado = equatorial.get("consumo_compensado", 0) or 0
    nao_comp = equatorial.get("consumo_nao_comp", 0) or 0

    # ── Multa/juros vindas da fatura anterior em tb_faturas ─────────
    # Busca a fatura PAGA do periodo anterior do cliente e le os campos
    # vlr_multa_proxima/vlr_juros_proxima dela. Isso substitui o calculo
    # legado feito pelo calculador (que dependia de cliente.data_pagamento_anterior).
    _multa_carry, _juros_carry = 0.0, 0.0
    try:
        from db import tb_get_cliente_por_uc, tb_get_multa_juros_proxima
        import re as _re_mr
        _m = _re_mr.match(r"^(\d{1,2})/(\d{4})$", str(mr or "").strip())
        if _m:
            _mes_atual, _ano_atual = int(_m.group(1)), int(_m.group(2))
            _c_tb = tb_get_cliente_por_uc(chave_uc)
            if _c_tb and _c_tb.get("id_cliente"):
                _pendente = tb_get_multa_juros_proxima(
                    _c_tb["id_cliente"], _ano_atual, _mes_atual
                )
                _multa_carry = _pendente.get("vlr_multa") or 0.0
                _juros_carry = _pendente.get("vlr_juros") or 0.0
                if _multa_carry > 0 or _juros_carry > 0:
                    print(f"   📥 Multa/Juros da fatura anterior (tb_faturas): "
                          f"R${_multa_carry:.2f} + R${_juros_carry:.2f}")
    except Exception as _e:
        print(f"   ⚠️ Falha ao buscar multa/juros anterior em tb_faturas: {_e}")

    # Idempotencia da economia acumulada (mesma logica do app.py gerar_manual):
    # desconta a economia ja registrada na fatura deste mes (se houver) para
    # regerar a mesma cobranca NAO duplicar a economia no PDF.
    _eco_acum_ant = cliente.get("economia_acumulada_anterior", 0.0) or 0
    try:
        from db import tb_get_cliente_por_uc as _gc_eco, tb_economia_mes_fatura as _emf_eco
        import re as _re_eco_a
        _mm_eco = _re_eco_a.match(r"^(\d{1,2})/(\d{4})$", str(mr or "").strip())
        if _mm_eco:
            _ctb_eco = _gc_eco(chave_uc)
            if _ctb_eco and _ctb_eco.get("id_cliente"):
                _eco_acum_ant = max(0.0, float(_eco_acum_ant) - _emf_eco(
                    _ctb_eco["id_cliente"], _mm_eco.group(2), _mm_eco.group(1)))
    except Exception as _e_eco:
        print(f"   ⚠️ idempotencia economia (auto): {_e_eco}")

    dados = {
        # ── Do cliente ──
        "nome":               cliente["nome"],
        "cpf":                cpf,
        "endereco":           endereco,
        "desconto_pct":       desc,
        "tarifa_sem":         tarifa_val,
        "modo_bandeira":      modo,
        "valor_cobranca_anterior":      cliente.get("valor_cobranca_anterior", 0.0) or 0,
        "venc_solev_anterior":       cliente.get("venc_solev_anterior", ""),
        "data_pagamento_anterior":      cliente.get("data_pagamento_anterior", ""),
        "economia_acumulada_anterior":  _eco_acum_ant,

        # ── Multa/juros CONTALEV deste mes — vem de tb_faturas (single source of truth)
        # Quando preenchidos, o calculador usa esses valores e ignora o
        # calculo legado baseado em data_pagamento_anterior.
        "multa_com_override":           _multa_carry,
        "juros_com_override":           _juros_carry,

        # ── Da fatura Equatorial ──
        "unidade_consumidora": equatorial.get("unidade_consumidora", chave_uc),
        "tipo_fornecimento":   equatorial.get("tipo_fornecimento", ""),
        "mes_referencia":      mr,
        "anterior_leitura":    equatorial.get("data_leitura_anterior", ""),  # data, nao numero do medidor
        "data_leitura":        equatorial.get("data_leitura_atual", ""),      # data_leitura_atual e mais explicito
        "proxima_leitura":     equatorial.get("proxima_leitura", ""),
        "venc_equatorial":     equatorial.get("venc_equatorial", ""),
        "consumo_kwh":         consumo,
        "consumo_compensado":  compensado,
        "consumo_nao_comp":    nao_comp,
        "iluminacao_publica":  equatorial.get("iluminacao_publica", 0) or 0,
        "multa":               equatorial.get("multa", 0) or 0,
        "juros":               equatorial.get("juros", 0) or 0,
        "correcao_ipca":       equatorial.get("correcao_ipca", 0) or 0,
        "difci":               equatorial.get("difci", 0) or 0,
        "ecnisenta":           equatorial.get("ecnisenta", 0) or 0,
        "ajuste_valor":        0,

        # Compensacao DIC Mensal — credito da distribuidora (valor negativo)
        # Aparece em algumas faturas como "COMPENSACAO DE DIC MENSAL -637,82"
        # Deve compor tanto o total SEM quanto o total COM CONTALEV
        "compensacao_dic":     equatorial.get("compensacao_dic", 0) or 0,

        # Lei 14.300 — cobranca parcial sobre energia injetada
        "valor_parc_injet":    equatorial.get("valor_parc_injet", 0) or 0,
        "pct_parc_injet":      equatorial.get("pct_parc_injet", 0) or 0,

        # Bandeiras — 4 entradas para o calculador:
        # 1+2: tarifa R$/kWh do tb_tarifas (so uma delas > 0 por mes)
        "bandeira_tarifa_amar":     ba,
        "bandeira_tarifa_verm":     bv,
        # 3+4: valor R$ que a Equatorial cobrou (ADC BANDEIRA do PDF)
        "adc_bandeira_amarela":     equatorial.get("adc_bandeira_amarela", 0) or 0,
        "adc_bandeira_vermelha":    equatorial.get("adc_bandeira_vermelha", 0) or 0,
        # 5+6: qtd kWh sob bandeira — calcular() resolve a tarifa real (adc/qtd)
        "_bandeira_amarela_qtd":    equatorial.get("bandeira_amarela", 0) or 0,
        "_bandeira_vermelha_qtd":   equatorial.get("bandeira_vermelha", 0) or 0,
        # 7+8: tarifa EXATA impressa na linha ADC do PDF (preferida pelo calcular)
        "tarifa_bandeira_amarela_pdf":  equatorial.get("tarifa_bandeira_amarela_pdf", 0) or 0,
        "tarifa_bandeira_vermelha_pdf": equatorial.get("tarifa_bandeira_vermelha_pdf", 0) or 0,
        # Legados (mantidos por compat — antigos chamadores)
        "bandeira_amarela":    ba * consumo if ba > 0 else 0,
        "bandeira_vermelha":   bv * consumo if bv > 0 else 0,

        # PDF da Equatorial (pagina 2)
        "equatorial_pdf":      pdf_equatorial,
    }

    print(f"   Tarifa: R$ {tarifa_val:.6f} ({tarifa_orig})")
    if ba > 0 or bv > 0:
        print(f"   Bandeiras: Am={ba:.6f} Vm={bv:.6f} R$/kWh")

    return dados


def atualizar_cliente_pos_geracao(chave_uc, clientes, dados_calculados):
    """Atualiza o cliente apos gerar cobranca."""
    if chave_uc not in clientes:
        return
    clientes[chave_uc]["valor_cobranca_anterior"] = round(
        dados_calculados.get("_total_com", 0), 2)
    clientes[chave_uc]["venc_solev_anterior"] = dados_calculados.get(
        "venc_solev", "")
    clientes[chave_uc]["data_pagamento_anterior"] = ""
    clientes[chave_uc]["economia_acumulada_anterior"] = round(
        dados_calculados.get("_economia_acum", 0), 2)


# ══════════════════════════════════════════════════════════════
#  FLUXO PRINCIPAL — Via Fatura Equatorial
# ══════════════════════════════════════════════════════════════

def gerar_cobranca_auto(pdf_equatorial, uc_override=None):
    """
    Fluxo completo:
      1. Extrai dados da fatura Equatorial
      2. Identifica o cliente pela UC
      3. Resolve tarifa e monta dados
      4. Gera cobranca PDF + QR Code PIX
      5. Atualiza o banco de clientes
    """
    print("=" * 60)
    print("  CONTALEV — Gerador Automatico de Cobranca")
    print("=" * 60)
    print()

    # 1. Extrair dados da Equatorial
    print("📄 Extraindo dados da fatura Equatorial...")
    equatorial = extrair_equatorial(pdf_equatorial, verbose=True)
    print()

    # 2. Identificar cliente
    uc = uc_override or equatorial.get("unidade_consumidora", "")
    if not uc:
        print("❌ Nao foi possivel extrair a Unidade Consumidora do PDF.")
        print("   Use: python gerar_cobranca_auto.py <pdf> --uc <numero>")
        return None

    print(f"🔍 Buscando cliente UC: {uc}")
    clientes = carregar_clientes()
    chave_real, cliente = buscar_cliente(uc, clientes)

    if not cliente:
        print(f"❌ Cliente nao encontrado para UC: {uc}")
        print(f"   Cadastre o cliente pelo sistema web ou execute migrar_clientes.py")
        return None

    desc_pct = cliente.get("desconto_pct", 0)
    if desc_pct <= 1:
        desc_pct = desc_pct * 100
    print(f"✅ Cliente encontrado: {cliente['nome']}")
    print(f"   Desconto: {desc_pct:.0f}%")
    if cliente.get("valor_cobranca_anterior", 0) > 0:
        print(f"   Cobranca anterior: {_fmt_brl(cliente['valor_cobranca_anterior'])}")
        print(f"   Venc. anterior: {cliente.get('venc_solev_anterior', '-')}")
        pgto = cliente.get('data_pagamento_anterior', '')
        print(f"   Pagamento anterior: {pgto or '(em dia)'}")
    print(f"   Economia acumulada: {_fmt_brl(cliente.get('economia_acumulada_anterior', 0))}")
    print()

    # 3. Montar dados
    print("🔧 Montando dados da cobranca...")
    dados = montar_dados(equatorial, cliente, chave_real, pdf_equatorial)

    # Validacoes
    erros = []
    if not dados["mes_referencia"]:
        erros.append("Mes de referencia nao extraido")
    if dados["consumo_kwh"] <= 0:
        erros.append("Consumo kWh nao extraido ou zero")
    if dados["tarifa_sem"] <= 0:
        erros.append("Tarifa nao encontrada — cadastre em Tarifas ou informe manualmente")

    if erros:
        print("⚠️  ALERTAS DE EXTRACAO:")
        for e in erros:
            print(f"   ⚠️  {e}")
        print()

    # 4. Gerar cobranca
    print("📊 Gerando cobranca...")

    # QR Code PIX dinamico
    dados_calc = calcular(dados)
    total_com = dados_calc.get("_total_com", 0)
    qr_path = gerar_qrcode_pix(total_com)
    if qr_path:
        dados["pix_qr_path"] = qr_path
        print(f"   QR Code PIX gerado: R$ {total_com:.2f}")

    # Resolve id_cliente (nome do arquivo) e id_fatura (texto no PDF)
    try:
        from db import _resolver_id_cliente_por_uc, tb_reservar_id_fatura
        import re as _re_mr_cli
        _id_cli_cli = _resolver_id_cliente_por_uc(chave_real)
        if _id_cli_cli:
            dados["id_cliente"] = _id_cli_cli
            _mm_cli = _re_mr_cli.match(r"^(\d{1,2})/(\d{4})$",
                                        str(equatorial.get("mes_referencia") or "").strip())
            if _mm_cli:
                dados["id_fatura"] = tb_reservar_id_fatura(
                    _id_cli_cli, int(_mm_cli.group(2)), int(_mm_cli.group(1)))
    except Exception as _e_res_cli:
        print(f"   ⚠️ Resolver id_cliente/id_fatura falhou: {_e_res_cli}")

    gerar_cobranca(dados)
    print()

    # 5. Atualizar banco e historico
    atualizar_cliente_pos_geracao(chave_real, clientes, dados_calc)
    salvar_clientes(clientes)

    adicionar_fatura(
        chave_real, cliente["nome"], equatorial.get("mes_referencia", ""),
        round(dados_calc.get("_total_sem", 0), 2),
        round(dados_calc.get("_total_com", 0), 2),
        round(dados_calc.get("_economia_mes", 0), 2),
        round(dados_calc.get("_economia_acum", 0), 2),
        dados_calc.get("venc_solev", ""),
        dados_calc.get("output_path", ""),
        consumo_kwh=equatorial.get("consumo_kwh", 0),
        compensado_kwh=equatorial.get("compensado_kwh", 0),
        data_leitura_atual=equatorial.get("data_leitura_atual", ""),
        saldo_kwh=equatorial.get("saldo_kwh", 0),
        multa_equatorial=equatorial.get("multa", 0),
        juros_equatorial=equatorial.get("juros", 0),
        multa_mes=dados_calc.get("_multa_com", 0),
        juros_mes=dados_calc.get("_juros_com", 0),
        fatura_equatorial=equatorial.get("total_fatura", 0),
        fio_b=equatorial.get("valor_parc_injet", 0),
        ilum_publica=equatorial.get("iluminacao_publica", 0),
        band_amar_equatorial=dados_calc.get("_band_amar_equatorial", 0),
        band_verm_equatorial=dados_calc.get("_band_verm_equatorial", 0),
        band_amar_solev=dados_calc.get("_band_amar_solev", 0),
        band_verm_solev=dados_calc.get("_band_verm_solev", 0),
        difci=dados_calc.get("difci", 0),
        ecnisenta=dados_calc.get("ecnisenta", 0),
        anterior_leitura=equatorial.get("data_leitura_anterior", ""),
        n_dias=int(equatorial.get("n_dias", 0) or 0))
    print("   Historico atualizado.")

    print()
    print("📋 RESUMO POS-GERACAO:")
    print(f"   Total COM CONTALEV: {dados_calc.get('total_com_fmt', _fmt_brl(total_com))}")
    print(f"   Venc. CONTALEV: {dados_calc.get('venc_solev', '')}")
    print(f"   Economia mes: {dados_calc.get('economia_mes_fmt', '')}")
    print(f"   Economia acumulada: {dados_calc.get('economia_acum_fmt', '')}")
    print(f"   (Banco atualizado para proximo mes)")

    return dados_calc.get("output_path")


# ══════════════════════════════════════════════════════════════
#  REGISTRAR PAGAMENTO
# ══════════════════════════════════════════════════════════════

def registrar_pagamento(uc, data_pagamento):
    """Registra a data de pagamento de um cliente."""
    clientes = carregar_clientes()
    chave_real, cliente = buscar_cliente(uc, clientes)

    if not cliente:
        print(f"❌ Cliente UC {uc} nao encontrado.")
        return

    clientes[chave_real]["data_pagamento_anterior"] = data_pagamento
    salvar_clientes(clientes)
    print(f"✅ Pagamento registrado para {cliente['nome']}:")
    print(f"   UC: {chave_real}")
    print(f"   Data pagamento: {data_pagamento}")
    print(f"   Valor: {_fmt_brl(cliente.get('valor_cobranca_anterior', 0))}")
    print(f"   Vencimento era: {cliente.get('venc_solev_anterior', '-')}")

    # Calcula atraso
    if cliente.get("venc_solev_anterior"):
        _dfmt = "%d/%m/%Y"
        try:
            dt_venc = datetime.strptime(cliente["venc_solev_anterior"], _dfmt)
            dt_pgto = datetime.strptime(data_pagamento, _dfmt)
            dias = (dt_pgto - dt_venc).days
            if dias > 0:
                base = cliente.get("valor_cobranca_anterior", 0)
                multa = base * 0.02
                juros = base * 0.001627 * dias
                print(f"   ⚠️  ATRASO: {dias} dias")
                print(f"   ⚠️  Multa proxima fatura: {_fmt_brl(multa)}")
                print(f"   ⚠️  Juros proxima fatura: {_fmt_brl(juros)}")
            else:
                print(f"   ✅ Pagamento em dia! Sem multa/juros na proxima fatura.")
        except ValueError:
            print("   ⚠️ Nao foi possivel calcular atraso (datas invalidas).")


# ══════════════════════════════════════════════════════════════
#  GERENCIAMENTO DE CLIENTES (CLI)
# ══════════════════════════════════════════════════════════════

def listar_clientes():
    """Lista todos os clientes cadastrados."""
    clientes = carregar_clientes()
    if not clientes:
        print("Nenhum cliente cadastrado.")
        return
    print(f"\n  {'UC':<15} {'Nome':<35} {'Desc':<6} {'Cobr.Ant':<12} {'Eco.Acum':<12}")
    print("  " + "-" * 80)
    for uc, c in clientes.items():
        desc = c.get("desconto_pct", 0)
        if desc <= 1:
            desc = desc * 100
        print(f"  {uc:<15} {c['nome']:<35} {desc:.0f}%   "
              f"{_fmt_brl(c.get('valor_cobranca_anterior', 0)):<12} "
              f"{_fmt_brl(c.get('economia_acumulada_anterior', 0)):<12}")
    print()


def _input_obrigatorio(prompt):
    while True:
        val = input(prompt).strip()
        if val:
            return val
        print("   ⚠️  Campo obrigatorio.")


def _input_float(prompt, default=0.0):
    while True:
        raw = input(prompt).strip()
        if not raw:
            return default
        raw = raw.replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            print("   ⚠️  Valor invalido.")


def _input_opcional(prompt, default=""):
    val = input(prompt).strip()
    return val if val else default


def cadastrar_cliente():
    """Cadastra novo cliente no formato v3."""
    clientes = carregar_clientes()

    print("=" * 55)
    print("  CONTALEV — Cadastro de Novo Cliente")
    print("=" * 55)
    print()

    uc = _input_obrigatorio("  Unidade Consumidora (UC): ")
    if uc in clientes:
        print(f"  ⚠️  UC {uc} ja cadastrada ({clientes[uc]['nome']}).")
        r = input("  Deseja sobrescrever? (s/N): ").strip().lower()
        if r != "s":
            print("  Cadastro cancelado.")
            return

    print("\n  ── Dados Pessoais ──")
    nome     = _input_obrigatorio("  Nome completo: ").upper()
    cpf      = _input_opcional("  CPF/CNPJ: ", "")
    telefone = _input_opcional("  Telefone: ", "")
    email    = _input_opcional("  E-mail: ", "")
    endereco = _input_obrigatorio("  Endereco completo (rua, nº, bairro, CEP, cidade/UF): ").upper()
    titular  = _input_opcional("  Titular da fatura (se diferente do cliente): ", "")

    print("\n  ── Contrato ──")
    desconto  = _input_float("  Desconto % (ex: 20 para 20%): ", 20)
    desconto  = desconto / 100 if desconto > 1 else desconto
    data_ades = _input_opcional("  Data de adesao (dd/mm/aaaa): ", "")

    print("\n  ── Modo de Bandeira ──")
    print("    1 = Compensar bandeira no desconto (padrao)")
    print("    2 = Nao compensar bandeira")
    modo_op = _input_opcional("  Opcao [1]: ", "1")
    modo = "sem_bandeira" if modo_op == "2" else "com_bandeira"

    usina = _input_opcional("  Usina (opcional): ", "")

    print("\n  ── Historico do Mes Anterior (vazio se cliente novo) ──")
    cobr_ant  = _input_float("  Valor cobranca anterior (R$): ", 0.0)
    venc_ant  = _input_opcional("  Vencimento anterior (dd/mm/aaaa): ", "")
    pgto_ant  = _input_opcional("  Data pagamento anterior: ", "")
    eco_acum  = _input_float("  Economia acumulada (R$): ", 0.0)

    registro = {
        "nome": nome,
        "cpf": cpf,
        "telefone": telefone,
        "email": email,
        "endereco": endereco,
        "titular_fatura": titular,
        "data_adesao": data_ades,
        "desconto_pct": round(desconto, 4),
        "modo_bandeira": modo,
        "usina": usina,
        "valor_cobranca_anterior": cobr_ant,
        "venc_solev_anterior": venc_ant,
        "data_pagamento_anterior": pgto_ant,
        "economia_acumulada_anterior": eco_acum,
    }

    print(f"\n  ── Confirmacao ──")
    print(f"  UC:        {uc}")
    print(f"  Nome:      {nome}")
    print(f"  CPF:       {cpf or '—'}")
    print(f"  Endereco:  {endereco}")
    print(f"  Desconto:  {int(desconto * 100)}%")
    print(f"  Bandeira:  {'Compensar' if modo == 'com_bandeira' else 'Nao compensar'}")
    print()

    confirma = input("  Salvar? (S/n): ").strip().lower()
    if confirma == "n":
        print("  Cadastro cancelado.")
        return

    clientes[uc] = registro
    salvar_clientes(clientes)
    print(f"  ✅ Cliente {nome} cadastrado com sucesso! (UC: {uc})")


def ver_cliente(uc):
    """Mostra dados de um cliente."""
    clientes = carregar_clientes()
    chave_real, cliente = buscar_cliente(uc, clientes)
    if not cliente:
        print(f"❌ Cliente UC {uc} nao encontrado.")
        return

    print(f"\n  ══════ Cliente UC: {chave_real} ══════")
    print(f"  Nome:       {cliente['nome']}")
    print(f"  CPF:        {cliente.get('cpf', '—')}")
    print(f"  Telefone:   {cliente.get('telefone', '—')}")
    print(f"  E-mail:     {cliente.get('email', '—')}")
    print(f"  Endereco:   {_resolver_endereco(cliente)}")
    print(f"  Titular:    {cliente.get('titular_fatura', '—')}")
    desc = cliente.get("desconto_pct", 0)
    if desc <= 1:
        desc = desc * 100
    print(f"  Desconto:   {desc:.0f}%")
    print(f"  Bandeira:   {cliente.get('modo_bandeira', 'com_bandeira')}")
    print(f"  Usina:      {cliente.get('usina', '—')}")
    print(f"  Adesao:     {cliente.get('data_adesao', '—')}")
    print(f"  ──────────────────────────────────────")
    cobr = cliente.get('valor_cobranca_anterior', 0)
    print(f"  Cobr. anterior: {_fmt_brl(cobr)}")
    print(f"  Venc. anterior: {cliente.get('venc_solev_anterior', '') or '—'}")
    print(f"  Pgto. anterior: {cliente.get('data_pagamento_anterior', '') or '(aguardando)'}")
    print(f"  Eco. acumulada: {_fmt_brl(cliente.get('economia_acumulada_anterior', 0))}")
    print()


def editar_cliente(uc):
    """Edita campos de um cliente existente."""
    clientes = carregar_clientes()
    chave_real, cliente = buscar_cliente(uc, clientes)
    if not cliente:
        print(f"❌ Cliente UC {uc} nao encontrado.")
        return

    c = clientes[chave_real]
    print(f"\n  ══════ Editar Cliente UC: {chave_real} ══════")
    print(f"  (Pressione Enter para manter o valor atual)")
    print()

    campos = [
        ("nome",                        "Nome",                     "str"),
        ("cpf",                         "CPF/CNPJ",                 "str"),
        ("telefone",                    "Telefone",                 "str"),
        ("email",                       "E-mail",                   "str"),
        ("endereco",                    "Endereco",                 "str"),
        ("titular_fatura",              "Titular da fatura",        "str"),
        ("desconto_pct",                "Desconto (0.20 = 20%)",    "float"),
        ("modo_bandeira",               "Modo bandeira",            "str"),
        ("usina",                       "Usina",                    "str"),
        ("valor_cobranca_anterior",     "Cobr. anterior (R$)",      "float"),
        ("venc_solev_anterior",      "Venc. anterior",           "str"),
        ("data_pagamento_anterior",     "Pgto. anterior",           "str"),
        ("economia_acumulada_anterior", "Eco. acumulada (R$)",      "float"),
    ]

    alterados = 0
    for campo, label, tipo in campos:
        atual = c.get(campo, "")
        display = str(atual) if atual else "(vazio)"
        if len(display) > 50:
            display = display[:47] + "..."

        novo = input(f"  {label} [{display}]: ").strip()
        if novo:
            if tipo == "float":
                try:
                    c[campo] = float(novo.replace(",", "."))
                    alterados += 1
                except ValueError:
                    print("    ⚠️ Valor invalido, mantendo anterior.")
            else:
                c[campo] = novo.upper() if campo == "nome" else novo
                alterados += 1

    if alterados > 0:
        salvar_clientes(clientes)
        print(f"\n  ✅ {alterados} campo(s) atualizado(s) para {c['nome']}!")
    else:
        print("\n  Nenhuma alteracao feita.")


def remover_cliente(uc):
    """Remove um cliente do banco."""
    clientes = carregar_clientes()
    chave_real, cliente = buscar_cliente(uc, clientes)
    if not cliente:
        print(f"❌ Cliente UC {uc} nao encontrado.")
        return

    confirma = input(f"  Remover {cliente['nome']} (UC: {chave_real})? (s/N): ").strip().lower()
    if confirma != "s":
        print("  Remocao cancelada.")
        return

    del clientes[chave_real]
    salvar_clientes(clientes)
    print(f"  ✅ Cliente {cliente['nome']} removido.")


# ── CLI ──────────────────────────────────────────────────────
if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or "--help" in args:
        print("""
CONTALEV — Gerador Automatico de Cobranca v3

Uso:
  GERAR COBRANCA:
    python gerar_cobranca_auto.py <fatura_equatorial.pdf>
    python gerar_cobranca_auto.py <fatura.pdf> --uc <numero>

  GERENCIAR CLIENTES:
    python gerar_cobranca_auto.py --cadastrar
    python gerar_cobranca_auto.py --listar
    python gerar_cobranca_auto.py --ver <uc>
    python gerar_cobranca_auto.py --editar <uc>
    python gerar_cobranca_auto.py --remover <uc>

  REGISTRAR PAGAMENTO:
    python gerar_cobranca_auto.py --pagar <uc> <dd/mm/yyyy>

Fluxo mensal:
  1. Cadastre o cliente (uma vez):  --cadastrar
  2. Gere a cobranca:  python gerar_cobranca_auto.py fatura.pdf
  3. Quando pagar:  --pagar <uc> <data>
  4. Proximo mes, repita o passo 2
        """)
        sys.exit(0)

    if "--cadastrar" in args:
        cadastrar_cliente(); sys.exit(0)
    if "--listar" in args:
        listar_clientes(); sys.exit(0)
    if "--ver" in args:
        idx = args.index("--ver")
        ver_cliente(args[idx + 1]) if idx + 1 < len(args) else print("Uso: --ver <uc>")
        sys.exit(0)
    if "--editar" in args:
        idx = args.index("--editar")
        editar_cliente(args[idx + 1]) if idx + 1 < len(args) else print("Uso: --editar <uc>")
        sys.exit(0)
    if "--remover" in args:
        idx = args.index("--remover")
        remover_cliente(args[idx + 1]) if idx + 1 < len(args) else print("Uso: --remover <uc>")
        sys.exit(0)
    if "--pagar" in args:
        idx = args.index("--pagar")
        if idx + 2 < len(args):
            registrar_pagamento(args[idx + 1], args[idx + 2])
        else:
            print("Uso: --pagar <uc> <dd/mm/yyyy>")
        sys.exit(0)

    # Gerar cobranca
    pdf_path = args[0]
    uc = None
    if "--uc" in args:
        idx = args.index("--uc")
        uc = args[idx + 1]

    resultado = gerar_cobranca_auto(pdf_path, uc_override=uc)
    if resultado:
        print(f"\n🎉 Cobranca gerada com sucesso: {resultado}")

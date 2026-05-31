"""
=============================================================
  SOLEV — TEMPLATE PADRAO DE COBRANCA (v2 - COM FORMULAS)
=============================================================
  FORMULAS AUTOMATICAS:
    • num_dias       = data_leitura - anterior_leitura
    • venc_solev  = venc_equatorial - 3 dias
    • mes_ano_fatura = mes_referencia → "Marco / 2026"
    • output_path    = Cobranca_{NomeCliente}.pdf
    • subtotal_sem   = consumo_kwh × tarifa_sem
    • total_sem      = subtotal_sem + iluminacao + multa + juros
    • tarifa_com     = tarifa_sem × (1 - desconto_pct)
    • subtotal_com   = (compensado × tarifa_com) + (nao_comp × tarifa_sem)
    • multa_com      = valor_cobranca_anterior × 2%    [se atraso]
    • juros_com      = valor_cobranca_anterior × 0,1627%/dia × dias_atraso
    • total_com      = subtotal_com + iluminacao + multa_com + juros_com
    • economia_mes   = total_sem - total_com
    • economia_acum  = economia_anterior + economia_mes
=============================================================
"""

DADOS = {
    "nome":               "SERGIO ALFREDO TALONE",
    "cpf":                "777.539.411-01",
    "endereco_linha1":    "AVENIDA LONDRES, Q.126,"
    "endereco_linha2"     "JARDIM EUROPA",
    "endereco_linha3":    "CEP 74.330-260, GOIANIA/GO",
    "unidade_consumidora":"16396078",
    "tipo_fornecimento":  "Trifasico",
    "mes_referencia":     "03/2026",
    "anterior_leitura":   "11/02/2026",
    "data_leitura":       "12/03/2026",
    "proxima_leitura":    "13/04/2026",
    "venc_equatorial":    "01/04/2026",
    "consumo_kwh":        679.00,
    "tarifa_sem":         1.135823,
    "desconto_pct":       0.20,
    "consumo_compensado": 451.45,
    "consumo_nao_comp":   227.55,
    "iluminacao_publica": 25.58,
    "multa":              0.00,
    "juros":              0.00,
    "correcao_ipca":      0.00,
    "economia_acumulada_anterior": 0.00,
    # ── Dados do mes anterior (para calculo de multa/juros COM) ──
    "valor_cobranca_anterior":  0.00,       # valor total COM SOLEV do mes anterior
    "venc_solev_anterior":   "",          # vencimento da cobranca anterior, ex: "28/02/2026"
    "data_pagamento_anterior":  "",          # data que o cliente pagou, ex: "05/03/2026" (vazio = em dia)
    "codigo_barras":      "CODIGO DE BARRA EM DESENVOLVIMENTO",
    "linha_digitavel":    "XXXX.XXXX  XXXXX.XXXXX  XXXXX.XXXXX  X  XXXXXXXXXXXXXX",
    "pix_payload":        "00020126710014BR.GOV.BCB.PIX0129daniloevangelista@hotmail.com0216SOLEV-MAR20265204000053039865406694.255802BR5925Danilo Evangelista de Sou6009SAO PAULO62140510ISFfe2uLzk6304EC1F",
    "equatorial_pdf":     "/home/claude/032026-FATURAEQUATORIAL.pdf",
}


def _fmt_brl(valor):
    if valor == 0:
        return "R$ 0,00"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def _fmt_kwh(valor):
    return f"{valor:,.2f} kWh".replace(",", "X").replace(".", ",").replace("X", ".")

def _fmt_tarifa(valor):
    return f"R$ {valor:.6f}".replace(".", ",")

def _fmt_pct(valor):
    return f"{int(valor * 100)}%"

def _fmt_cpf(cpf):
    import re as _re
    if not cpf: return ""
    d = _re.sub(r'\D', '', str(cpf))
    if len(d) == 11: return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    if len(d) == 14: return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return cpf

def calcular(d):
    out = dict(d)

    # ── Formulas de datas ──────────────────────────────────
    from datetime import datetime, timedelta
    _dfmt = "%d/%m/%Y"

    # Datas podem estar vazias no modo manual
    _dl = d.get("data_leitura", "").strip()
    _al = d.get("anterior_leitura", "").strip()
    _ve = d.get("venc_equatorial", "").strip()

    if _dl and _al:
        dt_leitura  = datetime.strptime(_dl, _dfmt)
        dt_anterior = datetime.strptime(_al, _dfmt)
        num_dias    = (dt_leitura - dt_anterior).days
    else:
        num_dias = int(d.get("n_dias", 0) or 0)

    # Vencimento SOLEV: usa o informado diretamente, ou calcula a partir do Equatorial
    venc_solev = d.get("vencimento_solev", "").strip()
    if not venc_solev and _ve:
        dt_venc_eq    = datetime.strptime(_ve, _dfmt)
        venc_solev = (dt_venc_eq - timedelta(days=3)).strftime(_dfmt)

    out["num_dias"]       = str(num_dias)
    out["venc_solev"]  = venc_solev

    # ── mes_ano_fatura a partir de mes_referencia ──────────
    _meses = {1:"Janeiro",2:"Fevereiro",3:"Marco",4:"Abril",5:"Maio",6:"Junho",
              7:"Julho",8:"Agosto",9:"Setembro",10:"Outubro",11:"Novembro",12:"Dezembro"}
    mes_num, ano = d["mes_referencia"].split("/")
    mes_ano_fatura = f"{_meses[int(mes_num)]} / {ano}"
    out["mes_ano_fatura"] = mes_ano_fatura

    if _dl and _al:
        print(f"📅 Leitura anterior: {_al} → Leitura atual: {_dl} = {num_dias} dias")
    if _ve:
        print(f"📅 Venc. Equatorial: {_ve} → Venc. SOLEV: {venc_solev}")
    print(f"📅 Mes referencia: {d['mes_referencia']} → {mes_ano_fatura}")

    consumo       = d["consumo_kwh"]
    tarifa_sem    = d["tarifa_sem"]
    desconto      = d["desconto_pct"]
    comp          = d["consumo_compensado"]
    nao_comp      = d["consumo_nao_comp"]
    ilum          = d["iluminacao_publica"]
    multa         = d["multa"]         # multa Equatorial (SEM)
    juros         = d["juros"]         # juros Equatorial (SEM)
    ipca          = float(d.get("correcao_ipca", 0) or 0)
    eco_anterior  = d["economia_acumulada_anterior"]

    # ── BANDEIRAS ──────────────────────────────────────────
    # Valor R$ que a Equatorial cobrou (extraido da linha ADC BANDEIRA do PDF).
    # Pela SCEE, a Equatorial cobra a bandeira apenas sobre o consumo NAO
    # compensado pela geracao solar (energia injetada nao paga bandeira).
    adc_band_amar_eq = float(d.get("adc_bandeira_amarela",  0) or 0)
    adc_band_verm_eq = float(d.get("adc_bandeira_vermelha", 0) or 0)

    # ── Tarifa R$/kWh da bandeira — RESOLUCAO (fonte unica) ──────────────
    # Prioridade: (1) tarifa EXATA impressa na linha ADC do PDF; (2) adc_R$ /
    #             qtd_kWh (aproximada); (3) valor armazenado em tb_tarifas (so
    #             serve p/ cliente 100% compensado, cujo PDF nao tem bandeira).
    # NUNCA usar tb_tarifas quando ha consumo nao compensado — a fatura traz a
    # tarifa real do mes. Detalhes em memory business_rules_cobranca.md.
    def _resolver_tarifa_band(pdf_key, adc_eq, qtd_key, stored_key):
        pdf = float(d.get(pdf_key, 0) or 0)
        if pdf > 0:
            return round(pdf, 6)
        qtd = float(d.get(qtd_key, 0) or 0)
        if adc_eq > 0 and qtd > 0:
            return round(adc_eq / qtd, 6)
        return round(float(d.get(stored_key, 0) or 0), 6)

    tarifa_band_amar = _resolver_tarifa_band(
        "tarifa_bandeira_amarela_pdf", adc_band_amar_eq, "_bandeira_amarela_qtd",  "bandeira_tarifa_amar")
    tarifa_band_verm = _resolver_tarifa_band(
        "tarifa_bandeira_vermelha_pdf", adc_band_verm_eq, "_bandeira_vermelha_qtd", "bandeira_tarifa_verm")

    # ── MODO BANDEIRA ──────────────────────────────────────────
    # Define como a bandeira tarifaria aparece na conta:
    #
    #   "sem_bandeira" (UI: "Nao compensar"):
    #     Bandeira EMBUTIDA na tarifa equatorial (uma linha so).
    #     Tarifa efetiva = tarifa_sem + band_amar + band_verm
    #     SEM SOLEV: energia = consumo × tarifa_efetiva
    #     COM SOLEV: energia = comp × tarifa_efetiva × (1 - desconto)
    #     Nao aparece linha separada de bandeira em nenhum lado.
    #
    #   "com_bandeira" (UI: "Compensar bandeira"):
    #     Bandeira SEPARADA da tarifa equatorial.
    #     SEM SOLEV: linha de energia (consumo × tarifa) + linhas de bandeira
    #     COM SOLEV: cliente paga bandeira tambem pra SOLEV com desconto
    modo_band = (d.get("modo_bandeira") or "com_bandeira").strip().lower()
    cobra_band_solev = modo_band != "com_bandeira"

    if cobra_band_solev:
        # ── Modo "Nao compensar": bandeira embutida na tarifa ──
        tarifa_efetiva_sem = tarifa_sem + tarifa_band_amar + tarifa_band_verm
        tarifa_com         = tarifa_efetiva_sem * (1 - desconto)

        # SEM SOLEV: linha unica de energia (sem linhas de bandeira)
        total_consumo_tarifa_sem    = consumo * tarifa_efetiva_sem
        total_consumo_band_amar_sem = 0.0
        total_consumo_band_verm_sem = 0.0
        band_amar_sem_solev         = 0.0  # nao usado, mas mantido pra compat
        band_verm_sem_solev         = 0.0

        # COM SOLEV: linhas de bandeira ZERADAS (bandeira ja incluida na tarifa_com)
        band_amar_solev              = 0.0
        band_verm_solev              = 0.0
        total_compensado_com         = comp     * tarifa_com
        total_nao_comp_tarifa_com    = nao_comp * tarifa_efetiva_sem  # nao_comp tambem com bandeira embutida
        total_nao_comp_band_amar_com = 0.0
        total_nao_comp_band_verm_com = 0.0

        # Tarifa "Equatorial" exibida no PDF (SEM SOLEV) = efetiva
        tarifa_sem_display = tarifa_efetiva_sem
    else:
        # ── Modo "Compensar bandeira": bandeira SEPARADA ──
        # Cliente paga linhas de bandeira pra Equatorial (no SEM SOLEV).
        # SOLEV nao cobra bandeira (passa direto pra Equatorial via nao_comp).
        band_amar_sem_solev = consumo * tarifa_band_amar if tarifa_band_amar > 0 else 0.0
        band_verm_sem_solev = consumo * tarifa_band_verm if tarifa_band_verm > 0 else 0.0
        band_amar_solev     = 0.0  # SOLEV nao cobra bandeira
        band_verm_solev     = 0.0
        tarifa_com          = tarifa_sem * (1 - desconto)

        # SEM SOLEV: 3 linhas (Consumo x Tarifa, Consumo x BandAmar, Consumo x BandVerm)
        total_consumo_tarifa_sem    = consumo * tarifa_sem
        total_consumo_band_amar_sem = band_amar_sem_solev
        total_consumo_band_verm_sem = band_verm_sem_solev

        # COM SOLEV: 4 linhas — comp com desconto, nao_comp com tarifa cheia + bandeiras
        total_compensado_com         = comp     * tarifa_com
        total_nao_comp_tarifa_com    = nao_comp * tarifa_sem            # NaoComp paga tarifa Equatorial cheia
        total_nao_comp_band_amar_com = nao_comp * tarifa_band_amar      # Equatorial cobra band sobre NaoComp
        total_nao_comp_band_verm_com = nao_comp * tarifa_band_verm

        # Tarifa "Equatorial" exibida no PDF (SEM SOLEV) = soh a tarifa de energia
        tarifa_sem_display = tarifa_sem

    subtotal_sem = total_consumo_tarifa_sem  # mantido para retrocompat
    total_sem    = (total_consumo_tarifa_sem + total_consumo_band_amar_sem + total_consumo_band_verm_sem
                    + ilum + multa + juros + ipca)
    subtotal_com = total_compensado_com + total_nao_comp_tarifa_com  # mantido para retrocompat

    # ── Multa e juros SOLEV (atraso no pagamento do mes anterior) ─
    multa_com = 0.0
    juros_com = 0.0

    # Prioridade 1: override manual (usado na primeira cobranca de transicao)
    _multa_ov = d.get("multa_com_override", 0.0) or 0.0
    _juros_ov = d.get("juros_com_override", 0.0) or 0.0
    if _multa_ov > 0 or _juros_ov > 0:
        multa_com = float(_multa_ov)
        juros_com = float(_juros_ov)
        if multa_com > 0 or juros_com > 0:
            print(f"⚠️  Multa/Juros COM (manual): Multa = {_fmt_brl(multa_com)}, Juros = {_fmt_brl(juros_com)}")
    else:
        # Prioridade 2: calculo automatico a partir do mes anterior
        valor_ant = d.get("valor_cobranca_anterior", 0.0)
        venc_ant  = d.get("venc_solev_anterior", "").strip()
        pgto_ant  = d.get("data_pagamento_anterior", "").strip()

        if valor_ant > 0 and venc_ant and pgto_ant:
            dt_venc_ant = datetime.strptime(venc_ant, _dfmt)
            dt_pgto_ant = datetime.strptime(pgto_ant, _dfmt)
            dias_atraso = (dt_pgto_ant - dt_venc_ant).days
            if dias_atraso > 0:
                multa_com = valor_ant * 0.02                            # 2% sobre valor anterior
                juros_com = valor_ant * 0.001627 * dias_atraso          # 0,1627% ao dia
                print(f"⚠️  ATRASO MES ANTERIOR: {dias_atraso} dias (pagou {pgto_ant}, vencia {venc_ant})")
                print(f"⚠️  Base: cobranca anterior = {_fmt_brl(valor_ant)}")
                print(f"⚠️  Multa SOLEV: 2% de {_fmt_brl(valor_ant)} = {_fmt_brl(multa_com)}")
                print(f"⚠️  Juros SOLEV: 0,1627%/dia × {dias_atraso} dias de {_fmt_brl(valor_ant)} = {_fmt_brl(juros_com)}")

    difci           = float(d.get("difci",           0) or 0)
    ecnisenta       = float(d.get("ecnisenta",       0) or 0)
    ajuste_valor    = float(d.get("ajuste_valor",    0) or 0)
    compensacao_dic = float(d.get("compensacao_dic", 0) or 0)  # negativo = credito da distribuidora

    # ── ITENS FINANCEIROS ─────────────────────────────────────────────────
    total_financeiro_sem = ilum + multa + juros + ipca
    total_financeiro_com = ilum + multa_com + juros_com + difci + ecnisenta

    # Compensacao DIC e Ajuste afetam ambos (SEM e COM)
    total_sem = total_sem + compensacao_dic + ajuste_valor
    # TOTAL COM = soma das 4 linhas de energia + financeiros + ajustes
    total_com = (total_compensado_com + total_nao_comp_tarifa_com
                 + total_nao_comp_band_amar_com + total_nao_comp_band_verm_com
                 + total_financeiro_com + ajuste_valor + compensacao_dic)

    # ── DEDUCAO DE FIO B (modelo FIXO - usina absorve) ────────────────────
    # Usado para clientes com vinculo FIXO (ex.: Luiz Camilo), onde o
    # proprietario da usina assume o fio B no calculo do SOLEV.
    # Afeta apenas total_com (nao mexe em total_sem).
    # IMPORTANTE: o fio B NAO conta como economia para o cliente — ele soh
    # existe porque ha geracao injetada. Eh um custo que o usina absorve,
    # nao um beneficio real do cliente. Por isso a economia eh calculada
    # ANTES da deducao (economia = total_sem - total_com SEM fio_b_deducao).
    fio_b_deducao = float(d.get("fio_b_deducao", 0) or 0)
    total_com_antes_fio_b = total_com  # guarda para calcular economia depois
    if fio_b_deducao > 0:
        total_com = total_com - fio_b_deducao
        print(f"⚙️  Deducao fio B (FIXO): -{_fmt_brl(fio_b_deducao)}  -> TOTAL COM = {_fmt_brl(total_com)}")
    out["_fio_b_deducao"]      = fio_b_deducao
    out["fio_b_deducao_fmt"]   = _fmt_brl(fio_b_deducao) if fio_b_deducao > 0 else ""

    # Modo FIXO: a tarifa efetiva exibida no PDF inclui a deducao do fio B
    # (tarifa × (1-desconto) - tarifa_fio_b). Permite o cliente ver o valor real.
    if fio_b_deducao > 0 and comp > 0:
        # tarifa_fio_b implicita (deducao / kwh)
        tarifa_fio_b = fio_b_deducao / comp
        tarifa_com_efetiva = tarifa_com - tarifa_fio_b
        out["_tarifa_com_efetiva"]    = tarifa_com_efetiva
        out["tarifa_com_efetiva_fmt"] = _fmt_tarifa(tarifa_com_efetiva)

    # ── ECONOMIA ───────────────────────────────────────────
    # Economia = total_sem - total_com (mas IGNORA a deducao do fio B no FIXO,
    # pois fio B nao eh beneficio real ao cliente, eh apenas custo absorvido
    # pela usina). Para clientes normais, total_com_antes_fio_b == total_com.
    economia_mes  = total_sem - total_com_antes_fio_b
    economia_acum = max(0.0, eco_anterior + economia_mes)

    print("┌─────────────────────────────────────────────────┐")
    print("│           CALCULOS AUTOMATICOS                  │")
    print("├─────────────────────────────────────────────────┤")
    print(f"│ SEM SOLEV:                                      │")
    print(f"│   Consumo: {consumo:.2f} kWh × R$ {tarifa_sem:.6f}")
    print(f"│   Subtotal: {_fmt_brl(subtotal_sem)}")
    print(f"│   + Ilum: {_fmt_brl(ilum)} + Multa: {_fmt_brl(multa)} + Juros: {_fmt_brl(juros)}" + (f" + IPCA: {_fmt_brl(ipca)}" if ipca else ""))
    print(f"│   TOTAL SEM: {_fmt_brl(total_sem)}")
    print(f"│                                                 │")
    print(f"│ COM SOLEV:                                      │")
    print(f"│   Tarifa: R$ {tarifa_sem:.6f} × (1 - {desconto:.0%}) = R$ {tarifa_com:.6f}")
    print(f"│   Compensado: {comp:.2f} × R$ {tarifa_com:.6f} = {_fmt_brl(comp * tarifa_com)}")
    print(f"│   Nao Comp:   {nao_comp:.2f} × R$ {tarifa_sem:.6f} = {_fmt_brl(nao_comp * tarifa_sem)}")
    print(f"│   Subtotal: {_fmt_brl(subtotal_com)}")
    print(f"│   + Ilum: {_fmt_brl(ilum)} + Multa: {_fmt_brl(multa_com)} + Juros: {_fmt_brl(juros_com)}")
    if compensacao_dic != 0:
        print(f"│   + Compensacao DIC: {_fmt_brl(compensacao_dic)}")
    if ajuste_valor != 0:
        print(f"│   + Ajuste: {_fmt_brl(ajuste_valor)}")
    print(f"│   TOTAL COM: {_fmt_brl(total_com)}")
    print(f"│                                                 │")
    print(f"│ ECONOMIA:                                       │")
    print(f"│   Este mes: {_fmt_brl(total_sem)} - {_fmt_brl(total_com)} = {_fmt_brl(economia_mes)}")
    print(f"│   Anterior: {_fmt_brl(eco_anterior)}")
    print(f"│   Acumulada: {_fmt_brl(economia_acum)}")
    print("└─────────────────────────────────────────────────┘")

    out["cpf_fmt"]           = _fmt_cpf(d.get("cpf", ""))
    out["consumo_kwh_fmt"]   = _fmt_kwh(consumo)
    # No modo "Nao compensar", a tarifa exibida no SEM SOLEV inclui bandeira
    out["tarifa_sem_fmt"]    = _fmt_tarifa(tarifa_sem_display)
    out["subtotal_sem_fmt"]  = _fmt_brl(subtotal_sem)
    out["total_sem_fmt"]     = _fmt_brl(total_sem)
    out["consumo_comp_fmt"]  = _fmt_kwh(comp)
    out["consumo_ncomp_fmt"] = _fmt_kwh(nao_comp)
    out["tarifa_com_fmt"]    = _fmt_tarifa(tarifa_com)
    out["desconto_pct_fmt"]  = _fmt_pct(desconto)
    out["subtotal_com_fmt"]  = _fmt_brl(subtotal_com)
    out["total_com_fmt"]     = _fmt_brl(total_com)
    out["ilum_fmt"]          = _fmt_brl(ilum)
    out["multa_fmt"]         = _fmt_brl(multa)          # Equatorial (SEM)
    out["juros_fmt"]         = _fmt_brl(juros)          # Equatorial (SEM)
    out["ipca_fmt"]          = _fmt_brl(ipca) if ipca > 0 else ""
    out["_ipca"]             = ipca
    out["multa_com_fmt"]     = _fmt_brl(multa_com)
    out["juros_com_fmt"]     = _fmt_brl(juros_com)
    out["_multa_com"]        = multa_com   # numerico para verificar se ha atraso SOLEV
    out["_juros_com"]        = juros_com
    out["difci"]                  = difci
    out["ecnisenta"]              = ecnisenta
    out["difci_fmt"]              = _fmt_brl(difci)
    out["ecnisenta_fmt"]          = _fmt_brl(ecnisenta)
    out["ajuste_valor"]           = ajuste_valor
    out["ajuste_valor_fmt"]       = _fmt_brl(abs(ajuste_valor)) if ajuste_valor else ""
    out["compensacao_dic"]        = compensacao_dic
    out["compensacao_dic_fmt"]    = _fmt_brl(abs(compensacao_dic)) if compensacao_dic else ""
    out["economia_mes_fmt"]  = _fmt_brl(economia_mes)
    out["economia_acum_fmt"] = _fmt_brl(economia_acum)
    out["_subtotal_sem"] = subtotal_sem
    out["_total_sem"]    = total_sem
    out["_tarifa_com"]   = tarifa_com
    out["_subtotal_com"] = subtotal_com
    out["_total_com"]    = total_com
    out["_economia_mes"] = economia_mes
    out["_economia_acum"]= economia_acum
    # Bandeiras — para persistencia em tb_faturas e exibicao na fatura
    out["_band_amar_equatorial"] = adc_band_amar_eq
    out["_band_verm_equatorial"] = adc_band_verm_eq
    out["_band_amar_solev"]   = band_amar_solev
    out["_band_verm_solev"]   = band_verm_solev
    # Valor cobrado COM SOLEV (equatorial + solev por cor)
    out["_band_amar_total_com"] = adc_band_amar_eq + band_amar_solev
    out["_band_verm_total_com"] = adc_band_verm_eq + band_verm_solev
    # Valor que seria pago SEM SOLEV (sobre todo o consumo — para economia)
    out["_band_amar_total_sem"] = band_amar_sem_solev
    out["_band_verm_total_sem"] = band_verm_sem_solev
    out["band_amar_total_com_fmt"] = _fmt_brl(out["_band_amar_total_com"]) if out["_band_amar_total_com"] > 0 else ""
    out["band_verm_total_com_fmt"] = _fmt_brl(out["_band_verm_total_com"]) if out["_band_verm_total_com"] > 0 else ""
    out["band_amar_total_sem_fmt"] = _fmt_brl(out["_band_amar_total_sem"]) if out["_band_amar_total_sem"] > 0 else ""
    out["band_verm_total_sem_fmt"] = _fmt_brl(out["_band_verm_total_sem"]) if out["_band_verm_total_sem"] > 0 else ""
    # Itemizacao por linha — SEM SOLEV (3 linhas)
    out["_total_consumo_tarifa_sem"]    = total_consumo_tarifa_sem
    out["_total_consumo_band_amar_sem"] = total_consumo_band_amar_sem
    out["_total_consumo_band_verm_sem"] = total_consumo_band_verm_sem
    out["_total_financeiro_sem"]        = total_financeiro_sem
    out["total_consumo_tarifa_sem_fmt"]    = _fmt_brl(total_consumo_tarifa_sem)
    out["total_consumo_band_amar_sem_fmt"] = _fmt_brl(total_consumo_band_amar_sem)
    out["total_consumo_band_verm_sem_fmt"] = _fmt_brl(total_consumo_band_verm_sem)
    out["total_financeiro_sem_fmt"]        = _fmt_brl(total_financeiro_sem)

    # Itemizacao por linha — COM SOLEV (4 linhas)
    out["_total_compensado_com"]         = total_compensado_com
    out["_total_nao_comp_tarifa_com"]    = total_nao_comp_tarifa_com
    out["_total_nao_comp_band_amar_com"] = total_nao_comp_band_amar_com
    out["_total_nao_comp_band_verm_com"] = total_nao_comp_band_verm_com
    out["_total_financeiro_com"]         = total_financeiro_com
    out["total_compensado_com_fmt"]         = _fmt_brl(total_compensado_com)
    out["total_nao_comp_tarifa_com_fmt"]    = _fmt_brl(total_nao_comp_tarifa_com)
    out["total_nao_comp_band_amar_com_fmt"] = _fmt_brl(total_nao_comp_band_amar_com)
    out["total_nao_comp_band_verm_com_fmt"] = _fmt_brl(total_nao_comp_band_verm_com)
    out["total_financeiro_com_fmt"]         = _fmt_brl(total_financeiro_com)

    # Tarifas formatadas (alem das ja existentes tarifa_sem_fmt e tarifa_com_fmt)
    out["tarifa_band_amar_fmt"] = _fmt_tarifa(tarifa_band_amar) if tarifa_band_amar > 0 else "—"
    out["tarifa_band_verm_fmt"] = _fmt_tarifa(tarifa_band_verm) if tarifa_band_verm > 0 else "—"
    # Tarifa de bandeira RESOLVIDA — sobrescreve o valor cru de entrada para que
    # o badge (em _dict_para_contexto) leia exatamente a mesma tarifa usada aqui.
    out["bandeira_tarifa_amar"] = tarifa_band_amar
    out["bandeira_tarifa_verm"] = tarifa_band_verm
    return out


from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128
from reportlab.graphics.shapes import Drawing
import io
import base64
import os
import tempfile

_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── Compat: app.py chama _preparar_logos() na inicializacao ──────────────────
def _preparar_logos():
    pass


# ─── Geracao de barcode PNG em base64 ─────────────────────────────────────────
def _gerar_barcode_b64(codigo_barras: str) -> str:
    digits = "".join(c for c in (codigo_barras or "") if c.isdigit())
    if len(digits) < 10:
        return ""
    try:
        BAR_H = 40
        bc = code128.Code128(digits, barHeight=BAR_H, barWidth=0.9, humanReadable=False)
        d = Drawing(bc.width, BAR_H)
        d.add(bc)
        buf = io.BytesIO()
        renderPM.drawToFile(d, buf, fmt="PNG")
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()
    except Exception:
        return ""


# ─── Geracao de QR Code PIX em base64 ─────────────────────────────────────────
def _gerar_qr_b64(pix_qr_path: str, pix_payload: str) -> str:
    if pix_qr_path and os.path.exists(pix_qr_path):
        with open(pix_qr_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    if pix_payload and len(pix_payload) >= 20:
        try:
            import qrcode as _qr
            qr_obj = _qr.QRCode(box_size=8, border=1)
            qr_obj.add_data(pix_payload)
            qr_obj.make(fit=True)
            img = qr_obj.make_image(fill_color="#0E1B2E", back_color="#FFFFFF")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()
        except Exception:
            pass
    return ""


# ─── Playwright HTML → PDF ────────────────────────────────────────────────────
def _html_para_pdf(html_str: str) -> bytes:
    """Renderiza HTML para PDF via Playwright/Chromium.

    Cada chamada cria um browser efêmero — seguro em ambiente multi-thread
    (Flask threaded). Otimizações vs. versão original:
      - Espera apenas DOMContentLoaded (não networkidle) — fontes externas
        do Google são baixadas mas não bloqueiam a renderização
      - Timeout reduzido (8s vs 20s default)
      - Args do Chromium otimizados (sem GPU, sem sandbox)
    """
    with tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", encoding="utf-8", delete=False
    ) as f:
        f.write(html_str)
        tmp_path = f.name
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                args=[
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )
            try:
                page = browser.new_page()
                # wait_until="load" garante que fontes e CSS externos terminaram
                # de carregar antes do PDF ser gerado. Timeout maior (15s) acomoda
                # redes mais lentas — Google Fonts pode demorar 3-5s no 1º load.
                page.goto(
                    "file:///" + tmp_path.replace("\\", "/"),
                    wait_until="load",
                    timeout=15000,
                )
                # Espera adicional para fontes via FontFace API (web fonts)
                try:
                    page.evaluate("document.fonts.ready")
                    page.wait_for_function("document.fonts.status === 'loaded'", timeout=8000)
                except Exception:
                    pass
                pdf_bytes = page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "0mm", "right": "0mm",
                            "bottom": "0mm", "left": "0mm"},
                    prefer_css_page_size=True,
                )
            finally:
                browser.close()
        return pdf_bytes
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ─── Registro de fonte decorativa para o rodape ──────────────────────────────
def _registrar_fonte_rodape():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os
    _base = r"C:\Windows\Fonts"
    _map = {
        "Georgia":           os.path.join(_base, "georgia.ttf"),
        "Georgia-Italic":    os.path.join(_base, "georgiai.ttf"),
        "Georgia-Bold":      os.path.join(_base, "georgiab.ttf"),
    }
    try:
        registered = pdfmetrics.getRegisteredFontNames()
        for name, path in _map.items():
            if name not in registered and os.path.exists(path):
                pdfmetrics.registerFont(TTFont(name, path))
        return "Georgia" in pdfmetrics.getRegisteredFontNames()
    except Exception:
        return False


# ─── Overlay ReportLab para a pagina da Equatorial ───────────────────────────
def _criar_overlay_pdf(page_w: float = None, page_h: float = None) -> bytes:
    INK    = HexColor("#0E1B2E")
    ACCENT = HexColor("#E26A14")  # Laranja oficial (handoff 30/05/2026)
    PAPER  = HexColor("#F2E8D4")
    WHITE  = HexColor("#FFFFFF")
    MUTED  = HexColor("#888888")

    _geo = _registrar_fonte_rodape()
    F_TITLE = "Helvetica-Bold"
    F_SUB   = "Georgia"        if _geo else "Times-Roman"
    F_VERSE = "Georgia-Italic" if _geo else "Times-Italic"

    buf = io.BytesIO()
    _ps = (page_w, page_h) if (page_w and page_h) else A4
    c = canvas.Canvas(buf, pagesize=_ps)
    W, H = _ps

    # ── Faixa superior: wordmark SoLev + label direita ─────────────────────────
    STRIP_H = 11 * mm
    c.setFillColor(INK)
    c.rect(0, H - STRIP_H, W, STRIP_H, fill=1, stroke=0)

    MID_Y = H - STRIP_H / 2
    SX    = 12 * mm
    FS_WM = 17  # ligeiramente menor

    # Wordmark SoLev — areia sobre fundo INK. Vem do handoff oficial em
    # static/logo/ (letras em paths SVG → PNG, sem dependência de fonte).
    # Substituiu desenho manual via Helvetica + círculos (30/05/2026 audit).
    LOGO_PATH = os.path.join(_DIR, "static", "logo", "solev-wordmark-areia.png")
    LOGO_H_MM = 7   # altura na faixa de 11mm, com padding visual
    LOGO_H_PT = LOGO_H_MM * mm
    LOGO_W_PT = LOGO_H_PT * 3.08   # aspect ratio ~3.08:1 do wordmark
    c.drawImage(LOGO_PATH, SX, MID_Y - LOGO_H_PT / 2,
                width=LOGO_W_PT, height=LOGO_H_PT, mask='auto',
                preserveAspectRatio=True)

    c.setFillColor(ACCENT)
    c.setFont("Helvetica", 7.5)
    right_txt = "FATURA EQUATORIAL GO  ·  ANEXO"
    rw = c.stringWidth(right_txt, "Helvetica", 7.5)
    c.drawString(W - 12 * mm - rw, MID_Y - 2.5, right_txt)

    # ── Rodape grande: fundo INK (azul da logo), texto PAPER (areia) ─────────
    FOOTER_H = 110.5 * mm  # cobre boleto/PIX/codigo de barras da Equatorial
    c.setFillColor(INK)
    c.rect(0, 0, W, FOOTER_H, fill=1, stroke=0)
    # Linha decorativa laranja no topo do rodape
    c.setFillColor(ACCENT)
    c.rect(0, FOOTER_H - 0.5 * mm, W, 0.5 * mm, fill=1, stroke=0)

    # ── Logo SoLev + titulo (alinhados horizontalmente, centralizados) ──
    F_TITLE_FOOT = "Helvetica-Bold"
    F_SUB_FOOT   = "Georgia"        if _geo else "Times-Roman"
    F_VERSE_FOOT = "Georgia-Italic" if _geo else "Times-Italic"

    TITLE_TXT = "Obrigado pela sua confianca!"
    TITLE_FS  = 20
    SUB1 = "E um prazer cuidar da sua energia e da sua economia."
    SUB2 = "Que o sol continue iluminando os seus dias."
    SUB_FS = 10.5

    SYM_R = 13 * mm
    GAP   = 8 * mm

    c.setFont(F_TITLE_FOOT, TITLE_FS)
    title_w = c.stringWidth(TITLE_TXT, F_TITLE_FOOT, TITLE_FS)
    c.setFont(F_SUB_FOOT, SUB_FS)
    sub1_w  = c.stringWidth(SUB1, F_SUB_FOOT, SUB_FS)
    sub2_w  = c.stringWidth(SUB2, F_SUB_FOOT, SUB_FS)
    TEXT_W  = max(title_w, sub1_w, sub2_w)

    GROUP_W  = 2 * SYM_R + GAP + TEXT_W
    GROUP_X  = (W - GROUP_W) / 2
    SYM_CX   = GROUP_X + SYM_R
    SYM_CY   = FOOTER_H - 28 * mm
    TEXT_LFT = GROUP_X + 2 * SYM_R + GAP

    # Símbolo "o" areia sobre fundo INK — vem do handoff oficial em static/logo/
    # (substituiu desenho manual via 2 círculos em 30/05/2026 audit).
    SYM_PATH = os.path.join(_DIR, "static", "logo", "solev-symbol-areia.png")
    SYM_SIDE = 2 * SYM_R
    c.drawImage(SYM_PATH, SYM_CX - SYM_R, SYM_CY - SYM_R,
                width=SYM_SIDE, height=SYM_SIDE, mask='auto')

    # Texto principal em PAPER (areia) sobre fundo INK
    c.setFillColor(PAPER)
    c.setFont(F_TITLE_FOOT, TITLE_FS)
    c.drawString(TEXT_LFT, SYM_CY + 5 * mm, TITLE_TXT)
    c.setFont(F_SUB_FOOT, SUB_FS)
    c.drawString(TEXT_LFT, SYM_CY - 2 * mm, SUB1)
    c.drawString(TEXT_LFT, SYM_CY - 9 * mm, SUB2)

    # ── Separador decorativo + versiculo 1Co 13:4-7 centralizado ──
    SEP_Y = FOOTER_H - 56 * mm
    c.setStrokeColor(ACCENT); c.setLineWidth(0.35 * mm)
    c.line(28 * mm, SEP_Y, W - 28 * mm, SEP_Y)

    # Versiculo em PAPER (areia), levemente atenuado pela transparencia natural do italico
    c.setFillColor(PAPER)
    c.setFont(F_VERSE_FOOT, 10)
    LH = 5.6 * mm
    versos = [
        "“O amor e paciente, o amor e bondoso. Nao inveja, nao se vangloria, nao se orgulha.",
        "Nao maltrata, nao procura seus interesses, nao se ira facilmente, nao guarda rancor.",
        "O amor nao se alegra com a injustica, mas se alegra com a verdade.",
        "Tudo sofre, tudo cre, tudo espera, tudo suporta.”",
    ]
    for i, linha in enumerate(versos):
        c.drawCentredString(W / 2, SEP_Y - 8 * mm - i * LH, linha)

    c.setFillColor(ACCENT)
    c.setFont(F_VERSE_FOOT, 9)
    c.drawCentredString(W / 2, SEP_Y - 8 * mm - len(versos) * LH - 3 * mm,
                        "1 Corintios 13:4-7")

    c.save()
    buf.seek(0)
    return buf.getvalue()


# ─── Listas de linhas extras (bandeiras, IPCA, etc.) ─────────────────────────
def _extras_sem(d: dict) -> list:
    extras = []
    if d.get("_ipca", 0) > 0:
        extras.append({"label": "Correcao IPCA", "valor": d["ipca_fmt"]})
    if d.get("_band_amar_total_sem", 0) > 0:
        extras.append({"label": "Bandeira Amarela",
                       "valor": d.get("band_amar_total_sem_fmt", "")})
    if d.get("_band_verm_total_sem", 0) > 0:
        extras.append({"label": "Bandeira Vermelha",
                       "valor": d.get("band_verm_total_sem_fmt", "")})
    av = d.get("ajuste_valor", 0)
    if av > 0:
        extras.append({"label": "Acrescimo", "valor": d["ajuste_valor_fmt"]})
    elif av < 0:
        extras.append({"label": "Desconto", "valor": "- " + d["ajuste_valor_fmt"]})
    if d.get("compensacao_dic", 0) != 0:
        extras.append({"label": "Comp. DIC Mensal",
                       "valor": "- " + d.get("compensacao_dic_fmt", "")})
    return extras


def _extras_com(d: dict) -> list:
    extras = []
    if d.get("_ipca", 0) > 0:
        extras.append({"label": "Correcao IPCA", "valor": d["ipca_fmt"]})
    if d.get("_band_amar_total_com", 0) > 0:
        extras.append({"label": "Bandeira Amarela",
                       "valor": d.get("band_amar_total_com_fmt", "")})
    if d.get("_band_verm_total_com", 0) > 0:
        extras.append({"label": "Bandeira Vermelha",
                       "valor": d.get("band_verm_total_com_fmt", "")})
    if d.get("_multa_com", 0) > 0:
        extras.append({"label": "Multa SOLEV", "valor": d["multa_com_fmt"]})
    if d.get("_juros_com", 0) > 0:
        extras.append({"label": "Juros SOLEV", "valor": d["juros_com_fmt"]})
    if d.get("difci", 0) > 0:
        extras.append({"label": "DIFCI", "valor": d["difci_fmt"]})
    if d.get("ecnisenta", 0) > 0:
        extras.append({"label": "ECNISENTA", "valor": d["ecnisenta_fmt"]})
    av = d.get("ajuste_valor", 0)
    if av > 0:
        extras.append({"label": "Acrescimo", "valor": d["ajuste_valor_fmt"]})
    elif av < 0:
        extras.append({"label": "Desconto", "valor": "- " + d["ajuste_valor_fmt"]})
    if d.get("compensacao_dic", 0) != 0:
        extras.append({"label": "Comp. DIC Mensal",
                       "valor": "- " + d.get("compensacao_dic_fmt", "")})
    return extras


# ─── Monta contexto para o template Jinja2 ────────────────────────────────────
def _dict_para_contexto(d: dict, qr_b64: str, bar_b64: str) -> dict:
    _meses = ["", "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
              "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    try:
        mes_num = int(str(d.get("mes_referencia", "01/2026")).split("/")[0])
        mes_nome = _meses[mes_num] if 1 <= mes_num <= 12 else ""
    except Exception:
        mes_nome = ""

    end = d.get("endereco", "")
    if not end:
        parts = [d.get("endereco_linha1", ""), d.get("endereco_linha2", ""),
                 d.get("endereco_linha3", "")]
        end = "\n".join(p for p in parts if p)

    # Desconto exibido depende do modo de bandeira do cliente:
    # - COMPENSA bandeira (com_bandeira): (tarifa_eq + band_am + band_vm - tarifa_com) / tarifa_eq * 100
    #   ex.: Antonio com band_am=0,006346 => 20,56% (= 20% cadastrado + bonus da bandeira)
    # - NAO COMPENSA (sem_bandeira): apenas o percentual cadastrado, sem calculo
    desconto_cadastro = float(d.get("desconto_pct", 0) or 0) * 100
    _modo_band = (d.get("modo_bandeira") or "com_bandeira").strip().lower()
    if _modo_band == "com_bandeira":
        _t_eq    = float(d.get("tarifa_sem", 0) or 0)
        _b_am    = float(d.get("bandeira_tarifa_amar", 0) or 0)
        _b_vm    = float(d.get("bandeira_tarifa_verm", 0) or 0)
        _t_com_t = float(d.get("_tarifa_com", 0) or 0)
        _t_full = _t_eq + _b_am + _b_vm
        if _t_full > 0:
            # Denominador = tarifa cheia (eq + amarela + vermelha), NAO so a eq.
            # Conferido contra Pasta1.xlsx: (eq+am+vm - com)/(eq+am+vm).
            pct_float = (_t_full - _t_com_t) / _t_full * 100
        else:
            pct_float = desconto_cadastro
    else:
        pct_float = desconto_cadastro
    pct_int = f"{pct_float:.2f}".replace(".", ",")
    eco_mes = d.get("economia_mes_fmt", "R$ 0,00").replace("R$ ", "")

    # Modo FIXO: cliente compra a geração da usina (não usa o consumo do PDF)
    # Marcador = fio_b_deducao > 0 (setado quando o script FIXO injeta a dedução)
    is_fixo = float(d.get("fio_b_deducao", 0) or 0) > 0
    labels = {
        "consumo_total":      "Geração comprada" if is_fixo else "Consumo total",
        "consumo_comp":       "Geração comprada" if is_fixo else "Consumo compensado",
        "consumo_nao_comp":   "Consumo não compensado",  # ocultado quando FIXO
        "tarifa_sem":         "Tarifa da usina (R$ / kWh)" if is_fixo else "Tarifa (R$ / kWh)",
        "tarifa_com":         "Tarifa com desconto",
        "fio_b_absorvido":    "(−) Fio B absorvido pela usina",
    }

    # Consolidada: lista de UCs (cada uma vira uma linha "Geração comprada (UC X)")
    consumo_por_uc = d.get("consumo_por_uc") or []
    is_consolidada = bool(consumo_por_uc)

    return {
        "mes_ref":    d.get("mes_ano_fatura", ""),
        "mes_nome":   mes_nome,
        "vencimento": d.get("venc_solev", ""),
        "id_fatura":  d.get("id_fatura", ""),
        "is_fixo":    is_fixo,
        "is_consolidada":  is_consolidada,
        "consumo_por_uc":  consumo_por_uc,
        "labels":     labels,
        "fio_b_deducao_fmt": d.get("fio_b_deducao_fmt", ""),
        "cliente": {
            "nome":     d.get("nome", ""),
            "cpf":      d.get("cpf_fmt", "") or d.get("cpf", ""),
            "endereco": end,
            "cep":      d.get("cep", ""),
        },
        "uc":          d.get("unidade_consumidora", ""),
        "fornecimento": d.get("tipo_fornecimento", ""),
        "leitura": {
            "mes_ref":  d.get("mes_referencia", ""),
            "anterior": d.get("anterior_leitura", ""),
            "atual":    d.get("data_leitura", ""),
            "proxima":  d.get("proxima_leitura", ""),
            "dias":     d.get("num_dias", ""),
        },
        "sem_solev": {
            "consumo":      d.get("consumo_kwh_fmt", ""),
            "tarifa":       d.get("tarifa_sem_fmt", ""),
            "energia":      d.get("subtotal_sem_fmt", ""),
            "ilum":         d.get("ilum_fmt", ""),
            "multa":        d.get("multa_fmt", "R$ 0,00"),
            "juros":        d.get("juros_fmt", "R$ 0,00"),
            "ipca":         d.get("ipca_fmt", ""),
            "total":        d.get("total_sem_fmt", ""),
        },
        "com_solev": {
            "consumo_comp":      d.get("consumo_comp_fmt", ""),
            "consumo_nao_comp":  d.get("consumo_ncomp_fmt", ""),
            "tarifa_desc":       d.get("tarifa_com_fmt", ""),
            "energia":           d.get("subtotal_com_fmt", ""),
            "ilum":              d.get("ilum_fmt", ""),
            "multa":             d.get("multa_com_fmt", "R$ 0,00"),
            "juros":             d.get("juros_com_fmt", "R$ 0,00"),
            "difci":             d.get("difci_fmt", ""),
            "ecnisenta":         d.get("ecnisenta_fmt", ""),
            "total":             d.get("total_com_fmt", ""),
            "desconto_pct":      pct_int,
        },
        "economia_mes":       eco_mes,
        "economia_acumulada": d.get("economia_acum_fmt", ""),
        "boleto": {
            "linha_digitavel": d.get("linha_digitavel", ""),
            "valor":           d.get("total_com_fmt", ""),
            "barcode_b64":     bar_b64,
        },
        "pix": {
            "qr_b64":        qr_b64,
            "chave_display": d.get("pix_chave_display", ""),
            "banco":         "Banco Inter",
        },
        "extras_sem": _extras_sem(d),
        "extras_com":  _extras_com(d),
    }




def _gerar_fontes_locais_css() -> str:
    """Gera <style> com @font-face apontando para fontes locais via file:// URLs.

    Elimina dependência de Google Fonts ao gerar PDFs — carregamento instantâneo
    e consistente, sem precisar de internet. Fontes baixadas via:
        python scripts/baixar_fontes_cobranca.py

    Retorna '' se a pasta static/fonts não existir (cai pro fallback Google).
    """
    from pathlib import Path
    fontes_dir = Path(_DIR) / "static" / "fonts"
    if not fontes_dir.is_dir():
        return ""
    fonts_map = {
        "Sora":           [300, 400, 500, 600, 700, 800],
        "Manrope":        [400, 500, 600, 700],
        "JetBrains Mono": [400, 500],
    }
    blocos = []
    for family, weights in fonts_map.items():
        fname_base = family.replace(" ", "")
        for w in weights:
            for ext in (".woff2", ".ttf", ".woff"):
                font_file = fontes_dir / f"{fname_base}-{w}-normal{ext}"
                if font_file.exists():
                    fmt = {".woff2": "woff2", ".woff": "woff", ".ttf": "truetype"}[ext]
                    uri = font_file.resolve().as_uri()  # file:///C:/...
                    blocos.append(
                        f"@font-face {{ font-family: '{family}'; font-weight: {w}; "
                        f"font-style: normal; src: url('{uri}') format('{fmt}'); "
                        f"font-display: block; }}"
                    )
                    break
    if not blocos:
        return ""
    return "<style>\n" + "\n".join(blocos) + "\n</style>\n"


def _pagina1(d: dict, path: str):
    from jinja2 import Environment, FileSystemLoader
    qr_b64  = _gerar_qr_b64(d.get("pix_qr_path", ""), d.get("pix_payload", ""))
    bar_b64 = _gerar_barcode_b64(d.get("codigo_barras", ""))
    fatura  = _dict_para_contexto(d, qr_b64, bar_b64)
    env = Environment(
        loader=FileSystemLoader(os.path.join(_DIR, "templates")),
        autoescape=False,
    )
    html = env.get_template("fatura/cobranca.html").render(fatura=fatura)

    # ── Injeta fontes locais ANTES das tags <link> do Google ──
    # Garante que o Chromium renderiza com as fontes corretas
    # mesmo sem internet (zero dependência externa).
    fontes_inline = _gerar_fontes_locais_css()
    if fontes_inline:
        # Insere antes do primeiro preconnect (ou no início do <head>)
        if '<link rel="preconnect"' in html:
            html = html.replace(
                '<link rel="preconnect"',
                fontes_inline + '<link rel="preconnect"',
                1,
            )
        else:
            html = html.replace("<head>", "<head>\n" + fontes_inline, 1)

    pdf  = _html_para_pdf(html)
    with open(path, "wb") as f:
        f.write(pdf)


def _pagina2(d: dict, path: str):
    eq = d.get("equatorial_pdf", "")
    if not eq or not os.path.exists(eq):
        return
    from pypdf import PdfReader, PdfWriter
    eq_reader  = PdfReader(eq)
    eq_page    = eq_reader.pages[0]
    pw = float(eq_page.mediabox.width)
    ph = float(eq_page.mediabox.height)
    overlay_bytes = _criar_overlay_pdf(pw, ph)
    overlay_page  = PdfReader(io.BytesIO(overlay_bytes)).pages[0]
    eq_page.merge_page(overlay_page)
    writer = PdfWriter()
    writer.add_page(eq_page)
    with open(path, "wb") as f:
        writer.write(f)


def _nome_para_arquivo(nome):
    """Converte nome do cliente para nome de arquivo: usa apenas primeiro+ultimo
    em CamelCase, sem acentos. Ex: 'SERGIO ALFREDO TALONE' → 'SergioTalone'.
    Ver skill file-naming/ para o padrao completo."""
    import unicodedata
    nome_limpo = unicodedata.normalize('NFKD', nome).encode('ascii', 'ignore').decode('ascii')
    partes = nome_limpo.strip().split()
    if len(partes) > 2:
        partes = [partes[0], partes[-1]]
    return "".join(word.capitalize() for word in partes)


def _mes_para_yyyymm(mes_ref):
    """Converte 'MM/AAAA' para 'AAAAMM'. Tolera 'M/AAAA' (sem zero a esquerda).
    Ex: '04/2026' → '202604', '4/2026' → '202604'."""
    s = (mes_ref or "").strip().replace("/", "")
    if len(s) == 5:  # MAAAA → ano comeca no indice 1
        return s[1:] + s[0].zfill(2)
    if len(s) == 6:  # MMAAAA → MMAAAA → AAAAMM
        return s[2:] + s[:2]
    return s


def gerar_cobranca(d):
    _preparar_logos()
    # Nome do arquivo: padrao novo (YYYYMM)_SoLev_PrimeiroUltimo_idCliente.pdf
    # Ver skill file-naming/SKILL.md para detalhes
    nome_arq = _nome_para_arquivo(d["nome"])
    yyyymm = _mes_para_yyyymm(d.get("mes_referencia", "01/2026"))
    id_cliente = d.get("id_cliente")
    if id_cliente:
        # Padrao novo (preferido)
        d["output_path"] = os.path.join(
            _DIR, f"{yyyymm}_SoLev_{nome_arq}_{int(id_cliente)}.pdf"
        )
    else:
        # Fallback: padrao legado com sufixo de UC (compatibilidade)
        uc_suffix = ""
        if "unidade_consumidora" in d and d["unidade_consumidora"]:
            uc = str(d["unidade_consumidora"]).strip().replace(".", "").replace("-", "")
            uc_suffix = f"-{uc[-4:]}" if len(uc) >= 4 else f"-{uc}"
        d["output_path"] = os.path.join(
            _DIR, f"{yyyymm}-SoLev{nome_arq}{uc_suffix}.pdf"
        )
    dados = calcular(d)
    base = dados["output_path"].replace(".pdf", "")
    p1 = base + "_p1_tmp.pdf"; p2 = base + "_p2_tmp.pdf"; pm = base + "_merge_tmp.pdf"
    os.makedirs(os.path.dirname(dados["output_path"]) or ".", exist_ok=True)
    print("\nGerando pagina 1 (cobranca SOLEV)...")
    _pagina1(dados, p1)
    eq = dados.get("equatorial_pdf", "")
    if eq and os.path.exists(eq):
        print("Gerando pagina 2 (fatura Equatorial modificada)...")
        _pagina2(dados, p2)
        # Mescla paginas usando pypdf (Python puro, sem qpdf externo)
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()
        for src_pdf in [p1, p2]:
            reader = PdfReader(src_pdf)
            writer.add_page(reader.pages[0])
        with open(dados["output_path"], "wb") as f_out:
            writer.write(f_out)
        os.remove(p1); os.remove(p2)
    else:
        print("(Fatura Equatorial nao informada — apenas pag. 1)")
        # Apenas renomeia/copia a pagina 1
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(p1)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])
        with open(dados["output_path"], "wb") as f_out:
            writer.write(f_out)
        os.remove(p1)
    print(f"\n✅ Cobranca gerada: {dados['output_path']}")


if __name__ == "__main__":
    gerar_cobranca(DADOS)

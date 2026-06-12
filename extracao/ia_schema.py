"""Schema Pydantic + prompt para extracao de fatura via Claude API.

Importado de forma tardia por extracao/ia.py — este modulo so e carregado
quando uma chamada de IA realmente vai acontecer (requer `anthropic`/`pydantic`
instalados). O resto do pacote extracao nao depende dele.

Principio: a IA extrai o que esta IMPRESSO; valores derivados (consumo total,
compensado, nao compensado, DIFCI, somas SCEE) sao calculados em Python,
espelhando exatamente as regras do parser regex.
"""
from typing import List, Literal

from pydantic import BaseModel, Field

from extracao.models import Fatura, RateioItem, ScopeSCEE


# ──────────────────────────────────────────────────────────────────
# Schema — cada descricao ensina o modelo a achar o campo no layout
# da Equatorial Goias.
# ──────────────────────────────────────────────────────────────────

class InjecaoIA(BaseModel):
    """Uma linha 'INJECAO SCEE' da tabela de itens da fatura."""
    uc_geradora: str = Field(description=(
        "UC geradora impressa na linha, ex: 'INJECAO SCEE - UC 12345678 - GD II 2' -> '12345678'. "
        "ATENCAO: quando o cliente recebe de 2+ usinas, uma das linhas vem SEM o trecho "
        "'UC <n> -' (ex: 'INJECAO SCEE - GD II 2 kWh 640,00 ...') — inclua essa linha "
        "mesmo assim, com uc_geradora=''. NUNCA ignore uma linha de injecao."
    ))
    grupo: str = Field(description="Grupo impresso na linha: 'GD II' ou 'GD I'.")
    kwh: float = Field(description="Quantidade em kWh (1o numero da linha).")
    tarifa: float = Field(description="Tarifa unitaria R$/kWh impressa (2o numero da linha).")
    valor: float = Field(description="Valor em R$ da linha (3o numero; negativo na fatura = credito, retorne o valor absoluto).")


class UsinaGeradoraIA(BaseModel):
    """Item do bloco SCEE 'GERACAO CICLO (M/AAAA) KWH: UC x: v, UC y: v ...'."""
    uc: str = Field(description="UC da usina geradora, exatamente como impressa.")
    geracao_kwh: float = Field(description="Geracao do ciclo desta UC em kWh (lista 'GERACAO CICLO').")
    excedente_kwh: float = Field(description="Excedente recebido desta UC em kWh (lista 'EXCEDENTE RECEBIDO KWH:'). 0 se a UC nao aparece nessa lista.")


class RateioIA(BaseModel):
    """Item de 'CADASTRO RATEIO GERACAO: UC <n> = <pct>%'."""
    uc_geradora: str = Field(description="UC geradora do cadastro de rateio.")
    percentual: float = Field(description="Percentual deste consumidor no rateio da geradora, ex: 3.0 para '3,00%'.")


class FaturaIA(BaseModel):
    """Campos impressos numa fatura Equatorial Goias (valores BR convertidos: '1.234,56' -> 1234.56)."""

    # Identificacao
    uc: str = Field(description="Unidade Consumidora, exatamente como impressa (pode ter pontos e hifen, ex: '1.234.567.890-12', ou so digitos).")
    mes_referencia: str = Field(description="Mes de referencia no formato 'M/AAAA' SEM zero a esquerda (JAN/2026 -> '1/2026', MAI/2026 -> '5/2026').")
    tipo_uc: Literal["consumidora", "geradora"] = Field(description="'geradora' se a fatura tem linha 'ENERGIA GERACAO - KWH UNICO'; senao 'consumidora'.")

    # Titular
    nome: str = Field(description="Nome do titular da conta.")
    cpf: str = Field(description="CPF ou CNPJ do titular como impresso (com mascara). '' se nao visivel.")
    endereco: str = Field(description="Endereco do titular (logradouro e numero).")
    cidade: str = Field(description="Cidade.")
    uf: str = Field(description="UF, ex 'GO'.")
    cep: str = Field(description="CEP como impresso. '' se nao visivel.")

    # Datas e total
    vencimento: str = Field(description="Data de vencimento no formato DD/MM/AAAA.")
    total_fatura: float = Field(description="Valor total da fatura em R$ (ex: linha 'R$***121,93').")
    data_leitura_anterior: str = Field(description="Data da leitura anterior, DD/MM/AAAA.")
    data_leitura_atual: str = Field(description="Data da leitura atual, DD/MM/AAAA.")
    n_dias: int = Field(description="Numero de dias do ciclo de faturamento.")
    proxima_leitura: str = Field(description="Data prevista da proxima leitura, DD/MM/AAAA.")

    # Medidor
    leitura_anterior: str = Field(description="Leitura anterior do medidor de consumo (numero do registrador, como impresso). '' se nao visivel.")
    leitura_atual: str = Field(description="Leitura atual do medidor de consumo. '' se nao visivel.")

    # Consumo — linhas impressas na tabela de itens
    consumo_scee_kwh: float = Field(description="kWh da linha 'CONSUMO SCEE' (1o numero). 0 se a linha nao existe.")
    tarifa_scee: float = Field(description="Tarifa R$/kWh da linha 'CONSUMO SCEE' (2o numero). 0 se a linha nao existe.")
    consumo_nao_compensado_kwh: float = Field(description="kWh da linha 'CONSUMO NAO COMPENSADO', ou da linha 'CONSUMO kWh' em fatura convencional sem GD. 0 se nao existe.")
    tarifa_nao_compensado: float = Field(description="Tarifa R$/kWh da linha 'CONSUMO NAO COMPENSADO' (ou do 'CONSUMO kWh' convencional). 0 se nao existe.")
    injecoes: List[InjecaoIA] = Field(description="TODAS as linhas 'INJECAO SCEE - ... GD I/GD II ...' da tabela de itens, inclusive a que vier sem 'UC <n> -'.")

    # Encargos
    iluminacao_publica: float = Field(description="Valor R$ da 'CONTRIB ILUM PUBLICA' (ou 'ILUM ... MUNICIPAL'). 0 se ausente.")
    adc_bandeira_amarela_kwh: float = Field(description="Linha 'ADC BANDEIRA AMARELA': quantidade kWh (1o numero). 0 se ausente.")
    tarifa_bandeira_amarela_pdf: float = Field(description="Linha 'ADC BANDEIRA AMARELA': tarifa R$/kWh EXATA impressa (2o numero). 0 se ausente.")
    adc_bandeira_amarela: float = Field(description="Linha 'ADC BANDEIRA AMARELA': valor R$ (3o numero). 0 se ausente.")
    adc_bandeira_vermelha_kwh: float = Field(description="Linha 'ADC BANDEIRA VERMELHA': quantidade kWh. 0 se ausente.")
    tarifa_bandeira_vermelha_pdf: float = Field(description="Linha 'ADC BANDEIRA VERMELHA': tarifa R$/kWh EXATA impressa. 0 se ausente.")
    adc_bandeira_vermelha: float = Field(description="Linha 'ADC BANDEIRA VERMELHA': valor R$. 0 se ausente.")

    # Parcela injetada sem desconto / ECNISENTA
    pct_parc_injet: float = Field(description="Percentual da linha 'PARC INJET S/DESC - <pct>%', ex 30.0. 0 se ausente.")
    tarifa_parc_injet: float = Field(description="Tarifa R$/kWh da linha de parcela injetada s/ desconto ('... II 2 kWh <qtd> <tarifa> <valor>'). 0 se ausente.")
    valor_parc_injet: float = Field(description="Soma dos valores R$ das linhas de parcela injetada s/ desconto. 0 se ausente.")
    ecnisenta: float = Field(description="Soma dos valores R$ das linhas 'ENERGIA COMP NAO ISENTA' (o valor pode estar na linha seguinte). 0 se ausente.")

    # Multa/juros
    multa: float = Field(description="Soma das linhas de MULTA em R$. 0 se ausente.")
    juros: float = Field(description="Soma das linhas de JUROS em R$. 0 se ausente.")

    # Bloco SCEE (texto corrido, geralmente apos a tabela de itens)
    ciclo_geracao_mes: str = Field(description="Mes do ciclo de geracao em 'GERACAO CICLO (M/AAAA)', formato 'MM/AAAA' COM zero a esquerda (ex '04/2026'). '' se ausente.")
    usinas_geradoras: List[UsinaGeradoraIA] = Field(description="TODAS as UCs das listas 'GERACAO CICLO ... KWH:' e 'EXCEDENTE RECEBIDO KWH:' do bloco SCEE (uniao das duas listas).")
    credito_recebido_kwh: float = Field(description="'CREDITO RECEBIDO KWH <v>' (valor ja agregado). 0 se ausente.")
    saldo_kwh: float = Field(description="'SALDO KWH: <v>' (agregado; NAO confundir com 'SALDO A EXPIRAR'). 0 se ausente.")
    saldo_expirar_30d_kwh: float = Field(description="'SALDO A EXPIRAR EM 30 DIAS KWH: <v>'. 0 se ausente.")
    saldo_expirar_60d_kwh: float = Field(description="'SALDO A EXPIRAR EM 60 DIAS KWH: <v>'. 0 se ausente.")
    rateio: List[RateioIA] = Field(description="Itens de 'CADASTRO RATEIO GERACAO: UC <n> = <pct>%'. Lista vazia se ausente.")


PROMPT_SISTEMA = """Voce extrai dados de faturas de energia da Equatorial Goias (PDF anexado).

Regras:
- Transcreva EXATAMENTE o que esta impresso. Nao calcule, nao some, nao corrija valores — exceto onde o campo pedir soma explicitamente.
- Numeros vem no formato brasileiro ('1.234,56'); converta para decimal (1234.56).
- Campo ausente na fatura: use 0 para numeros, '' para textos, [] para listas.
- A tabela 'DESCRICAO / QUANT. / TARIFA / VALOR' e a fonte das linhas de consumo, injecao, bandeira e encargos. Em cada linha: 1o numero = quantidade, 2o = tarifa unitaria, 3o = valor em R$.
- Linhas de INJECAO SCEE aparecem com valor negativo (credito); retorne kwh/tarifa/valor como numeros positivos.
- O bloco SCEE (texto corrido com 'GERACAO CICLO', 'EXCEDENTE RECEBIDO', 'CREDITO RECEBIDO', 'SALDO', 'CADASTRO RATEIO GERACAO') pode listar VARIAS usinas separadas por virgula — capture todas.
- Se um campo aparecer mais de uma vez, use a ocorrencia da tabela de itens da pagina 1."""


# ──────────────────────────────────────────────────────────────────
# Conversao FaturaIA -> Fatura (deriva os mesmos campos que o regex)
# ──────────────────────────────────────────────────────────────────

def para_fatura(ia: FaturaIA) -> Fatura:
    """Monta uma Fatura a partir do extraido pela IA, replicando as
    derivacoes do parser regex (consumo total, compensado, DIFCI, somas SCEE)."""
    consumo_kwh = ia.consumo_scee_kwh + ia.consumo_nao_compensado_kwh
    compensado  = sum(i.kwh for i in ia.injecoes)
    nao_comp    = max(0.0, consumo_kwh - compensado)
    if ia.consumo_nao_compensado_kwh > 0:
        nao_comp = ia.consumo_nao_compensado_kwh

    consumo_val = ia.consumo_scee_kwh * ia.tarifa_scee
    injecao_val = sum(i.kwh * i.tarifa for i in ia.injecoes)
    difci       = round(max(0.0, consumo_val - injecao_val), 2)

    # Fallback identico ao parser: compensado via credito recebido
    if compensado == 0 and ia.credito_recebido_kwh > 0:
        compensado = ia.credito_recebido_kwh
        nao_comp   = max(0.0, consumo_kwh - compensado)
        if ia.consumo_nao_compensado_kwh > 0:
            nao_comp = ia.consumo_nao_compensado_kwh

    geracao_kwh   = sum(u.geracao_kwh for u in ia.usinas_geradoras)
    excedente_kwh = sum(u.excedente_kwh for u in ia.usinas_geradoras)
    rateio_items  = [RateioItem(uc_geradora=r.uc_geradora, percentual=r.percentual) for r in ia.rateio]

    scee = None
    if geracao_kwh > 0 or excedente_kwh > 0 or ia.credito_recebido_kwh > 0:
        scee = ScopeSCEE(
            uc_geradora=ia.usinas_geradoras[0].uc if ia.usinas_geradoras else "",
            geracao_ciclo_kwh=geracao_kwh,
            excedente_recebido_kwh=excedente_kwh,
            credito_recebido_kwh=ia.credito_recebido_kwh,
            saldo_kwh=ia.saldo_kwh,
            saldo_expirar_30d_kwh=ia.saldo_expirar_30d_kwh,
            saldo_expirar_60d_kwh=ia.saldo_expirar_60d_kwh,
            ciclo_mes=ia.ciclo_geracao_mes,
            rateio=rateio_items,
        )

    return Fatura(
        uc=ia.uc,
        mes_referencia=ia.mes_referencia,
        tipo_uc=ia.tipo_uc,
        nome=ia.nome,
        cpf=ia.cpf,
        endereco=ia.endereco,
        cidade=ia.cidade,
        uf=ia.uf,
        cep=ia.cep,
        vencimento=ia.vencimento,
        total_fatura=ia.total_fatura,
        data_leitura_anterior=ia.data_leitura_anterior,
        data_leitura_atual=ia.data_leitura_atual,
        n_dias=ia.n_dias,
        proxima_leitura=ia.proxima_leitura,
        leitura_anterior=ia.leitura_anterior,
        leitura_atual=ia.leitura_atual,
        consumo_kwh=consumo_kwh,
        tarifa_scee=ia.tarifa_scee,
        compensado_kwh=compensado,
        nao_comp_kwh=nao_comp,
        consumo_nao_comp_kwh=ia.consumo_nao_compensado_kwh,
        tarifa_convencional=ia.tarifa_nao_compensado,
        pct_parc_injet=ia.pct_parc_injet,
        tarifa_nao_comp=ia.tarifa_parc_injet,
        valor_parc_injet=ia.valor_parc_injet,
        ecnisenta=ia.ecnisenta,
        difci=difci,
        iluminacao_publica=ia.iluminacao_publica,
        adc_bandeira_amarela=ia.adc_bandeira_amarela,
        adc_bandeira_vermelha=ia.adc_bandeira_vermelha,
        # No dict da extracao, bandeira_* carrega a QUANTIDADE kWh da linha ADC
        # (consumida como _bandeira_*_qtd na cobranca), nao o valor em R$.
        bandeira_amarela=ia.adc_bandeira_amarela_kwh,
        bandeira_vermelha=ia.adc_bandeira_vermelha_kwh,
        tarifa_bandeira_amarela_pdf=ia.tarifa_bandeira_amarela_pdf,
        tarifa_bandeira_vermelha_pdf=ia.tarifa_bandeira_vermelha_pdf,
        multa=ia.multa,
        juros=ia.juros,
        ciclo_geracao_mes=ia.ciclo_geracao_mes,
        geracao_ciclo_kwh=geracao_kwh,
        excedente_recebido_kwh=excedente_kwh,
        credito_recebido_kwh=ia.credito_recebido_kwh,
        saldo_kwh=ia.saldo_kwh,
        saldo_expirar_30d_kwh=ia.saldo_expirar_30d_kwh,
        saldo_expirar_60d_kwh=ia.saldo_expirar_60d_kwh,
        scee=scee,
        rateio=rateio_items,
        usinas_geradoras=[
            {"uc": u.uc, "geracao_kwh": u.geracao_kwh, "excedente_kwh": u.excedente_kwh}
            for u in ia.usinas_geradoras
        ],
        fonte_extracao="ia",
    )

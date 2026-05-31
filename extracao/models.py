from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class ItemFinanceiro:
    tipo: str        # "MULTA" | "JUROS" | "CORRECAO_IPCA"
    mes_origem: str  # "03/2026" quando extraivel, "" caso contrario
    base: float
    valor: float


@dataclass
class RateioItem:
    uc_geradora: str   # UC da geradora que alimenta este consumidor
    percentual: float  # percentual alocado para este consumidor (ex: 3.0 = 3%)


@dataclass
class HistoricoMes:
    consumo_kwh: float
    valor_rs: float
    dias: int
    status: str  # "LIDA" | "MINIMO" | ""


@dataclass
class ScopeSCEE:
    uc_geradora: str
    geracao_ciclo_kwh: float
    excedente_recebido_kwh: float
    credito_recebido_kwh: float
    saldo_kwh: float
    saldo_expirar_30d_kwh: float
    saldo_expirar_60d_kwh: float
    ciclo_mes: str = ""              # ex: "04/2026"
    rateio: List[RateioItem] = field(default_factory=list)


@dataclass
class Fatura:
    # Identificacao
    uc: str = ""
    mes_referencia: str = ""
    tipo_uc: str = "consumidora"  # "consumidora" | "geradora"
    tipo_fornecimento: str = ""
    classificacao: str = ""

    # Titular
    nome: str = ""
    cpf: str = ""
    endereco: str = ""
    cep: str = ""
    cidade: str = ""
    uf: str = ""

    # Datas
    vencimento: str = ""
    data_leitura_anterior: str = ""
    data_leitura_atual: str = ""
    n_dias: int = 0
    proxima_leitura: str = ""

    # Totais
    total_fatura: float = 0.0

    # Consumo / SCEE
    consumo_kwh: float = 0.0
    tarifa_scee: float = 0.0
    compensado_kwh: float = 0.0
    nao_comp_kwh: float = 0.0
    consumo_nao_comp_kwh: float = 0.0
    tarifa_convencional: float = 0.0
    pct_parc_injet: float = 0.0
    tarifa_nao_comp: float = 0.0
    valor_parc_injet: float = 0.0
    ecnisenta: float = 0.0
    difci: float = 0.0

    # Encargos
    iluminacao_publica: float = 0.0
    adc_bandeira_amarela: float = 0.0
    adc_bandeira_vermelha: float = 0.0
    bandeira_amarela: float = 0.0
    bandeira_vermelha: float = 0.0
    # Tarifa R$/kWh impressa na linha ADC BANDEIRA do PDF (exata — preferida no resolver)
    tarifa_bandeira_amarela_pdf: float = 0.0
    tarifa_bandeira_vermelha_pdf: float = 0.0

    # Itens financeiros (multa/juros com detalhe)
    multa: float = 0.0
    juros: float = 0.0
    correcao_ipca: float = 0.0
    compensacao_dic: float = 0.0
    itens_financeiros: List[ItemFinanceiro] = field(default_factory=list)

    # Tributos
    pis_pasep_base: float = 0.0
    pis_pasep_aliquota: float = 0.0
    pis_pasep_valor: float = 0.0
    cofins_base: float = 0.0
    cofins_aliquota: float = 0.0
    cofins_valor: float = 0.0
    icms_base: float = 0.0
    icms_aliquota: float = 0.0
    icms_valor: float = 0.0

    # Medidor
    leitura_anterior: str = ""
    leitura_atual: str = ""
    constante: float = 1.0
    geracao_leitura_anterior: str = ""
    geracao_leitura_atual: str = ""
    geracao_medidor_kwh: float = 0.0

    # SCEE (campos planos para compatibilidade)
    ciclo_geracao_mes: str = ""          # ex: "04/2026"  — mês da geração (pode diferir do mês da fatura)
    geracao_ciclo_kwh: float = 0.0
    excedente_recebido_kwh: float = 0.0
    credito_recebido_kwh: float = 0.0
    saldo_kwh: float = 0.0
    saldo_expirar_30d_kwh: float = 0.0
    saldo_expirar_60d_kwh: float = 0.0
    scee: Optional[ScopeSCEE] = None

    # Rateio — percentual deste consumidor na(s) geradora(s)
    rateio: List[RateioItem] = field(default_factory=list)

    # Lista detalhada de usinas geradoras que contribuiram com kWh nesta UC.
    # Cada item: {"uc": str, "geracao_kwh": float, "excedente_kwh": float}
    # Cliente pode receber credito de N usinas; campos escalares acima sao SOMAS.
    usinas_geradoras: List[dict] = field(default_factory=list)

    # Historico 12 meses
    historico_meses: List[HistoricoMes] = field(default_factory=list)

    # NF-e e pagamento
    nota_fiscal_num: str = ""
    chave_acesso: str = ""
    protocolo_autorizacao: str = ""
    cfop: str = ""
    cfop_descricao: str = ""
    data_emissao_nf: str = ""
    codigo_barras: str = ""
    pix_br_code: str = ""

    # Tecnico
    tensao_nominal: float = 0.0
    vrc: float = 0.0
    _n_paginas: int = 1

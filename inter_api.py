# inter_api.py — cliente para a API do Banco Inter (Cobrança v3)
#
# Autenticação: OAuth 2.0 client_credentials + mTLS (certificado digital).
# Cada requisição precisa do par (cert.crt, cert.key) em disco.
#
# Variáveis de ambiente necessárias (.env e Railway):
#   INTER_CLIENT_ID      — client_id do app Inter
#   INTER_CLIENT_SECRET  — client_secret do app Inter
#   INTER_CERT_PATH      — caminho absoluto para o .crt (PEM)
#   INTER_KEY_PATH       — caminho absoluto para o .key (PEM)
#   INTER_AMBIENTE       — "sandbox" | "producao"  (default: sandbox)
#
# Geração do certificado (uma vez só, no terminal):
#   openssl req -newkey rsa:2048 -nodes -keyout inter.key -out inter.csr
#   → Suba o inter.csr no portal Inter > Configurações > Certificados
#   → Baixe o inter.crt devolvido
#   → Guarde inter.key e inter.crt em local seguro (não commite)

import os
import time
import logging
import requests

log = logging.getLogger(__name__)

_BASES = {
    "sandbox":  "https://cdpj.partners.uatinter.com.br",
    "producao": "https://cdpj.partners.bancointer.com.br",
}

# Cache em memória do token (evita pedir novo a cada chamada)
_token_cache: dict = {"token": None, "expires_at": 0.0}


def _cfg() -> dict:
    ambiente = os.getenv("INTER_AMBIENTE", "sandbox")
    return {
        "client_id":     os.getenv("INTER_CLIENT_ID", ""),
        "client_secret": os.getenv("INTER_CLIENT_SECRET", ""),
        "cert":          (os.getenv("INTER_CERT_PATH", ""), os.getenv("INTER_KEY_PATH", "")),
        "base":          _BASES.get(ambiente, _BASES["sandbox"]),
        "ambiente":      ambiente,
    }


def _inter_configurado() -> bool:
    cfg = _cfg()
    return bool(cfg["client_id"] and cfg["client_secret"]
                and cfg["cert"][0] and cfg["cert"][1]
                and os.path.exists(cfg["cert"][0])
                and os.path.exists(cfg["cert"][1]))


def _get_token() -> str:
    cfg = _cfg()
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]

    r = requests.post(
        f"{cfg['base']}/oauth/v2/token",
        cert=cfg["cert"],
        data={
            "client_id":     cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "scope":         "cobranca.write cobranca.read webhook.write webhook.read",
            "grant_type":    "client_credentials",
        },
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    _token_cache["token"]      = data["access_token"]
    _token_cache["expires_at"] = now + int(data.get("expires_in", 3600))
    log.info(f"[inter] token obtido (ambiente={cfg['ambiente']})")
    return _token_cache["token"]


def criar_cobranca(
    valor: float,
    vencimento_iso: str,   # "YYYY-MM-DD"
    nome_pagador: str,
    cpf_cnpj: str,
    seu_numero: str,       # sua referência única, ex: "SOLEV-42"
    descricao: str = "",
    cep: str = "65000000",
    cidade: str = "Sao Luis",
    uf: str = "MA",
    multa_pct: float = 2.0,
    mora_mes_pct: float = 1.0,
) -> dict:
    """Emite boleto + PIX via API Inter.

    Retorna o dict completo da Inter. Campos úteis:
      nossoNumero   — ID único da cobrança no Inter (guardar em tb_faturas)
      linhaDigitavel — linha digitável do boleto
      pixCopiaECola  — string Pix Copia e Cola (BR Code EMV com valor)
      codigoBarras   — código de barras numérico
    """
    if not _inter_configurado():
        raise RuntimeError("Inter API não configurada — verifique INTER_CLIENT_ID, "
                           "INTER_CLIENT_SECRET, INTER_CERT_PATH, INTER_KEY_PATH no .env")

    cfg   = _cfg()
    token = _get_token()

    # Limpa CPF/CNPJ (só dígitos)
    cpf_cnpj_digits = "".join(c for c in cpf_cnpj if c.isdigit())
    tipo_pessoa = "FISICA" if len(cpf_cnpj_digits) <= 11 else "JURIDICA"

    payload = {
        "seuNumero":      seu_numero[:35],
        "valorNominal":   round(float(valor), 2),
        "dataVencimento": vencimento_iso,
        "numDiasAgenda":  60,
        "pagador": {
            "cpfCnpj":   cpf_cnpj_digits,
            "tipoPessoa": tipo_pessoa,
            "nome":       nome_pagador[:40],
            "endereco":   "Nao informado",
            "numero":     "SN",
            "bairro":     "Centro",
            "cidade":     cidade[:30],
            "uf":         uf[:2].upper(),
            "cep":        cep.replace("-", "")[:8],
        },
        "descricao":  (descricao or "Energia solar SOLEV")[:50],
        "multa":      {"codigo": "PERCENTUAL", "taxa": multa_pct},
        "mora":       {"codigo": "TAXAMENSAL", "taxa": mora_mes_pct},
        "descontos":  [],
        "mensagens":  ["Obrigado por escolher energia solar!"],
    }

    r = requests.post(
        f"{cfg['base']}/cobranca/v3/cobrancas",
        cert=cfg["cert"],
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    log.info(f"[inter] cobrança emitida: seuNumero={seu_numero} "
             f"nossoNumero={data.get('nossoNumero')} valor={valor}")
    return data


def get_cobranca(nosso_numero: str) -> dict:
    """Consulta status atualizado de uma cobrança pelo nossoNumero."""
    if not _inter_configurado():
        raise RuntimeError("Inter API não configurada")

    cfg   = _cfg()
    token = _get_token()
    r = requests.get(
        f"{cfg['base']}/cobranca/v3/cobrancas/{nosso_numero}",
        cert=cfg["cert"],
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def get_pdf_bytes(nosso_numero: str) -> bytes:
    """Baixa o PDF do boleto como bytes (para salvar ou servir ao cliente)."""
    if not _inter_configurado():
        raise RuntimeError("Inter API não configurada")

    cfg   = _cfg()
    token = _get_token()
    r = requests.get(
        f"{cfg['base']}/cobranca/v3/cobrancas/{nosso_numero}/pdf",
        cert=cfg["cert"],
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.content


def configurar_webhook(webhook_url: str) -> dict:
    """Registra (ou atualiza) a URL de webhook no Inter.

    O Inter chama essa URL via POST quando uma cobrança é paga.
    Deve ser chamado uma vez durante o setup.
    """
    if not _inter_configurado():
        raise RuntimeError("Inter API não configurada")

    cfg   = _cfg()
    token = _get_token()
    r = requests.put(
        f"{cfg['base']}/cobranca/v3/cobrancas/webhook",
        cert=cfg["cert"],
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"webhookUrl": webhook_url},
        timeout=15,
    )
    r.raise_for_status()
    result = r.json() if r.text.strip() else {"ok": True}
    log.info(f"[inter] webhook configurado: {webhook_url}")
    return result

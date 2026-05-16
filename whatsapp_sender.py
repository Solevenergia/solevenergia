"""
whatsapp_sender.py — SOLEV
Envia mensagens e PDFs via Evolution API (WhatsApp)
"""

import requests
import base64
import os
import json
from pathlib import Path
from datetime import datetime


# ─── CONFIGURACAO ───────────────────────────────────────────────────────────
EVOLUTION_API_URL = "http://localhost:8080"   # URL da sua Evolution API
EVOLUTION_API_KEY = "SUA_API_KEY_AQUI"        # API Key configurada
INSTANCE_NAME    = "contalev"                  # Nome da instancia no Evolution


# ─── HEADERS PADRAO ─────────────────────────────────────────────────────────
def _headers():
    return {
        "Content-Type": "application/json",
        "apikey": EVOLUTION_API_KEY,
    }


# ─── VERIFICA STATUS DA INSTANCIA ───────────────────────────────────────────
def verificar_conexao() -> dict:
    """Verifica se a instancia WhatsApp esta conectada."""
    url = f"{EVOLUTION_API_URL}/instance/connectionState/{INSTANCE_NAME}"
    resp = requests.get(url, headers=_headers(), timeout=10)
    resp.raise_for_status()
    data = resp.json()
    estado = data.get("instance", {}).get("state", "unknown")
    print(f"[WA] Status da instancia '{INSTANCE_NAME}': {estado}")
    return data


# ─── FORMATA NUMERO ─────────────────────────────────────────────────────────
def _formatar_numero(numero: str) -> str:
    """
    Normaliza numero para formato Evolution API.
    Entrada:  (62) 99999-9999  ou  62999999999  ou  5562999999999
    Saida:    5562999999999@s.whatsapp.net
    """
    limpo = "".join(filter(str.isdigit, numero))
    if not limpo.startswith("55"):
        limpo = "55" + limpo
    return f"{limpo}@s.whatsapp.net"


# ─── ENVIA TEXTO ────────────────────────────────────────────────────────────
def enviar_texto(numero: str, mensagem: str) -> dict:
    """Envia mensagem de texto simples."""
    url = f"{EVOLUTION_API_URL}/message/sendText/{INSTANCE_NAME}"
    payload = {
        "number": _formatar_numero(numero),
        "text": mensagem,
    }
    resp = requests.post(url, headers=_headers(), json=payload, timeout=15)
    resp.raise_for_status()
    print(f"[WA] Texto enviado para {numero}")
    return resp.json()


# ─── ENVIA PDF ──────────────────────────────────────────────────────────────
def enviar_pdf(numero: str, caminho_pdf: str, caption: str = "") -> dict:
    """
    Envia um PDF como documento.
    caminho_pdf: caminho absoluto ou relativo ao arquivo .pdf
    caption: legenda exibida embaixo do documento
    """
    caminho = Path(caminho_pdf)
    if not caminho.exists():
        raise FileNotFoundError(f"PDF nao encontrado: {caminho_pdf}")

    # Codifica em base64
    with open(caminho, "rb") as f:
        conteudo_b64 = base64.b64encode(f.read()).decode("utf-8")

    url = f"{EVOLUTION_API_URL}/message/sendMedia/{INSTANCE_NAME}"
    payload = {
        "number": _formatar_numero(numero),
        "mediatype": "document",
        "mimetype": "application/pdf",
        "caption": caption,
        "fileName": caminho.name,
        "media": conteudo_b64,
    }
    resp = requests.post(url, headers=_headers(), json=payload, timeout=60)
    resp.raise_for_status()
    print(f"[WA] PDF '{caminho.name}' enviado para {numero}")
    return resp.json()


# ─── MENSAGEM PADRAO SOLEV ────────────────────────────────────────────────
def montar_mensagem_cobranca(nome: str, mes_ref: str, valor: float, vencimento: str, economia: float) -> str:
    """
    Monta a mensagem padrao de cobranca SOLEV.
    """
    primeiro_nome = nome.strip().split()[0].title()
    return (
        f"Ola, *{primeiro_nome}*! 👋\n\n"
        f"Segue sua fatura SOLEV referente a *{mes_ref}*.\n\n"
        f"💰 *Valor:* R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + "\n"
        f"📅 *Vencimento:* {vencimento}\n"
        f"🌿 *Economia do mes:* R$ {economia:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + "\n\n"
        f"O PDF com o boleto e QR Code PIX esta anexo.\n\n"
        f"Qualquer duvida, estamos a disposicao! 😊\n"
        f"*Equipe SOLEV* — _O sol gera. A SOLEV reduz._"
    )


# ─── ENVIO COMPLETO (TEXTO + PDF) ────────────────────────────────────────────
def enviar_cobranca_completa(
    numero: str,
    nome: str,
    mes_ref: str,
    valor: float,
    vencimento: str,
    economia: float,
    caminho_pdf: str,
) -> bool:
    """
    Envia mensagem de texto + PDF de cobranca para o cliente.
    Retorna True se sucesso, False se falhou.
    """
    try:
        mensagem = montar_mensagem_cobranca(nome, mes_ref, valor, vencimento, economia)
        enviar_texto(numero, mensagem)

        caption = f"Fatura SOLEV — {mes_ref} | Venc. {vencimento}"
        enviar_pdf(numero, caminho_pdf, caption=caption)

        print(f"[WA] ✅ Cobranca enviada com sucesso para {nome} ({numero})")
        return True

    except requests.exceptions.ConnectionError:
        print(f"[WA] ❌ Erro de conexao com Evolution API. Verifique se esta rodando em {EVOLUTION_API_URL}")
        return False
    except requests.exceptions.HTTPError as e:
        print(f"[WA] ❌ Erro HTTP: {e.response.status_code} — {e.response.text}")
        return False
    except Exception as e:
        print(f"[WA] ❌ Erro inesperado: {e}")
        return False


# ─── LOG DE ENVIOS ───────────────────────────────────────────────────────────
def registrar_envio(uc: str, nome: str, numero: str, sucesso: bool, log_path: str = "log_envios.json"):
    """Registra resultado do envio em arquivo JSON."""
    log = []
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            try:
                log = json.load(f)
            except json.JSONDecodeError:
                log = []

    log.append({
        "timestamp": datetime.now().isoformat(),
        "uc": uc,
        "nome": nome,
        "numero": numero,
        "sucesso": sucesso,
    })

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# ─── TESTE RAPIDO ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Testando conexao com Evolution API...")
    try:
        status = verificar_conexao()
        print(json.dumps(status, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Falha na conexao: {e}")

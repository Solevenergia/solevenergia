"""
Funcoes utilitarias compartilhadas — formatacao, PIX, clientes, tarifas.
Importar daqui em vez de definir no app.py.
"""
import re
from datetime import datetime

from db import carregar_tarifas, carregar_clientes

# ── Formatacao de datas ──────────────────────────────────────

def _iso_to_br(v):
    """Converte YYYY-MM-DD -> DD/MM/YYYY. Retorna '' se invalido."""
    if not v:
        return ""
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(v)

def _data_br_para_iso(s):
    """Converte 'DD/MM/AAAA' em 'AAAA-MM-DD'. Retorna None se vazio/invalido.
    Aceita tambem ISO ja formatado (passa direto)."""
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return s[:10]
    try:
        return datetime.strptime(s, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None

# ── Formatacao de campos ─────────────────────────────────────

def _fmt_uc15(v):
    """Formata UC de 15 digitos como xxxx.xxx.xxx.xxx-xx. Retorna original se nao for 15 digitos."""
    d = re.sub(r'[.\-\s]', '', str(v or ''))
    if len(d) == 15:
        return f"{d[:4]}.{d[4:7]}.{d[7:10]}.{d[10:13]}-{d[13:]}"
    return v or ''

def _fmt_cpf_cnpj(v):
    """Formata CPF (xxx.xxx.xxx-xx) ou CNPJ (xx.xxx.xxx/xxxx-xx). Retorna original se invalido."""
    d = re.sub(r'[.\-/\s]', '', str(v or ''))
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return v or ''

def _fmt_cep(v):
    """Formata CEP de 8 digitos como xx.xxx-xxx. Retorna original se nao for 8 digitos."""
    d = re.sub(r'[.\-\s]', '', str(v or ''))
    if len(d) == 8:
        return f"{d[:2]}.{d[2:5]}-{d[5:]}"
    return v or ''

# ── PIX ──────────────────────────────────────────────────────

PIX_CHAVE  = "danilopetitpao@gmail.com"
PIX_NOME   = "CONTALEV ENERGIA"
PIX_CIDADE = "GOIANIA"

def _is_cpf_valido(digits: str) -> bool:
    """Verifica se 11 digitos formam um CPF valido."""
    if len(digits) != 11 or not digits.isdigit():
        return False
    if len(set(digits)) == 1:  # 00000000000, 11111111111 etc.
        return False
    def _calc(nums, weights):
        total = sum(int(d) * w for d, w in zip(nums, weights))
        r = total % 11
        return 0 if r < 2 else 11 - r
    if int(digits[9])  != _calc(digits[:9],  range(10, 1, -1)):
        return False
    if int(digits[10]) != _calc(digits[:10], range(11, 1, -1)):
        return False
    return True


def _formatar_chave_pix_display(chave: str) -> str:
    """Formata a chave PIX para exibicao amigavel (CPF, CNPJ, telefone, etc).

    Usa _normalizar_chave_pix internamente para detectar o tipo.
    """
    if not chave:
        return ""
    norm = _normalizar_chave_pix(chave)
    if not norm:
        return ""
    # Telefone com prefixo +55
    if norm.startswith("+55") and len(norm) in (13, 14):
        ddi  = norm[:3]
        ddd  = norm[3:5]
        rest = norm[5:]
        if len(rest) == 9:  # celular com 9
            return f"{ddi} ({ddd}) {rest[:5]}-{rest[5:]}"
        else:  # fixo (8 digitos)
            return f"{ddi} ({ddd}) {rest[:4]}-{rest[4:]}"
    # Telefone +XX outros paises — devolve cru
    if norm.startswith("+"):
        return norm
    # Email
    if "@" in norm:
        return norm
    # CPF (11 digitos)
    if len(norm) == 11 and norm.isdigit():
        return f"{norm[:3]}.{norm[3:6]}.{norm[6:9]}-{norm[9:]}"
    # CNPJ (14 digitos)
    if len(norm) == 14 and norm.isdigit():
        return f"{norm[:2]}.{norm[2:5]}.{norm[5:8]}/{norm[8:12]}-{norm[12:]}"
    return norm


def _normalizar_chave_pix(chave: str) -> str:
    """Detecta o tipo da chave PIX e normaliza para o formato aceito pelo BR Code.

    Tipos suportados:
    - CPF: 11 digitos validos (mantem como esta)
    - CNPJ: 14 digitos (mantem)
    - Email: contem @ (lowercase)
    - Telefone: 10-11 digitos (prefixa +55) ou ja com +55
    - EVP (chave aleatoria UUID): 32-36 chars (mantem)
    """
    if not chave:
        return chave
    c = str(chave).strip()
    # Ja em formato internacional
    if c.startswith("+"):
        return c
    # Email
    if "@" in c:
        return c.lower()
    # Apenas digitos (extrai pra detectar tipo)
    digits = re.sub(r"\D", "", c)
    if digits and digits == c.replace(".", "").replace("-", "").replace("/", "").replace(" ", ""):
        if len(digits) == 11:
            # CPF se valido, senao trata como telefone (BR DDD + numero)
            return digits if _is_cpf_valido(digits) else f"+55{digits}"
        elif len(digits) == 14:
            return digits  # CNPJ
        elif len(digits) == 10:
            # Telefone sem o 9 inicial (formato antigo) — prefixa +55
            return f"+55{digits}"
    # Fallback: usa como esta (provavelmente EVP UUID)
    return c


def _build_pix_payload(valor, chave_pix=None, nome_pix=None, cidade_pix=None):
    """Monta o BR Code PIX (copia-e-cola) como string. Retorna '' se chave invalida."""
    chave  = _normalizar_chave_pix(chave_pix or PIX_CHAVE)
    nome   = (nome_pix   or PIX_NOME)[:25]
    cidade = (cidade_pix or PIX_CIDADE)[:15].upper()
    if not chave:
        return ""
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
    payload = _tlv(0, "01")
    payload += _tlv(26, _tlv(0, "br.gov.bcb.pix") + _tlv(1, chave[:77]))
    payload += _tlv(52, "0000") + _tlv(53, "986")
    payload += _tlv(54, f"{valor:.2f}") + _tlv(58, "BR")
    payload += _tlv(59, nome) + _tlv(60, cidade)
    payload += _tlv(62, _tlv(5, "***")) + "6304"
    payload += _crc16(payload)
    return payload

def gerar_qrcode_pix(valor, chave_pix=None, nome_pix=None, cidade_pix=None):
    """Gera QR Code PIX BRCode com valor dinamico. Retorna caminho do PNG ou None."""
    import tempfile
    payload = _build_pix_payload(valor, chave_pix, nome_pix, cidade_pix)
    if not payload:
        return None
    try:
        import qrcode
        qr_obj = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
        qr_obj.add_data(payload)
        qr_obj.make(fit=True)
        img = qr_obj.make_image(fill_color="black", back_color="white")
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix="pix_qr_")
        img.save(tmp.name)
        return tmp.name
    except Exception as e:
        print(f"[AVISO] Erro QR Code: {e}")
        return None

# ── Bandeira tarifária (FONTE ÚNICA) ─────────────────────────

def resolver_tarifa_bandeira(equatorial: dict, ba_stored: float = 0.0,
                             bv_stored: float = 0.0):
    """Fonte ÚNICA da tarifa de bandeira (R$/kWh) amarela e vermelha de uma fatura.

    TODOS os caminhos (extrair, gerar web, montar_dados, manual, scripts) devem
    usar esta função — assim a bandeira nunca diverge entre telas.

    Prioridade:
      1) tarifa REAL da fatura = adc_R$ / qtd_kWh da linha ADC BANDEIRA do PDF
      2) valor cadastrado em tb_tarifas (fallback p/ 100% compensado, sem linha
         de bandeira pra extrair)

    `equatorial` é o dict cru do extrair_equatorial (tem adc_bandeira_* e
    bandeira_* = qtd kWh). Retorna (ba, bv, info) onde info["ba_pdf"]/["bv_pdf"]
    é a tarifa derivada do PDF (ou None) — útil p/ auto-aprendizado do tb_tarifas.
    """
    def _pdf(adc_key, qtd_key):
        adc = float(equatorial.get(adc_key, 0) or 0)
        qtd = float(equatorial.get(qtd_key, 0) or 0)
        return (adc / qtd) if (adc > 0 and qtd > 0) else None

    ba_pdf = _pdf("adc_bandeira_amarela", "bandeira_amarela")
    bv_pdf = _pdf("adc_bandeira_vermelha", "bandeira_vermelha")
    ba = ba_pdf if ba_pdf is not None else float(ba_stored or 0)
    bv = bv_pdf if bv_pdf is not None else float(bv_stored or 0)
    return ba, bv, {"ba_pdf": ba_pdf, "bv_pdf": bv_pdf}

# ── Clientes ─────────────────────────────────────────────────

def _buscar_cliente_por_uc(uc, clientes):
    """Busca cliente por UC principal OU UC Antiga (formato legado).
    Retorna (chave_real, cliente) ou (None, None)."""
    if not uc:
        return None, None
    def _norm_uc(v):
        return re.sub(r'[.\-\s]', '', str(v)).lstrip("0")
    def _match(a, b):
        if a == b:
            return True
        if abs(len(a) - len(b)) == 2:
            shorter, longer = (a, b) if len(a) < len(b) else (b, a)
            if longer[:len(shorter)] == shorter:
                return True
        return False
    uc_norm = _norm_uc(uc)
    for key, cli in clientes.items():
        if _match(_norm_uc(key), uc_norm):
            return key, cli
        alt = cli.get("uc_alternativa", "") or ""
        if alt and _match(_norm_uc(alt), uc_norm):
            return key, cli
    return None, None

def _carregar_cliente_hibrido(uc: str) -> tuple:
    """Busca cliente por UC principal ou UC alternativa.
    Retorna (chave_real, cliente_dict) ou (None, None)."""
    clientes = carregar_clientes()
    chave_real, cli = _buscar_cliente_por_uc(uc, clientes)
    return chave_real, cli

# ── Tarifas ──────────────────────────────────────────────────

def obter_tarifa_mes(mes_ref):
    """Retorna tarifa e bandeiras para um mes de referencia, ou None.
    Aceita tanto '3/2026' quanto '03/2026'."""
    tarifas = carregar_tarifas()
    if mes_ref in tarifas:
        return tarifas[mes_ref]
    partes = mes_ref.split("/")
    if len(partes) == 2:
        alt = f"{int(partes[0])}/{partes[1]}"
        if alt in tarifas:
            return tarifas[alt]
        alt2 = f"{int(partes[0]):02d}/{partes[1]}"
        if alt2 in tarifas:
            return tarifas[alt2]
    return None

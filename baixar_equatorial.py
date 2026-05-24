"""
baixar_equatorial.py — SoLev
Baixa automaticamente as faturas do portal Equatorial GO via Playwright.

Uso:
  python baixar_equatorial.py --uc 3011234567
  python baixar_equatorial.py --todos
  python baixar_equatorial.py --uc 3011234567 --mes 04/2026
  python baixar_equatorial.py --todos --headless   (sem abrir janela)

Dependencias:
  pip install playwright
  playwright install chromium
"""

import argparse
import os
import re
import sys
import time
import shutil
from pathlib import Path
from datetime import datetime

# Windows: stdout/stderr default cp1252 quebra emojis quando redirecionado pra arquivo
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("❌ Playwright nao instalado.")
    print("   Execute: pip install playwright && playwright install chromium")
    sys.exit(1)


# ─── UTILITARIOS ──────────────────────────────────────────────────────────────
def _sanitizar_nome(nome: str) -> str:
    """Remove caracteres invalidos para nomes de arquivo/pasta no Windows."""
    return re.sub(r'[\\/:*?"<>|]', "", nome).strip()


def _primeiro_ultimo(nome: str) -> str:
    """Retorna so o primeiro e ultimo nome. Ex: 'KELLEN LETICIA CARDOSO DE SOUZA' → 'KELLEN SOUZA'"""
    partes = nome.strip().split()
    if len(partes) <= 2:
        return nome.strip()
    return f"{partes[0]} {partes[-1]}"


def _camel_case(nome: str) -> str:
    """CamelCase sem espacos. Ex: 'KELLEN SOUZA' → 'KellenSouza'"""
    return "".join(p.capitalize() for p in nome.strip().split())


def _mes_para_yyyymm(mes_ref: str) -> str:
    """
    Converte mes referencia para prefixo de arquivo no formato YYYYMM.
    Aceita qualquer variante:
      '4/2026'  → '202604'
      '04/2026' → '202604'
      '05/2026' → '202605'
    Fallback: retira barra (MMYYYY) — nao ideal, mas nunca quebra.
    """
    partes = (mes_ref or "").strip().split("/")
    if len(partes) == 2 and all(p.isdigit() for p in partes):
        mm, yyyy = partes[0].zfill(2), partes[1]
        return f"{yyyy}{mm}"
    return (mes_ref or "").replace("/", "")


def _formatar_uc_nova(uc_nova: str) -> str:
    """Formata 15 digitos como XXXX.XXX.XXX.XXX-XX.
    Ex: '000030328101201' → '0000.303.281.012-01'
    Se nao tiver 15 digitos, retorna como esta."""
    digits = "".join(filter(str.isdigit, uc_nova))
    if len(digits) == 15:
        return f"{digits[0:4]}.{digits[4:7]}.{digits[7:10]}.{digits[10:13]}-{digits[13:15]}"
    return uc_nova


# ─── CONFIGURACAO ─────────────────────────────────────────────────────────────
PASTA_FATURAS      = "faturas"           # legado / fallback
BASE_PASTA_USINAS  = r"C:\Users\danil\OneDrive\Desktop\Usinas"
PORTAL_URL         = "https://goias.equatorialenergia.com.br/LoginGO.aspx?envia-dados=Entrar"

# Tempo maximo de espera para elementos (ms)
TIMEOUT_PADRAO = 30_000
TIMEOUT_DOWNLOAD = 60_000

# Excecao especial: CPF rejeitado pelo portal (nao e timeout de rede)
class CredenciaisRejeitadas(Exception):
    pass


# Excecao especial: portal nao tem fatura disponivel para esta UC neste periodo
# (Equatorial ainda nao emitiu). Diferente de timeout — nao adianta re-tentar.
class SemFaturaDisponivel(Exception):
    pass


# ─── CARREGA CLIENTES ─────────────────────────────────────────────────────────
def carregar_clientes() -> dict:
    from db import carregar_clientes as _db_carregar
    return _db_carregar()


# ─── BUSCA CREDENCIAIS DA USINA VINCULADA AO CLIENTE ─────────────────────────
def buscar_credenciais_usina(uc: str) -> dict:
    """
    Retorna {'cpf': ..., 'data_nascimento': ...} do titular da usina
    vinculada ao cliente. Usa a cadeia:
      tb_clientes (por UC) → tb_cliente_usina (vinculo ativo) → tb_usinas
    """
    from db import (
        tb_get_cliente_por_uc,
        tb_get_vinculo_ativo_do_cliente,
        tb_get_usina,
        tb_get_titular,
    )

    cliente_tb = tb_get_cliente_por_uc(uc)
    if not cliente_tb:
        return {}

    id_cliente = cliente_tb.get("id_cliente")
    if not id_cliente:
        return {}

    vinculo = tb_get_vinculo_ativo_do_cliente(id_cliente)
    if not vinculo:
        return {}

    id_usina = vinculo.get("id_usina")
    if not id_usina:
        return {}

    usina = tb_get_usina(id_usina)
    if not usina:
        return {}

    # CPF/DN/nome do titular vivem em tb_titulares (referenciada por id_titular).
    # Os campos antigos desc_cpf_titular/dt_nascimento_titular/desc_titular_uc
    # na tb_usinas ficaram NULL apos a migracao — usar tb_titulares como fonte
    # primaria e cair nos campos antigos so como fallback.
    cpf  = (usina.get("desc_cpf_titular") or "").strip()
    dn   = (usina.get("dt_nascimento_titular") or "").strip()
    nome = (usina.get("desc_titular_uc") or "").strip()

    id_titular = usina.get("id_titular")
    if id_titular and (not cpf or not dn):
        titular = tb_get_titular(id_titular)
        if titular:
            if not cpf:
                cpf = (titular.get("desc_cpf_cnpj") or "").strip()
            if not dn:
                dn = (titular.get("dt_nascimento") or "").strip()
            if not nome:
                nome = (titular.get("desc_nome") or "").strip()

    return {
        "id_usina":        id_usina,
        "cpf":             cpf,
        "data_nascimento": dn,
        "nome_titular":    nome,
        "nome_usina":      usina.get("desc_nome", ""),
    }


# ─── FORMATA MES REFERENCIA ───────────────────────────────────────────────────
def mes_atual_formatado() -> str:
    """Retorna mes atual no formato MM/AAAA."""
    return datetime.now().strftime("%m/%Y")


# ─── NORMALIZA DATA DE NASCIMENTO ─────────────────────────────────────────────
def _normalizar_dn(data_nascimento: str) -> str:
    """Valida e converte data de nascimento para DD/MM/AAAA.
    Lança NotImplementedError se inválida."""
    dn = (data_nascimento or "").strip()
    if not dn or not any(c.isdigit() for c in dn):
        raise NotImplementedError(
            f"Data de nascimento invalida ou nao cadastrada para a usina: {repr(dn)}"
        )
    if len(dn) == 10 and dn[4] == "-":
        a, m, d = dn.split("-")
        dn = f"{d}/{m}/{a}"
    return dn


# ─── ETAPAS 1-3: LOGIN (UC + CPF + DATA NASC.) ────────────────────────────────
def _login_portal(page, uc_login: str, cpf: str, dn: str) -> None:
    """Realiza login completo no portal Equatorial GO.
    Assume que page já está na URL do portal.
    Lança CredenciaisRejeitadas se portal rejeitar silenciosamente.
    Lança PWTimeout em outras falhas.
    """
    cpf_limpo = "".join(filter(str.isdigit, cpf))
    print(f"  🔐 Login: UC {uc_login} | CPF {cpf_limpo[:3]}.***.***-{cpf_limpo[-2:]}...")

    # Campo UC: type() caractere a caractere para acionar eventos JS
    page.click("#WEBDOOR_headercorporativogo_txtUC")
    page.type("#WEBDOOR_headercorporativogo_txtUC", uc_login, delay=80)
    page.wait_for_timeout(300)

    # Campo CPF: digita APENAS digitos — a mascara JS do portal insere pontos e traco
    page.click("#WEBDOOR_headercorporativogo_txtDocumento")
    page.type("#WEBDOOR_headercorporativogo_txtDocumento", cpf_limpo, delay=80)
    page.wait_for_timeout(300)

    salvar_screenshot_erro(page, f"{uc_login}_1_preclick")

    # Clica ENTRAR — tenta multiplos seletores para robustez
    clicou_entrar = False
    for _sel in [
        "button.button:has-text('ENTRAR')",
        "button:has-text('ENTRAR')",
        "input[type='submit'][value*='ENTRAR']",
        "input[type='submit'][value*='Entrar']",
        "a:has-text('ENTRAR')",
        "#WEBDOOR_headercorporativogo_btnEntrar",
        "button[onclick*='ValidarCampos']",
    ]:
        try:
            el = page.locator(_sel).first
            el.wait_for(state="visible", timeout=3_000)
            el.click()
            clicou_entrar = True
            print(f"  ✔️  Botao ENTRAR clicado via: {_sel}")
            break
        except Exception:
            continue

    if not clicou_entrar:
        raise PWTimeout("Botao ENTRAR nao encontrado com nenhum seletor conhecido")

    page.wait_for_timeout(5000)  # aguarda postback ASP.NET
    salvar_screenshot_erro(page, f"{uc_login}_2_postclick")

    # ── Etapa 2: data de nascimento ───────────────────────────────────────────
    print(f"  📅 Validando data de nascimento: {dn}...")

    # Aguarda o campo de data aparecer (confirma que o login da 1ª etapa passou)
    try:
        campo_nasc = page.locator(
            "input[placeholder*='DD/MM'], input[placeholder*='dd/mm'], "
            "input[id*='nasc'], input[id*='Nasc'], input[name*='nasc'], "
            "input[id*='Data'], input[id*='data']"
        ).first
        campo_nasc.wait_for(state="visible", timeout=15_000)
    except PWTimeout:
        entrar_ainda_visivel = False
        try:
            entrar_ainda_visivel = page.locator("button:has-text('ENTRAR')").is_visible(timeout=2_000)
        except Exception:
            pass
        salvar_screenshot_erro(page, f"{uc_login}_2_postclick")
        if entrar_ainda_visivel:
            cpf_exib = cpf[:3] + ".***.***-" + cpf[-2:] if len(cpf) >= 5 else cpf
            print(f"  ❌ Portal rejeitou o CPF {cpf_exib} para a UC {uc_login}")
            raise CredenciaisRejeitadas(f"CPF rejeitado para UC {uc_login}")
        try:
            erros = page.locator(".error, .erro, .mensagem-erro, [id*='lblErro'], [id*='lblMensagem']")
            if erros.count() > 0:
                print(f"  ❌ Mensagem do portal: {erros.first.text_content()}")
        except Exception:
            pass
        raise PWTimeout("Campo de data de nascimento nao apareceu — login da 1ª etapa falhou")

    # Preenche a data — tenta fill(), depois type() com barras, depois JS direto
    campo_nasc.click()
    page.wait_for_timeout(300)
    preencheu_data = False

    try:
        campo_nasc.fill(dn)
        val = campo_nasc.input_value()
        if val and len("".join(filter(str.isdigit, val))) >= 8:
            preencheu_data = True
            print(f"  ✔️  Data via fill(): {val}")
    except Exception:
        pass

    if not preencheu_data:
        try:
            campo_nasc.triple_click()
            page.keyboard.press("Control+a")
            page.keyboard.press("Delete")
            page.wait_for_timeout(200)
            campo_nasc.type(dn, delay=120)
            val = campo_nasc.input_value()
            if val and len("".join(filter(str.isdigit, val))) >= 8:
                preencheu_data = True
                print(f"  ✔️  Data via type(): {val}")
        except Exception:
            pass

    if not preencheu_data:
        try:
            page.evaluate(
                """(val) => {
                    const inputs = document.querySelectorAll('input');
                    for (const el of inputs) {
                        const ph = (el.placeholder || '').toUpperCase();
                        if (ph.includes('DD') || ph.includes('NASC') || ph.includes('DATA')) {
                            el.value = val;
                            el.dispatchEvent(new Event('input',  { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            el.dispatchEvent(new Event('blur',   { bubbles: true }));
                            break;
                        }
                    }
                }""",
                dn,
            )
            preencheu_data = True
            print(f"  ✔️  Data via JavaScript: {dn}")
        except Exception as _e:
            print(f"  ⚠️  Falhou ao preencher data: {_e}")

    page.wait_for_timeout(500)
    salvar_screenshot_erro(page, f"{uc_login}_3_nasc")

    # Clica VALIDAR — tenta multiplos seletores
    clicou_validar = False
    for _sel in [
        "button:has-text('VALIDAR')",
        "button:has-text('Validar')",
        "input[value*='VALIDAR']",
        "input[value*='Validar']",
        "#WEBDOOR_headercorporativogo_btnValidar",
    ]:
        try:
            el = page.locator(_sel).first
            el.wait_for(state="visible", timeout=3_000)
            el.click()
            clicou_validar = True
            print(f"  ✔️  Botao VALIDAR clicado via: {_sel}")
            break
        except Exception:
            continue

    if not clicou_validar:
        page.get_by_text("VALIDAR").first.click()
    page.wait_for_load_state("networkidle", timeout=TIMEOUT_PADRAO)


# ─── ETAPA 4: FECHA POPUP DE PROPAGANDA ───────────────────────────────────────
def _fechar_popup_propaganda(page) -> None:
    """No-op se popup_promocao não aparecer."""
    try:
        popup = page.locator("#popup_promocao")
        if popup.is_visible(timeout=6_000):
            print(f"  🗙  Fechando popup de propaganda...")
            fechou = False
            for sel in [
                "#popup_promocao button.close",
                "#popup_promocao [data-dismiss='modal']",
                "#popup_promocao button:has-text('×')",
                "#popup_promocao button:has-text('Fechar')",
                "#popup_promocao button:has-text('OK')",
            ]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=1_000):
                        btn.click()
                        fechou = True
                        break
                except PWTimeout:
                    continue
            if not fechou:
                page.keyboard.press("Escape")
            page.wait_for_timeout(1_000)
    except PWTimeout:
        pass


# ─── DETECTA SE A SESSAO AINDA ESTA ATIVA ─────────────────────────────────────
def _sessao_ativa(page) -> bool:
    """Heurística: se o campo de login (#txtUC) está visível, perdeu sessão."""
    try:
        if page.locator("#WEBDOOR_headercorporativogo_txtUC").is_visible(timeout=1_500):
            return False
    except Exception:
        pass
    return True


# ─── ETAPAS 5-10: BAIXA UMA UC ASSUMINDO SESSAO ATIVA ────────────────────────
def _baixar_pela_sessao(
    page,
    uc: str,
    uc_dropdown: str,
    uc_nova_fmt: str | None,
    nome: str,
    mes_ref: str,
    pasta_saida: str,
) -> str | None:
    """Navega Contas → Segunda Via, troca dropdown, emite e baixa o PDF.
    Assume que o portal já está logado e na sessão do CPF titular.
    Retorna caminho do arquivo ou None.
    """
    # Navega Contas → Segunda Via de Fatura
    print(f"  📂 Navegando para Segunda Via de Fatura...")
    page.get_by_text("Contas").first.click()
    page.wait_for_timeout(800)
    page.get_by_text("Segunda Via de Fatura").first.click()
    page.wait_for_load_state("networkidle", timeout=TIMEOUT_PADRAO)

    # Preenche o formulario de emissao
    print(f"  🗓️  Selecionando UC {uc_dropdown}, tipo=completa, motivo=Outros...")
    page.select_option("#CONTENT_comboBoxUC", value=uc_dropdown)
    page.wait_for_timeout(300)
    page.select_option("#CONTENT_cbTipoEmissao", value="completa")
    page.wait_for_timeout(300)
    page.select_option("#CONTENT_cbMotivo", value="ESV05")
    page.wait_for_timeout(300)

    # Emite → navega para SegundaViaDownload.aspx
    print(f"  ⬇️  Emitindo fatura completa...")
    page.click("#CONTENT_btEnviar")
    page.wait_for_load_state("networkidle", timeout=TIMEOUT_PADRAO)
    page.wait_for_timeout(2000)

    # Detecta se o portal nao retornou nenhuma fatura (UC sem fatura emitida
    # ainda para o periodo solicitado). Espera curta (5s) em vez de timeout
    # padrao de 30s — se nao tem Download visivel, nao vai aparecer.
    try:
        page.locator("a:has-text('Download')").first.wait_for(state="visible", timeout=5_000)
    except PWTimeout:
        # Verifica se ha mensagem explicita de "sem fatura"
        msg = ""
        try:
            for sel in [".message", ".alert", "[id*='lblMensagem']", "[id*='lblErro']", "p.text-center"]:
                els = page.locator(sel)
                if els.count() > 0:
                    txt = (els.first.text_content() or "").strip()
                    if txt:
                        msg = txt[:120]
                        break
        except Exception:
            pass
        print(f"  📭 Portal sem fatura disponivel para UC {uc}" + (f" — {msg}" if msg else ""))
        salvar_screenshot_erro(page, f"{uc}_sem_fatura")
        raise SemFaturaDisponivel(f"UC {uc}: portal nao retornou fatura para {mes_ref}")

    # Clica Download → modal de confirmacao
    print(f"  📥 Clicando em Download na tabela...")

    nome_curto  = _primeiro_ultimo(nome)
    nome_camel  = _camel_case(nome_curto)
    uc_pasta    = uc_nova_fmt or uc
    nome_pasta  = _sanitizar_nome(f"{nome_camel}-{uc_pasta}")
    pasta_cliente = os.path.join(pasta_saida, nome_pasta)
    os.makedirs(pasta_cliente, exist_ok=True)

    ts = datetime.now().strftime("%H%M%S")
    caminho_temp = os.path.join(pasta_cliente, f"_temp_{ts}.pdf")

    page.locator("a:has-text('Download')").first.click()

    btn_ok = page.locator("#CONTENT_btnModal")
    btn_ok.wait_for(timeout=15_000)
    page.wait_for_timeout(500)

    print(f"  ✔️  Confirmando OK no modal...")
    with page.expect_download(timeout=TIMEOUT_DOWNLOAD) as download_info:
        btn_ok.click()

    download = download_info.value
    download.save_as(caminho_temp)

    # Renomeia com mes de referencia real do PDF
    mes_str_final = _mes_para_yyyymm(mes_ref)
    mes_ref_pdf_extraido = ""
    try:
        from extrair_equatorial import extrair_equatorial as _ext_eq
        _eq_data = _ext_eq(caminho_temp, verbose=False)
        mes_ref_pdf_extraido = _eq_data.get("mes_referencia", "").strip()
        if mes_ref_pdf_extraido:
            mes_str_final = _mes_para_yyyymm(mes_ref_pdf_extraido)
            print(f"  📅 Mes de referencia da fatura: {mes_ref_pdf_extraido} → prefixo {mes_str_final}")
    except Exception as _e:
        print(f"  ⚠️  Nao foi possivel extrair mes da fatura ({_e}); usando {mes_str_final}")

    _id_cli_eq = None
    try:
        from db import _resolver_id_cliente_por_uc
        _id_cli_eq = _resolver_id_cliente_por_uc(uc)
    except Exception as _e_eq_res:
        print(f"  ⚠️  Resolver id_cliente (Equatorial) falhou: {_e_eq_res}")

    if _id_cli_eq:
        nome_arquivo = f"{mes_str_final}_Equatorial_{nome_camel}_{_id_cli_eq}.pdf"
    else:
        nome_arquivo = f"{mes_str_final}-Equatorial{nome_camel}.pdf"
    caminho_destino = os.path.join(pasta_cliente, nome_arquivo)

    if os.path.exists(caminho_destino):
        os.remove(caminho_destino)
    shutil.move(caminho_temp, caminho_destino)

    print(f"  ✅ Fatura salva: {caminho_destino}")
    return caminho_destino


# ─── BAIXA FATURA DE UM CLIENTE ───────────────────────────────────────────────
def baixar_fatura(
    page,
    uc: str,
    cpf: str,
    data_nascimento: str,
    nome: str,
    mes_ref: str,
    pasta_saida: str,
    tentativa: int = 1,
    uc_arquivo: str | None = None,
    uc_dropdown: str | None = None,
    uc_nova_fmt: str | None = None,
) -> str | None:
    """
    Faz login no portal Equatorial com CPF + data de nascimento do titular
    da usina e baixa a fatura da UC do cliente.

    Mantida para compatibilidade. Internamente delega para
    _login_portal + _baixar_pela_sessao (cada chamada loga 1×).

    uc          = UC para login (sem zeros a esquerda, sem chars): '379437901261'
    uc_arquivo  = UC original do cliente (para fallback de nome de pasta)
    uc_dropdown = UC para o select da Segunda Via (15 digitos c/ zeros): '000379437901261'
    uc_nova_fmt = UC nova formatada para nome da pasta: '0000.303.281.012-01'
    pasta_saida = pasta da usina: C:\\...\\Usinas\\USGuylhehme
    Retorna o caminho do arquivo baixado ou None se falhar.
    """
    uc_arquivo  = uc_arquivo  or uc
    uc_dropdown = uc_dropdown or uc_arquivo

    print(f"  🌐 Acessando portal Equatorial GO...")
    dn = _normalizar_dn(data_nascimento)

    try:
        page.goto(PORTAL_URL, timeout=TIMEOUT_PADRAO)
        page.wait_for_load_state("networkidle", timeout=TIMEOUT_PADRAO)
        page.wait_for_timeout(2000)

        _login_portal(page, uc, cpf, dn)
        _fechar_popup_propaganda(page)

        return _baixar_pela_sessao(
            page, uc_arquivo, uc_dropdown, uc_nova_fmt,
            nome, mes_ref, pasta_saida,
        )

    except CredenciaisRejeitadas:
        raise
    except NotImplementedError as e:
        print(f"  ⚠️  {e}")
        return None
    except PWTimeout as e:
        print(f"  ❌ Timeout ao navegar no portal: {e}")
        salvar_screenshot_erro(page, uc)
        if tentativa < 3:
            espera = 10 * tentativa
            print(f"  🔄 Tentando novamente ({tentativa + 1}/3) em {espera}s...")
            time.sleep(espera)
            return baixar_fatura(page, uc, cpf, data_nascimento, nome, mes_ref, pasta_saida, tentativa + 1, uc_arquivo, uc_dropdown, uc_nova_fmt)
        return None
    except Exception as e:
        print(f"  ❌ Erro inesperado: {type(e).__name__}: {e}")
        salvar_screenshot_erro(page, uc)
        return None


# ─── SALVA SCREENSHOT EM CASO DE ERRO ────────────────────────────────────────
def salvar_screenshot_erro(page, uc: str):
    try:
        os.makedirs("logs_screenshots", exist_ok=True)
        path = f"logs_screenshots/erro_{uc}_{datetime.now().strftime('%H%M%S')}.png"
        page.screenshot(path=path)
        print(f"  📸 Screenshot salvo: {path}")
    except Exception:
        pass


# ─── BUSCA UC NOVA DO CLIENTE (cod_uc) ───────────────────────────
def buscar_uc_nova(uc: str) -> dict:
    """
    Retorna dict com as versoes da UC nova para uso no portal Equatorial:
      'login'    : so digitos sem zeros a esquerda → campo UC da tela de login
                   Ex: '0003.794.379.012-61' → '379437901261'
      'dropdown' : so digitos COM zeros a esquerda → select na pagina Segunda Via
                   Ex: '0003.794.379.012-61' → '000379437901261'
    Se nao existe UC nova, ambos retornam a UC original.
    """
    from db import tb_get_cliente_por_uc
    cliente_tb = tb_get_cliente_por_uc(uc)
    if not cliente_tb:
        return {"login": uc, "dropdown": uc}
    uc_nova = (cliente_tb.get("cod_uc") or "").strip()
    if uc_nova:
        digits = "".join(filter(str.isdigit, uc_nova))
        return {
            "login":     str(int(digits)) if digits else uc,   # sem zeros a esquerda
            "dropdown":  digits if digits else uc,              # com zeros a esquerda
            "formatada": _formatar_uc_nova(digits) if digits else uc,  # XXXX.XXX.XXX.XXX-XX
        }
    return {"login": uc, "dropdown": uc, "formatada": uc}


# ─── PROCESSA UM CLIENTE ──────────────────────────────────────────────────────
def processar_uc(playwright, uc: str, cliente: dict, mes_ref: str, headless: bool) -> str | None:
    """Abre browser, busca credenciais da usina vinculada, faz login e baixa a fatura."""
    nome = cliente.get("nome", "Cliente")

    # Busca versoes da UC nova para cada uso no portal
    ucs = buscar_uc_nova(uc)
    uc_login    = ucs["login"]      # sem zeros a esquerda → campo login
    uc_dropdown = ucs["dropdown"]   # com zeros a esquerda → select Segunda Via
    uc_nova_fmt = ucs["formatada"]  # XXXX.XXX.XXX.XXX-XX → nome da pasta do cliente

    if uc_login != uc:
        print(f"\n{'─'*55}")
        print(f"  Cliente: {nome} | UC antiga: {uc}")
        print(f"  {'':5}UC nova (login): {uc_login}")
        print(f"{'─'*55}")
    else:
        print(f"\n{'─'*55}")
        print(f"  Cliente: {nome} | UC: {uc}")
        print(f"{'─'*55}")

    # Busca CPF e data de nascimento do titular da usina vinculada
    creds = buscar_credenciais_usina(uc)
    cpf_usina       = creds.get("cpf", "")
    data_nascimento = creds.get("data_nascimento", "")
    nome_usina      = creds.get("nome_usina", "")

    if not cpf_usina:
        print(f"  ⚠️  Usina vinculada sem CPF do titular cadastrado (UC {uc})")
        if nome_usina:
            print(f"     Usina: {nome_usina} — complete o cadastro da usina")
        return None

    # Valida data de nascimento — rejeita vazio, "?", texto sem digitos
    dn_raw = (data_nascimento or "").strip()
    if not dn_raw or not any(c.isdigit() for c in dn_raw):
        print(f"  ⚠️  Usina '{nome_usina}' sem data de nascimento valida cadastrada (valor: {repr(dn_raw)})")
        print(f"     → Cadastre a data de nascimento do titular no cadastro da usina")
        return None

    if nome_usina:
        print(f"  🏭 Usando credenciais da usina: {nome_usina}")

    # Credenciais fixas: sempre usa o titular da usina
    credenciais = [{"cpf": cpf_usina, "fonte": f"usina {nome_usina or ''}"}]

    browser = playwright.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-infobars",
            "--window-size=1280,900",
        ],
    )
    context = browser.new_context(
        accept_downloads=True,
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        extra_http_headers={
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    # Oculta flags de automacao que o Imperva/Cloudflare detecta
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US'] });
        window.chrome = { runtime: {} };
    """)
    page = context.new_page()

    # Pasta de destino: BASE_PASTA_USINAS\{nome_usina} (ex: ...Usinas\USGuylhehme)
    if nome_usina:
        pasta_saida = os.path.join(BASE_PASTA_USINAS, nome_usina)
    else:
        pasta_saida = PASTA_FATURAS  # fallback legado

    try:
        resultado = None
        # Portal Equatorial rejeita silenciosamente em ~50% das tentativas
        # mesmo no login manual. Solucao: insistir ate MAX_TENTATIVAS_LOGIN.
        MAX_TENTATIVAS_LOGIN = 4
        for cred in credenciais:
            cpf_tentativa = cred["cpf"]
            fonte         = cred["fonte"]
            print(f"  🔑 Tentando login com {fonte}...")

            for tentativa_login in range(1, MAX_TENTATIVAS_LOGIN + 1):
                try:
                    resultado = baixar_fatura(
                        page, uc_login, cpf_tentativa, data_nascimento, nome, mes_ref, pasta_saida,
                        uc_arquivo=uc, uc_dropdown=uc_dropdown, uc_nova_fmt=uc_nova_fmt,
                    )
                    if resultado:
                        print(f"  ✅ Login bem-sucedido com {fonte} (tentativa {tentativa_login})")
                        break
                    # resultado None sem excecao: provavelmente NotImplementedError tratado
                    break
                except CredenciaisRejeitadas:
                    if tentativa_login < MAX_TENTATIVAS_LOGIN:
                        espera = 5 + tentativa_login * 2  # 7s, 9s, 11s, ...
                        print(f"  🔁 Rejeicao silenciosa do portal — tentativa {tentativa_login}/{MAX_TENTATIVAS_LOGIN}. "
                              f"Aguardando {espera}s e insistindo...")
                        time.sleep(espera)
                        continue
                    else:
                        print(f"  ❌ Portal rejeitou {MAX_TENTATIVAS_LOGIN} vezes seguidas o CPF da {fonte} para UC {uc}")
                        print(f"     → Verifique manualmente se UC + CPF + data ainda estao corretos no portal")
                        break
                except Exception as _e:
                    print(f"  ❌ Erro com {fonte}: {_e}")
                    break

            if resultado:
                break

        if resultado is None:
            return None

        # Gera cobranca CONTALEV na mesma pasta do PDF Equatorial
        pasta_cli  = os.path.dirname(resultado)
        mes_str    = mes_ref.replace("/", "")
        nome_camel = _camel_case(_primeiro_ultimo(nome))
        gerar_cobranca_cliente(resultado, pasta_cli, mes_str, nome_camel, uc)

        return resultado
    except Exception as e:
        print(f"  ❌ Falha geral: {e}")
        salvar_screenshot_erro(page, uc)
        return None
    finally:
        context.close()
        browser.close()


# ─── PROCESSA TODAS AS UCs DE UMA USINA COM UM UNICO LOGIN ────────────────────
def processar_usina(
    playwright,
    clientes_da_usina: list,
    creds_usina: dict,
    mes_ref: str,
    headless: bool,
    forcar: bool = False,
) -> dict:
    """
    Abre 1 browser/contexto e faz 1 login no portal. Reaproveita a sessao
    para baixar varias UCs da mesma usina (mesmo CPF titular) via troca
    do dropdown #CONTENT_comboBoxUC na pagina Segunda Via.

    clientes_da_usina: lista de tuplas (uc, cliente_dict).
    creds_usina:       dict com 'cpf', 'data_nascimento', 'nome_usina'.

    Retorna: {'sucesso': [ucs], 'falha': [ucs], 'ignorado': [ucs]}.
    """
    resumo = {"sucesso": [], "falha": [], "ignorado": [], "sem_fatura": []}
    if not clientes_da_usina:
        return resumo

    cpf_usina  = creds_usina.get("cpf", "")
    dn_raw     = creds_usina.get("data_nascimento", "")
    nome_usina = creds_usina.get("nome_usina", "")

    if not cpf_usina or not dn_raw or not any(c.isdigit() for c in str(dn_raw)):
        print(f"  ⚠️  Usina '{nome_usina}' sem CPF/data de nascimento — pulando {len(clientes_da_usina)} UCs")
        resumo["falha"].extend([uc for uc, _ in clientes_da_usina])
        return resumo

    try:
        dn = _normalizar_dn(dn_raw)
    except NotImplementedError as e:
        print(f"  ⚠️  {e}")
        resumo["falha"].extend([uc for uc, _ in clientes_da_usina])
        return resumo

    # Pasta de destino da usina
    pasta_saida = os.path.join(BASE_PASTA_USINAS, nome_usina) if nome_usina else PASTA_FATURAS

    # Resolve UCs (login/dropdown/formatada) para todos os clientes da usina
    enriquecidos = []
    for uc, cliente in clientes_da_usina:
        ucs_info = buscar_uc_nova(uc)
        enriquecidos.append({
            "uc":         uc,
            "cliente":    cliente,
            "uc_login":   ucs_info.get("login", uc),
            "uc_dropdown": ucs_info.get("dropdown", uc),
            "uc_nova_fmt": ucs_info.get("formatada", uc),
        })

    # Filtra os ja baixados antes de abrir browser
    pendentes = []
    for r in enriquecidos:
        if not forcar:
            existente = ja_baixado(
                r["uc"], mes_ref,
                nome=r["cliente"].get("nome", ""),
                nome_usina=nome_usina,
                uc_nova_fmt=r["uc_nova_fmt"],
            )
            if existente:
                print(f"  ⏭️  {r['cliente'].get('nome', r['uc'])} — ja baixado: {existente}")
                resumo["ignorado"].append(r["uc"])
                continue
        pendentes.append(r)

    if not pendentes:
        print(f"  ✅ Usina '{nome_usina}' — todos os {len(enriquecidos)} clientes ja baixados.")
        return resumo

    print(f"\n🏭 Usina: {nome_usina} | {len(pendentes)} UC(s) pendente(s) | 1 login compartilhado")

    browser = playwright.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-infobars",
            "--window-size=1280,900",
        ],
    )
    context = browser.new_context(
        accept_downloads=True,
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"},
    )
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US'] });
        window.chrome = { runtime: {} };
    """)
    page = context.new_page()

    MAX_TENTATIVAS_LOGIN = 4
    logado = False

    def _fazer_login(uc_para_login: str) -> bool:
        """Tenta fazer login. Retorna True se sucesso."""
        for tentativa in range(1, MAX_TENTATIVAS_LOGIN + 1):
            try:
                page.goto(PORTAL_URL, timeout=TIMEOUT_PADRAO)
                page.wait_for_load_state("networkidle", timeout=TIMEOUT_PADRAO)
                page.wait_for_timeout(2000)
                _login_portal(page, uc_para_login, cpf_usina, dn)
                _fechar_popup_propaganda(page)
                print(f"  ✅ Login da usina '{nome_usina}' OK (tentativa {tentativa})")
                return True
            except CredenciaisRejeitadas:
                if tentativa < MAX_TENTATIVAS_LOGIN:
                    espera = 5 + tentativa * 2
                    print(f"  🔁 Rejeicao silenciosa — tentativa {tentativa}/{MAX_TENTATIVAS_LOGIN}, aguardando {espera}s")
                    time.sleep(espera)
                else:
                    print(f"  ❌ Portal rejeitou {MAX_TENTATIVAS_LOGIN}× o CPF do titular ({nome_usina})")
            except Exception as e:
                print(f"  ❌ Erro no login da usina '{nome_usina}': {type(e).__name__}: {e}")
                return False
        return False

    # Acumula PDFs baixados para gerar cobrancas DEPOIS de fechar o browser.
    # Motivo: gerar_cobranca renderiza HTML via Playwright async, que conflita
    # com a sessao Playwright sync ainda aberta (loop asyncio).
    baixados_para_cobranca = []  # lista de (pdf_path, nome, uc)

    try:
        # Login inicial usando a UC do primeiro cliente do grupo
        logado = _fazer_login(pendentes[0]["uc_login"])
        if not logado:
            resumo["falha"].extend([r["uc"] for r in pendentes])
            return resumo

        for r in pendentes:
            uc = r["uc"]
            cliente = r["cliente"]
            nome = cliente.get("nome", uc)

            print(f"\n  --- Cliente: {nome} | UC: {uc} ---")

            # Se sessao caiu (timeout do portal entre downloads), reloga
            if not _sessao_ativa(page):
                print(f"  ⚠️  Sessao expirou — re-logando...")
                logado = _fazer_login(r["uc_login"])
                if not logado:
                    print(f"  ❌ Re-login falhou — abortando UCs restantes da usina")
                    restantes = [x["uc"] for x in pendentes[pendentes.index(r):]]
                    resumo["falha"].extend(restantes)
                    return resumo

            # Tenta baixar; se der PWTimeout (botao Download nao apareceu,
            # sessao expirou, etc.), reloga e tenta de novo (max 1 retry).
            # SemFaturaDisponivel = portal nao tem fatura — nao adianta retentar.
            resultado = None
            sem_fatura = False
            MAX_RETRY_DOWNLOAD = 1  # tentativas extras alem da primeira
            for tentativa_download in range(MAX_RETRY_DOWNLOAD + 1):
                try:
                    resultado = _baixar_pela_sessao(
                        page, uc, r["uc_dropdown"], r["uc_nova_fmt"],
                        nome, mes_ref, pasta_saida,
                    )
                    break  # sucesso
                except SemFaturaDisponivel:
                    sem_fatura = True
                    resultado = None
                    break  # nao retenta
                except PWTimeout as e:
                    print(f"  ❌ Timeout na UC {uc} (tentativa {tentativa_download+1}/{MAX_RETRY_DOWNLOAD+1}): {e}")
                    salvar_screenshot_erro(page, uc)
                    if tentativa_download >= MAX_RETRY_DOWNLOAD:
                        resultado = None
                        break
                    print(f"  🔁 Re-logando e tentando novamente a UC {uc}...")
                    if not _fazer_login(r["uc_login"]):
                        print(f"  ❌ Re-login durante retry falhou — desistindo da UC {uc}")
                        resultado = None
                        break
                except Exception as e:
                    print(f"  ❌ Erro inesperado UC {uc}: {type(e).__name__}: {e}")
                    salvar_screenshot_erro(page, uc)
                    resultado = None
                    break

            if resultado:
                resumo["sucesso"].append(uc)
                baixados_para_cobranca.append((resultado, nome, uc))
            elif sem_fatura:
                resumo["sem_fatura"].append(uc)
            else:
                resumo["falha"].append(uc)

            # Pausa curta entre downloads na mesma sessao
            time.sleep(2)
    finally:
        try:
            context.close()
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass

    # Browser FECHADO — agora gera cobrancas CONTALEV (Playwright async pode rodar)
    if baixados_para_cobranca:
        print(f"\n📊 Gerando {len(baixados_para_cobranca)} cobranca(s) CONTALEV...")
        for pdf_path, nome, uc in baixados_para_cobranca:
            try:
                pasta_cli  = os.path.dirname(pdf_path)
                mes_str    = mes_ref.replace("/", "")
                nome_camel = _camel_case(_primeiro_ultimo(nome))
                gerar_cobranca_cliente(pdf_path, pasta_cli, mes_str, nome_camel, uc)
            except Exception as e:
                print(f"  ⚠️  Cobranca CONTALEV falhou para UC {uc} (PDF Equatorial OK): {e}")

    return resumo


# ─── GERA COBRANCA CONTALEV APOS DOWNLOAD ─────────────────────────────────────
def gerar_cobranca_cliente(
    pdf_equatorial: str,
    pasta_cliente: str,
    mes_str: str,
    nome_camel: str,
    uc_original: str,
) -> str | None:
    """
    Extrai dados do PDF Equatorial, busca o cliente no Supabase e gera
    o PDF de cobranca SoLev na mesma pasta do cliente.

    Nome do arquivo: {mes_str}-SoLev{nome_camel}.pdf
    Ex: 042026-SoLevKellenSouza.pdf
    """
    print(f"  📊 Gerando cobranca SoLev...")
    try:
        from extrair_equatorial import extrair_equatorial
        from contalev_cobranca_v2_padrao import gerar_cobranca, calcular
        from gerar_cobranca_auto import montar_dados, gerar_qrcode_pix
    except ImportError as e:
        print(f"  ⚠️  Modulo nao disponivel para gerar cobranca: {e}")
        return None

    # 1. Extrai dados da fatura Equatorial
    try:
        equatorial = extrair_equatorial(pdf_equatorial, verbose=False)
    except Exception as e:
        print(f"  ⚠️  Erro ao extrair dados da fatura: {e}")
        return None

    # 2. Busca cliente no Supabase (via carregar_clientes para compatibilidade de campos)
    from db import carregar_clientes as _db_clientes
    clientes = _db_clientes()
    cliente = clientes.get(uc_original)
    if not cliente:
        uc_limpo = str(uc_original).lstrip("0")
        for k, v in clientes.items():
            if k.lstrip("0") == uc_limpo:
                cliente = v
                uc_original = k
                break
    if not cliente:
        print(f"  ⚠️  Cliente UC {uc_original} nao encontrado para gerar cobranca")
        return None

    # 3. Monta dados e gera cobranca
    try:
        dados = montar_dados(equatorial, cliente, uc_original, pdf_equatorial)

        # Garante campos de cobranca com defaults (podem nao vir do Supabase)
        dados.setdefault("codigo_barras",   cliente.get("codigo_barras",  ""))
        dados.setdefault("linha_digitavel", cliente.get("linha_digitavel",""))
        dados.setdefault("pix_payload",     cliente.get("pix_payload",    ""))
        dados.setdefault("multa",  0.0)
        dados.setdefault("juros",  0.0)

        # Sanitiza datas extraidas do PDF (OCR pode retornar valores invalidos)
        _re_data = re.compile(r'^\d{2}/\d{2}/\d{4}$')
        for _campo in ("anterior_leitura", "data_leitura", "proxima_leitura", "venc_equatorial"):
            val = dados.get(_campo, "")
            if not isinstance(val, str) or not _re_data.match(val.strip()):
                if val:
                    print(f"  ⚠️  Data invalida ignorada — {_campo}: {repr(val)}")
                dados[_campo] = ""

        dados_calc = calcular(dados)
        total_com = dados_calc.get("_total_com", 0)

        # QR Code PIX dinamico — busca dados do recebedor da usina vinculada ao cliente
        try:
            from db import (
                tb_get_cliente_por_uc as _tb_cli,
                tb_get_usinas_do_cliente as _tb_us_cli,
                tb_get_pix_da_usina as _tb_pix,
            )
            qr_path = None
            _cli_tb = _tb_cli(uc_original)
            _id_cli = _cli_tb.get("id_cliente") if _cli_tb else None
            if _id_cli:
                _vinc = _tb_us_cli(_id_cli)
                if _vinc:
                    _rec = _tb_pix(_vinc[0]["id_usina"])
                    if _rec:
                        qr_path = gerar_qrcode_pix(
                            total_com,
                            chave_pix=_rec.get("desc_pix"),
                            nome_recebedor=_rec.get("desc_nome_pix") or _rec.get("desc_nome"),
                            cidade=_rec.get("desc_cidade_pix"),
                        )
                        if qr_path:
                            print(f"  💠 QR PIX gerado para recebedor: {_rec.get('desc_nome_pix') or _rec.get('desc_nome')}")
                        else:
                            print(f"  ⚠️  QR PIX nao gerado — recebedor sem chave PIX cadastrada")
                    else:
                        print(f"  ⚠️  Usina sem recebedor PIX vinculado — QR PIX omitido da cobranca")
            if qr_path:
                dados["pix_qr_path"] = qr_path
                # Chave formatada para mostrar abaixo do QR
                try:
                    from utils import _formatar_chave_pix_display
                    dados["pix_chave_display"] = _formatar_chave_pix_display(
                        _rec.get("desc_pix"))
                except Exception:
                    pass
        except Exception as _e:
            print(f"  ⚠️  Falha ao gerar QR PIX: {_e}")

        # Resolve id_cliente (nome do arquivo) e id_fatura (texto no PDF)
        try:
            from db import _resolver_id_cliente_por_uc, tb_reservar_id_fatura
            import re as _re_mr_b
            _id_cli_b = _resolver_id_cliente_por_uc(uc_original)
            if _id_cli_b:
                dados["id_cliente"] = _id_cli_b
                _mm_b = _re_mr_b.match(r"^(\d{1,2})/(\d{4})$",
                                       str(equatorial.get("mes_referencia") or "").strip())
                if _mm_b:
                    dados["id_fatura"] = tb_reservar_id_fatura(
                        _id_cli_b, int(_mm_b.group(2)), int(_mm_b.group(1)))
        except Exception as _e_res_b:
            print(f"  ⚠️  Resolver id_cliente/id_fatura falhou: {_e_res_b}")

        # Gera PDF
        gerar_cobranca(dados)

        arquivo_gerado = dados.get("output_path", "")
        if not arquivo_gerado or not os.path.exists(arquivo_gerado):
            print(f"  ⚠️  Arquivo de cobranca nao encontrado apos geracao: {arquivo_gerado}")
            return None

        # Nome do arquivo SoLev: YYYYMM-SoLevPrimeiroUltimo.pdf
        # Usa mes_referencia ja extraido do PDF Equatorial (equatorial dict)
        _mes_ref_extr = (equatorial.get("mes_referencia") or "").strip()
        mes_str_cob   = _mes_para_yyyymm(_mes_ref_extr) if _mes_ref_extr else mes_str
        nome_arquivo = f"{mes_str_cob}-SoLev{nome_camel}.pdf"
        destino = os.path.join(pasta_cliente, nome_arquivo)
        shutil.move(arquivo_gerado, destino)
        print(f"  ✅ Cobranca salva: {destino}")

        # Upload para Supabase Storage (desacopla PDFs da estrutura de pastas)
        _pdf_url = ""
        _pdf_eq_url = ""
        try:
            from db import storage_ensure_bucket, storage_upload_pdf
            storage_ensure_bucket("faturas")
            # Cobranca CONTALEV
            _pdf_url = storage_upload_pdf(destino, nome_arquivo, "faturas")
            print(f"  Cobranca enviada ao Storage: {nome_arquivo}")
            # Fatura Equatorial (fonte)
            _eq_basename = os.path.basename(pdf_equatorial)
            _pdf_eq_url = storage_upload_pdf(pdf_equatorial, _eq_basename, "faturas")
            print(f"  Fatura Equatorial enviada ao Storage: {_eq_basename}")
        except Exception as _e:
            print(f"  Upload Storage falhou (PDFs salvos localmente): {_e}")

        # Writeback ao Supabase
        try:
            from db import tb_get_cliente_por_uc, tb_writeback_pos_cobranca
            cliente_tb = tb_get_cliente_por_uc(uc_original)
            if cliente_tb:
                tb_writeback_pos_cobranca(
                    cliente_tb["id_cliente"],
                    round(dados_calc.get("_total_com", 0), 2),
                    dados_calc.get("venc_solev", ""),
                    round(dados_calc.get("_economia_acum", 0), 2),
                )
                print(f"  💾 Supabase atualizado (economia acumulada, vencimento)")
        except Exception as e:
            print(f"  ⚠️  Writeback ao Supabase falhou: {e}")

        # Registra no historico de cobrancas (aparece em /historico)
        try:
            from db import inserir_fatura as _inserir_hist
            _inserir_hist(
                uc=uc_original,
                nome=cliente["nome"],
                mes_ref=equatorial.get("mes_referencia", ""),
                total_sem=dados_calc.get("_total_sem", 0),
                total_com=dados_calc.get("_total_com", 0),
                economia_mes=dados_calc.get("_economia_mes", 0),
                economia_acum=dados_calc.get("_economia_acum", 0),
                venc=dados_calc.get("venc_solev", ""),
                pdf_path=destino,
                consumo_kwh=equatorial.get("consumo_kwh", 0),
                compensado_kwh=equatorial.get("valor_parc_injet", 0),
                data_leitura_atual=equatorial.get("data_leitura", ""),
                compensacao_dic=equatorial.get("compensacao_dic", 0),
                pdf_url=_pdf_url,
                pdf_equatorial=pdf_equatorial,
                pdf_equatorial_url=_pdf_eq_url,
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
                ajuste_valor=dados_calc.get("ajuste_valor", 0),
                difci=dados_calc.get("difci", 0),
                ecnisenta=dados_calc.get("ecnisenta", 0),
                anterior_leitura=equatorial.get("data_leitura_anterior", ""),
                proxima_leitura=equatorial.get("proxima_leitura", ""),
                n_dias=int(equatorial.get("n_dias", 0) or 0),
                # SCEE — dados da geração solar extraídos do PDF Equatorial
                scee_ciclo_mes=equatorial.get("scee_ciclo_mes", "") or equatorial.get("ciclo_geracao_mes", ""),
                scee_uc_geradora=equatorial.get("scee_uc_geradora", ""),
                scee_pct_rateio=equatorial.get("scee_pct_rateio", 0) or 0,
                scee_geracao_usina_kwh=equatorial.get("geracao_ciclo_kwh", 0) or 0,
                scee_excedente_kwh=equatorial.get("excedente_recebido_kwh", 0) or 0,
                scee_credito_kwh=equatorial.get("credito_recebido_kwh", 0) or 0,
                scee_saldo_exp_30d_kwh=equatorial.get("saldo_expirar_30d_kwh", 0) or 0,
                scee_saldo_exp_60d_kwh=equatorial.get("saldo_expirar_60d_kwh", 0) or 0,
            )
            print(f"  📋 Historico registrado: {cliente['nome']} — {equatorial.get('mes_referencia', '')}")
        except Exception as e:
            print(f"  ⚠️  Falha ao registrar historico: {e}")

        return destino

    except Exception as e:
        print(f"  ⚠️  Erro ao gerar cobranca: {type(e).__name__}: {e}")
        return None


# ─── VERIFICA SE JA FOI BAIXADO ───────────────────────────────────────────────
def ja_baixado(
    uc: str,
    mes_ref: str,
    nome: str = "",
    nome_usina: str = "",
    uc_nova_fmt: str = "",
) -> str | None:
    """Retorna caminho se fatura ja existir localmente."""
    import glob as _glob
    # Formato novo: YYYYMM-EquatorialPrimeiroUltimo.pdf
    yyyymm  = _mes_para_yyyymm(mes_ref)   # ex: '202604'
    mes_str = mes_ref.replace("/", "")     # ex: '042026' (legado)

    if nome and nome_usina:
        nome_curto  = _primeiro_ultimo(nome)
        nome_camel  = _camel_case(nome_curto)
        uc_pasta    = uc_nova_fmt or uc
        nome_pasta  = _sanitizar_nome(f"{nome_camel}-{uc_pasta}")
        pasta_cli   = os.path.join(BASE_PASTA_USINAS, nome_usina, nome_pasta)

        # Tenta formato atual YYYYMM primeiro
        novo = os.path.join(pasta_cli, f"{yyyymm}-Equatorial{nome_camel}.pdf")
        if os.path.exists(novo):
            return novo

        # Compatibilidade retroativa: formato antigo MMYYYY
        legado = os.path.join(pasta_cli, f"{mes_str}-Equatorial{nome_camel}.pdf")
        if os.path.exists(legado):
            return legado

        # Glob: qualquer arquivo *-EquatorialNome.pdf na pasta (safeguard)
        matches = _glob.glob(os.path.join(pasta_cli, f"*-Equatorial{nome_camel}.pdf"))
        for m in matches:
            # Verifica se e do mes correto pelo prefixo (YYYYMM ou MMYYYY)
            base = os.path.basename(m)
            if base.startswith(yyyymm) or base.startswith(mes_str):
                return m

    # Fallback legado: faturas/uc_mesano.pdf
    antigo = os.path.join(PASTA_FATURAS, f"{uc}_{mes_str}.pdf")
    return antigo if os.path.exists(antigo) else None


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="CONTALEV — Download automatico de faturas Equatorial GO",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python baixar_equatorial.py --uc 3011234567
  python baixar_equatorial.py --todos
  python baixar_equatorial.py --todos --mes 03/2026
  python baixar_equatorial.py --todos --headless
        """
    )
    parser.add_argument("--uc",       type=str,              help="UC especifica")
    parser.add_argument("--ucs",      type=str, default=None,help="Lista de UCs separadas por virgula (ex: 000123,000456)")
    parser.add_argument("--todos",    action="store_true",   help="Baixa de todos os clientes")
    parser.add_argument("--usina",    type=int, default=None,help="Baixa so as UCs de uma usina especifica (id_usina)")
    parser.add_argument("--mes",      type=str, default=None,help="Mes referencia MM/AAAA (padrao: mes atual)")
    parser.add_argument("--headless", action="store_true",   help="Executa sem abrir janela do browser")
    parser.add_argument("--forcar",   action="store_true",   help="Re-baixa mesmo se ja existir")

    args = parser.parse_args()
    mes_ref = args.mes or mes_atual_formatado()

    clientes = carregar_clientes()

    if not args.uc and not args.ucs and not args.todos and not args.usina:
        parser.print_help()
        sys.exit(0)

    # Define lista de UCs a processar
    if args.uc:
        if args.uc not in clientes:
            print(f"❌ UC {args.uc} nao encontrada no Supabase")
            sys.exit(1)
        ucs = [args.uc]
    elif args.ucs:
        # Aceita formatos: '000123,000456' ou '0003.951.199.012-66,0000.302.762.01227'
        ucs_pedidas = [u.strip() for u in args.ucs.split(",") if u.strip()]
        # Indexa clientes por digitos para resolver formatos com pontos/hifens
        por_digitos = {"".join(c for c in k if c.isdigit()).zfill(15): k for k in clientes}
        ucs = []
        nao_achadas = []
        for u in ucs_pedidas:
            digits = "".join(c for c in u if c.isdigit()).zfill(15)
            chave = por_digitos.get(digits)
            if chave:
                ucs.append(chave)
            else:
                nao_achadas.append(u)
        if nao_achadas:
            print(f"⚠️  UCs nao encontradas no Supabase (serao ignoradas): {nao_achadas}")
        if not ucs:
            print(f"❌ Nenhuma UC encontrada na lista informada")
            sys.exit(1)
        print(f"📍 Filtro: --ucs → {len(ucs)} UC(s) encontrada(s)")
    elif args.usina:
        ucs = [uc for uc in clientes if buscar_credenciais_usina(uc).get("id_usina") == args.usina]
        if not ucs:
            print(f"❌ Nenhum cliente vinculado a usina id={args.usina}")
            sys.exit(1)
        print(f"📍 Filtro: usina id={args.usina} → {len(ucs)} UC(s)")
    else:
        ucs = list(clientes.keys())

    print(f"\n🚀 CONTALEV — Download Faturas Equatorial GO")
    print(f"   Mes: {mes_ref} | Clientes: {len(ucs)} | Headless: {args.headless}")
    print()

    resultados = {"sucesso": [], "falha": [], "ignorado": [], "sem_fatura": []}

    # ── Agrupa UCs por usina (mesmo CPF do titular = 1 login compartilhado) ──
    grupos_usina = {}   # id_usina -> {"creds": dict, "clientes": [(uc, cliente), ...]}
    sem_usina    = []   # [(uc, cliente), ...] — caem no fluxo legado (1 browser/UC)

    for uc in ucs:
        cliente = clientes[uc]
        creds = buscar_credenciais_usina(uc)
        id_usina = creds.get("id_usina")
        if id_usina and creds.get("cpf"):
            grupo = grupos_usina.setdefault(id_usina, {"creds": creds, "clientes": []})
            grupo["clientes"].append((uc, cliente))
        else:
            sem_usina.append((uc, cliente))

    print(f"📦 Agrupamento: {len(grupos_usina)} usina(s) com login compartilhado | {len(sem_usina)} UC(s) avulsa(s)")

    with sync_playwright() as playwright:
        # 1) Processa por grupo de usina (1 login por usina, várias UCs)
        for id_usina, grupo in grupos_usina.items():
            r = processar_usina(
                playwright,
                grupo["clientes"],
                grupo["creds"],
                mes_ref,
                args.headless,
                forcar=args.forcar,
            )
            resultados["sucesso"].extend(r["sucesso"])
            resultados["falha"].extend(r["falha"])
            resultados["ignorado"].extend(r["ignorado"])
            resultados["sem_fatura"].extend(r.get("sem_fatura", []))

        # 2) Fallback: UCs sem usina vinculada usam o fluxo antigo (1 browser por UC)
        for i, (uc, cliente) in enumerate(sem_usina, 1):
            nome = cliente.get("nome", uc)
            print(f"\n[avulsa {i}/{len(sem_usina)}] {nome} | UC {uc}")

            if not args.forcar:
                _ucs  = buscar_uc_nova(uc)
                _creds = buscar_credenciais_usina(uc)
                existente = ja_baixado(
                    uc, mes_ref,
                    nome=nome,
                    nome_usina=_creds.get("nome_usina", ""),
                    uc_nova_fmt=_ucs.get("formatada", uc),
                )
                if existente:
                    print(f"  ⏭️  {nome} — ja baixado: {existente}")
                    resultados["ignorado"].append(uc)
                    continue

            caminho = processar_uc(playwright, uc, cliente, mes_ref, args.headless)
            if caminho:
                resultados["sucesso"].append(uc)
            else:
                resultados["falha"].append(uc)

            if i < len(sem_usina):
                time.sleep(3)

    # ── Resumo ────────────────────────────────────────────────────────────────
    print(f"\n{'═'*55}")
    print(f"  RESUMO — {mes_ref}")
    print(f"  ✅ Baixados:    {len(resultados['sucesso'])}")
    print(f"  ❌ Falhas:      {len(resultados['falha'])}")
    print(f"  📭 Sem fatura:  {len(resultados['sem_fatura'])} (portal ainda nao emitiu)")
    print(f"  ⏭️  Ignorados:   {len(resultados['ignorado'])} (ja existiam)")

    if resultados["sem_fatura"]:
        print(f"\n  UCs sem fatura disponivel no portal:")
        for uc in resultados["sem_fatura"]:
            nome = clientes[uc].get("nome", uc)
            print(f"    • {uc} — {nome}")

    if resultados["falha"]:
        print(f"\n  UCs com falha:")
        for uc in resultados["falha"]:
            nome = clientes[uc].get("nome", uc)
            print(f"    • {uc} — {nome}")
        print(f"\n  💡 Dica: verifique screenshots em logs_screenshots/")

    print(f"{'═'*55}\n")

    # Retorna codigo de saida com base no resultado
    sys.exit(0 if not resultados["falha"] else 1)


if __name__ == "__main__":
    main()

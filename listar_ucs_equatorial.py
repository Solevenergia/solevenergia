"""
listar_ucs_equatorial.py — Lista todas as UCs da conta do usuário no portal Equatorial

Uso:
  python listar_ucs_equatorial.py --cpf 01873853190 --dn 14051986

Dependências:
  pip install playwright
  playwright install chromium
"""

import sys
import argparse
from datetime import datetime

# Fix encoding for Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("❌ Playwright nao instalado.")
    print("   Execute: pip install playwright && playwright install chromium")
    sys.exit(1)

PORTAL_URL = "https://goias.equatorialenergia.com.br/LoginGO.aspx?envia-dados=Entrar"
TIMEOUT_PADRAO = 30_000

def normalizar_dn(data_nascimento: str) -> str:
    """Converte DN para DD/MM/AAAA."""
    dn = (data_nascimento or "").strip()
    if len(dn) == 8 and dn.isdigit():
        return f"{dn[0:2]}/{dn[2:4]}/{dn[4:8]}"
    if len(dn) == 10 and dn[4] == "-":
        a, m, d = dn.split("-")
        return f"{d}/{m}/{a}"
    return dn

def listar_ucs_equatorial(cpf: str, data_nascimento: str, uc_login: str = "0", headless: bool = True):
    """
    Lista todas as UCs associadas à conta no portal Equatorial.
    """
    cpf_limpo = "".join(filter(str.isdigit, cpf))
    dn = normalizar_dn(data_nascimento)

    print(f"📄 Acessando portal Equatorial...")
    print(f"   CPF: {cpf_limpo[:3]}.***-{cpf_limpo[-2:]}")
    print(f"   DN: {dn}")
    print()

    with sync_playwright() as playwright:
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
            accept_downloads=False,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            # Navega para portal
            print("🌐 Navegando para portal...")
            page.goto(PORTAL_URL, wait_until="networkidle", timeout=TIMEOUT_PADRAO)
            page.wait_for_timeout(1000)

            # Login — UC, CPF, data de nascimento
            print("🔐 Fazendo login...")

            # UC
            page.click("#WEBDOOR_headercorporativogo_txtUC", timeout=10_000)
            page.type("#WEBDOOR_headercorporativogo_txtUC", uc_login, delay=80)
            page.wait_for_timeout(300)

            # CPF
            page.click("#WEBDOOR_headercorporativogo_txtDocumento", timeout=10_000)
            page.type("#WEBDOOR_headercorporativogo_txtDocumento", cpf_limpo, delay=80)
            page.wait_for_timeout(300)

            # Clica ENTRAR
            for sel in [
                "button:has-text('ENTRAR')",
                "button:has-text('Entrar')",
                "#WEBDOOR_headercorporativogo_btnEntrar",
            ]:
                try:
                    el = page.locator(sel).first
                    el.wait_for(state="visible", timeout=3_000)
                    el.click()
                    print("✔️  Clicado ENTRAR")
                    break
                except Exception:
                    continue

            page.wait_for_timeout(5000)

            # Data de nascimento
            print("📅 Validando data de nascimento...")
            campo_nasc = page.locator(
                "input[placeholder*='DD/MM'], input[placeholder*='dd/mm'], "
                "input[id*='nasc'], input[id*='Nasc'], input[name*='nasc'], "
                "input[id*='Data'], input[id*='data']"
            ).first
            campo_nasc.wait_for(state="visible", timeout=15_000)

            campo_nasc.click()
            page.wait_for_timeout(300)
            campo_nasc.fill(dn)
            page.wait_for_timeout(300)

            # Clica VALIDAR
            for sel in [
                "button:has-text('VALIDAR')",
                "button:has-text('Validar')",
                "#WEBDOOR_headercorporativogo_btnValidar",
            ]:
                try:
                    el = page.locator(sel).first
                    el.wait_for(state="visible", timeout=3_000)
                    el.click()
                    print("✔️  Clicado VALIDAR")
                    break
                except Exception:
                    continue

            page.wait_for_load_state("networkidle", timeout=TIMEOUT_PADRAO)
            page.wait_for_timeout(3000)

            # Fecha popup ANTES de qualquer interação (interfere com clicks)
            print("🔕 Fechando popup se existir...")
            try:
                popup = page.locator("#popup_promocao")
                if popup.is_visible(timeout=2_000):
                    for sel in [
                        "#popup_promocao button.close",
                        "#popup_promocao button:has-text('×')",
                        ".modal-header button.close",
                    ]:
                        try:
                            btn = page.locator(sel).first
                            if btn.is_visible(timeout=500):
                                btn.click(force=True)
                                page.wait_for_timeout(500)
                                break
                        except Exception:
                            pass
                    # Tenta fechar pressionando ESC como fallback
                    try:
                        page.press("Escape")
                        page.wait_for_timeout(500)
                    except:
                        pass
            except Exception:
                pass

            # Navega Contas → Segunda Via de Fatura (como em baixar_equatorial.py)
            print("📂 Navegando para Segunda Via de Fatura...")
            try:
                page.get_by_text("Contas").first.click(timeout=10_000)
                page.wait_for_timeout(800)
                page.get_by_text("Segunda Via de Fatura").first.click(timeout=10_000)
                page.wait_for_load_state("networkidle", timeout=TIMEOUT_PADRAO)
                page.wait_for_timeout(2000)
                print("✔️  Navegação por menu concluída")
            except Exception as e:
                print(f"⚠️  Navegação por menu falhou: {e}")
                print("   Tentando navegação direta...")
                try:
                    page.goto(
                        "https://goias.equatorialenergia.com.br/AgenciaGO/Servicos/aberto/SegundaVia.aspx",
                        wait_until="networkidle",
                        timeout=TIMEOUT_PADRAO
                    )
                    page.wait_for_timeout(3000)
                except Exception as e2:
                    print(f"   ❌ Navegação direta também falhou: {e2}")

            # Debug: mostra URL
            print(f"\n📍 URL atual: {page.url}")

            # Verifica se estamos em página de erro e tenta voltar ao Index
            if "Suporte" in page.url or "aspxerrorpath" in page.url:
                print("⚠️  Redirecionado para página de erro, voltando para Index...")
                page.goto("https://goias.equatorialenergia.com.br/Index.aspx", wait_until="networkidle", timeout=TIMEOUT_PADRAO)
                page.wait_for_timeout(3000)
                print(f"   Nova URL: {page.url}")

            # Procura pelo dropdown/combobox de UC na página atual
            print("🔍 Procurando dropdown de UCs na página...")

            # Extrai UCs do dropdown usando JavaScript
            print("📊 Extraindo opções do dropdown usando JavaScript...")

            ucs_data = page.evaluate("""() => {
                // Debug: lista todos os elementos select na página
                const allSelects = document.querySelectorAll('select');
                console.log('Total de <select> encontrados:', allSelects.length);

                let select = null;

                // Tenta encontrar por vários critérios
                const selectores = [
                    () => document.getElementById('CONTENT_comboBoxUC'),
                    () => document.querySelector('[id*="comboBoxUC"]'),
                    () => document.querySelector('select[name*="UC"]'),
                    () => document.querySelector('select[id*="Unidade"]'),
                    () => document.querySelector('select[id*="unidade"]'),
                ];

                for (let seletor of selectores) {
                    try {
                        select = seletor();
                        if (select) {
                            console.log('Select encontrado com:', seletor.toString());
                            break;
                        }
                    } catch (e) {}
                }

                // Se não achou, lista todos os selects disponíveis
                if (!select && allSelects.length > 0) {
                    console.log('Listando todos os <select> disponíveis:');
                    for (let i = 0; i < allSelects.length; i++) {
                        const s = allSelects[i];
                        console.log(`  [${i}] ID: ${s.id}, Name: ${s.name}, Options: ${s.options.length}`);
                    }
                    // Tenta usar o primeiro select com mais de 2 opções
                    for (let s of allSelects) {
                        if (s.options.length > 2) {
                            select = s;
                            console.log('Usando primeiro select com múltiplas opções');
                            break;
                        }
                    }
                }

                if (!select) {
                    console.log('Nenhum select foi encontrado na página');
                    return { error: 'select_nao_encontrado', selects_totais: allSelects.length };
                }

                const options = [];
                console.log('Extraindo de select com ' + select.options.length + ' opções');

                for (let i = 0; i < select.options.length; i++) {
                    const opt = select.options[i];
                    const valor = (opt.value || '').trim();
                    const texto = (opt.textContent || '').trim();

                    if (valor !== '' && valor !== '0') {
                        options.push({
                            valor: valor,
                            texto: texto
                        });
                    }
                }

                console.log('Total de opções extraídas:', options.length);
                return options;
            }""")

            # Verifica se há erro na extração
            if isinstance(ucs_data, dict) and "error" in ucs_data:
                print(f"\n❌ Erro na extração: {ucs_data.get('error')}")
                print(f"   Total de <select> na página: {ucs_data.get('selects_totais', 'desconhecido')}")
                print(f"\n   Tentando alternativa: buscar por class, role, ou onclick handlers...")

                # Tenta extração alternativa
                ucs_data = page.evaluate("""() => {
                    const options = [];

                    // Procura por inputs com datalist ou combobox
                    const inputs = document.querySelectorAll('input[list], input[role="combobox"]');
                    for (let inp of inputs) {
                        console.log('Input encontrado:', inp.id, inp.name);
                        const list = inp.list || document.getElementById(inp.getAttribute('list'));
                        if (list) {
                            for (let opt of list.querySelectorAll('option')) {
                                options.push({
                                    valor: opt.value,
                                    texto: opt.textContent
                                });
                            }
                        }
                    }

                    // Procura por divs com classe combobox ou dropdown
                    const dropdowns = document.querySelectorAll('[class*="combo"], [class*="dropdown"]');
                    console.log('Dropdowns alternativos encontrados:', dropdowns.length);

                    return options;
                }""")

            ucs = ucs_data if ucs_data and isinstance(ucs_data, list) else []

            print(f"\n🔍 Encontradas {len(ucs)} opções no dropdown:\n")
            print(f"{'#':<4} {'UC (15 dígitos)':<20} {'Descrição':<60}")
            print("-" * 85)

            for i, uc_item in enumerate(ucs, 1):
                valor = uc_item.get("valor", "")
                texto = uc_item.get("texto", "")
                print(f"{i:<4} {valor:<20} {texto:<60}")

            print("\n" + "=" * 85)
            print(f"✅ Total de UCs encontradas: {len(ucs)}")
            print("=" * 85)

            return ucs

        except Exception as e:
            print(f"❌ Erro: {e}")
            print(f"\n📸 Tire um print da tela do navegador para diagnosticar.")
            import traceback
            traceback.print_exc()
            return []

        finally:
            context.close()
            browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lista UCs do portal Equatorial")
    parser.add_argument("--cpf", required=True, help="CPF (ex: 01873853190)")
    parser.add_argument("--dn", required=True, help="Data de nascimento (ex: 14051986 ou 14/05/1986)")
    parser.add_argument("--uc", default="0", help="UC inicial (padrão: 0)")
    parser.add_argument("--headless", action="store_true", help="Executar sem mostrar navegador")

    args = parser.parse_args()

    ucs = listar_ucs_equatorial(args.cpf, args.dn, args.uc, headless=args.headless)

    if ucs:
        print("\n💾 UCs em formato JSON:")
        import json
        print(json.dumps(ucs, indent=2, ensure_ascii=False))

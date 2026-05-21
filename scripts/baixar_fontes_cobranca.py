"""
Baixa as fontes do Google Fonts usadas no template de cobrança e salva
localmente em static/fonts/. Elimina dependência da internet ao gerar PDFs.

Fontes utilizadas pelo template fatura/cobranca.html:
  - Sora (300, 400, 500, 600, 700, 800)
  - Manrope (400, 500, 600, 700)
  - JetBrains Mono (400, 500)

Após rodar este script, atualize o template para usar @font-face local
(o script imprime o CSS pronto pra colar).

Uso:
    python scripts/baixar_fontes_cobranca.py
"""
import sys, os, re
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "static", "fonts")
os.makedirs(FONT_DIR, exist_ok=True)

# URL CSS do Google Fonts (mesmo do template)
CSS_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Sora:wght@300;400;500;600;700;800"
    "&family=Manrope:wght@400;500;600;700"
    "&family=JetBrains+Mono:wght@400;500"
    "&display=swap"
)

# User-Agent que faz Google retornar WOFF2 (mais compacto que TTF)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

print("1. Baixando CSS do Google Fonts...")
r = httpx.get(CSS_URL, headers=HEADERS, timeout=30)
css = r.text
print(f"   OK ({len(css)} chars)")

# Extrai blocos @font-face e suas URLs
# Padrão: src: url(https://...woff2)
font_face_blocks = re.findall(r"@font-face\s*\{[^}]+\}", css)
print(f"\n2. Encontradas {len(font_face_blocks)} variantes de fonte")

baixadas = 0
css_local = []  # CSS reescrito apontando para arquivos locais

for bloco in font_face_blocks:
    # Extrai family, weight, style
    m_family = re.search(r"font-family:\s*['\"]([^'\"]+)['\"]", bloco)
    m_weight = re.search(r"font-weight:\s*(\d+)", bloco)
    m_style  = re.search(r"font-style:\s*(\w+)", bloco)
    m_url    = re.search(r"src:\s*url\(([^)]+)\)", bloco)
    m_unicode = re.search(r"unicode-range:\s*([^;]+);", bloco)

    if not (m_family and m_url):
        continue

    family = m_family.group(1)
    weight = m_weight.group(1) if m_weight else "400"
    style  = m_style.group(1)  if m_style  else "normal"
    url    = m_url.group(1).strip()
    unicode_range = m_unicode.group(1).strip() if m_unicode else None

    # Pula variantes Cyrillic/Greek/Vietnamese (só latin precisa)
    if unicode_range and not (
        unicode_range.startswith("U+0000") or
        unicode_range.startswith("U+00") or
        "latin" in bloco.lower()
    ):
        # Tenta detectar latin pelo unicode range
        if "U+0000-00FF" not in unicode_range and "U+0100" not in unicode_range:
            # Mantém só blocos latin (range com 0000-00FF normalmente)
            continue

    # Nome do arquivo local
    fname_safe = family.replace(" ", "")
    ext = os.path.splitext(url.split("?")[0])[1] or ".woff2"
    out_name = f"{fname_safe}-{weight}-{style}{ext}"
    out_path = os.path.join(FONT_DIR, out_name)

    if not os.path.exists(out_path):
        try:
            rf = httpx.get(url, timeout=30)
            with open(out_path, "wb") as f:
                f.write(rf.content)
            baixadas += 1
            print(f"   ✓ {family} {weight}{'/'+style if style != 'normal' else ''}: {len(rf.content):,} bytes")
        except Exception as e:
            print(f"   ✗ {family} {weight}: {e}")
            continue
    else:
        print(f"   = {family} {weight}{'/'+style if style != 'normal' else ''}: já existe")

    # Reescreve o bloco com URL local
    bloco_local = bloco.replace(url, f"/static/fonts/{out_name}")
    css_local.append(bloco_local)

print(f"\n3. Total baixadas: {baixadas} fontes em {FONT_DIR}")

# Gera o CSS final pra embutir no template
css_path = os.path.join(FONT_DIR, "fonts_cobranca.css")
with open(css_path, "w", encoding="utf-8") as f:
    f.write("/* Fontes embutidas localmente — geradas por scripts/baixar_fontes_cobranca.py */\n")
    f.write("\n".join(css_local))
print(f"\n4. CSS gerado: {css_path}")

# Resumo de fontes baixadas (apenas latin)
fontes_latin = sorted({
    fname for fname in os.listdir(FONT_DIR)
    if fname.endswith((".woff2", ".woff", ".ttf"))
})
print(f"\n5. Fontes salvas ({len(fontes_latin)}):")
for fname in fontes_latin:
    size = os.path.getsize(os.path.join(FONT_DIR, fname))
    print(f"   {fname}: {size:,} bytes")

print(f"\n{'='*60}")
print("PRÓXIMO PASSO: atualizar o template cobranca.html para usar")
print("as fontes locais em vez do CDN do Google.")
print(f"{'='*60}")

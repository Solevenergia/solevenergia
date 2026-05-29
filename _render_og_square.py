# _render_og_square.py — ONE-SHOT (build-time, não roda em runtime)
# Constrói o BG quadrado 1080×1080 com elementos estáticos:
#   - Wordmark "solev" renderizado das fontes Sora (Bold+Light + circulos do "o")
#   - Eyebrow "— COBRANÇA MENSAL —"
#   - Label "VALOR A PAGAR"
#   - Rodapé "SOLEV ENERGIA · SOLEVENERGIA.COM.BR"
#
# Os 3 textos dinâmicos (saudação, valor, pílula vence) entram em runtime via
# solev_og_card.gerar_card_quadrado_bytes().
#
# Saída: static/og_background_square.png

from PIL import Image, ImageDraw, ImageFont
import os

ROOT     = os.path.dirname(os.path.abspath(__file__))
BOLD_F   = os.path.join(ROOT, 'static', 'fonts', 'Sora-ExtraBold.ttf')
LIGHT_F  = os.path.join(ROOT, 'static', 'fonts', 'Sora-Light.ttf')
SEMIB_F  = os.path.join(ROOT, 'static', 'fonts', 'Sora-SemiBold.ttf')
MAN_BOLD = os.path.join(ROOT, 'static', 'fonts', 'Manrope-Bold.ttf')
WM_SRC   = os.path.join(ROOT, 'static', 'logo', 'solev-wordmark-ink-rendered.png')
OUT      = os.path.join(ROOT, 'static', 'og_background_square.png')

INK    = '#0E1B2E'
ACCENT = '#E8732A'
PAPER  = '#F2E8D4'
MUTED  = (14, 27, 46, 140)   # INK 55% alpha

W, H = 1080, 1080

# ──────────────────────────────────────────────────────────────────────────
# Canvas areia
img = Image.new('RGBA', (W, H), PAPER)
d   = ImageDraw.Draw(img)

# ──── Wordmark "solev" centralizado em (540, 200), altura ~110px ────────
# Reusa o PNG já renderizado das fontes Sora (com cap correto no 'l').
wm = Image.open(WM_SRC).convert('RGBA')
# original 219×68; redimensiono pra altura 110 mantendo aspect
wm_h = 110
wm_w = round(wm.width * wm_h / wm.height)
wm_scaled = wm.resize((wm_w, wm_h), Image.LANCZOS)
img.paste(wm_scaled, (540 - wm_w // 2, 200 - wm_h // 2), wm_scaled)

# ──── Eyebrow "— COBRANÇA MENSAL —" centralizado em y=345 ──────────────
eyebrow_font = ImageFont.truetype(SEMIB_F, 22)
eyebrow_txt  = "COBRANÇA MENSAL"
# espaço-letra largo (uppercase tracked)
gap = 6
parts = list(eyebrow_txt)
total_w = 0
widths = []
for ch in parts:
    w_ch = d.textlength(ch, font=eyebrow_font)
    widths.append(w_ch)
    total_w += w_ch + gap
total_w -= gap
# Desenha + linhas decorativas laranja
line_len = 50
line_gap = 16
total_block_w = line_len + line_gap + total_w + line_gap + line_len
x = 540 - total_block_w / 2
y_eb = 345
# linha esq
d.line([x, y_eb, x + line_len, y_eb], fill=ACCENT, width=2)
x += line_len + line_gap
# letras
for ch, wch in zip(parts, widths):
    d.text((x, y_eb - 14), ch, font=eyebrow_font, fill=ACCENT)
    x += wch + gap
x -= gap
x += line_gap
# linha dir
d.line([x, y_eb, x + line_len, y_eb], fill=ACCENT, width=2)

# ──── Label "VALOR A PAGAR" centralizado em y=560 ───────────────────────
label_font = ImageFont.truetype(SEMIB_F, 22)
label_txt  = "VALOR A PAGAR"
parts = list(label_txt)
widths = []
total_w = 0
for ch in parts:
    w_ch = d.textlength(ch, font=label_font)
    widths.append(w_ch)
    total_w += w_ch + gap
total_w -= gap
x = 540 - total_w / 2
y_lb = 560
for ch, wch in zip(parts, widths):
    d.text((x, y_lb - 14), ch, font=label_font, fill=MUTED)
    x += wch + gap

# ──── Rodapé "SOLEV ENERGIA · SOLEVENERGIA.COM.BR" em y=1000 ───────────
foot_font = ImageFont.truetype(SEMIB_F, 18)
parts_left  = list("SOLEV ENERGIA")
parts_right = list("SOLEVENERGIA.COM.BR")

def _stretched_width(parts, font, gap_letters):
    total = 0
    for ch in parts:
        total += d.textlength(ch, font=font) + gap_letters
    return total - gap_letters

bullet_gap = 18
gap_letters = 4
w_l = _stretched_width(parts_left,  foot_font, gap_letters)
w_r = _stretched_width(parts_right, foot_font, gap_letters)
bullet_r = 4

total = w_l + bullet_gap + bullet_r * 2 + bullet_gap + w_r
x = 540 - total / 2
y_ft = 1000

for ch in parts_left:
    d.text((x, y_ft - 12), ch, font=foot_font, fill=INK)
    x += d.textlength(ch, font=foot_font) + gap_letters
x -= gap_letters
x += bullet_gap

# bullet laranja
d.ellipse([x, y_ft - bullet_r, x + bullet_r * 2, y_ft + bullet_r], fill=ACCENT)
x += bullet_r * 2 + bullet_gap

for ch in parts_right:
    d.text((x, y_ft - 12), ch, font=foot_font, fill=INK)
    x += d.textlength(ch, font=foot_font) + gap_letters

# ──── Marcador "— ENERGIA SOLAR" em y=70 (top right) ────────────────────
top_font = ImageFont.truetype(SEMIB_F, 18)
top_txt  = "ENERGIA SOLAR"
parts = list(top_txt)
gap_letters = 5
widths = [d.textlength(ch, font=top_font) for ch in parts]
total_w = sum(widths) + gap_letters * (len(parts) - 1)
top_line_len = 40
top_line_gap = 14
total_block_w = top_line_len + top_line_gap + total_w
x = 540 - total_block_w / 2
y_tp = 70
d.line([x, y_tp, x + top_line_len, y_tp], fill=ACCENT, width=2)
x += top_line_len + top_line_gap
for ch, w_ch in zip(parts, widths):
    d.text((x, y_tp - 12), ch, font=top_font, fill=INK)
    x += w_ch + gap_letters

# ──────────────────────────────────────────────────────────────────────────
img.convert('RGB').save(OUT, 'PNG', optimize=True)
print(f'salvo: {OUT}  ({os.path.getsize(OUT)} bytes)')

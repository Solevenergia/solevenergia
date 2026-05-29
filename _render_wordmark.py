# _render_wordmark.py — script ONE-SHOT (não roda em runtime do app)
# Renderiza o wordmark "solev" no tamanho exato 210×68 px usando:
#   - Sora-ExtraBold (TTF) pro "s" e "l"
#   - Sora-Light (TTF) pro "e" e "v"
#   - Círculos concêntricos pro "o" (anel navy + miolo laranja) — desenho oficial
# Letter-spacing -0.045em conforme brand guide.
#
# Renderiza em 4× pra ficar afiado e downsample com LANCZOS.
# Resultado: static/logo/solev-wordmark-ink-rendered.png (PNG transparente).
#
# Em seguida cola esse PNG no BG no lugar da logo antiga.

from PIL import Image, ImageDraw, ImageFont
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
BOLD_F  = os.path.join(ROOT, 'static', 'fonts', 'Sora-ExtraBold.ttf')
LIGHT_F = os.path.join(ROOT, 'static', 'fonts', 'Sora-Light.ttf')
OUT     = os.path.join(ROOT, 'static', 'logo', 'solev-wordmark-ink-rendered.png')
BG_PATH = os.path.join(ROOT, 'static', 'og_background.png')

INK    = '#0E1B2E'
ACCENT = '#E8732A'
PAPER  = '#F2E8D4'

# Wordmark final dimensions in the BG (medido empiricamente antes)
TARGET_W, TARGET_H = 210, 68

# Render 4x pra qualidade
SCALE = 4
W = TARGET_W * SCALE * 2          # canvas grande, recorto depois
H = TARGET_H * SCALE * 2
FONT_SIZE = int(TARGET_H * SCALE / 0.78)   # ascender 'l' ≈ 0.78em

img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

bold  = ImageFont.truetype(BOLD_F,  FONT_SIZE)
light = ImageFont.truetype(LIGHT_F, FONT_SIZE)

LS = int(round(-0.045 * FONT_SIZE))   # letter-spacing negativo

baseline_y = H // 2 + int(0.35 * FONT_SIZE)
x = 100

def adv(txt, font):
    return int(d.textlength(txt, font=font))

# 's' — Bold
d.text((x, baseline_y), 's', font=bold, fill=INK, anchor='ls')
x += adv('s', bold) + LS

# 'o' — circulo concentrico
# Diâmetro do 'o' = 0.65em (calibrado pra bater com x-height + overshoot)
o_dia = int(0.65 * FONT_SIZE)
overshoot = int(0.03 * FONT_SIZE)
o_top = baseline_y - o_dia + overshoot
o_bot = o_top + o_dia
o_cx = x + o_dia / 2
o_cy = (o_top + o_bot) / 2

d.ellipse([x, o_top, x + o_dia, o_bot], fill=INK)
inner_r = o_dia / 2 * 0.66    # raio interno = 33/50 do externo
d.ellipse([o_cx - inner_r, o_cy - inner_r, o_cx + inner_r, o_cy + inner_r], fill=ACCENT)
x += o_dia + LS

# 'l' — Bold (tem o cap horizontal nativo)
d.text((x, baseline_y), 'l', font=bold, fill=INK, anchor='ls')
x += adv('l', bold) + LS

# 'e' — Light
d.text((x, baseline_y), 'e', font=light, fill=INK, anchor='ls')
x += adv('e', light) + LS

# 'v' — Light
d.text((x, baseline_y), 'v', font=light, fill=INK, anchor='ls')

# Crop ao bbox visual e downsample pra TARGET
bbox = img.getbbox()
print(f'render 4x bbox: {bbox} ({bbox[2]-bbox[0]}x{bbox[3]-bbox[1]})')
cropped = img.crop(bbox)

# Resize mantendo aspect ratio com base na altura
aspect = cropped.width / cropped.height
new_w = int(round(TARGET_H * aspect))
final = cropped.resize((new_w, TARGET_H), Image.LANCZOS)
print(f'final size: {final.size} (aspect ratio preservado)')

final.save(OUT)
print(f'salvo: {OUT}')

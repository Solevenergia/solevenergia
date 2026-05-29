# solev_og_card.py — geração do OG card de cobrança Solev (1200×630)
# ───────────────────────────────────────────────────────────────────
# REGRA DE OURO: o visual é um PNG de fundo FIXO (static/og_background.png)
# entregue pelo designer. Este módulo SÓ carimba 4 textos por cima com Pillow:
#   1 · saudação      "Olá, {nome}!"           — centro (321, 256)
#   2 · valor         "R$ {valor}"             — centro (321, 383)
#   3 · pílula        "vence em {DD/MM/AAAA}"  — centro (321, 473)
#   4 · mês ref       "{MÊS / ANO}"            — centro (921, 538)
#
# NÃO redesenha logo, anéis, labels, rodapé ou tagline — tudo isso já está
# no PNG de fundo. Spec completa: "SOLEV - Handoff Claude Code/03-og-card/
# Solev OG Background - spec.json".

import os
import hashlib
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

_DIR        = os.path.dirname(os.path.abspath(__file__))
BG_PATH     = os.path.join(_DIR, "static", "og_background.png")
BG_SQ_PATH  = os.path.join(_DIR, "static", "og_background_square.png")
FONT_DIR    = os.path.join(_DIR, "static", "fonts")
CACHE_DIR   = os.path.join(_DIR, "static", "cache", "og")

INK         = "#0E1B2E"
PAPER       = "#F2E8D4"
ACCENT_SOFT = "#F5A867"
RS_GREY     = "#7A8190"

# Carregar TTF não é grátis — cacheia ImageFont por (nome, size).
_FONT_CACHE: dict = {}


def _f(nome: str, size: int) -> ImageFont.FreeTypeFont:
    key = (nome, size)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(os.path.join(FONT_DIR, f"{nome}.ttf"), size)
    return _FONT_CACHE[key]


def _fit_size(draw: ImageDraw.ImageDraw, nome_arq: str, size_max: int,
              size_min: int, txt: str, max_w: int) -> ImageFont.FreeTypeFont:
    """Maior fonte ≤ size_max cujo texto cabe em max_w; piso em size_min."""
    for size in range(size_max, size_min - 1, -1):
        font = _f(nome_arq, size)
        if draw.textlength(txt, font=font) <= max_w:
            return font
    return _f(nome_arq, size_min)


def _centro_bbox(draw, txt, font, cx, cy, fill):
    """Centraliza pelo bbox visual em (cx, cy). Usa anchor padrão 'la'."""
    l, t, r, b = draw.textbbox((0, 0), txt, font=font)
    draw.text((cx - (r - l) / 2 - l, cy - (b - t) / 2 - t),
              txt, font=font, fill=fill)


def gerar_card_bytes(nome: str, valor: str, vencimento: str, mes_ref: str) -> bytes:
    """Compõe o OG card e devolve bytes PNG (RGB).

    Args:
        nome       : ex "Tacielly" (primeiro nome típico, mas aceita longo)
        valor      : número formatado SEM prefixo R$, ex "373,56" / "12.345,67"
        vencimento : DD/MM/AAAA, ex "31/05/2026" (vazio omite a pílula)
        mes_ref    : ex "Maio / 2026" (vazio omite o rótulo do painel direito)
    """
    bg = Image.open(BG_PATH).convert("RGBA")
    d  = ImageDraw.Draw(bg)

    # ── 1 · Saudação ─────────────────────────────────────────────────────
    #     Sora Bold 36px, INK, centro (321, 256), max 480px, min 26px
    saud_txt = f"Olá, {nome}!"
    saud_f   = _fit_size(d, "Sora-Bold", 36, 26, saud_txt, 480)
    _centro_bbox(d, saud_txt, saud_f, 321, 256, INK)

    # ── 2 · Valor (R$ + número, mesma linha de base) ─────────────────────
    #     R$  : Sora SemiBold 46px, #7A8190 (cinza)
    #     num : Sora ExtraBold 98px, INK
    #     Bloco completo cabe em 520px (auto-shrink proporcional).
    NUM_MAX, NUM_MIN = 98, 64
    RS_MAX           = 46
    MAX_W            = 520
    rs_txt = "R$ "

    num_size = NUM_MAX
    while True:
        rs_size = max(int(round(RS_MAX * (num_size / NUM_MAX))), 24)
        num_f = _f("Sora-ExtraBold", num_size)
        rs_f  = _f("Sora-SemiBold",  rs_size)
        rs_w  = d.textlength(rs_txt, font=rs_f)
        num_w = d.textlength(valor,  font=num_f)
        if rs_w + num_w <= MAX_W or num_size <= NUM_MIN:
            break
        num_size -= 2

    # Anchor "ls" = left + baseline → o y passado É a linha de base do glifo.
    # Setando a mesma baseline_y pra R$ e pro número, eles ALINHAM pela base
    # automaticamente — independe do tamanho (essencial pro auto-shrink).
    # baseline_y é calculada de modo que o bbox visual do número fique
    # centrado em y=383.
    _, nt, _, nb = d.textbbox((0, 0), valor, font=num_f, anchor="ls")
    baseline_y = 383 - (nt + nb) / 2

    x0 = 321 - (rs_w + num_w) / 2
    d.text((x0,        baseline_y), rs_txt, font=rs_f, fill=RS_GREY, anchor="ls")
    d.text((x0 + rs_w, baseline_y), valor,  font=num_f, fill=INK,    anchor="ls")

    # ── 3 · Pílula "vence em DD/MM/AAAA" ─────────────────────────────────
    if vencimento:
        txt = f"vence em {vencimento}"
        pf  = _f("Manrope-Bold", 15)
        tw  = d.textlength(txt, font=pf)
        icon, gap, pad_x, ph = 16, 9, 16, 38
        pw = pad_x + icon + gap + tw + pad_x
        px = 321 - pw / 2
        py = 473 - ph / 2
        d.rounded_rectangle([px, py, px + pw, py + ph], radius=ph / 2, fill=INK)

        # Ícone calendário (#F5A867) — corpo + cabeçalho + 2 ganchos
        ix, iy = px + pad_x, 473 - icon / 2
        d.rounded_rectangle([ix, iy + 2, ix + icon, iy + icon],
                            radius=3, outline=ACCENT_SOFT, width=2)
        d.line([ix,            iy + 6, ix + icon,        iy + 6], fill=ACCENT_SOFT, width=2)
        d.line([ix + 4,        iy,     ix + 4,           iy + 4], fill=ACCENT_SOFT, width=2)
        d.line([ix + icon - 4, iy,     ix + icon - 4,    iy + 4], fill=ACCENT_SOFT, width=2)

        d.text((px + pad_x + icon + gap, 473 - 9), txt, font=pf, fill=PAPER)

    # ── 4 · Mês de referência (painel escuro, centro 921, 538) ───────────
    #     JetBrains Mono 15px, uppercase, paper 65% alpha, max 420px, min 11px
    if mes_ref:
        mes_txt  = mes_ref.upper()
        mes_font = _fit_size(d, "JetBrainsMono-Medium", 15, 11, mes_txt, 420)
        _centro_bbox(d, mes_txt, mes_font, 921, 538, (242, 232, 212, 166))

    out = bg.convert("RGB")
    buf = BytesIO()
    out.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def gerar_card_quadrado_bytes(nome: str, valor: str, vencimento: str) -> bytes:
    """Versão 1080×1080 do OG card, otimizada pra thumb do WhatsApp.

    BG estático (og_background_square.png) já contém logo, eyebrow 'COBRANÇA
    MENSAL', label 'VALOR A PAGAR' e rodapé. Aqui carimbamos 3 textos:
        1 · saudação    — centro (540, 460)
        2 · valor R$    — centro (540, 680)
        3 · pílula vence — centro (540, 870)
    """
    bg = Image.open(BG_SQ_PATH).convert("RGBA")
    d  = ImageDraw.Draw(bg)

    # ── 1 · Saudação (Sora Bold 44px, max 760, min 30)
    saud_txt = f"Olá, {nome}!"
    saud_f   = _fit_size(d, "Sora-Bold", 44, 30, saud_txt, 760)
    _centro_bbox(d, saud_txt, saud_f, 540, 460, INK)

    # ── 2 · Valor: R$ Sora SemiBold + número Sora ExtraBold, bases alinhadas
    NUM_MAX, NUM_MIN = 130, 80
    RS_MAX           = 60
    MAX_W            = 820
    rs_txt = "R$ "
    num_size = NUM_MAX
    while True:
        rs_size = max(int(round(RS_MAX * (num_size / NUM_MAX))), 30)
        num_f = _f("Sora-ExtraBold", num_size)
        rs_f  = _f("Sora-SemiBold",  rs_size)
        rs_w  = d.textlength(rs_txt, font=rs_f)
        num_w = d.textlength(valor,  font=num_f)
        if rs_w + num_w <= MAX_W or num_size <= NUM_MIN:
            break
        num_size -= 2

    _, nt, _, nb = d.textbbox((0, 0), valor, font=num_f, anchor="ls")
    baseline_y = 680 - (nt + nb) / 2
    x0 = 540 - (rs_w + num_w) / 2
    d.text((x0,        baseline_y), rs_txt, font=rs_f, fill=RS_GREY, anchor="ls")
    d.text((x0 + rs_w, baseline_y), valor,  font=num_f, fill=INK,    anchor="ls")

    # ── 3 · Pílula "vence em DD/MM/AAAA" (centro 540, 870)
    if vencimento:
        txt = f"vence em {vencimento}"
        pf  = _f("Manrope-Bold", 22)
        tw  = d.textlength(txt, font=pf)
        icon, gap, pad_x, ph = 22, 12, 22, 54
        pw = pad_x + icon + gap + tw + pad_x
        px = 540 - pw / 2
        py = 870 - ph / 2
        d.rounded_rectangle([px, py, px + pw, py + ph], radius=ph / 2, fill=INK)

        ix, iy = px + pad_x, 870 - icon / 2
        d.rounded_rectangle([ix, iy + 3, ix + icon, iy + icon],
                            radius=4, outline=ACCENT_SOFT, width=2)
        d.line([ix,            iy + 8, ix + icon,        iy + 8], fill=ACCENT_SOFT, width=2)
        d.line([ix + 6,        iy,     ix + 6,           iy + 5], fill=ACCENT_SOFT, width=2)
        d.line([ix + icon - 6, iy,     ix + icon - 6,    iy + 5], fill=ACCENT_SOFT, width=2)

        d.text((px + pad_x + icon + gap, 870 - 14), txt, font=pf, fill=PAPER)

    out = bg.convert("RGB")
    buf = BytesIO()
    out.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ── Cache em disco ───────────────────────────────────────────────────────
# Hash inclui todos os campos que aparecem visíveis: se a fatura mudar valor,
# vencimento, mês ou nome do titular, o nome do arquivo muda e regenera.
# Arquivos antigos ficam órfãos — limpe com `python solev_og_card.py --clean`.

def _hash_card(*partes) -> str:
    chave = "|".join(str(p) for p in partes)
    return hashlib.sha1(chave.encode("utf-8")).hexdigest()[:10]


def caminho_cache(id_fatura, nome, valor, vencimento, mes_ref) -> str:
    h = _hash_card(nome, valor, vencimento, mes_ref)
    return os.path.join(CACHE_DIR, f"fatura_{id_fatura}_{h}.png")


def caminho_cache_quadrado(id_fatura, nome, valor, vencimento) -> str:
    h = _hash_card("SQ", nome, valor, vencimento)
    return os.path.join(CACHE_DIR, f"fatura_{id_fatura}_sq_{h}.png")


def gerar_card_cached(id_fatura, nome, valor, vencimento, mes_ref) -> str:
    """Retorna o caminho no disco; gera só se ainda não existe pra esse hash."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = caminho_cache(id_fatura, nome, valor, vencimento, mes_ref)
    if not os.path.exists(path):
        with open(path, "wb") as fp:
            fp.write(gerar_card_bytes(nome, valor, vencimento, mes_ref))
    return path


def gerar_card_quadrado_cached(id_fatura, nome, valor, vencimento) -> str:
    """Variante quadrada — usada como og:image principal no WhatsApp."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = caminho_cache_quadrado(id_fatura, nome, valor, vencimento)
    if not os.path.exists(path):
        with open(path, "wb") as fp:
            fp.write(gerar_card_quadrado_bytes(nome, valor, vencimento))
    return path


# ── CLI: testes e limpeza ────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--clean":
        # Apaga PNGs do cache (deixa diretório)
        n = 0
        if os.path.isdir(CACHE_DIR):
            for nm in os.listdir(CACHE_DIR):
                if nm.startswith("fatura_") and nm.endswith(".png"):
                    os.remove(os.path.join(CACHE_DIR, nm))
                    n += 1
        print(f"removidos {n} arquivos de {CACHE_DIR}")
        sys.exit(0)

    # Testes de smoke — gera 2 cards em static/cache/og/_test/
    out_dir = os.path.join(_DIR, "static", "cache", "og", "_test")
    os.makedirs(out_dir, exist_ok=True)

    casos = [
        ("card_curto.png",
         ("Tacielly", "373,56", "31/05/2026", "Maio / 2026")),
        ("card_longo.png",
         ("Maria Aparecida da Conceição", "12.345.678,90", "31/12/2026", "Dezembro / 2026")),
    ]
    for arq, args in casos:
        path = os.path.join(out_dir, arq)
        with open(path, "wb") as fp:
            fp.write(gerar_card_bytes(*args))
        print(f"gerado: {path}")

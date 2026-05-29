# Logo Solev — NUNCA recriar com código

O Claude Code erra o logo porque **tenta desenhá-lo** (HTML/CSS, fonte). A
regra para nunca mais errar: o logo é um **arquivo de imagem**, não código.

## ❌ NÃO faça
- Não escreva "solev" com fonte / `<span>`
- Não recrie o "o" com CSS / `border-radius`
- Não gere SVG de texto novo

## ✅ FAÇA — insira o arquivo PNG pronto

```html
<!-- fundo claro (areia/branco) -->
<img src="/static/logo/solev-wordmark-ink.png" alt="Solev" height="48">

<!-- fundo escuro (navy) -->
<img src="/static/logo/solev-wordmark-paper.png" alt="Solev" height="48">
```

Pillow:
```python
logo = Image.open("logo/solev-wordmark-ink.png").convert("RGBA")
logo.thumbnail((300, 300))
fundo.paste(logo, (x, y), logo)   # 3º arg = máscara alfa
```

## Arquivos (transparentes, prontos)

| Arquivo | Uso |
|---|---|
| `solev-wordmark-ink.png` | Wordmark navy · **fundos claros** · transparente |
| `solev-wordmark-paper.png` | Wordmark areia · **fundos escuros** · transparente |
| `solev-wordmark-ink-on-paper.png` | Já sobre fundo Areia Quente (sem transparência) |
| `solev-wordmark-paper-on-ink.png` | Já sobre fundo Noite Solev (sem transparência) |
| `solev-symbolo-ink.png` / `-paper.png` | Só o "o" · favicon / avatar |

> Estes PNGs foram capturados da construção **oficial** do wordmark (Sora
> ExtraBold 800 no "s/l" + Light 300 no "e/v", com o "o" justo). O contraste
> de peso e o espaçamento já estão corretos e embutidos — impossível quebrar.

## Regra de ouro
> O logo da Solev é um **arquivo**. Sempre insira o PNG. Nunca reconstrua.

Cores oficiais: INK `#0E1B2E` · PAPER `#F2E8D4` · ACCENT `#E8732A`

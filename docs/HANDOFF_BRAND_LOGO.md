# Handoff — Identidade visual SoLev (31/05/2026)

> **Pra quem trabalhar no projeto depois das mudanças de 28-31/05/2026.**
> Antes de mexer em qualquer coisa visual, **`git pull`** e leia isso.

---

## Contexto

Entre 28 e 31/05/2026 uma sessão paralela fez **~13 commits** no `main` focados em:

1. Sistema completo de **OG card** pra preview no WhatsApp/Twitter/social
2. Adoção do **handoff oficial da logo** (pasta `solev-logo/`)
3. Limpeza de assets e pastas antigas
4. Atualização da **cor laranja oficial** (`#E8732A` → `#E26A14`)
5. **Pre-commit hook** anti-recidiva da regra de ouro

Commits relevantes em ordem cronológica:

```
f7a4a09  feat(og-card): card dinâmico da fatura como preview de link no WhatsApp/social
92ca7f6  feat(brand): adota handoff oficial solev-logo/ e remove OG card dinâmico
ef5cc99  fix(brand): audit completo — propaga logo em contrato/simulador/cobrança
db7f118  fix(brand): round 2 audit — manifest CONTALEV, favicons antigos, soleconomia, órfãos
c9bb73a  fix(brand): cobrança PDF não recria mais wordmark/símbolo em código
3fff23e  fix(brand): troca SVGs decorativos inline (sun-deco/savings-sun) pelo símbolo oficial
4acde54  fix(brand): atualiza laranja para #E26A14 (oficial) + hook anti-recidiva
```

---

## 1. Pegue as mudanças

```bash
git pull origin main
```

Se você tinha trabalho local não-commitado, salve antes:

```bash
git stash
git pull origin main
git stash pop
```

---

## 2. Instale o hook anti-recidiva (uma vez por clone)

```bash
cp scripts/hooks/pre-commit-brand.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

Esse hook **bloqueia commits** que tentem recriar a logo via código. Sem ele instalado, o git não roda a checagem (hooks não viajam pelo clone). Cada dev instala uma vez no clone.

**Quer testar?**
```bash
echo 'c.drawString(0, 0, "s")' > test.py
git add test.py && git commit -m "teste"
# → deve bloquear com mensagem clara
git reset HEAD test.py && rm test.py
```

---

## 3. Regra de ouro — Logo é arquivo, nunca código

### ❌ NÃO faça

- `<svg><circle r="50"/><circle r="33"/></svg>` (recria o símbolo "o")
- `<span class="logo">SoLev</span>` + CSS com fonte Sora
- `drawString` reportlab desenhando "s", "o", "l", "ev"
- `Image.open()` de `logo_transparent.png` ou `logo_white_v_colored.png` (**deletadas**)
- `Image.open()` de `solev-wordmark-ink.png` ou `-paper.png` (**renomeadas**)

### ✅ SEMPRE faça

**Em Jinja (recomendado — usa o macro canônico):**
```jinja
{% from '_solev_brand.html' import solev_wordmark, solev_symbol %}

{{ solev_wordmark(size=36) }}                {# fundo claro (navy default) #}
{{ solev_wordmark(size=36, on_dark=True) }}  {# fundo escuro (areia) #}
{{ solev_symbol(size=24) }}                  {# só o "o" navy (sobre claro) #}
{{ solev_symbol(size=24, on_dark=True) }}    {# o "o" areia (sobre escuro) #}
```

**Em HTML direto:**
```html
<img src="/static/logo/solev-wordmark-navy.svg"  alt="SoLev"> {# fundo claro #}
<img src="/static/logo/solev-wordmark-areia.svg" alt="SoLev"> {# fundo escuro #}
```

**Em Python (reportlab — PDFs):**
```python
c.drawImage("static/logo/solev-wordmark-areia.png", x, y,
            width=W, height=H, mask='auto', preserveAspectRatio=True)
```

**Em Python (Pillow — composição):**
```python
logo = Image.open("static/logo/solev-wordmark-navy.png").convert("RGBA")
fundo.paste(logo, (x, y), logo)  # 3o arg = máscara alfa
```

---

## 4. Cores oficiais

| Nome | Hex | Uso |
|---|---|---|
| Noite Solev (navy) | `#0E1B2E` | Texto principal, fundos escuros, anel do "o" |
| Areia Quente | `#F2E8D4` | Fundo claro, paper de documentos, anel "o" sobre escuro |
| **Sol Cerrado (laranja)** | **`#E26A14`** | Acento, destaque, CTAs, miolo do "o" |

⚠️ O laranja **MUDOU em 30/05**: era `#E8732A`, agora é `#E26A14`. Não use o velho.

Os tons derivados continuam pendentes de calibragem pelo designer:
- `--accent-soft: #F5A867` (clareado)
- `--accent-deep: #C25C1C` (escurecido)

---

## 5. Arquivos que JÁ ESTÃO CORRETOS — não precisa mexer

| Caminho | Conteúdo |
|---|---|
| `solev-logo/` | Pasta master do handoff (designer 30/05/2026), commitada no repo |
| `static/logo/*.{png,svg}` | 11 arquivos: wordmark + símbolo + variantes navy/areia |
| `static/icons/*` | 8 arquivos: favicons (16/32/48/svg) + app icons + avatares |
| `static/og_background.png` | OG card horizontal 1200×630 (Twitter/FB) |
| `static/og_square_logo.png` | OG card quadrado 1000×1000 (WhatsApp thumb) |
| `static/site.webmanifest` | PWA: `name: "SoLev Energia"`, ícones em `/static/icons/` |
| `templates/_solev_brand.html` | Macros canônicos `solev_wordmark` e `solev_symbol` |
| `scripts/hooks/pre-commit-brand.sh` | Hook anti-recidiva versionado |

---

## 6. Arquivos DELETADOS — não recrie

### Código removido
- `solev_og_card.py` — módulo de OG dinâmico (substituído por estáticos do handoff)
- `_render_wordmark.py` e `_render_og_square.py` — build scripts não usados mais
- `static/css/solev-brand.css` — CSS obsoleto que era dead code
- 4 rotas em `app.py`: `/c/<token>/og.png`, `/og-square.png`, `/cliente/<id>/cobranca.png` e `-square.png`
- Rota `/logo/<filename>` em `app.py` (servia logos da raiz deletadas)
- Rota `/contrato/assets/<filename>` em `routes/contrato.py`

### Assets removidos
- `static/favicon.ico`, `static/icon-192.png`, `static/icon-512.png` (logos CONTALEV antigas)
- `static/solev-sua-fatura-1200x630.png` (OG card pré-handoff)
- `static/solev.ico` (favicon antigo)
- Na raiz: `LOGO_SOLEV.jpeg`, `logo_blue_v_colored.svg`, `logo_white_v_colored.svg`, `logo_transparent.png`, `logo_white_v_colored.png`, `qr_solev.png`
- Pastas: `design_handoff_solev_{brand,cobranca,og_card,app_cliente,sistema}/`, `logo/`

### Por que? 
Todas substituídas pelos novos do handoff `solev-logo/`. Manter os antigos só confunde quando você for buscar a logo certa.

---

## 7. Docs de referência

| Onde | O quê |
|---|---|
| `static/logo/README.md` | Doc oficial do designer sobre os arquivos da logo |
| `scripts/hooks/pre-commit-brand.sh` | Lista exata dos padrões bloqueados pelo hook |
| `~/.claude/projects/C--Rede-SOLEV/memory/logo_solev_regra_de_ouro.md` | Regra de ouro completa (memória de IA) |
| `~/.claude/projects/C--Rede-SOLEV/memory/session_summary_2026_05_30.md` | Histórico detalhado das mudanças |

---

## 8. TL;DR

1. `git pull origin main`
2. `cp scripts/hooks/pre-commit-brand.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit`
3. Pra logo: use macro `solev_wordmark` / `solev_symbol`, OU `<img src="/static/logo/solev-wordmark-{navy|areia}.svg">`, OU `c.drawImage("static/logo/...png")` no reportlab.
4. Laranja oficial agora é **`#E26A14`** (não use `#E8732A`).
5. Não toque em `solev-logo/`, `static/logo/`, `static/icons/`, `static/og_*.png`, `static/site.webmanifest`, `templates/_solev_brand.html`.

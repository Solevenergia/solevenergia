#!/bin/sh
# scripts/hooks/pre-commit-brand.sh
# ──────────────────────────────────────────────────────────────
# Hook git anti-recidiva: bloqueia reintrodução de logo desenhada em código.
# Regra de ouro: ver memory/logo_solev_regra_de_ouro.md
#
# Instalar no clone atual:
#   cp scripts/hooks/pre-commit-brand.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#
# Cada dev precisa instalar uma vez (hooks não são compartilhados via git).
# ──────────────────────────────────────────────────────────────

FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.(py|html|css|js|jinja)$')
[ -z "$FILES" ] && exit 0

# Cores
RED='\033[0;31m'
YEL='\033[0;33m'
NC='\033[0m'

# Padrões proibidos — recriam o wordmark ou o símbolo.
# Separador: ::: (pra não conflitar com | dentro dos regex)
# Formato: <regex>:::<descrição-humana>
PATTERNS='
drawString[^)]*"(s|o|l|ev)":::drawString reportlab simulando o wordmark
<svg[^>]*viewBox="0 0 100 100":::SVG inline 100x100 (forma do símbolo solev)
<circle[^>]*r="50"[^>]*fill="#(0E1B2E|F2E8D4)":::circle r=50 navy/areia (anel do símbolo)
<circle[^>]*r="33"[^>]*fill="#E:::circle r=33 laranja (miolo do símbolo)
\.solev-wm\b:::classe CSS .solev-wm recriando wordmark via font
class="solev-wm:::elemento HTML class="solev-wm"
Helvetica.*Sora:::comentário "Helvetica como aproximação de Sora"
solev-wordmark-(ink|paper|color|dark|on-paper|rendered):::nome de arquivo antigo do wordmark
solev-symbolo:::nome antigo do símbolo (typo: solev-symbolo)
logo_(blue|white|transparent)_v_colored:::nome antigo de logo na raiz do projeto
LOGO_SOLEV\.jpeg:::arquivo antigo LOGO_SOLEV.jpeg na raiz
'

VIOLATIONS=0
echo "$PATTERNS" | while IFS= read -r line; do
  [ -z "$line" ] && continue
  PAT="${line%%:::*}"
  DESC="${line#*:::}"
  HITS=$(echo "$FILES" | tr ' ' '\n' | xargs grep -lE "$PAT" 2>/dev/null || true)
  if [ -n "$HITS" ]; then
    printf "${RED}X${NC} %s\n" "$DESC"
    for f in $HITS; do
      printf "  ${YEL}%s${NC}\n" "$f"
      grep -nE "$PAT" "$f" 2>/dev/null | sed 's/^/    /' | head -3
    done
    VIOLATIONS=$((VIOLATIONS+1))
    echo
  fi
done

# Como o while está em sub-shell, $VIOLATIONS não propaga. Truque: recontar.
TOTAL=$(echo "$PATTERNS" | while IFS= read -r line; do
  [ -z "$line" ] && continue
  PAT="${line%%:::*}"
  HITS=$(echo "$FILES" | tr ' ' '\n' | xargs grep -lE "$PAT" 2>/dev/null || true)
  [ -n "$HITS" ] && echo "1"
done | wc -l)

if [ "$TOTAL" -gt 0 ]; then
  printf "${RED}=== Commit bloqueado: %d violacao(oes) da regra de ouro da logo ===${NC}\n" "$TOTAL"
  echo
  echo "Logo SoLev e arquivo de imagem, nunca codigo."
  echo "Use:"
  echo "  - Jinja:  {{ solev_wordmark(...) }} ou {{ solev_symbol(...) }}"
  echo "  - HTML:   <img src=\"/static/logo/solev-wordmark-{navy|areia}.{png|svg}\">"
  echo "  - Python: c.drawImage('static/logo/solev-...png', ...) (reportlab)"
  echo
  echo "Veja: memory/logo_solev_regra_de_ouro.md"
  echo
  echo "Pra forcar o commit assim mesmo (desaconselhado): git commit --no-verify"
  exit 1
fi

exit 0

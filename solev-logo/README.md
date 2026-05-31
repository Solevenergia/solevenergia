# solev — Logo (handoff p/ Claude Code)

Arquivos da logomarca **solev** prontos para `static/logo/`. O **master** é vetor de verdade: as letras foram **convertidas em contornos (paths)** a partir da Sora, então **não dependem de nenhuma fonte instalada** — renderizam idênticas no navegador e no servidor (OG images).

## Cores
- Navy: `#0E1B2E`  (letras sobre fundo claro/areia)
- Areia: `#F2E8D4` (letras sobre fundo escuro/navy)
- Laranja (miolo do “o”): `#E26A14`

## Arquivos

### Wordmark — vetor (master)
| Arquivo | Cor | Usar sobre |
|---|---|---|
| `solev-wordmark.svg` | navy | claro / areia · **master** |
| `solev-wordmark-navy.svg` | navy | claro / areia |
| `solev-wordmark-areia.svg` | areia | escuro / navy |

viewBox `0 0 2470 803` (proporção ~3,08:1), fundo transparente.

### Wordmark — PNG transparente (3000px de largura)
| Arquivo | Cor |
|---|---|
| `solev-wordmark.png` | navy (3000×975) |
| `solev-wordmark-navy.png` | navy |
| `solev-wordmark-areia.png` | areia |

### Símbolo isolado (o “o” = anel + miolo laranja)
| Arquivo | Anel | Uso |
|---|---|---|
| `solev-symbol.svg` / `.png` (1024) | navy | sobre claro |
| `solev-symbol-areia.svg` / `.png` (1024) | areia | sobre escuro |
| `favicon.svg` | navy | favicon vetorial |

### Favicon / app / avatar (PNG)
| Arquivo | Formato |
|---|---|
| `favicon-16.png` `favicon-32.png` `favicon-48.png` | símbolo navy, transparente |
| `apple-touch-icon-180.png` | tile navy arredondado + anel areia + miolo laranja |
| `app-icon-1024.png` | tile navy arredondado (App/Play Store) |
| `avatar-1000.png` `avatar-512.png` | círculo navy + anel areia + miolo laranja (WhatsApp/Instagram) |

### OG / social share (prontos)
| Arquivo | Tamanho | Uso |
|---|---|---|
| `og_background.png` | 1200×630 | OG card horizontal (link preview / Twitter/Facebook) |
| `og_square_logo.png` | 1000×1000 | OG quadrado (WhatsApp) |

Ambos: fundo navy `#0E1B2E` com brilho solar + wordmark marfim centralizado.

## Para a integração que você descreveu

1. **`static/logo/`** — substitua os antigos:
   - `solev-wordmark-ink.png`  → use `solev-wordmark-navy.png`
   - `solev-wordmark-paper.png`→ use `solev-wordmark-areia.png`
   - mantenha também os `.svg` como master.
2. **OG cards** — **já gerados**: use `og_background.png` (horizontal 1200×630) e `og_square_logo.png` (quadrado 1000×1000). Se preferir gerar dinamicamente, parta de `solev-wordmark.svg` (vetor, sem fonte).
3. **`og_background.png` (horizontal)** — pronto na pasta (navy + brilho solar + wordmark marfim).
4. **`og_square_logo.png` (WhatsApp)** — pronto na pasta (quadrado, navy + wordmark marfim).
5. **`templates/_solev_brand.html`** — aponte o `<img>`/inline-SVG para os arquivos acima. Para inline crítico, o conteúdo de `solev-wordmark.svg` pode ser colado direto no template (sem dependência de fonte).

## Favicon / head
```html
<link rel="icon" href="/static/logo/favicon.svg" type="image/svg+xml">
<link rel="icon" sizes="32x32" href="/static/logo/favicon-32.png">
<link rel="apple-touch-icon" href="/static/logo/apple-touch-icon-180.png">
```

> Observação: estes arquivos usam navy `#0E1B2E` e areia `#F2E8D4`. Todo o projeto (brand kit incluso) foi unificado neste mesmo navy.

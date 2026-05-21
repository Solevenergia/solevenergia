"""
CONTALEV — Correcoes de Portugues, Estrutura e Layout
========================================================
Revisao profissional do PDF de cobranca (contalev_cobranca_v2_padrao.py)

Aplique cada correcao com Ctrl+H (Localizar e Substituir) no arquivo
contalev_cobranca_v2_padrao.py.
========================================================

═══════════════════════════════════════════════════════
  1. CORRECOES DE PORTUGUES (ortografia e acentuacao)
═══════════════════════════════════════════════════════

BUSCAR → SUBSTITUIR POR:

"FATURA DE ENERGIA"
→ "FATURA DE ENERGIA SOLAR"
  (Mais preciso — diferencia de uma fatura comum de energia)

"Apos o vencimento: multa de 2% + juros de 0,1627% ao dia (valor CONTALEV)."
→ "Apos o vencimento: multa de 2% + juros de 0,1627% ao dia sobre o valor CONTALEV."
  (Acento em "Apos"; preposicao "sobre" para clareza)

"Apos o vencimento: multa de 2% + juros de 5% ao mes (valor CONTALEV)."
→ "Apos o vencimento: multa de 2% + juros de 0,1627% ao dia sobre o valor CONTALEV."
  (Versao antiga — caso ainda exista no codigo)

"Pague ate"
→ "Pague ate"
  (Acento obrigatorio)

"SIMULACAO DE ECONOMIA"
→ "SIMULACAO DE ECONOMIA"
  (Cedilha e til — usar codificacao UTF-8)

"SIMULACAO PARA"
→ "SIMULACAO PARA"

"ILUMINACAO PUBLICA"
→ "ILUMINACAO PUBLICA"

"Iluminacao Publica"
→ "Iluminacao Publica"

"Iluminacao Publica:"
→ "Iluminacao Publica:"

"Ilum. Publica:"
→ "Ilum. Publica:"

"INFORMACOES DO CLIENTE"
→ "INFORMACOES DO CLIENTE"

"Informacoes"
→ "Informacoes"

"CODIGO DE BARRAS EM DESENVOLVIMENTO"
→ "CODIGO DE BARRAS EM DESENVOLVIMENTO"

"CODIGO DE BARRA EM DESENVOLVIMENTO"
→ "CODIGO DE BARRAS EM DESENVOLVIMENTO"
  (Plural: "barras", nao "barra")

"Endereco:"
→ "Endereco:"

"Referencia:"
→ "Referencia:"

"Projecao anual estimada:"
→ "Projecao anual estimada:"

"PROJECAO DE ECONOMIA ANUAL"
→ "PROJECAO DE ECONOMIA ANUAL"

"Nao Comp.:"
→ "Nao Comp.:"

"Leit. Ant.:"
→ "Leit. Anterior:"

"Prox. Leit.:"
→ "Prox. Leitura:"

"Economia mensal"
→ "Economia Mensal"

"economia acumulada"
→ "Economia Acumulada"

"Escaneie para pagar"
→ "Leia o QR Code para pagar"
  (Mais claro para o publico geral)


═══════════════════════════════════════════════════════
  2. CORRECOES DE TEXTO DE MARKETING (chamada para acao)
═══════════════════════════════════════════════════════

BUSCAR (frase de fechamento na simulacao):

"Cada dia que voce espera e dinheiro que deixa na mesa. "
"Sem investimento, sem fidelidade e com economia ja na proxima fatura "
"— vamos comecar agora?"

SUBSTITUIR POR:

"Cada dia que voce espera e dinheiro que deixa na mesa. "
"Sem investimento, sem fidelidade e com economia a partir da proxima fatura "
"— vamos comecar agora?"
  (Correcao: "a partir da" em vez de "ja na" — mais preciso formalmente)


═══════════════════════════════════════════════════════
  3. TEXTO DO RODAPE (padronizar nas duas paginas)
═══════════════════════════════════════════════════════

Rodape pagina 1 (cobranca):
  "Apos o vencimento: multa de 2% + juros de 0,1627% ao dia sobre o valor CONTALEV."

Rodape pagina 2 (Equatorial):
  "Documento de conferencia — Fatura original da distribuidora Equatorial."

Rodape da simulacao:
  "Simulacao ilustrativa. Valores sujeitos a variacao conforme consumo e tarifas vigentes."
  → "Simulacao ilustrativa. Valores sujeitos a variacao conforme consumo e tarifas vigentes."
  (Crase obrigatoria: "sujeitos a variacao")


═══════════════════════════════════════════════════════
  4. CAIXA "IMPORTANTE" — Melhorar redacao
═══════════════════════════════════════════════════════

BUSCAR:
"IMPORTANTE:  {d['desconto_pct']}% de desconto sobre a tarifa Equatorial GO. "
"Pague ate {d['vencimento_solev']}."

SUBSTITUIR POR:
"IMPORTANTE: Desconto de {d['desconto_pct']}% aplicado sobre a tarifa da "
"distribuidora Equatorial GO. Vencimento: {d['vencimento_solev']}."
  (Frase mais clara; "Vencimento:" em vez de "Pague ate" — tom profissional)


═══════════════════════════════════════════════════════
  5. LAYOUT E ESPACAMENTO — Sugestoes
═══════════════════════════════════════════════════════

5a. CABECALHO
    - Manter "FATURA DE ENERGIA SOLAR" com fonte 14pt bold
    - Mes/Ano na faixa laranja: manter centralizado
    - Espacamento entre header e bloco de cliente: +2mm

5b. BLOCO DE DADOS DO CLIENTE
    - Labels em Helvetica-Bold 6.5pt → OK
    - Valores em Helvetica 6.5pt → OK
    - Espacamento entre linhas (line_h): manter 4.5mm
    - Separadores verticais: manter 0.2pt cinza claro

5c. COLUNAS SEM/COM CONTALEV
    - Garantir alinhamento vertical simetrico entre as duas colunas
    - Se uma coluna tem mais itens que a outra, o espacamento
      deve ser igual (nao deixar uma "mais curta" que a outra)
    - Linha separadora "Itens financeiros": manter em cinza medio

5d. BARRAS COMPARATIVAS
    - Barra "SEM CONTALEV" (cinza azulado): largura total
    - Barra "COM CONTALEV" (azul escuro): largura proporcional
    - Manter minimo de 200pt para legibilidade

5e. CAIXA DE VENCIMENTO
    - Fundo laranja com texto azul escuro
    - Manter destaque visual — e o CTA principal

5f. BLOCO DE BOLETO/PIX
    - Codigo de barras: fonte Helvetica 9pt, centralizado
    - Linha digitavel: fonte Helvetica 7pt, abaixo do codigo
    - QR Code PIX: 55×55pt, a direita do codigo de barras
    - Label "PIX" em Helvetica-Bold 9pt acima do QR Code

5g. RODAPE
    - Fundo azul escuro, altura 35pt
    - Logo branca a esquerda
    - Texto de multa/juros a direita, Helvetica 5.5pt cinza claro
    - "CONTALEV © 2026" abaixo — Helvetica 4.5pt


═══════════════════════════════════════════════════════
  6. SIMETRIA E ALINHAMENTO — Checklist
═══════════════════════════════════════════════════════

✓ Margens: 30pt esquerda e direita (MARGIN_LEFT, MARGIN_RIGHT)
✓ Espacamento uniforme entre secoes: 10-15pt
✓ Fontes padronizadas:
    - Titulos de secao: Helvetica-Bold 9pt
    - Labels: Helvetica-Bold 7-8pt
    - Valores: Helvetica 7-8pt
    - Destaques (totais): Helvetica-Bold 14pt
    - Notas/disclaimers: Helvetica 5.5-6pt
✓ Cores padronizadas:
    - Azul escuro (#1a2a4a): headers, titulos, barra COM
    - Laranja (#f5a623): destaques, vencimento, CTA
    - Cinza azulado (#455a64): barra SEM
    - Verde (#2e7d32): economia
    - Cinza claro (#f4f4f4): fundos de blocos
✓ Cantos arredondados: 3-6pt (roundRect)
✓ Alinhamento justificado nos textos longos


═══════════════════════════════════════════════════════
  7. APLICACAO RAPIDA NO CODIGO
═══════════════════════════════════════════════════════

No contalev_cobranca_v2_padrao.py, as strings com acentos
podem precisar de tratamento especial se a fonte Helvetica
nao suportar. Nesse caso, use:

  from reportlab.pdfbase import pdfmetrics
  from reportlab.pdfbase.ttfonts import TTFont
  # Registrar DejaVuSans (suporta UTF-8 completo)
  pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))

Porem, se voce ja usa Bahnschrift para o nome do cliente,
Helvetica padrao do ReportLab JA suporta os acentos do
portugues (a, e, i, o, u, a, o, c, a, e, o). Entao basta
colocar os acentos diretamente nas strings Python.

TESTE: apos aplicar, gere um PDF e verifique se os acentos
aparecem corretamente em todos os campos.
"""

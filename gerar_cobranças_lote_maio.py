"""
gerar_cobranças_lote_maio.py
Gera cobranças SOLEV para os 21 PDFs Equatorial já baixados do lote de maio.
Executa direto: python gerar_cobranças_lote_maio.py
"""
import os, sys
sys.path.insert(0, r"C:\Rede\SOLEV")
sys.path.insert(0, r"C:\Rede\SOLEV\scripts")

# UCs que foram baixadas com sucesso no lote de maio
UCS_BAIXADAS = [
    ("000247090901292", "DILSON DA SILVA BORGES"),
    ("000261387501288", "DILSON DA SILVA BORGES"),
    ("000343711301208", "EDJANE APARECIDA PEREIRA"),
    ("000248906401207", "EDUARDO SANDOVAL JAMALLUDDIN"),
    ("000043522501209", "MARIA DE FATIMA CARVALHO"),
    ("000007288001222", "FRANCISCO RENALISSOM FLORENCIO ARIAIS"),
    ("000393129601256", "GABRIELA SILVA"),
    ("000064212501292", "GOFRIO INTALACOES COMERCIAIS"),
    ("000443222401274", "JACIELE APARECIDA BERCHIOR"),
    ("000003285301230", "JOAO BATISTA DE REZENDE"),
    ("000330188601277", "JULIANA DI PAULA OLIVEIRA"),
    ("000400238501287", "JULIANA DI PAULA OLIVEIRA"),
    ("000330189001206", "JULIANA DI PAULA OLIVEIRA"),
    ("000330189301282", "JULIANA DI PAULA OLIVEIRA"),
    ("000330189601259", "JULIANA DI PAULA OLIVEIRA"),
    ("000012628001214", "JULIANA ROSA DE SOUZA RIBEIRO"),
    ("000015150401296", "KRYSHYNA DE OLIVEIRA BARCELOS"),
    ("000030276201227", "LUCAS PAULINELLI FERNANDES"),
    ("000282470001290", "MARCOS FERNANDES BORGES"),
    ("000306671801213", "MAURO CESAR SAHB"),
    ("000423593901210", "MURILO ALVES DOS SANTOS"),
]

MES_REF  = "05/2026"
MES_STR  = "202605"
NOME_USINA = "USDaniloEvangelista70"
BASE_PASTA = r"C:\Users\danil\OneDrive\Desktop\Usinas"

def _camel_case(nome: str) -> str:
    import unicodedata, re
    s = unicodedata.normalize("NFD", nome)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    partes = re.sub(r"[^a-zA-Z0-9 ]", "", s).split()
    return "".join(p.capitalize() for p in partes)

def _primeiro_ultimo(nome: str) -> str:
    partes = nome.strip().split()
    if len(partes) <= 1:
        return nome
    return f"{partes[0]} {partes[-1]}"

def encontrar_pdf_equatorial(uc: str, nome: str) -> str | None:
    """Procura o PDF Equatorial 202605 na pasta do cliente."""
    nome_camel = _camel_case(_primeiro_ultimo(nome))
    pasta_usina = os.path.join(BASE_PASTA, NOME_USINA)
    if not os.path.exists(pasta_usina):
        return None
    for pasta_cliente in os.listdir(pasta_usina):
        # Tenta por nome do cliente
        if nome_camel.lower() in pasta_cliente.lower():
            pasta_path = os.path.join(pasta_usina, pasta_cliente)
            for arq in os.listdir(pasta_path):
                if arq.startswith(MES_STR) and "Equatorial" in arq and arq.endswith(".pdf"):
                    return os.path.join(pasta_path, arq)
    # Tenta por UC (sem zeros à esquerda no nome da pasta)
    uc_sem_zeros = uc.lstrip("0")
    for pasta_cliente in os.listdir(pasta_usina):
        if uc_sem_zeros in pasta_cliente or uc in pasta_cliente:
            pasta_path = os.path.join(pasta_usina, pasta_cliente)
            for arq in os.listdir(pasta_path):
                if arq.startswith(MES_STR) and "Equatorial" in arq and arq.endswith(".pdf"):
                    return os.path.join(pasta_path, arq)
    return None

def main():
    from baixar_equatorial import gerar_cobranca_cliente

    print(f"\n{'='*60}")
    print(f"  Geração retroativa de cobranças — {MES_REF}")
    print(f"  {len(UCS_BAIXADAS)} UCs")
    print(f"{'='*60}\n")

    ok = 0
    falha = 0
    nao_encontrado = 0

    for uc, nome in UCS_BAIXADAS:
        print(f"\n--- {nome} | UC {uc} ---")

        pdf = encontrar_pdf_equatorial(uc, nome)
        if not pdf:
            print(f"  ⚠️  PDF Equatorial não encontrado na pasta — pulando")
            nao_encontrado += 1
            continue

        print(f"  📄 PDF: {os.path.basename(pdf)}")
        pasta_cli = os.path.dirname(pdf)
        nome_camel = _camel_case(_primeiro_ultimo(nome))

        # Verifica se cobrança já existe
        cob_esperada = os.path.join(pasta_cli, f"{MES_STR}-SoLev{nome_camel}.pdf")
        if os.path.exists(cob_esperada):
            print(f"  ⏭️  Cobrança já existe: {os.path.basename(cob_esperada)}")
            ok += 1
            continue

        resultado = gerar_cobranca_cliente(pdf, pasta_cli, MES_STR, nome_camel, uc)
        if resultado:
            ok += 1
        else:
            # Tenta encontrar o arquivo gerado com nome alternativo
            for arq in os.listdir(pasta_cli):
                if arq.startswith(MES_STR) and "SoLev" in arq:
                    print(f"  ✅ Cobrança encontrada: {arq}")
                    ok += 1
                    resultado = True
                    break
            if not resultado:
                falha += 1

    print(f"\n{'='*60}")
    print(f"  ✅ Geradas (ou já existiam): {ok}")
    print(f"  ⚠️  PDF não encontrado:      {nao_encontrado}")
    print(f"  ❌ Falhas na geração:        {falha}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()

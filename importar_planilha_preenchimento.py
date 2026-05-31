"""
importar_planilha_preenchimento.py
Importa dados preenchidos na planilha SOLEV_Preenchimento.xlsx para o Supabase.

Atualiza:
  tb_clientes  → qtd_consumo_medio_kwh, qtd_saldo_inicial_kwh, proxima_leitura
  tb_usinas    → qtd_dia_leitura, dt_proxima_leitura, qtd_geracao_media_mensal,
                 desc_pix_recebimento

Execute: python importar_planilha_preenchimento.py
"""
import sys, re, io
from datetime import datetime, date
sys.path.insert(0, r"C:\Rede\SOLEV")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pandas as pd
from db import _db

PLANILHA = r"C:\Rede\SOLEV\SOLEV_Preenchimento.xlsx"

# ─── UTILITÁRIOS ──────────────────────────────────────────────────────────────

def _float(val) -> float | None:
    """Converte string ou número para float, aceitando vírgula como decimal."""
    if val is None or (isinstance(val, float) and str(val) == "nan"):
        return None
    s = str(val).strip().replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _data_iso(val, dia_habitual: int | None = None) -> str | None:
    """
    Converte vários formatos de data para ISO (YYYY-MM-DD).
    Detecta e corrige troca de dia/mês quando Dia Habitual é fornecido.

    Formatos suportados:
      • datetime / date objects
      • "YYYY-MM-DD HH:MM:SS"  (pandas datetime)
      • "DD/MM/YYYY"
      • "DD/MMYYYY"  (barra faltando, ex: 16/062026)
    """
    if val is None or (isinstance(val, float) and str(val) == "nan"):
        return None
    if isinstance(val, (datetime, date)):
        d = val if isinstance(val, date) else val.date()
    else:
        s = str(val).strip()
        # Remove hora se presente
        s = s.split(" ")[0]

        # Tenta detectar formato
        # YYYY-MM-DD
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
        if m:
            try:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
        # DD/MM/YYYY ou DD/MMYYYY (barra faltando)
        elif "/" in s:
            partes = s.split("/")
            if len(partes) == 2:
                # Provavelmente "DD/MMYYYY"
                p0 = partes[0].strip()
                p1 = partes[1].strip()
                if len(p1) == 6:  # ex: "062026"
                    mm, aa = p1[:2], p1[2:]
                    try:
                        d = date(int(aa), int(mm), int(p0))
                    except ValueError:
                        return None
                else:
                    return None
            elif len(partes) == 3:
                dd, mm, aa = partes
                try:
                    d = date(int(aa), int(mm), int(dd))
                except ValueError:
                    return None
            else:
                return None
        else:
            return None

    # Corrige troca de dia/mês: se o dia não bate com Dia Habitual mas o mês bate, troca
    if dia_habitual and 1 <= dia_habitual <= 31:
        if d.day != dia_habitual and d.month == dia_habitual:
            try:
                d_corrigida = date(d.year, d.day, d.month)
                d = d_corrigida
            except ValueError:
                pass  # troca inválida, mantém original

    return d.isoformat()


# ─── IMPORTAR CLIENTES ────────────────────────────────────────────────────────

def importar_clientes():
    df = pd.read_excel(PLANILHA, sheet_name="Clientes", header=None, dtype=str)

    # Linha 1 (índice 1) tem os cabeçalhos reais; dados começam no índice 3
    colunas = list(df.iloc[1])
    # colunas[0]=ID, [1]=Nome, [2]=UC, [3]=Consumo Médio, [4]=Saldo Atual,
    # [5]=Próxima Leitura, [6]=Dia Habitual

    dados = df.iloc[3:].reset_index(drop=True)
    dados.columns = range(len(dados.columns))

    ok = erros = pulados = 0
    alteracoes = []

    for _, row in dados.iterrows():
        id_val = str(row[0]).strip() if not pd.isna(row[0]) else ""
        if not id_val or id_val == "nan":
            continue
        try:
            id_cliente = int(float(id_val))
        except ValueError:
            continue

        consumo   = _float(row[3]) if len(row) > 3 else None
        saldo     = _float(row[4]) if len(row) > 4 else None
        prox_raw  = row[5] if len(row) > 5 else None
        dia_hab_raw = row[6] if len(row) > 6 else None
        dia_hab   = int(float(str(dia_hab_raw))) if dia_hab_raw and str(dia_hab_raw) != "nan" else None
        nome      = str(row[1]).strip() if not pd.isna(row[1]) else "?"

        proxima = _data_iso(prox_raw, dia_hab) if prox_raw and str(prox_raw) != "nan" else None

        patch = {}
        if consumo is not None:
            patch["qtd_consumo_medio_kwh"] = round(consumo, 2)
        if saldo is not None:
            patch["qtd_saldo_inicial_kwh"] = round(saldo, 2)
        if proxima:
            patch["proxima_leitura"] = proxima

        if not patch:
            pulados += 1
            continue

        try:
            _db().patch("tb_clientes", {"id_cliente": id_cliente}, patch)
            alteracoes.append(f"  ✅ [{id_cliente:>3}] {nome[:40]:<40} consumo={patch.get('qtd_consumo_medio_kwh','—'):>8}  saldo={patch.get('qtd_saldo_inicial_kwh','—'):>10}  prox={patch.get('proxima_leitura','—')}")
            ok += 1
        except Exception as e:
            print(f"  ❌ [{id_cliente}] {nome}: {e}")
            erros += 1

    print(f"\n{'─'*60}")
    print(f"  CLIENTES")
    print(f"{'─'*60}")
    for linha in alteracoes:
        print(linha)
    print(f"{'─'*60}")
    print(f"  ✅ Atualizados: {ok}  |  ⏭️  Sem dados novos: {pulados}  |  ❌ Erros: {erros}")
    return ok, erros


# ─── IMPORTAR USINAS ──────────────────────────────────────────────────────────

def importar_usinas():
    df = pd.read_excel(PLANILHA, sheet_name="Usinas", header=None, dtype=str)

    # Linha 1 (índice 1) tem cabeçalhos; dados a partir do índice 3
    dados = df.iloc[3:].reset_index(drop=True)
    dados.columns = range(len(dados.columns))

    # cols: [0]=ID, [1]=Nome, [2]=UC, [3]=Potência, [4]=Dia Leitura,
    #       [5]=Próxima Leitura, [6]=Geração Média, [7]=PIX Recebimento

    ok = erros = pulados = 0
    alteracoes = []

    for _, row in dados.iterrows():
        id_val = str(row[0]).strip() if not pd.isna(row[0]) else ""
        if not id_val or id_val == "nan":
            continue
        try:
            id_usina = int(float(id_val))
        except ValueError:
            continue

        nome     = str(row[1]).strip() if len(row) > 1 and not pd.isna(row[1]) else "?"
        dia_raw  = row[4] if len(row) > 4 else None
        prox_raw = row[5] if len(row) > 5 else None
        ger_raw  = row[6] if len(row) > 6 else None
        pix_raw  = row[7] if len(row) > 7 else None

        dia_leitura = int(float(str(dia_raw))) if dia_raw and str(dia_raw) != "nan" else None
        geracao     = _float(ger_raw)
        pix         = str(pix_raw).strip() if pix_raw and str(pix_raw) not in ("nan", "None", "") else None
        proxima     = _data_iso(prox_raw, dia_leitura) if prox_raw and str(prox_raw) != "nan" else None

        patch = {}
        if dia_leitura:
            patch["qtd_dia_leitura"] = dia_leitura
        if proxima:
            patch["dt_proxima_leitura"] = proxima
        if geracao is not None:
            patch["qtd_geracao_media_mensal"] = round(geracao, 2)
        if pix:
            patch["desc_pix_recebimento"] = pix

        if not patch:
            pulados += 1
            continue

        try:
            _db().patch("tb_usinas", {"id_usina": id_usina}, patch)
            alteracoes.append(
                f"  ✅ [{id_usina:>2}] {nome[:30]:<30} dia={patch.get('qtd_dia_leitura','—'):>2}  "
                f"ger={patch.get('qtd_geracao_media_mensal','—'):>6} kWh  "
                f"prox={patch.get('dt_proxima_leitura','—')}  "
                f"pix={'✓' if pix else '—'}"
            )
            ok += 1
        except Exception as e:
            print(f"  ❌ [{id_usina}] {nome}: {e}")
            erros += 1

    print(f"\n{'─'*60}")
    print(f"  USINAS")
    print(f"{'─'*60}")
    for linha in alteracoes:
        print(linha)
    print(f"{'─'*60}")
    print(f"  ✅ Atualizadas: {ok}  |  ⏭️  Sem dados novos: {pulados}  |  ❌ Erros: {erros}")
    return ok, erros


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"  Importação — SOLEV_Preenchimento.xlsx")
    print(f"{'='*60}")

    ok_c, err_c = importar_clientes()
    ok_u, err_u = importar_usinas()

    print(f"\n{'='*60}")
    print(f"  RESUMO FINAL")
    print(f"  Clientes: {ok_c} atualizados, {err_c} erros")
    print(f"  Usinas:   {ok_u} atualizadas, {err_u} erros")
    print(f"{'='*60}\n")

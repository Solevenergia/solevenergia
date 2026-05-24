"""
SoLev - Camada de acesso ao banco de dados (Supabase/PostgreSQL)
# versao: 2026-05-03
=====================================================================
Substitui o armazenamento em JSON local por chamadas diretas ao Supabase
via REST API (PostgREST).

Uso tipico:
    from db import carregar_clientes, salvar_clientes, get_cliente, save_cliente

Mantem a mesma assinatura das antigas funcoes baseadas em JSON para
facilitar a migracao.
"""
import json
import os
import sys
from typing import Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
SUPABASE_CONFIG_JSON = os.path.join(_DIR, "supabase_config.json")


# ==================================================================
#  Cliente HTTP para Supabase (PostgREST)
# ==================================================================
class _SupabaseDB:
    """Cliente singleton para o Supabase via REST API."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            inst = super().__new__(cls)
            inst.client = None
            try:
                inst._init_client()
                cls._instance = inst
            except Exception as e:
                raise RuntimeError(f"Falha ao inicializar Supabase: {e}")
        return cls._instance

    def _init_client(self):
        cfg = self._carregar_config()
        url = cfg.get("url", "").rstrip("/")
        key = cfg.get("service_role_key", "") or cfg.get("anon_key", "")
        if not url or not key:
            raise RuntimeError(
                "Supabase nao configurado. Edite supabase_config.json com URL e chaves."
            )
        try:
            import httpx
        except ImportError:
            raise RuntimeError("httpx nao instalado. Execute: pip install httpx")

        self.base = f"{url}/rest/v1"
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        self.client = httpx.Client(headers=self.headers, timeout=30.0)
        self._httpx = httpx  # guarda ref para uso em _retry

    def _retry(self, fn, *, tries=3, delay=0.6):
        """Executa fn() com retry em erros transitorios de rede (timeout, connect)."""
        import time as _t
        last = None
        for i in range(tries):
            try:
                return fn()
            except (self._httpx.TimeoutException,
                    self._httpx.ConnectError,
                    self._httpx.RemoteProtocolError) as e:
                last = e
                if i < tries - 1:
                    _t.sleep(delay * (2 ** i))  # 0.6, 1.2, 2.4
        raise last

    @staticmethod
    def _carregar_config():
        # PRIORIDADE 1: Variáveis de ambiente (produção — Railway, etc.)
        env_url      = os.environ.get("SUPABASE_URL", "").strip()
        env_anon     = os.environ.get("SUPABASE_ANON_KEY", "").strip()
        env_service  = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
        if env_url and (env_anon or env_service):
            return {
                "url": env_url,
                "anon_key": env_anon,
                "service_role_key": env_service,
            }
        # PRIORIDADE 2: Arquivo JSON local (dev — PC do operador)
        if os.path.exists(SUPABASE_CONFIG_JSON):
            with open(SUPABASE_CONFIG_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        raise RuntimeError(
            "Supabase nao configurado.\n"
            "  - Produção: defina env vars SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY\n"
            "  - Local: crie o arquivo supabase_config.json"
        )

    # -- Operacoes basicas --------------------------------------
    def select(self, table, columns="*", filtros=None, order=None, raw_params=None):
        """SELECT FROM table [WHERE ...] [ORDER BY ...]
        raw_params aceita operadores PostgREST diretos, ex: {"dt_fim": "is.null"}
        """
        params = {"select": columns}
        if order:
            params["order"] = order
        if filtros:
            for k, v in filtros.items():
                params[k] = f"eq.{v}"
        if raw_params:
            params.update(raw_params)
        headers = {**self.headers, "Range": "0-999999"}
        resp = self._retry(lambda: self.client.get(
            f"{self.base}/{table}", params=params, headers=headers
        ))
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Extrai nome da coluna de um erro PGRST204 do Supabase.
    # Retorna None se nao for esse tipo de erro.
    # ------------------------------------------------------------------
    @staticmethod
    def _coluna_inexistente(resp) -> "str | None":
        import re
        if resp.status_code != 400:
            return None
        try:
            err = resp.json()
        except Exception:
            return None
        if err.get("code") != "PGRST204":
            return None
        # Mensagem: "Could not find the 'col' column of 'table' in the schema cache"
        m = re.search(r"'(\w+)' column", err.get("message", ""))
        return m.group(1) if m else "__unknown__"

    def patch(self, table, filtros, dados, _removidas=None):
        """PATCH (atualizacao parcial). Remove colunas inexistentes automaticamente."""
        params = {k: f"eq.{v}" for k, v in filtros.items()}
        headers = {**self.headers, "Prefer": "return=minimal"}
        resp = self._retry(lambda: self.client.patch(
            f"{self.base}/{table}", params=params, json=dados, headers=headers
        ))
        if resp.status_code >= 400:
            col = self._coluna_inexistente(resp)
            if col:
                removidas = (_removidas or set()) | {col}
                dados2 = {k: v for k, v in dados.items() if k != col}
                print(f"[DB] ⚠️  Coluna '{col}' nao existe em '{table}' — execute a migration SQL. Campo ignorado.")
                if dados2:
                    return self.patch(table, filtros, dados2, removidas)
                return
            raise Exception(f"Erro patch {table}: {resp.status_code} -- {resp.text[:300]}")

    def upsert_returning(self, table, row, on_conflict=None, _removidas=None):
        """INSERT/UPDATE retornando o registro. Remove colunas inexistentes automaticamente."""
        headers = {
            **self.headers,
            "Prefer": "resolution=merge-duplicates,return=representation",
        }
        url = f"{self.base}/{table}"
        if on_conflict:
            url += f"?on_conflict={on_conflict}"
        resp = self._retry(lambda: self.client.post(url, json=[row], headers=headers))
        if resp.status_code >= 400:
            col = self._coluna_inexistente(resp)
            if col:
                removidas = (_removidas or set()) | {col}
                row2 = {k: v for k, v in row.items() if k != col}
                print(f"[DB] ⚠️  Coluna '{col}' nao existe em '{table}' — execute a migration SQL. Campo ignorado.")
                return self.upsert_returning(table, row2, on_conflict, removidas)
            raise Exception(f"Erro upsert {table}: {resp.status_code} -- {resp.text[:300]}")
        data = resp.json()
        return data[0] if data else {}

    def upsert(self, table, row_ou_rows, on_conflict=None, _removidas=None):
        """INSERT ... ON CONFLICT DO UPDATE. Remove colunas inexistentes automaticamente."""
        rows = row_ou_rows if isinstance(row_ou_rows, list) else [row_ou_rows]
        if not rows:
            return
        # Normaliza: todos os rows devem ter as mesmas chaves
        all_keys = set()
        for r in rows:
            all_keys.update(r.keys())
        for r in rows:
            for k in all_keys:
                if k not in r:
                    r[k] = None
        headers = {
            **self.headers,
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
        url = f"{self.base}/{table}"
        if on_conflict:
            url += f"?on_conflict={on_conflict}"
        # Envia em lotes de 500
        for i in range(0, len(rows), 500):
            lote = rows[i:i+500]
            resp = self._retry(lambda: self.client.post(url, json=lote, headers=headers))
            if resp.status_code >= 400:
                col = self._coluna_inexistente(resp)
                if col:
                    removidas = (_removidas or set()) | {col}
                    print(f"[DB] ⚠️  Coluna '{col}' nao existe em '{table}' — execute a migration SQL. Campo ignorado.")
                    rows2 = [{k: v for k, v in r.items() if k != col} for r in rows]
                    return self.upsert(table, rows2, on_conflict, removidas)
                raise Exception(
                    f"Erro upsert {table}: {resp.status_code} -- {resp.text[:300]}"
                )

    def delete(self, table, filtros):
        """DELETE FROM table WHERE ..."""
        params = {k: f"eq.{v}" for k, v in filtros.items()}
        resp = self._retry(lambda: self.client.delete(f"{self.base}/{table}", params=params))
        if resp.status_code >= 400:
            raise Exception(f"Erro delete {table}: {resp.status_code} -- {resp.text[:300]}")


# ==================================================================
#  Conexao global (lazy)
# ==================================================================
_db_instance: Optional[_SupabaseDB] = None

def _db() -> _SupabaseDB:
    global _db_instance
    if _db_instance is None or _db_instance.client is None:
        _SupabaseDB._instance = None  # forca reinicializacao
        _db_instance = _SupabaseDB()
    return _db_instance


def is_configured() -> bool:
    """Verifica se o Supabase esta configurado corretamente."""
    try:
        if not os.path.exists(SUPABASE_CONFIG_JSON):
            return False
        with open(SUPABASE_CONFIG_JSON, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        url = cfg.get("url", "")
        key = cfg.get("service_role_key", "") or cfg.get("anon_key", "")
        if not url or not key:
            return False
        if "SEU-PROJETO" in url or "COLE_AQUI" in key:
            return False
        return bool(cfg.get("ativo", False))
    except Exception:
        return False


# ==================================================================
#  SUPABASE STORAGE
# ==================================================================

def _storage_cfg() -> tuple[str, str]:
    """Retorna (supabase_url, service_key) do config."""
    cfg = _SupabaseDB._carregar_config()
    url = cfg.get("url", "").rstrip("/")
    key = cfg.get("service_role_key", "") or cfg.get("anon_key", "")
    return url, key


def storage_ensure_bucket(bucket: str = "faturas") -> None:
    """Cria o bucket no Supabase Storage se ainda nao existir. Seguro chamar multiplas vezes."""
    import httpx
    url, key = _storage_cfg()
    base = f"{url}/storage/v1"
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    resp = httpx.get(f"{base}/bucket/{bucket}", headers=headers, timeout=10)
    if resp.status_code == 200:
        return  # ja existe
    resp2 = httpx.post(
        f"{base}/bucket",
        json={"id": bucket, "name": bucket, "public": False},
        headers=headers,
        timeout=10,
    )
    if resp2.status_code >= 400 and "already exists" not in resp2.text.lower():
        raise Exception(f"Erro ao criar bucket '{bucket}': {resp2.status_code} {resp2.text[:200]}")


def _sanitizar_storage_key(nome: str) -> str:
    """
    Remove acentos, cedilha e outros diacriticos do nome do arquivo.
    Supabase Storage rejeita chaves com caracteres nao-ASCII.
    Ex: '202604-ContalevYanGuimaraes.pdf' -> '202604-ContalevYanGuimaraes.pdf'
    """
    import unicodedata
    # Decompoe cada caractere em base + diacritico, depois descarta os diacriticos (Mn)
    normalizado = unicodedata.normalize("NFKD", nome)
    return "".join(c for c in normalizado if not unicodedata.category(c).startswith("M"))


def storage_upload_pdf(pdf_local_path: str, storage_filename: str, bucket: str = "faturas") -> str:
    """
    Faz upload de um PDF local para o Supabase Storage.
    Retorna o storage path no formato '{bucket}/{storage_filename_sanitizado}'.

    storage_filename: nome do arquivo (acentos sao removidos automaticamente).
    """
    import httpx
    # Supabase Storage rejeita chaves com acentos — sanitiza antes de enviar
    storage_filename = _sanitizar_storage_key(storage_filename)
    url, key = _storage_cfg()
    base = f"{url}/storage/v1"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/pdf",
        "x-upsert": "true",  # sobrescreve se ja existir
    }
    with open(pdf_local_path, "rb") as f:
        data = f.read()
    resp = httpx.put(
        f"{base}/object/{bucket}/{storage_filename}",
        content=data,
        headers=headers,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise Exception(
            f"Erro ao fazer upload '{storage_filename}': {resp.status_code} {resp.text[:300]}"
        )
    return f"{bucket}/{storage_filename}"


def storage_signed_url(storage_path: str, expires_in: int = 3600) -> str:
    """
    Gera URL temporaria (assinada) para download de arquivo privado no Storage.
    storage_path: valor retornado por storage_upload_pdf (ex: 'faturas/arquivo.pdf').
    expires_in: segundos ate expirar (padrao: 1 hora).
    """
    import httpx
    url, key = _storage_cfg()
    base = f"{url}/storage/v1"
    # Separa bucket e caminho do arquivo
    parts = storage_path.split("/", 1)
    bucket = parts[0]
    file_path = parts[1] if len(parts) > 1 else storage_path
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    resp = httpx.post(
        f"{base}/object/sign/{bucket}/{file_path}",
        json={"expiresIn": expires_in},
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    signed = resp.json().get("signedURL", "")
    if signed.startswith("http"):
        return signed
    # Supabase retorna caminho relativo "/object/sign/..." sem o prefixo "/storage/v1"
    return f"{url}/storage/v1{signed}"


# ==================================================================
#  CLIENTES
# ==================================================================
# Colunas da tabela `clientes` no Supabase
_COLS_CLIENTE = [
    "uc", "nome", "cpf", "cod_uc", "telefone", "email",
    "endereco", "endereco_linha1", "endereco_linha2", "endereco_linha3",
    "titular_fatura", "desconto_pct", "data_adesao",
    "valor_cobranca_anterior", "venc_solev_anterior", "data_pagamento_anterior",
    "economia_acumulada_anterior", "codigo_barras", "linha_digitavel",
    "pix_payload", "usina_id", "rateio_pct", "saldo_kwh", "apelido",
    "tipo_fornecimento", "proxima_leitura", "modo_bandeira", "kwh_creditado_real",
]


def _limpar_nulos(row: dict) -> dict:
    """Remove chaves com valor None para evitar sobrescrever defaults."""
    return {k: v for k, v in row.items() if v is not None}


def carregar_clientes() -> dict:
    """Retorna {uc: dados_do_cliente} lidos de tb_clientes (tabela normalizada).

    Faz join em memoria com tb_enderecos.
    Mantem a mesma assinatura que o resto do codigo espera: {uc: dados}.
    Cada entrada inclui '_fonte': 'tb_clientes' e '_id_cliente': id_cliente.
    """
    import re as _re
    try:
        rows = _db().select("tb_clientes", order="desc_nome.asc")
        enderecos = tb_carregar_todos_enderecos()  # {id_cliente: endereco_dict}
        out = {}
        for row in rows:
            uc = row.get("cod_uc")
            if not uc:
                continue
            id_c = row.get("id_cliente")
            end = enderecos.get(id_c, {})

            # Monta string de endereco compativel com o formato legado
            _cep_d = _re.sub(r'\D', '', str(end.get("cod_cep") or ""))
            _cep_fmt = f"{_cep_d[:2]}.{_cep_d[2:5]}-{_cep_d[5:]}" if len(_cep_d) == 8 else ""
            _cid = end.get("desc_cidade", ""); _est = end.get("desc_estado", "")
            end_str = ", ".join(p for p in [
                end.get("desc_logradouro", ""), end.get("desc_numero", ""),
                end.get("desc_complemento", ""), end.get("desc_setor", ""),
                f"CEP {_cep_fmt}" if _cep_fmt else "",
                f"{_cid}/{_est}" if _cid and _est else _cid,
            ] if p)

            out[str(uc)] = {
                "nome":                        row.get("desc_nome", ""),
                "apelido":                     row.get("desc_apelido", "") or "",
                "cpf":                         row.get("desc_cpf", "") or "",
                "telefone":                    row.get("desc_telefone", "") or "",
                "email":                       row.get("desc_email", "") or "",
                "titular_fatura":              row.get("desc_titular_fatura", "") or "",
                "desconto_pct":                row.get("pct_desconto") or 0,
                "tipo_fornecimento":           row.get("tp_fornecimento", "") or "",
                "modo_bandeira":               row.get("tp_bandeira", "") or "",
                "data_adesao":                 row.get("dt_adesao", "") or "",
                "status":                      row.get("STATUS", True) if row.get("STATUS") is not None else True,
                "valor_cobranca_anterior":     row.get("vlr_cobranca_anterior", 0) or 0,
                "venc_solev_anterior":      row.get("dt_venc_anterior", "") or "",
                "data_pagamento_anterior":     row.get("dt_ultimo_pagamento", "") or "",
                "economia_acumulada_anterior": max(0, row.get("qtd_economia_acumulada", 0) or 0),
                "saldo_kwh":                   row.get("saldo_kwh", 0) or 0,
                "proxima_leitura":             row.get("proxima_leitura", "") or "",
                "kwh_creditado_real":          row.get("kwh_creditado_real", 0) or 0,
                "endereco":                    end_str,
                # Placeholders para campos sem equivalente na nova tabela
                "codigo_barras":   "CODIGO DE BARRA EM DESENVOLVIMENTO",
                "linha_digitavel":  "XXXX.XXXX  XXXXX.XXXXX  XXXXX.XXXXX  X  XXXXXXXXXXXXXX",
                "pix_payload":      "",
                # Metadados internos
                "_fonte":      "tb_clientes",
                "_id_cliente": id_c,
            }
        return out
    except Exception as e:
        print(f"[DB] Erro ao carregar clientes do Supabase: {e}")
        raise


def salvar_clientes(clientes: dict) -> None:
    """Salva o dict {uc: dados} em tb_clientes (tabela normalizada).

    - Se dados tiver '_id_cliente': faz PATCH diretamente pelo id_cliente.
    - Caso contrario: faz upsert com on_conflict='cod_uc'.
    - Campos internos (_fonte, _id_cliente, codigo_barras, linha_digitavel,
      pix_payload) sao ignorados.
    """
    # Campos a ignorar (internos ou sem equivalente na nova tabela)
    _IGNORAR = {"_fonte", "_id_cliente", "codigo_barras", "linha_digitavel", "pix_payload"}

    def _to_iso(v) -> "Optional[str]":
        """DD/MM/YYYY -> YYYY-MM-DD. Retorna None se invalido."""
        if not v:
            return None
        s = str(v).strip()
        if len(s) >= 10 and s[2] == "/" and s[5] == "/":
            try:
                d, m, y = s[:10].split("/")
                return f"{y}-{m}-{d}"
            except ValueError:
                return None
        return None

    def _mapear(uc: str, c: dict) -> dict:
        """Converte campos no formato legado para o formato de tb_clientes."""
        return {
            "cod_uc":                str(uc),
            "cod_uc":    c.get("cod_uc") or None,
            "desc_nome":             c.get("nome", ""),
            "desc_apelido":          c.get("apelido") or None,
            "desc_cpf":              c.get("cpf") or None,
            "desc_telefone":         c.get("telefone") or None,
            "desc_email":            c.get("email") or None,
            "desc_titular_fatura":   c.get("titular_fatura") or None,
            "pct_desconto":          c.get("desconto_pct") or None,
            "tp_fornecimento":       c.get("tipo_fornecimento") or None,
            "tp_bandeira":           c.get("modo_bandeira") or None,
            "dt_adesao":             _to_iso(c.get("data_adesao")),
            "vlr_cobranca_anterior": c.get("valor_cobranca_anterior") or None,
            "dt_venc_anterior":      _to_iso(c.get("venc_solev_anterior")),
            "dt_ultimo_pagamento":   _to_iso(c.get("data_pagamento_anterior")),
            "qtd_economia_acumulada":c.get("economia_acumulada_anterior") or None,
            "saldo_kwh":             c.get("saldo_kwh", 0) or 0,
            "proxima_leitura":       c.get("proxima_leitura", "") or "",
            "kwh_creditado_real":    c.get("kwh_creditado_real", 0) or 0,
        }

    if not clientes:
        return

    # Separa clientes com id_cliente conhecido (PATCH) dos demais (upsert em lote)
    rows_upsert = []
    for uc, c in clientes.items():
        id_c = c.get("_id_cliente")
        campos = _mapear(uc, c)
        # Remove campos None do mapeamento para nao sobrescrever com null
        campos = {k: v for k, v in campos.items() if v is not None}

        if id_c:
            # PATCH individual preserva campos nao enviados
            _db().patch("tb_clientes", {"id_cliente": id_c}, campos)
        else:
            rows_upsert.append(campos)

    if rows_upsert:
        _db().upsert("tb_clientes", rows_upsert, on_conflict="cod_uc")




# ==================================================================
#  TB_CLIENTES (tabela normalizada)
# ==================================================================

def tb_carregar_clientes() -> list:
    """Retorna lista de clientes da tabela normalizada tb_clientes."""
    rows = _db().select("tb_clientes", order="desc_nome.asc")
    return [_limpar_nulos(r) for r in rows]


def tb_carregar_clientes_paginado(page: int = 1, per_page: int = 50, busca: str = "") -> tuple:
    """Retorna (lista, total) com paginacao e busca server-side por nome/UC.
    total = numero total de registros (para calcular paginas)."""
    db = _db()
    offset = (page - 1) * per_page
    fim    = offset + per_page - 1

    params = {"select": "*", "order": "desc_nome.asc"}
    if busca and busca.strip():
        b = busca.strip().replace("'", "")  # evita injecao basica
        params["or"] = f"(desc_nome.ilike.*{b}*,cod_uc.ilike.*{b}*,cod_uc.ilike.*{b}*)"

    headers = {
        **db.headers,
        "Range":      f"{offset}-{fim}",
        "Range-Unit": "items",
        "Prefer":     "count=exact",
    }
    resp = db._retry(lambda: db.client.get(
        f"{db.base}/tb_clientes", params=params, headers=headers
    ))
    resp.raise_for_status()

    total = 0
    cr = resp.headers.get("Content-Range", "")
    if "/" in cr:
        try:
            total = int(cr.split("/")[1])
        except Exception:
            pass

    return [_limpar_nulos(r) for r in resp.json()], total


def tb_get_cliente(id_cliente: int) -> Optional[dict]:
    """Busca um cliente pelo id_cliente."""
    rows = _db().select("tb_clientes", filtros={"id_cliente": id_cliente})
    return _limpar_nulos(rows[0]) if rows else None


def tb_get_cliente_por_uc(cod_uc: str) -> Optional[dict]:
    """Busca um cliente pela UC (novo formato) ou pela UC Antiga."""
    rows = _db().select("tb_clientes", filtros={"cod_uc": str(cod_uc)})
    if rows:
        return _limpar_nulos(rows[0])
    # Tenta pela UC alternativa (novo formato 15 digitos)
    rows = _db().select("tb_clientes", filtros={"cod_uc": str(cod_uc)})
    return _limpar_nulos(rows[0]) if rows else None


def tb_save_cliente(dados: dict) -> dict:
    """Insere ou atualiza um cliente em tb_clientes."""
    row = {}
    cols = [
        "id_cliente", "cod_uc", "cod_uc", "desc_nome", "desc_apelido",
        "desc_cpf", "desc_telefone", "desc_email", "desc_titular_fatura",
        "tp_fornecimento", "tp_bandeira",
        "pct_desconto", "dt_adesao", "STATUS",
        # campos de estado pos-cobranca
        "qtd_economia_acumulada", "vlr_cobranca_anterior",
        "dt_venc_anterior", "dt_ultimo_pagamento",
    ]
    for col in cols:
        if col in dados:
            row[col] = dados[col]
    if "desc_cpf" in row and row["desc_cpf"]:
        import re
        row["desc_cpf"] = re.sub(r'[.\-/]', '', row["desc_cpf"])
    # PATCH quando temos id_cliente (permite atualizar cod_uc)
    if "id_cliente" in row:
        id_cliente = row.pop("id_cliente")
        _db().patch("tb_clientes", {"id_cliente": id_cliente}, row)
        return tb_get_cliente_por_uc(dados.get("cod_uc", "")) or {"id_cliente": id_cliente}
    _db().upsert("tb_clientes", row, on_conflict="cod_uc")
    return tb_get_cliente_por_uc(dados.get("cod_uc", "")) or row


def tb_writeback_pos_cobranca(id_cliente: int, total_com: float,
                               venc_solev: str, economia_acum: float) -> None:
    """Atualiza campos pos-cobranca via PATCH (nao toca em outros campos).

    NOTA: o parâmetro economia_acum é IGNORADO porque ele é recalculado
    de forma idempotente a partir da soma das faturas em
    recalcular_economia_acumulada(). Isso evita duplicação por re-submit."""
    from utils import _data_br_para_iso
    _db().patch("tb_clientes", {"id_cliente": id_cliente}, {
        "vlr_cobranca_anterior":  round(total_com, 2),
        "dt_venc_anterior":       _data_br_para_iso(venc_solev),
        "dt_ultimo_pagamento":    None,
        # qtd_economia_acumulada gerenciada por recalcular_economia_acumulada
    })


def recalcular_economia_acumulada(id_cliente: int) -> float:
    """Recalcula a economia acumulada do cliente como SOMA cronológica
    das economias_mes de todas as faturas não-canceladas.

    Idempotente: pode ser chamada N vezes que o resultado é sempre o mesmo.
    Atualiza:
      - vlr_economia_acum de cada fatura (saldo cumulativo até aquele mês)
      - qtd_economia_acumulada do cliente (total geral)

    Retorna o valor final acumulado.
    """
    if not id_cliente:
        return 0.0
    # Pega todas as faturas do cliente em ordem cronológica
    fats = _db().select(
        "tb_faturas",
        filtros={"id_cliente": id_cliente},
        order="ano_referencia.asc,mes_referencia.asc",
        columns="id_fatura,ano_referencia,mes_referencia,vlr_economia_mes,vlr_economia_acum,status",
    )
    fats = [f for f in fats if (f.get("status") or "") != "cancelado"]

    acum = 0.0
    for f in fats:
        eco_mes = float(f.get("vlr_economia_mes") or 0)
        acum += eco_mes
        eco_acum_existente = float(f.get("vlr_economia_acum") or 0)
        if abs(eco_acum_existente - acum) > 0.01:
            _db().patch("tb_faturas",
                        {"id_fatura": f["id_fatura"]},
                        {"vlr_economia_acum": round(acum, 2)})
    # Atualiza o total no cliente
    _db().patch("tb_clientes",
                {"id_cliente": id_cliente},
                {"qtd_economia_acumulada": round(acum, 2)})
    return round(acum, 2)


def tb_delete_cliente(id_cliente: int) -> None:
    """Remove um cliente pelo id_cliente."""
    _db().delete("tb_clientes", {"id_cliente": id_cliente})


# ==================================================================
#  TB_ENDERECOS (tabela normalizada)
# ==================================================================

def tb_get_endereco_cliente(id_cliente: int) -> Optional[dict]:
    """Retorna o endereco de um cliente."""
    rows = _db().select("tb_enderecos", filtros={"id_cliente": id_cliente})
    return _limpar_nulos(rows[0]) if rows else None


def tb_save_endereco(id_cliente: int, dados: dict) -> None:
    """Insere ou atualiza o endereco de um cliente."""
    import re
    row = {"id_cliente": id_cliente}
    cols = [
        "desc_logradouro", "desc_numero", "desc_complemento",
        "desc_setor", "desc_cidade", "desc_estado", "cod_cep",
    ]
    for col in cols:
        if col in dados:
            row[col] = dados[col]
    # Normaliza CEP: remove ponto, mantem traco → "XXXXX-XXX" (9 chars)
    if row.get("cod_cep"):
        cep = re.sub(r'[^\d\-]', '', str(row["cod_cep"]))   # remove ponto e espacos
        if '-' not in cep and len(cep) == 8:
            cep = f"{cep[:5]}-{cep[5:]}"
        row["cod_cep"] = cep[:20]  # garante nao excede limite
    _db().upsert("tb_enderecos", row, on_conflict="id_cliente")


def tb_delete_endereco_cliente(id_cliente: int) -> None:
    """Remove o endereco de um cliente."""
    _db().delete("tb_enderecos", {"id_cliente": id_cliente})


def tb_carregar_todos_enderecos() -> dict:
    """Retorna {id_cliente: endereco_dict} para todos os clientes."""
    rows = _db().select("tb_enderecos")
    return {r["id_cliente"]: _limpar_nulos(r) for r in rows if r.get("id_cliente")}


def tb_carregar_enderecos_usinas() -> dict:
    """Retorna {id_usina: endereco_dict} para todas as usinas."""
    rows = _db().select("tb_enderecos")
    return {r["id_usina"]: _limpar_nulos(r) for r in rows if r.get("id_usina")}


def tb_get_endereco_usina(id_usina: int) -> Optional[dict]:
    """Retorna o endereco de uma usina."""
    rows = _db().select("tb_enderecos", filtros={"id_usina": id_usina})
    return _limpar_nulos(rows[0]) if rows else None


def tb_save_endereco_usina(id_usina: int, dados: dict) -> None:
    """Insere ou atualiza o endereco de uma usina."""
    import re
    cols = [
        "desc_logradouro", "desc_numero", "desc_complemento",
        "desc_setor", "desc_cidade", "desc_estado", "cod_cep",
    ]
    row: dict = {}
    for col in cols:
        if col in dados:
            row[col] = dados[col]
    if row.get("cod_cep"):
        cep = re.sub(r'[^\d\-]', '', str(row["cod_cep"]))
        if '-' not in cep and len(cep) == 8:
            cep = f"{cep[:5]}-{cep[5:]}"
        row["cod_cep"] = cep[:20]

    existing = tb_get_endereco_usina(id_usina)
    if existing:
        # Atualiza registro existente via PATCH (evita NOT NULL em id_cliente)
        _db().patch("tb_enderecos", {"id_usina": id_usina}, row)
    else:
        # Primeiro cadastro: precisa que id_cliente seja nullable no banco
        # (execute migration_pix_recebedores.sql no Supabase SQL Editor)
        # tb_enderecos.id_usina não tem unique constraint, então usamos
        # upsert sem on_conflict (INSERT puro).
        row["id_usina"] = id_usina
        _db().upsert("tb_enderecos", row)


def tb_delete_endereco_usina(id_usina: int) -> None:
    """Remove o endereco de uma usina."""
    _db().delete("tb_enderecos", {"id_usina": id_usina})


def tb_carregar_todas_vinculacoes() -> dict:
    """Retorna {id_cliente: [vinculos ativos]} para todos os clientes."""
    rows = _db().select("tb_cliente_usina", raw_params={"dt_fim": "is.null"})
    out: dict = {}
    for r in rows:
        id_c = r.get("id_cliente")
        if id_c:
            out.setdefault(id_c, []).append(_limpar_nulos(r))
    return out


def tb_mapa_uc_para_uc_nova() -> dict:
    """Retorna {cod_uc: cod_uc} para exibir a UC nova (formatada) no historico."""
    try:
        rows = _db().select("tb_clientes", columns="cod_uc,cod_uc")
        return {
            str(r["cod_uc"]): str(r["cod_uc"])
            for r in rows
            if r.get("cod_uc") and r.get("cod_uc")
        }
    except Exception as _e:
        print(f"[DB] tb_mapa_uc_para_uc_nova falhou: {_e}")
        return {}


def tb_mapa_uc_para_usina() -> dict:
    """Retorna {uc: nome_usina} para todos os clientes com vinculo ativo.
    Faz 3 queries (clientes, vinculacoes, usinas) e junta em memoria."""
    try:
        clientes = _db().select("tb_clientes", columns="id_cliente,cod_uc")
        vinc     = _db().select("tb_cliente_usina", columns="id_cliente,id_usina",
                                raw_params={"dt_fim": "is.null"})
        usinas   = _db().select("tb_usinas", columns="id_usina,desc_nome")

        uc_para_idcli  = {r["id_cliente"]: str(r["cod_uc"])  for r in clientes if r.get("cod_uc")}
        idcli_para_idu = {r["id_cliente"]: r["id_usina"]      for r in vinc    if r.get("id_usina")}
        idu_para_nome  = {r["id_usina"]:   r.get("desc_nome","") for r in usinas}

        out = {}
        for id_cli, uc in uc_para_idcli.items():
            id_u = idcli_para_idu.get(id_cli)
            if id_u:
                out[uc] = idu_para_nome.get(id_u, "")
        return out
    except Exception as _e:
        print(f"[DB] tb_mapa_uc_para_usina falhou: {_e}")
        return {}


# ==================================================================
#  TB_CLIENTE_USINA (tabela normalizada com historico)
# ==================================================================

def tb_get_vinculo_ativo_do_cliente(id_cliente: int) -> Optional[dict]:
    """Retorna o vinculo ativo (dt_fim IS NULL) de um cliente, ou None."""
    rows = _db().select(
        "tb_cliente_usina",
        raw_params={"id_cliente": f"eq.{id_cliente}", "dt_fim": "is.null"},
    )
    return _limpar_nulos(rows[0]) if rows else None


def tb_get_usinas_do_cliente(id_cliente: int) -> list:
    """Retorna apenas os vinculos ativos de um cliente (dt_fim IS NULL)."""
    rows = _db().select(
        "tb_cliente_usina",
        raw_params={"id_cliente": f"eq.{id_cliente}", "dt_fim": "is.null"},
    )
    return [_limpar_nulos(r) for r in rows]


def tb_get_historico_usinas_do_cliente(id_cliente: int) -> list:
    """Retorna todos os vinculos (ativos e encerrados) de um cliente."""
    rows = _db().select(
        "tb_cliente_usina",
        filtros={"id_cliente": id_cliente},
        order="dt_inicio.asc",
    )
    return [_limpar_nulos(r) for r in rows]


def tb_get_clientes_da_usina(id_usina: int) -> list:
    """Retorna apenas os clientes ativos vinculados a uma usina (dt_fim IS NULL)."""
    rows = _db().select(
        "tb_cliente_usina",
        raw_params={"id_usina": f"eq.{id_usina}", "dt_fim": "is.null"},
    )
    return [_limpar_nulos(r) for r in rows]


def tb_save_cliente_usina(id_cliente: int, id_usina: int, dados: dict) -> None:
    """Vincula cliente a usina com historico.

    - Se ja existe vinculo ativo para a MESMA usina → atualiza dados (rateio etc.)
    - Se existe vinculo ativo para OUTRA usina → fecha o antigo e cria novo
    - Se nao existe vinculo ativo → cria novo
    """
    from datetime import date
    hoje = date.today().isoformat()
    cols = ["pct_rateio", "qtd_saldo_kwh", "qtd_kwh_creditado",
            "dt_proxima_leitura", "dt_saldo_conferido", "desc_saldo_obs"]

    ativo = tb_get_vinculo_ativo_do_cliente(id_cliente)

    if ativo:
        if ativo.get("id_usina") == id_usina:
            # Mesma usina: apenas atualiza campos opcionais
            row_update = {col: dados[col] for col in cols if col in dados}
            if row_update:
                _db().patch("tb_cliente_usina", {"id": ativo["id"]}, row_update)
            return
        # Usina diferente: encerra vinculo anterior
        _db().patch("tb_cliente_usina", {"id": ativo["id"]}, {"dt_fim": hoje})

    # Insere novo vinculo (id e BIGSERIAL, sem on_conflict necessario)
    row: dict = {"id_cliente": id_cliente, "id_usina": id_usina, "dt_inicio": hoje}
    for col in cols:
        if col in dados:
            row[col] = dados[col]
    _db().upsert("tb_cliente_usina", row)


def tb_delete_cliente_usina(id_cliente: int, id_usina: int) -> None:
    """Encerra o vinculo ativo (define dt_fim = hoje) em vez de apagar o registro."""
    from datetime import date
    ativo = tb_get_vinculo_ativo_do_cliente(id_cliente)
    if ativo and ativo.get("id_usina") == id_usina:
        _db().patch(
            "tb_cliente_usina",
            {"id": ativo["id"]},
            {"dt_fim": date.today().isoformat()},
        )


# ==================================================================
#  TB_INVESTIDORES (tabela normalizada)
# ==================================================================

def tb_carregar_investidores() -> list:
    """Retorna lista de investidores."""
    rows = _db().select("tb_investidores", order="desc_nome.asc")
    return [_limpar_nulos(r) for r in rows]


def tb_get_investidor(id_investidor: int) -> Optional[dict]:
    """Busca um investidor pelo ID."""
    rows = _db().select("tb_investidores", filtros={"id_investidor": id_investidor})
    return _limpar_nulos(rows[0]) if rows else None


def tb_save_investidor(dados: dict) -> dict:
    """Insere ou atualiza um investidor/recebedor. Retorna o registro salvo."""
    row = {}
    cols = [
        "id_investidor", "desc_nome", "desc_cpf_cnpj", "desc_email",
        "desc_telefone", "desc_banco", "desc_agencia", "desc_conta",
        "desc_pix", "desc_nome_pix", "desc_cidade_pix",
        "qtd_dia_pagamento", "vlr_minimo", "pct_desagio",
    ]
    for col in cols:
        if col in dados:
            row[col] = dados[col]
    if "desc_cpf_cnpj" in row and row["desc_cpf_cnpj"]:
        import re
        row["desc_cpf_cnpj"] = re.sub(r'[.\-/]', '', row["desc_cpf_cnpj"])
    on_conflict = "id_investidor" if "id_investidor" in row else None
    return _db().upsert_returning("tb_investidores", row, on_conflict=on_conflict)


def tb_delete_investidor(id_investidor: int) -> None:
    """Remove um investidor pelo ID."""
    _db().delete("tb_investidores", {"id_investidor": id_investidor})


def tb_get_pix_da_usina(id_usina: int) -> Optional[dict]:
    """Retorna dados PIX do recebedor vinculado a usina, ou None se nao configurado."""
    usina = tb_get_usina(id_usina)
    if not usina or not usina.get("id_investidor"):
        return None
    rec = tb_get_investidor(usina["id_investidor"])
    if not rec or not rec.get("desc_pix"):
        return None
    return rec


# ==================================================================
#  TB_DONOS (donos das usinas — separados de tb_usinas)
# ==================================================================

def tb_carregar_donos() -> list:
    """Retorna lista de donos cadastrados, ordenados por nome."""
    rows = _db().select("tb_donos", order="desc_nome.asc")
    return [_limpar_nulos(r) for r in rows]


def tb_get_dono(id_dono: int) -> Optional[dict]:
    """Busca um dono pelo ID."""
    rows = _db().select("tb_donos", filtros={"id_dono": id_dono})
    return _limpar_nulos(rows[0]) if rows else None


def tb_save_dono(dados: dict) -> dict:
    """Insere ou atualiza um dono. Retorna o registro salvo."""
    row = {}
    cols = [
        "id_dono", "desc_nome", "desc_cpf_cnpj",
        "desc_telefone", "desc_email", "dt_nascimento",
    ]
    for col in cols:
        if col in dados:
            row[col] = dados[col]
    if "desc_cpf_cnpj" in row and row["desc_cpf_cnpj"]:
        import re
        row["desc_cpf_cnpj"] = re.sub(r'[.\-/]', '', row["desc_cpf_cnpj"])
    on_conflict = "id_dono" if "id_dono" in row else None
    return _db().upsert_returning("tb_donos", row, on_conflict=on_conflict)


def tb_delete_dono(id_dono: int) -> None:
    """Remove um dono pelo ID. As usinas com FK ficam com id_dono = NULL."""
    _db().delete("tb_donos", {"id_dono": id_dono})


# ==================================================================
#  TB_TITULARES (titulares da UC — separados de tb_usinas)
# ==================================================================

def tb_carregar_titulares() -> list:
    """Retorna lista de titulares cadastrados, ordenados por nome."""
    rows = _db().select("tb_titulares", order="desc_nome.asc")
    return [_limpar_nulos(r) for r in rows]


def tb_get_titular(id_titular: int) -> Optional[dict]:
    """Busca um titular pelo ID."""
    rows = _db().select("tb_titulares", filtros={"id_titular": id_titular})
    return _limpar_nulos(rows[0]) if rows else None


def tb_save_titular(dados: dict) -> dict:
    """Insere ou atualiza um titular. Retorna o registro salvo."""
    row = {}
    cols = [
        "id_titular", "desc_nome", "desc_cpf_cnpj",
        "desc_telefone", "desc_email", "dt_nascimento",
    ]
    for col in cols:
        if col in dados:
            row[col] = dados[col]
    if "desc_cpf_cnpj" in row and row["desc_cpf_cnpj"]:
        import re
        row["desc_cpf_cnpj"] = re.sub(r'[.\-/]', '', row["desc_cpf_cnpj"])
    on_conflict = "id_titular" if "id_titular" in row else None
    return _db().upsert_returning("tb_titulares", row, on_conflict=on_conflict)


def tb_delete_titular(id_titular: int) -> None:
    """Remove um titular pelo ID. As usinas com FK ficam com id_titular = NULL."""
    _db().delete("tb_titulares", {"id_titular": id_titular})


# ==================================================================
#  TB_USINAS (tabela normalizada)
# ==================================================================

def tb_carregar_usinas() -> list:
    """Retorna lista de usinas."""
    rows = _db().select("tb_usinas", order="desc_nome.asc")
    return [_limpar_nulos(r) for r in rows]


def tb_carregar_usinas_com_titular() -> list:
    """Lista de usinas com dados do titular embutidos via id_titular → tb_titulares.

    Cada usina recebe os campos adicionais:
      desc_titular_uc       (nome, sobrescreve fallback legado vazio)
      _titular_cpf
      _titular_dn           (ISO YYYY-MM-DD)
      _titular_dn_br        (DD/MM/AAAA, conveniencia para front)
      _titular_telefone
      _titular_email
    Usado pelos forms de cliente para preencher o quadro de titularidade da UC
    ao selecionar uma usina vinculada.
    """
    usinas = tb_carregar_usinas()
    titulares_rows = _db().select("tb_titulares")
    by_id = {t["id_titular"]: _limpar_nulos(t) for t in titulares_rows if t.get("id_titular")}
    for u in usinas:
        t = by_id.get(u.get("id_titular")) if u.get("id_titular") else None
        if t:
            if not u.get("desc_titular_uc"):
                u["desc_titular_uc"] = t.get("desc_nome", "")
            u["_titular_cpf"]      = t.get("desc_cpf_cnpj", "")
            dn = (t.get("dt_nascimento") or "").strip()
            u["_titular_dn"]       = dn
            if len(dn) == 10 and dn[4] == "-":
                a, m, d = dn.split("-")
                u["_titular_dn_br"] = f"{d}/{m}/{a}"
            else:
                u["_titular_dn_br"] = dn
            u["_titular_telefone"] = t.get("desc_telefone", "")
            u["_titular_email"]    = t.get("desc_email", "")
        else:
            u.setdefault("_titular_cpf", "")
            u.setdefault("_titular_dn", "")
            u.setdefault("_titular_dn_br", "")
            u.setdefault("_titular_telefone", "")
            u.setdefault("_titular_email", "")
    return usinas


def tb_get_usina(id_usina: int) -> Optional[dict]:
    """Busca uma usina pelo ID."""
    rows = _db().select("tb_usinas", filtros={"id_usina": id_usina})
    return _limpar_nulos(rows[0]) if rows else None


def tb_get_usina_por_nome(desc_nome: str) -> Optional[dict]:
    """Busca uma usina pelo nome (usado na transicao uid legado → id_usina)."""
    rows = _db().select("tb_usinas", filtros={"desc_nome": desc_nome})
    return _limpar_nulos(rows[0]) if rows else None


def tb_save_usina(dados: dict) -> dict:
    """Insere ou atualiza uma usina. Retorna o registro salvo (com id_usina)."""
    row = {}
    cols = [
        "id_usina", "id_investidor", "id_dono", "id_titular",
        "desc_nome", "cod_uc_geradora", "desc_classe",
        "qtd_potencia_kwp",
        "desc_modulos_tipo", "qtd_modulos", "desc_inversor",
        "desc_estrutura", "dt_comissionamento", "desc_garantia_modulos",
        "desc_garantia_inversor", "qtd_geracao_media_mensal",
        "qtd_geracao_prevista_diaria", "desc_observacoes",
        "desc_documento_titular_pdf",
        "dt_proxima_leitura", "qtd_saldo_kwh",
        "path_doc_cnh_rg", "path_doc_procuracao", "path_doc_cnh_rg_proc",
    ]
    # Colunas opcionais que so entram no payload se tiverem valor
    _optional_cols = {"desc_classe", "desc_telefone_titular", "desc_email_titular"}
    for col in cols:
        if col in dados:
            if col in _optional_cols and dados[col] is None:
                continue  # nao envia null para colunas que podem nao existir ainda
            row[col] = dados[col]
    if "desc_cpf_titular" in row and row["desc_cpf_titular"]:
        import re
        row["desc_cpf_titular"] = re.sub(r'[.\-/]', '', row["desc_cpf_titular"])
    # PATCH quando temos id_usina (edicao) — preserva colunas nao enviadas
    if "id_usina" in row:
        id_usina = row.pop("id_usina")
        _db().patch("tb_usinas", {"id_usina": id_usina}, row)
        rows = _db().select("tb_usinas", filtros={"id_usina": id_usina})
        return _limpar_nulos(rows[0]) if rows else {"id_usina": id_usina}
    # INSERT novo registro
    return _db().insert_returning("tb_usinas", row)


def tb_delete_usina(id_usina: int) -> None:
    """Remove uma usina pelo ID."""
    _db().delete("tb_usinas", {"id_usina": id_usina})


# ==================================================================
#  RATEIOS MENSAIS (tb_rateios_mensais)
# ==================================================================
def tb_get_rateio_mes(id_usina: int, mes_ref: str) -> Optional[dict]:
    """Retorna o registro de rateio de uma usina em determinado mes, ou None."""
    rows = _db().select(
        "tb_rateios_mensais",
        filtros={"id_usina": id_usina, "mes_referencia": mes_ref},
    )
    if not rows:
        return None
    r = rows[0]
    return {
        "data_registro":  r.get("data_registro", ""),
        "soma_percentual": float(r.get("soma_percentual") or 0),
        "beneficiarios":  r.get("beneficiarios") or [],
    }


def tb_get_rateios_usina(id_usina: int) -> dict:
    """Retorna dict {mes_ref: {data_registro, soma_percentual, beneficiarios}}
    com todos os meses cadastrados para a usina."""
    rows = _db().select("tb_rateios_mensais", filtros={"id_usina": id_usina})
    result = {}
    for r in rows:
        mes = r["mes_referencia"]
        result[mes] = {
            "data_registro":  r.get("data_registro", ""),
            "soma_percentual": float(r.get("soma_percentual") or 0),
            "beneficiarios":  r.get("beneficiarios") or [],
        }
    return result


def tb_get_todos_rateios() -> dict:
    """Retorna dict {str(id_usina): {mes_ref: {...}}} — todos os rateios cadastrados."""
    rows = _db().select("tb_rateios_mensais")
    result = {}
    for r in rows:
        uid_str = str(r["id_usina"])
        mes = r["mes_referencia"]
        result.setdefault(uid_str, {})[mes] = {
            "data_registro":  r.get("data_registro", ""),
            "soma_percentual": float(r.get("soma_percentual") or 0),
            "beneficiarios":  r.get("beneficiarios") or [],
        }
    return result


def tb_save_rateio_mes(
    id_usina: int,
    mes_ref: str,
    beneficiarios: list,
    soma_pct: float,
    data_registro: str = "",
) -> None:
    """Salva (upsert) o rateio de uma usina em determinado mes."""
    from datetime import datetime as _dt
    row = {
        "id_usina":       id_usina,
        "mes_referencia": mes_ref,
        "beneficiarios":  beneficiarios,
        "soma_percentual": round(float(soma_pct or 0), 4),
        "data_registro":  data_registro or _dt.now().strftime("%d/%m/%Y %H:%M"),
    }
    _db().upsert("tb_rateios_mensais", row, on_conflict="id_usina,mes_referencia")


def tb_delete_rateio_mes(id_usina: int, mes_ref: str) -> None:
    """Remove o rateio de uma usina em determinado mes."""
    _db().delete("tb_rateios_mensais", {"id_usina": id_usina, "mes_referencia": mes_ref})


# ==================================================================
#  USINAS (legado)
# ==================================================================
_COLS_USINA = [
    "uid", "nome", "endereco", "cep", "cidade_uf", "potencia_kwp",
    "modulos_tipo", "modulos_qtd", "inversor", "estrutura",
    "uc_geradora", "titular_uc", "cpf_titular", "data_comissionamento",
    "garantia_modulos", "garantia_inversor",
    "geracao_media_mensal", "geracao_prevista_diaria", "observacoes",
    "investidor_nome", "investidor_cpf_cnpj", "investidor_email",
    "investidor_telefone", "investidor_banco", "investidor_agencia",
    "investidor_conta", "investidor_pix", "investidor_dia_pagamento",
    "investidor_valor_minimo", "investidor_desagio_pct",
    "proxima_leitura", "documento_titular_pdf", "saldo_kwh",
]


def carregar_usinas() -> dict:
    """Retorna {str(id_usina): dados_dict} lidos de tb_usinas (tabela normalizada).

    Faz join em memoria com tb_enderecos via tb_carregar_enderecos_usinas().
    Mantem os mesmos nomes de campo legados (nome, endereco, cep, etc.) para
    compatibilidade com o restante do codigo.
    Cada entrada inclui '_id_usina' e '_fonte': 'tb_usinas'.
    """
    import re as _re
    try:
        rows = _db().select("tb_usinas", order="desc_nome.asc")
        enderecos = tb_carregar_enderecos_usinas()  # {id_usina: endereco_dict}
        out = {}
        for row in rows:
            id_usina = row.get("id_usina")
            if not id_usina:
                continue
            end = enderecos.get(id_usina, {})

            # Monta string de endereco compativel com o formato legado
            _cep_d = _re.sub(r'\D', '', str(end.get("cod_cep") or ""))
            _cep_fmt = f"{_cep_d[:2]}.{_cep_d[2:5]}-{_cep_d[5:]}" if len(_cep_d) == 8 else ""
            _cid = end.get("desc_cidade", ""); _est = end.get("desc_estado", "")
            end_str = ", ".join(p for p in [
                end.get("desc_logradouro", ""), end.get("desc_numero", ""),
                end.get("desc_complemento", ""), end.get("desc_setor", ""),
                f"CEP {_cep_fmt}" if _cep_fmt else "",
                f"{_cid}/{_est}" if _cid and _est else _cid,
            ] if p)
            cidade_uf = f"{_cid}/{_est}" if _cid and _est else _cid

            out[str(id_usina)] = {
                "nome":                      row.get("desc_nome", ""),
                "endereco":                  end_str,
                "cep":                       end.get("cod_cep", "") or "",
                "cidade_uf":                 cidade_uf,
                "potencia_kwp":              row.get("qtd_potencia_kwp") or 0,
                "modulos_tipo":              row.get("desc_modulos_tipo", "") or "",
                "modulos_qtd":               row.get("qtd_modulos") or 0,
                "inversor":                  row.get("desc_inversor", "") or "",
                "estrutura":                 row.get("desc_estrutura", "") or "",
                "uc_geradora":               row.get("cod_uc_geradora", "") or "",
                "titular_uc":                row.get("desc_titular_uc", "") or "",
                "cpf_titular":               row.get("desc_cpf_titular", "") or "",
                "data_comissionamento":      row.get("dt_comissionamento", "") or "",
                "garantia_modulos":          row.get("desc_garantia_modulos", "") or "",
                "garantia_inversor":         row.get("desc_garantia_inversor", "") or "",
                "geracao_media_mensal":      row.get("qtd_geracao_media_mensal") or 0,
                "geracao_prevista_diaria":   row.get("qtd_geracao_prevista_diaria") or 0,
                "observacoes":               row.get("desc_observacoes", "") or "",
                "documento_titular_pdf":     row.get("desc_documento_titular_pdf", "") or "",
                "proxima_leitura":           row.get("dt_proxima_leitura", "") or "",
                "saldo_kwh":                 row.get("qtd_saldo_kwh") or 0,
                # Campos extras apenas em tb_usinas
                "classe":                    row.get("desc_classe", "") or "",
                "telefone_titular":          row.get("desc_telefone_titular", "") or "",
                "email_titular":             row.get("desc_email_titular", "") or "",
                # Metadados internos
                "_id_usina":                 id_usina,
                "_fonte":                    "tb_usinas",
            }
        return out
    except Exception as e:
        print(f"[DB] Erro ao carregar usinas do Supabase: {e}")
        raise


def _row_usina(uid: str, u: dict) -> dict:
    row = {"uid": str(uid)}
    for col in _COLS_USINA:
        if col == "uid":
            continue
        if col == "investidor_desagio_pct":
            if "investidor_desagio_pct" in u:
                row[col] = u["investidor_desagio_pct"]
            elif "investidor_desagio_pct" in u:
                row[col] = u["investidor_desagio_pct"]
            continue
        if col in u:
            row[col] = u[col]
    return row


def salvar_usinas(usinas: dict) -> None:
    """Salva o dict {str(id_usina): dados} em tb_usinas (tabela normalizada).

    - Se dados tiver '_id_usina': faz PATCH por id_usina.
    - Campos internos (_id_usina, _fonte) e de endereco (endereco, cep, cidade_uf)
      sao ignorados — enderecos tem tabela propria (tb_enderecos).
    """
    _IGNORAR = {"_id_usina", "_fonte", "endereco", "cep", "cidade_uf",
                "classe", "telefone_titular", "email_titular"}

    def _mapear(u: dict) -> dict:
        """Converte campos legados para colunas de tb_usinas."""
        def _iso(s):
            if not s: return None
            s = str(s).strip()
            if len(s) >= 10 and s[4] == '-': return s[:10]
            try:
                from datetime import datetime as _dt
                return _dt.strptime(s, "%d/%m/%Y").strftime("%Y-%m-%d")
            except Exception:
                return None
        row = {
            "desc_nome":                  u.get("nome") or None,
            "qtd_potencia_kwp":           u.get("potencia_kwp") or None,
            "desc_modulos_tipo":          u.get("modulos_tipo") or None,
            "qtd_modulos":                u.get("modulos_qtd") or None,
            "desc_inversor":              u.get("inversor") or None,
            "desc_estrutura":             u.get("estrutura") or None,
            "cod_uc_geradora":            u.get("uc_geradora") or None,
            "desc_titular_uc":            u.get("titular_uc") or None,
            "desc_cpf_titular":           u.get("cpf_titular") or None,
            "dt_comissionamento":         _iso(u.get("data_comissionamento")),
            "desc_garantia_modulos":      u.get("garantia_modulos") or None,
            "desc_garantia_inversor":     u.get("garantia_inversor") or None,
            "qtd_geracao_media_mensal":   u.get("geracao_media_mensal") or None,
            "qtd_geracao_prevista_diaria":u.get("geracao_prevista_diaria") or None,
            "desc_observacoes":           u.get("observacoes") or None,
            "desc_documento_titular_pdf": u.get("documento_titular_pdf") or None,
            "dt_proxima_leitura":         _iso(u.get("proxima_leitura")),
            "qtd_saldo_kwh":              u.get("saldo_kwh") if u.get("saldo_kwh") is not None else None,
            # Campos extras presentes em tb_usinas
            "desc_classe":                u.get("classe") or None,
            "desc_telefone_titular":      u.get("telefone_titular") or None,
            "desc_email_titular":         u.get("email_titular") or None,
        }
        return {k: v for k, v in row.items() if v is not None}

    if not usinas:
        return

    for uid, u in usinas.items():
        id_usina = u.get("_id_usina") or (int(uid) if str(uid).isdigit() else None)
        campos = _mapear(u)
        if not campos:
            continue
        if id_usina:
            _db().patch("tb_usinas", {"id_usina": id_usina}, campos)
        else:
            # Sem id_usina conhecido: tenta upsert por nome
            if "desc_nome" in campos:
                _db().upsert("tb_usinas", campos, on_conflict="desc_nome")



# ==================================================================
#  FATURAS (lista — adapter para codigo legado que iterava historico)
# ==================================================================


def carregar_faturas() -> list:
    """Le todas as faturas de tb_faturas e devolve no formato legado
    (com aliases id, nome, uc, mes_referencia 'MM/AAAA', vencimento BR, etc).

    Util para rotas de rateio que precisam iterar todas as faturas em
    Python (ja que filtros agregados PostgREST nao cobrem todos os casos).

    Renomeada de carregar_historico() na etapa 7B.5 — a tabela historico
    foi congelada e nao existe mais no fluxo do app.
    """
    from datetime import datetime as _dt

    rows = _db().select(
        "tb_faturas",
        columns=_FATURA_COLS_EMBED,
        order="ano_referencia.desc,mes_referencia.desc,id_fatura.desc",
    )
    out = []
    for r in rows:
        e = _enriquecer_fatura(r)

        # Aliases legados — nomes de campo que codigo antigo espera
        e["id"]                = str(e.get("id_fatura") or "")
        e["nome"]              = e.get("_nome") or ""
        e["uc"]                = e.get("_cod_uc") or ""
        e["mes_referencia"]    = e.get("_mes_ref_br") or ""
        e["total_sem"]         = e.get("vlr_total_sem") or 0
        e["total_com"]         = e.get("vlr_total_com") or 0
        e["economia_mes"]      = e.get("vlr_economia_mes") or 0
        e["economia_acum"]     = e.get("vlr_economia_acum") or 0
        e["consumo_kwh"]       = e.get("qtd_consumo_kwh") or 0
        e["compensado_kwh"]    = e.get("qtd_compensado_kwh") or 0
        e["compensacao_dic"]   = e.get("vlr_compensacao_dic") or 0
        e["pdf"]               = e.get("pdf_solev") or ""
        e["pdf_url"]           = e.get("pdf_solev_url") or ""
        e["pdf_equatorial"]    = e.get("pdf_equatorial") or ""
        e["pdf_equatorial_url"]= e.get("pdf_equatorial_url") or ""

        # dt_geracao -> data "dd/mm/aaaa HH:MM"
        v = e.get("dt_geracao")
        if v:
            try:
                s = str(v)
                if "T" in s or " " in s:
                    dt = _dt.fromisoformat(s.replace("Z", "").split("+")[0][:19])
                else:
                    dt = _dt.fromisoformat(s)
                e["data"] = dt.strftime("%d/%m/%Y %H:%M")
            except (ValueError, TypeError):
                e["data"] = str(v)
        else:
            e["data"] = ""

        # ISO DATE -> "dd/mm/aaaa"
        for src, dst in (("dt_venc_solev",   "vencimento"),
                         ("dt_venc_equatorial", "venc_equatorial"),
                         ("dt_leitura_atual",   "data_leitura_atual")):
            iso = e.get(src)
            if iso:
                try:
                    e[dst] = _dt.fromisoformat(str(iso)).strftime("%d/%m/%Y")
                except (ValueError, TypeError):
                    e[dst] = str(iso)
            else:
                e[dst] = ""

        # status enum -> texto legado
        st = e.get("status") or "pendente"
        if st == "pago" and e.get("dt_pagamento"):
            try:
                d = _dt.fromisoformat(str(e["dt_pagamento"])).strftime("%d/%m/%Y")
                e["status"] = f"Pago em {d}"
            except (ValueError, TypeError):
                e["status"] = "Pago"
        elif st == "cancelado":
            e["status"] = "Cancelado"
        else:
            e["status"] = "Aguardando pagamento"

        out.append(e)
    return out


def salvar_historico_consumo(id_cliente: int, mes_ref_atual: str,
                              historico_meses: list, origem: str = "") -> int:
    """Salva histórico de consumo de 12+ meses extraído da fatura.

    Parâmetros:
      id_cliente       — ID do cliente em tb_clientes
      mes_ref_atual    — "MM/AAAA" (mês da fatura — posição 0 do histórico)
      historico_meses  — lista do extrator. Pode ser de dicts ou dataclasses;
                         posição 0 = mes_ref_atual, posição N = mes_ref - N meses
      origem           — texto identificando a fonte (ex: "fatura_05_2026")

    A tabela tb_historico_consumo deve ter:
      id_historico BIGSERIAL PK, id_cliente, ano_referencia, mes_referencia,
      qtd_consumo_kwh, vlr_total, qtd_dias, desc_status, origem, atualizado_em
      UNIQUE (id_cliente, ano_referencia, mes_referencia)

    Retorna o número de meses gravados (0 se nada foi salvo).
    """
    import re as _re_hc
    if not id_cliente or not mes_ref_atual or not historico_meses:
        return 0
    m = _re_hc.match(r"^(\d{1,2})/(\d{4})$", str(mes_ref_atual).strip())
    if not m:
        return 0
    mes_base, ano_base = int(m.group(1)), int(m.group(2))

    rows = []
    for i, h in enumerate(historico_meses):
        # Aceita dict ou dataclass
        consumo = (h.get("consumo_kwh") if isinstance(h, dict) else getattr(h, "consumo_kwh", 0)) or 0
        valor   = (h.get("valor_rs")    if isinstance(h, dict) else getattr(h, "valor_rs", 0))    or 0
        dias    = (h.get("dias")        if isinstance(h, dict) else getattr(h, "dias", 0))        or 0
        status  = (h.get("status")      if isinstance(h, dict) else getattr(h, "status", ""))     or ""
        # Pula meses completamente vazios
        if float(consumo) <= 0 and float(valor) <= 0 and int(dias) <= 0:
            continue
        mes_i = mes_base - i
        ano_i = ano_base
        while mes_i < 1:
            mes_i += 12
            ano_i -= 1
        rows.append({
            "id_cliente":      id_cliente,
            "ano_referencia":  ano_i,
            "mes_referencia":  mes_i,
            "qtd_consumo_kwh": round(float(consumo), 2),
            "vlr_total":       round(float(valor), 2),
            "qtd_dias":        int(dias),
            "desc_status":     str(status),
            "origem":          origem,
        })
    if not rows:
        return 0
    try:
        _db().upsert("tb_historico_consumo", rows,
                     on_conflict="id_cliente,ano_referencia,mes_referencia")
        return len(rows)
    except Exception as _e:
        print(f"  [DB] salvar_historico_consumo falhou: {_e}")
        return 0


def carregar_historico_consumo(id_cliente: int, meses: int = 12) -> list:
    """Retorna histórico de consumo dos últimos N meses para um cliente.
    Lista ordenada do mais recente pro mais antigo."""
    rows = _db().select(
        "tb_historico_consumo",
        filtros={"id_cliente": id_cliente},
        order="ano_referencia.desc,mes_referencia.desc",
    )
    return rows[:meses] if rows else []


def inserir_fatura(
    uc: str,
    nome: str,
    mes_ref: str,
    total_sem: float,
    total_com: float,
    economia_mes: float,
    economia_acum: float,
    venc: str,
    pdf_path: str,
    consumo_kwh: float = 0,
    compensado_kwh: float = 0,
    data_leitura_atual: str = "",
    compensacao_dic: float = 0,
    pdf_url: str = "",
    pdf_equatorial: str = "",
    pdf_equatorial_url: str = "",
    venc_equatorial: str = "",
    saldo_kwh: float = 0,
    multa_equatorial: float = 0,
    juros_equatorial: float = 0,
    multa_mes: float = 0,
    juros_mes: float = 0,
    fatura_equatorial: float = 0,
    fio_b: float = 0,
    ilum_publica: float = 0,
    band_amar_equatorial: float = 0,
    band_verm_equatorial: float = 0,
    band_amar_solev:   float = 0,
    band_verm_solev:   float = 0,
    ajuste_valor:         float = 0,
    difci:                float = 0,
    ecnisenta:            float = 0,
    anterior_leitura:     str = "",
    proxima_leitura:      str = "",
    n_dias:               int = 0,
    # SCEE — dados da geração solar
    scee_ciclo_mes:         str   = "",   # ex: "04/2026"
    scee_uc_geradora:       str   = "",   # UC da usina geradora
    scee_pct_rateio:          float = 0,    # % rateio deste cliente
    scee_geracao_usina_kwh:   float = 0,    # geração total da usina (calculada: excedente ÷ % rateio)
    scee_excedente_kwh:       float = 0,    # kWh destinados a esta UC pelo rateio
    scee_credito_kwh:       float = 0,    # crédito recebido
    scee_saldo_exp_30d_kwh: float = 0,    # saldo a expirar em 30 dias
    scee_saldo_exp_60d_kwh: float = 0,    # saldo a expirar em 60 dias
    usinas_geradoras:       list = None,  # NOVO — lista de {uc, geracao_kwh, excedente_kwh}
) -> None:
    """Insere ou ATUALIZA uma fatura em tb_faturas.

    Se ja existe entrada para o mesmo (id_cliente, ano, mes), faz UPDATE
    preservando status e dt_pagamento existentes (nao zerar "pago" se
    estava marcado).

    Use esta funcao em modulos que nao podem importar de app.py
    (ex: baixar_equatorial.py, gerar_cobranca_auto.py).

    Renomeada de inserir_historico() na etapa 7B.5."""
    import re as _re_ih

    # Verifica se ja existe fatura para reusar status/dt_pagamento
    existing_status = "Aguardando pagamento"
    id_cli = None
    try:
        id_cli = _resolver_id_cliente_por_uc(uc)
        m = _re_ih.match(r"^(\d{1,2})/(\d{4})$", str(mes_ref or "").strip())
        if id_cli and m:
            mes_int = int(m.group(1)); ano_int = int(m.group(2))
            existentes = _db().select(
                "tb_faturas",
                columns="status,dt_pagamento",
                filtros={"id_cliente": id_cli,
                         "ano_referencia": ano_int,
                         "mes_referencia": mes_int},
            )
            if existentes:
                st_atual = existentes[0].get("status") or "pendente"
                dt_pgto  = existentes[0].get("dt_pagamento")
                if st_atual == "pago" and dt_pgto:
                    # reconstroi formato legado para passar a _upsert_tb_faturas
                    try:
                        from datetime import datetime as _dt2
                        d_br = _dt2.fromisoformat(str(dt_pgto)).strftime("%d/%m/%Y")
                        existing_status = f"Pago em {d_br}"
                    except (ValueError, TypeError):
                        existing_status = "Pago"
                elif st_atual == "cancelado":
                    existing_status = "Cancelado"
    except Exception as _e:
        print(f"[DB] Aviso: nao foi possivel verificar fatura existente: {_e}")

    # Grava em tb_faturas (unica tabela de escrita agora)
    try:
        _upsert_tb_faturas(
            uc=uc, mes_ref=mes_ref,
            total_sem=total_sem, total_com=total_com,
            economia_mes=economia_mes, economia_acum=economia_acum,
            compensacao_dic=compensacao_dic,
            consumo_kwh=consumo_kwh, compensado_kwh=compensado_kwh,
            saldo_kwh=saldo_kwh,
            venc_solev=venc, venc_equatorial=venc_equatorial,
            data_leitura_atual=data_leitura_atual,
            existing_status=existing_status,
            pdf_solev=pdf_path, pdf_solev_url=pdf_url,
            pdf_equatorial=pdf_equatorial, pdf_equatorial_url=pdf_equatorial_url,
            multa_equatorial=multa_equatorial, juros_equatorial=juros_equatorial,
            multa_mes=multa_mes, juros_mes=juros_mes,
            fatura_equatorial=fatura_equatorial, fio_b=fio_b,
            ilum_publica=ilum_publica,
            band_amar_equatorial=band_amar_equatorial,
            band_verm_equatorial=band_verm_equatorial,
            band_amar_solev=band_amar_solev,
            band_verm_solev=band_verm_solev,
            ajuste_valor=ajuste_valor,
            difci=difci,
            ecnisenta=ecnisenta,
            anterior_leitura=anterior_leitura,
            n_dias=n_dias,
            scee_ciclo_mes=scee_ciclo_mes,
            scee_uc_geradora=scee_uc_geradora,
            scee_pct_rateio=scee_pct_rateio,
            scee_geracao_usina_kwh=scee_geracao_usina_kwh,
            scee_excedente_kwh=scee_excedente_kwh,
            scee_credito_kwh=scee_credito_kwh,
            scee_saldo_exp_30d_kwh=scee_saldo_exp_30d_kwh,
            scee_saldo_exp_60d_kwh=scee_saldo_exp_60d_kwh,
            usinas_geradoras=usinas_geradoras,
        )
    except Exception as e:
        print(f"  [DB] ERRO ao inserir em tb_faturas: {e}")
        raise

    # Writeback automático: atualiza proxima_leitura no cadastro do cliente.
    # Prioridade: campo extraído do PDF Equatorial ("PROXIMA LEITURA"); se
    # ausente, aproxima por dt_leitura_atual + n_dias (1 ciclo da Equatorial).
    try:
        dt_iso = _parse_data_br_iso(str(proxima_leitura)) if proxima_leitura else None
        if not dt_iso and data_leitura_atual:
            base_iso = _parse_data_br_iso(str(data_leitura_atual))
            if base_iso:
                from datetime import datetime as _dt3, timedelta as _td3
                ciclo = int(n_dias) if n_dias else 30
                dt_iso = (_dt3.fromisoformat(base_iso) + _td3(days=ciclo)).strftime("%Y-%m-%d")
        if dt_iso and id_cli:
            _db().patch("tb_clientes", {"id_cliente": id_cli},
                        {"proxima_leitura": dt_iso})
    except Exception as _e:
        print(f"  [DB] Aviso: writeback proxima_leitura falhou: {_e}")


def _resolver_id_cliente_por_uc(uc: str) -> Optional[int]:
    """Busca id_cliente em tb_clientes por cod_uc ou cod_uc
    (com ou sem zeros a esquerda). Retorna None se nao achar."""
    import re as _re
    digits = _re.sub(r"\D", "", str(uc or ""))
    if not digits:
        return None
    db = _db()
    for col in ("cod_uc", "cod_uc"):
        for valor in (digits, digits.lstrip("0") or digits):
            try:
                rows = db.select("tb_clientes", columns="id_cliente",
                                 filtros={col: valor})
                if rows:
                    return rows[0].get("id_cliente")
            except Exception:
                pass
    return None


def _parse_data_br_iso(v: str) -> Optional[str]:
    """'dd/mm/aaaa' (com ou sem hora) -> 'YYYY-MM-DD'. None se invalido."""
    from datetime import datetime as _dt
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return _dt.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _upsert_tb_faturas(
    uc: str, mes_ref: str,
    total_sem: float, total_com: float,
    economia_mes: float, economia_acum: float,
    compensacao_dic: float,
    consumo_kwh: float, compensado_kwh: float, saldo_kwh: float,
    venc_solev: str, venc_equatorial: str, data_leitura_atual: str,
    existing_status: str,
    pdf_solev: str, pdf_solev_url: str,
    pdf_equatorial: str, pdf_equatorial_url: str,
    multa_equatorial: float = 0, juros_equatorial: float = 0,
    multa_mes: float = 0, juros_mes: float = 0,
    fatura_equatorial: float = 0, fio_b: float = 0, ilum_publica: float = 0,
    band_amar_equatorial: float = 0, band_verm_equatorial: float = 0,
    band_amar_solev:   float = 0, band_verm_solev:   float = 0,
    ajuste_valor:         float = 0,
    difci:                float = 0,
    ecnisenta:            float = 0,
    anterior_leitura:     str = "",
    n_dias:               int = 0,
    scee_ciclo_mes:         str   = "",
    scee_uc_geradora:       str   = "",
    scee_pct_rateio:          float = 0,
    scee_geracao_usina_kwh:   float = 0,
    scee_excedente_kwh:       float = 0,
    scee_credito_kwh:       float = 0,
    scee_saldo_exp_30d_kwh: float = 0,
    scee_saldo_exp_60d_kwh: float = 0,
    usinas_geradoras:       list = None,
) -> None:
    """Faz upsert em tb_faturas a partir dos mesmos dados que vao para historico.

    UNIQUE (id_cliente, ano_referencia, mes_referencia) garante 1 fatura/mes.
    Se mes_referencia ou cliente nao puderem ser resolvidos, levanta ValueError."""
    import os as _os
    import re as _re
    from datetime import datetime as _dt

    # 1) Resolver id_cliente
    id_cliente = _resolver_id_cliente_por_uc(uc)
    if not id_cliente:
        raise ValueError(f"UC {uc!r} sem cliente em tb_clientes")

    # 2) Parse mes_referencia 'MM/AAAA' -> (ano, mes)
    m = _re.match(r"^(\d{1,2})/(\d{4})$", str(mes_ref or "").strip())
    if not m:
        raise ValueError(f"mes_referencia invalido: {mes_ref!r}")
    mes = int(m.group(1)); ano = int(m.group(2))

    # 3) Status: pago/pendente + dt_pagamento
    s = (existing_status or "").lower()
    if s.startswith("pago"):
        status_enum = "pago"
        m2 = _re.search(r"(\d{1,2}/\d{1,2}/\d{4})", s)
        dt_pgto = _parse_data_br_iso(m2.group(1)) if m2 else None
    elif s.startswith("cancel"):
        status_enum, dt_pgto = "cancelado", None
    else:
        status_enum, dt_pgto = "pendente", None

    # 4) Monta o registro
    reg = {
        "id_cliente":          id_cliente,
        "ano_referencia":      ano,
        "mes_referencia":      mes,

        "vlr_total_sem":       round(float(total_sem or 0), 2),
        "vlr_total_com":       round(float(total_com or 0), 2),
        "vlr_economia_mes":    round(float(economia_mes or 0), 2),
        "vlr_economia_acum":   round(float(economia_acum or 0), 2),
        "vlr_compensacao_dic": round(float(compensacao_dic or 0), 2),

        # Multa/juros — 3 origens distintas
        "vlr_multa_equatorial": round(float(multa_equatorial or 0), 2),
        "vlr_juros_equatorial": round(float(juros_equatorial or 0), 2),
        "vlr_multa_mes":        round(float(multa_mes or 0), 2),
        "vlr_juros_mes":        round(float(juros_mes or 0), 2),
        # vlr_multa_proxima / vlr_juros_proxima — preenchidas em tb_marcar_fatura_pago

        # Campos extraidos diretamente da fatura Equatorial (do PDF)
        "vlr_fatura_equatorial": round(float(fatura_equatorial or 0), 2),
        "vlr_fio_b":             round(float(fio_b or 0), 2),
        "vlr_ilum_publica":      round(float(ilum_publica or 0), 2),

        # Bandeira tarifaria — 2 fontes (Equatorial via PDF + CONTALEV calculado)
        "vlr_band_amar_equatorial": round(float(band_amar_equatorial or 0), 2),
        "vlr_band_verm_equatorial": round(float(band_verm_equatorial or 0), 2),
        "vlr_band_amar_solev":   round(float(band_amar_solev   or 0), 2),
        "vlr_band_verm_solev":   round(float(band_verm_solev   or 0), 2),

        "ajuste_valor":             round(float(ajuste_valor or 0), 2),
        "difci":                    round(float(difci or 0), 2),
        "ecnisenta":                round(float(ecnisenta or 0), 2),
        "anterior_leitura":         str(anterior_leitura or ""),
        "n_dias":                   int(n_dias or 0),

        "qtd_consumo_kwh":     round(float(consumo_kwh or 0), 2),
        "qtd_compensado_kwh":  round(float(compensado_kwh or 0), 2),
        "qtd_saldo_kwh":       round(float(saldo_kwh or 0), 2),

        # SCEE — dados da geração solar deste mês
        "desc_ciclo_geracao":       str(scee_ciclo_mes or ""),
        "cod_uc_usina":             str(scee_uc_geradora or ""),
        "pct_rateio_scee":          round(float(scee_pct_rateio or 0), 4),
        "qtd_geracao_usina_kwh":    round(float(scee_geracao_usina_kwh or 0), 2),
        "qtd_excedente_kwh":        round(float(scee_excedente_kwh or 0), 2),
        "qtd_credito_kwh":          round(float(scee_credito_kwh or 0), 2),
        "qtd_saldo_exp_30d_kwh":    round(float(scee_saldo_exp_30d_kwh or 0), 2),
        "qtd_saldo_exp_60d_kwh":    round(float(scee_saldo_exp_60d_kwh or 0), 2),

        # Lista detalhada de usinas geradoras (multi-usina por UC)
        "usinas_geradoras":   usinas_geradoras or [],

        "dt_geracao":          _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status":              status_enum,
    }
    # Datas opcionais (so envia se conseguir parsear)
    for chave_dest, valor_origem in (
        ("dt_venc_solev",   venc_solev),
        ("dt_venc_equatorial", venc_equatorial),
        ("dt_leitura_atual",   data_leitura_atual),
    ):
        iso = _parse_data_br_iso(valor_origem)
        if iso:
            reg[chave_dest] = iso
    if dt_pgto:
        reg["dt_pagamento"] = dt_pgto

    if pdf_solev:
        reg["pdf_solev"] = _os.path.basename(pdf_solev)
    if pdf_solev_url:
        reg["pdf_solev_url"] = pdf_solev_url
    if pdf_equatorial:
        reg["pdf_equatorial"] = _os.path.basename(pdf_equatorial)
    if pdf_equatorial_url:
        reg["pdf_equatorial_url"] = pdf_equatorial_url

    _db().upsert("tb_faturas", [reg],
                 on_conflict="id_cliente,ano_referencia,mes_referencia")
    print(f"  [DB] tb_faturas upsert cliente={id_cliente} {mes:02d}/{ano} "
          f"status={status_enum} total_com=R${reg['vlr_total_com']:.2f}")

    # Recalcula economia_acumulada do cliente de forma idempotente.
    # Garante consistência mesmo em caso de re-submit ou múltiplas chamadas.
    try:
        novo_acum = recalcular_economia_acumulada(id_cliente)
        print(f"  [DB] economia_acum recalculada: R${novo_acum:.2f}")
    except Exception as _e:
        print(f"  [DB] AVISO: falha ao recalcular economia_acum: {_e}")


# ==================================================================
#  TARIFAS
# ==================================================================
_COLS_TARIFA = ["mes_referencia", "tarifa_sem", "bandeira_amarela",
                "bandeira_vermelha", "fio_b", "observacao"]


def carregar_tarifas() -> dict:
    rows = _db().select("tarifas", order="mes_referencia.asc")
    out = {}
    for row in rows:
        mes = row.pop("mes_referencia", None)
        row.pop("atualizado_em", None)
        if mes:
            out[str(mes)] = _limpar_nulos(row)
    return out


def salvar_tarifas(tarifas: dict) -> None:
    if not tarifas:
        return
    rows = []
    for mes, t in tarifas.items():
        row = {"mes_referencia": str(mes)}
        for col in _COLS_TARIFA:
            if col == "mes_referencia":
                continue
            if col in t:
                row[col] = t[col]
        rows.append(row)
    _db().upsert("tarifas", rows, on_conflict="mes_referencia")


def salvar_tarifa_mes(mes_ref: str, dados: dict, mes_ref_antigo: str = None) -> None:
    """Salva ou atualiza UMA tarifa. Usa PATCH para evitar duplicatas por falta de constraint."""
    db = _db()
    campos = {col: dados.get(col) for col in _COLS_TARIFA if col != "mes_referencia"}

    if mes_ref_antigo and mes_ref_antigo != mes_ref:
        db.delete("tarifas", {"mes_referencia": mes_ref_antigo})
        db.upsert("tarifas", [{"mes_referencia": str(mes_ref), **campos}], on_conflict="mes_referencia")
    else:
        db.patch("tarifas", {"mes_referencia": str(mes_ref)}, campos)


# ==================================================================
#  GERACAO MENSAL  {uid: {mes_ref: dados}}
# ==================================================================
_COLS_GER_MENSAL = ["kwh_gerado", "data_leitura_anterior", "data_leitura_atual",
                    "n_dias", "saldo_kwh", "excedente_kwh",
                    "data_registro", "origem", "fatura_pdf"]


def carregar_geracao_mensal() -> dict:
    rows = _db().select("geracao_mensal")
    out = {}
    for row in rows:
        id_usina = row.pop("id_usina", None)
        mes = row.pop("mes_referencia", None)
        row.pop("atualizado_em", None)
        if not id_usina or not mes:
            continue
        out.setdefault(str(id_usina), {})[str(mes)] = _limpar_nulos(row)
    return out


def salvar_geracao_mensal(dados: dict) -> None:
    if not dados:
        return
    rows = []
    for uid, meses in dados.items():
        for mes, g in meses.items():
            row = {
                "id_usina": int(uid),
                "mes_referencia": str(mes),
            }
            for col in _COLS_GER_MENSAL:
                if col in g:
                    row[col] = g[col]
            rows.append(row)
    if rows:
        _db().upsert("geracao_mensal", rows, on_conflict="id_usina,mes_referencia")


# ==================================================================
#  GERACAO DIARIA  {uid: [{data, kwh, obs}, ...]}
# ==================================================================
def carregar_geracao() -> dict:
    rows = _db().select("geracao_diaria", order="data.asc")
    out: dict = {}
    for row in rows:
        uid = str(row.get("id_usina", ""))
        if not uid:
            continue
        out.setdefault(uid, []).append({
            "data": row.get("data", "") or "",
            "kwh": row.get("kwh", 0) or 0,
            "obs": row.get("obs", "") or "",
        })
    return out


def salvar_geracao(dados: dict) -> None:
    """Substitui integralmente a geracao diaria (delete + upsert por usina)."""
    if not dados:
        return
    for uid, registros in dados.items():
        _db().delete("geracao_diaria", {"id_usina": int(uid)})
        rows = [{
            "id_usina": int(uid),
            "data": r.get("data", ""),
            "kwh": r.get("kwh", 0),
            "obs": r.get("obs", ""),
        } for r in registros]
        if rows:
            _db().upsert("geracao_diaria", rows, on_conflict="id_usina,data")


# ==================================================================
#  INVESTIDOR HISTORICO (lista)
# ==================================================================
_COLS_INV_HIST = [
    "uid", "usina_nome", "investidor_nome", "investidor_cpf_cnpj",
    "investidor_banco", "investidor_agencia", "investidor_conta",
    "investidor_pix", "mes_referencia", "kwh_gerado",
    "tarifa_equatorial", "valor_bruto", "valor_minimo",
    "valor_liquido", "dia_pagamento", "data_geracao",
    "uc_geradora", "pdf", "fio_b",
    "desagio_pct", "valor_desagio", "valor_com_desagio",
]


# ==================================================================
#  SIMULACOES (tb_simulacoes)
# ==================================================================
def carregar_simulacoes() -> list:
    """Retorna lista de simulacoes ordenada da mais recente para a mais antiga.
    Cada item e o dict 'dados' com 'id', 'status' e 'pdf' sobrepostos das colunas indexadas."""
    rows = _db().select("tb_simulacoes", order="criado_em.desc")
    out = []
    for r in rows:
        sim = dict(r.get("dados") or {})
        sim["id"]             = r["id"]
        sim["nome"]           = r.get("nome") or sim.get("nome", "")
        sim["uc"]             = r.get("uc") or sim.get("uc", "")
        sim["mes_referencia"] = r.get("mes_referencia") or sim.get("mes_referencia", "")
        sim["status"]         = r.get("status") or sim.get("status", "Pendente")
        sim["pdf"]            = r.get("pdf") or sim.get("pdf", "")
        out.append(sim)
    return out


def salvar_simulacao(sim: dict) -> int:
    """Insere uma simulacao, removendo duplicatas (mesmo nome+uc+mes_referencia). Retorna o id."""
    nome = sim.get("nome", "")
    uc   = sim.get("uc", "")
    mes  = sim.get("mes_referencia", "")
    # Remove duplicatas existentes
    if nome and mes:
        dups = _db().select("tb_simulacoes", columns="id",
                            filtros={"nome": nome, "uc": uc or "", "mes_referencia": mes})
        for dup in dups:
            _db().delete("tb_simulacoes", {"id": dup["id"]})
    row = {
        "nome":          nome,
        "uc":            uc,
        "mes_referencia": mes,
        "status":        sim.get("status", "Pendente"),
        "pdf":           sim.get("pdf", ""),
        "dados":         sim,
    }
    result = _db().upsert_returning("tb_simulacoes", row)
    return result.get("id")


def atualizar_simulacao(id_sim: int, **campos) -> None:
    """Atualiza colunas indexadas e/ou o JSONB dados de uma simulacao."""
    _COLS = {"nome", "uc", "mes_referencia", "status", "pdf"}
    update = {k: v for k, v in campos.items() if k in _COLS}
    if update:
        _db().patch("tb_simulacoes", {"id": id_sim}, update)


def deletar_simulacao(id_sim: int) -> None:
    """Remove uma simulacao pelo id."""
    _db().delete("tb_simulacoes", {"id": id_sim})


def carregar_investidor_hist() -> list:
    rows = _db().select("investidor_historico", order="data_geracao.desc")
    out = []
    for row in rows:
        row.pop("id", None)
        row.pop("atualizado_em", None)
        if "desagio_pct" in row:
            row["desagio_pct"] = row.pop("desagio_pct")
        if "valor_desagio" in row:
            row["valor_desagio"] = row.pop("valor_desagio")
        if "valor_com_desagio" in row:
            row["valor_com_desagio"] = row.pop("valor_com_desagio")
        out.append(_limpar_nulos(row))
    return out


def salvar_investidor_hist(historico: list) -> None:
    if not historico:
        return
    rows = []
    for item in historico:
        row = {}
        for col in _COLS_INV_HIST:
            if col == "desagio_pct":
                if "desagio_pct" in item:
                    row[col] = item["desagio_pct"]
                elif "desagio_pct" in item:
                    row[col] = item["desagio_pct"]
            elif col == "valor_desagio":
                if "valor_desagio" in item:
                    row[col] = item["valor_desagio"]
                elif "valor_desagio" in item:
                    row[col] = item["valor_desagio"]
            elif col == "valor_com_desagio":
                if "valor_com_desagio" in item:
                    row[col] = item["valor_com_desagio"]
                elif "valor_com_desagio" in item:
                    row[col] = item["valor_com_desagio"]
            elif col in item:
                row[col] = item[col]
        rows.append(row)
    _db().upsert("investidor_historico", rows, on_conflict="uid,mes_referencia")


# ==================================================================
#  MIGRACAO ONE-SHOT: clientes.json -> Supabase
# ==================================================================
def migrar_clientes_do_json(caminho_json: Optional[str] = None) -> int:
    """Le clientes.json local e envia tudo para o Supabase.
    Chame isso UMA VEZ para migrar os dados existentes.
    Retorna o numero de clientes enviados.
    """
    if caminho_json is None:
        caminho_json = os.path.join(_DIR, "clientes.json")
    if not os.path.exists(caminho_json):
        print(f"[MIGRACAO] Arquivo {caminho_json} nao encontrado.")
        return 0
    with open(caminho_json, "r", encoding="utf-8") as f:
        clientes = json.load(f)
    if not clientes:
        print("[MIGRACAO] clientes.json vazio.")
        return 0
    print(f"[MIGRACAO] Enviando {len(clientes)} clientes para o Supabase...")
    salvar_clientes(clientes)
    print(f"[MIGRACAO] OK! {len(clientes)} clientes migrados.")
    return len(clientes)


# ==================================================================
#  CLI
# ==================================================================
def migrar_tudo_do_json() -> None:
    """Migra TODOS os JSONs locais para o Supabase (one-shot)."""
    def _ler(nome):
        p = os.path.join(_DIR, nome)
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    print("[MIGRACAO] Iniciando migracao completa...")

    # historico.json removido: tabela historico foi congelada (etapa 7B);
    # nova fatura agora vai direto para tb_faturas via inserir_fatura.
    for nome, salvar in [
        ("usinas.json",               salvar_usinas),
        ("clientes.json",             salvar_clientes),
        ("tarifas.json",              salvar_tarifas),
        ("geracao_mensal.json",       salvar_geracao_mensal),
        ("geracao.json",              salvar_geracao),
        ("investidor_historico.json", salvar_investidor_hist),
    ]:
        data = _ler(nome)
        if not data:
            print(f"  [-] {nome} vazio/inexistente, pulando.")
            continue
        try:
            salvar(data)
            qtd = len(data) if not isinstance(data, list) else len(data)
            print(f"  [OK] {nome}: {qtd} registros enviados")
        except Exception as e:
            print(f"  [ERRO] {nome}: {e}")

    print("[MIGRACAO] Concluida.")


# ==================================================================
#  TB_FATURAS — leitura (estrutura nova normalizada)
# ==================================================================
_FATURA_COLS_EMBED = (
    "*,tb_clientes(id_cliente,desc_nome,desc_apelido,cod_uc)"
)


def _enriquecer_fatura(row: dict) -> dict:
    """Achata o cliente embedded em campos planos para o template,
    e adiciona campos derivados uteis."""
    cliente = row.pop("tb_clientes", None) or {}
    row["_nome"]              = cliente.get("desc_nome", "") or ""
    row["_apelido"]           = cliente.get("desc_apelido", "") or ""
    row["_cod_uc"]            = cliente.get("cod_uc", "") or ""

    mes = row.get("mes_referencia") or 0
    ano = row.get("ano_referencia") or 0
    row["_mes_ref_br"] = f"{int(mes):02d}/{int(ano)}" if mes and ano else ""

    from datetime import date as _date
    if row.get("status") == "pendente" and row.get("dt_venc_solev"):
        try:
            dv = _date.fromisoformat(row["dt_venc_solev"])
            row["_vencido"] = dv < _date.today()
        except (ValueError, TypeError):
            row["_vencido"] = False
    else:
        row["_vencido"] = False
    return row


def tb_get_fatura_por_id(id_fatura) -> Optional[dict]:
    rows = _db().select("tb_faturas",
                        columns=_FATURA_COLS_EMBED,
                        filtros={"id_fatura": id_fatura})
    if not rows:
        return None
    return _enriquecer_fatura(rows[0])


def tb_get_faturas_por_cliente(id_cliente: int, limite: int = 100) -> list:
    rows = _db().select("tb_faturas",
                        columns=_FATURA_COLS_EMBED,
                        filtros={"id_cliente": id_cliente},
                        order="ano_referencia.desc,mes_referencia.desc")
    return [_enriquecer_fatura(r) for r in rows[:limite]]


def tb_get_faturas_paginado(
    page: int = 1, per_page: int = 20,
    busca: str = "",
    ano: Optional[int] = None, mes: Optional[int] = None,
    status: str = "todos",
) -> tuple:
    """Lista paginada com filtros server-side. Retorna (lista, total)."""
    db = _db()
    offset = (page - 1) * per_page
    fim    = offset + per_page - 1

    select_cols = _FATURA_COLS_EMBED
    if busca and busca.strip():
        select_cols = select_cols.replace(
            "tb_clientes(", "tb_clientes!inner("
        )
    params = {
        "select": select_cols,
        "order":  "ano_referencia.desc,mes_referencia.desc,id_fatura.desc",
    }
    if ano:
        params["ano_referencia"] = f"eq.{int(ano)}"
    if mes:
        params["mes_referencia"] = f"eq.{int(mes)}"
    if status == "pendente":
        params["status"] = "eq.pendente"
    elif status == "pago":
        params["status"] = "eq.pago"
    elif status == "cancelado":
        params["status"] = "eq.cancelado"
    elif status == "vencido":
        from datetime import date as _date
        params["status"]            = "eq.pendente"
        params["dt_venc_solev"]  = f"lt.{_date.today().isoformat()}"

    if busca and busca.strip():
        b = busca.strip().replace("'", "")
        params["tb_clientes.or"] = (
            f"(desc_nome.ilike.*{b}*,"
            f"cod_uc.ilike.*{b}*,"
            f"cod_uc.ilike.*{b}*)"
        )

    headers = {
        **db.headers,
        "Range":      f"{offset}-{fim}",
        "Range-Unit": "items",
        "Prefer":     "count=exact",
    }
    resp = db._retry(lambda: db.client.get(
        f"{db.base}/tb_faturas", params=params, headers=headers
    ))
    resp.raise_for_status()

    total = 0
    cr = resp.headers.get("Content-Range", "")
    if "/" in cr:
        try:
            total = int(cr.split("/")[1])
        except Exception:
            pass

    rows = [_enriquecer_fatura(r) for r in resp.json()]
    return rows, total


def tb_get_faturas_pendentes_ordenadas() -> list:
    rows = _db().select("tb_faturas",
                        columns=_FATURA_COLS_EMBED,
                        filtros={"status": "pendente"},
                        order="dt_venc_solev.asc.nullslast")
    return [_enriquecer_fatura(r) for r in rows]


def tb_sync_proxima_leitura_por_fatura() -> dict:
    """Atualiza proxima_leitura em tb_clientes para cada cliente, projetando
    a próxima leitura como dt_leitura_atual + n_dias (1 ciclo Equatorial) da
    fatura mais recente.

    Retorna um dict com contagens: {'atualizados': N, 'sem_data': M, 'erros': K}
    """
    from datetime import datetime as _dt_s, timedelta as _td_s
    db = _db()
    rows = db.select(
        "tb_faturas",
        columns="id_cliente,dt_leitura_atual,n_dias,ano_referencia,mes_referencia",
        order="id_cliente.asc,ano_referencia.desc,mes_referencia.desc",
    )

    # Para cada cliente, pega a fatura mais recente (já ordenada desc)
    mais_recente: dict[int, str] = {}
    for r in rows:
        id_c = r.get("id_cliente")
        dt_atual = r.get("dt_leitura_atual")
        if not id_c or not dt_atual or id_c in mais_recente:
            continue
        try:
            ciclo = int(r.get("n_dias") or 0) or 30
            proj = (_dt_s.fromisoformat(str(dt_atual)) + _td_s(days=ciclo)).strftime("%Y-%m-%d")
            mais_recente[id_c] = proj
        except (ValueError, TypeError):
            continue

    atualizados = 0
    erros = 0
    for id_c, dt in mais_recente.items():
        try:
            db.patch("tb_clientes", {"id_cliente": id_c}, {"proxima_leitura": dt})
            atualizados += 1
        except Exception:
            erros += 1

    return {"atualizados": atualizados, "sem_data": len(rows) - len(mais_recente), "erros": erros}


def tb_marcar_fatura_pago(
    id_fatura: int, dt_pagamento: str,
    vlr_pago: float = None,
    vlr_multa_proxima: float = None, vlr_juros_proxima: float = None,
) -> dict:
    """Marca uma fatura como paga.

    vlr_pago         : valor que o cliente efetivamente pagou (geralmente
                       igual ao vlr_total_com — sem multa/juros).
    vlr_multa_proxima: multa CONTALEV calculada agora pelo atraso desta
                       fatura — sera cobrada na PROXIMA fatura do cliente.
    vlr_juros_proxima: idem para juros.
    """
    campos = {"status": "pago", "dt_pagamento": dt_pagamento}
    if vlr_pago is not None:
        campos["vlr_pago"] = round(float(vlr_pago), 2)
    if vlr_multa_proxima is not None:
        campos["vlr_multa_proxima"] = round(float(vlr_multa_proxima), 2)
    if vlr_juros_proxima is not None:
        campos["vlr_juros_proxima"] = round(float(vlr_juros_proxima), 2)
    _db().patch("tb_faturas", {"id_fatura": id_fatura}, campos)
    return {"id_fatura": id_fatura, **campos}


def tb_reservar_id_fatura(id_cliente: int, ano: int, mes: int) -> int:
    """Garante existencia de uma fatura para (id_cliente, ano, mes) e retorna
    o id_fatura. Cria placeholder com status='pendente' se nao existir.

    Util para reservar o id ANTES de gerar o PDF, ja que o nome do arquivo
    precisa do id_fatura no final.
    """
    db = _db()
    rows = db.select("tb_faturas", columns="id_fatura",
                     filtros={"id_cliente":     id_cliente,
                              "ano_referencia": ano,
                              "mes_referencia": mes})
    if rows:
        return int(rows[0]["id_fatura"])
    # Cria placeholder. Posteriormente inserir_fatura faz upsert e popula
    # os demais campos.
    novo = db.upsert_returning(
        "tb_faturas",
        {"id_cliente":      id_cliente,
         "ano_referencia":  ano,
         "mes_referencia":  mes,
         "status":          "pendente"},
        on_conflict="id_cliente,ano_referencia,mes_referencia",
    )
    return int(novo["id_fatura"])


def tb_get_multa_juros_proxima(id_cliente: int, ano: int, mes: int) -> dict:
    """Retorna a multa/juros 'proxima' que deve ser cobrada na fatura
    (ano, mes), buscando na fatura PAGA do periodo anterior.

    Retorna {'vlr_multa': X, 'vlr_juros': Y}. Zeros se nao houver fatura
    paga no periodo anterior, ou se ela nao tiver atraso registrado.

    Logica:
    - Periodo anterior = (ano, mes-1), com transicao de ano em janeiro
    - Busca em tb_faturas com status='pago'
    - Le vlr_multa_proxima + vlr_juros_proxima (preenchidos no momento
      da baixa quando o cliente atrasou)
    """
    if mes == 1:
        ano_ant, mes_ant = ano - 1, 12
    else:
        ano_ant, mes_ant = ano, mes - 1
    try:
        rows = _db().select(
            "tb_faturas",
            columns="id_fatura,vlr_multa_proxima,vlr_juros_proxima,status",
            filtros={
                "id_cliente":     id_cliente,
                "ano_referencia": ano_ant,
                "mes_referencia": mes_ant,
                "status":         "pago",
            },
        )
        if rows:
            return {
                "vlr_multa": float(rows[0].get("vlr_multa_proxima") or 0),
                "vlr_juros": float(rows[0].get("vlr_juros_proxima") or 0),
                "id_fatura_origem": rows[0].get("id_fatura"),
            }
    except Exception as e:
        print(f"[DB] Aviso: falha ao buscar multa/juros proxima: {e}")
    return {"vlr_multa": 0.0, "vlr_juros": 0.0, "id_fatura_origem": None}


def tb_cancelar_fatura(id_fatura: int) -> None:
    _db().patch("tb_faturas", {"id_fatura": id_fatura}, {"status": "cancelado"})


def tb_delete_fatura(id_fatura: int) -> None:
    _db().delete("tb_faturas", {"id_fatura": id_fatura})


def tb_resumo_faturas_por_periodo(ano: int, mes: int = None) -> dict:
    db = _db()
    params = {
        "select": "status,vlr_total_com,vlr_pago",
        "ano_referencia": f"eq.{int(ano)}",
    }
    if mes:
        params["mes_referencia"] = f"eq.{int(mes)}"
    headers = {**db.headers, "Range": "0-999999"}
    resp = db._retry(lambda: db.client.get(
        f"{db.base}/tb_faturas", params=params, headers=headers
    ))
    resp.raise_for_status()
    rows = resp.json()

    out = {"pendente": {"count": 0, "soma_total": 0.0},
           "pago":     {"count": 0, "soma_total": 0.0, "soma_pago": 0.0},
           "cancelado":{"count": 0, "soma_total": 0.0},
           "total_geral": len(rows)}
    for r in rows:
        st = r.get("status") or "pendente"
        if st not in out:
            continue
        out[st]["count"] += 1
        out[st]["soma_total"] += float(r.get("vlr_total_com") or 0)
        if st == "pago":
            out["pago"]["soma_pago"] += float(r.get("vlr_pago") or r.get("vlr_total_com") or 0)
    return out


# ==================================================================
#  DOCUMENTOS DE CLIENTES
# ==================================================================

def storage_delete_arquivo(storage_path: str) -> None:
    """Remove arquivo do Supabase Storage. Nao levanta excecao se nao existir."""
    import httpx
    url, key = _storage_cfg()
    base = f"{url}/storage/v1"
    parts = storage_path.split("/", 1)
    bucket = parts[0]
    file_path = parts[1] if len(parts) > 1 else storage_path
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    try:
        httpx.delete(f"{base}/object/{bucket}/{file_path}", headers=headers, timeout=15)
    except Exception:
        pass


def tb_get_outras_ucs(id_cliente: int, desc_cpf: str = "", desc_nome: str = "") -> list:
    """Retorna outros registros de cliente com mesmo CPF (ou mesmo nome se sem CPF),
    excluindo o id_cliente informado. Usado para listar múltiplas UCs da mesma pessoa."""
    db = _db()
    candidatos = []
    if desc_cpf and desc_cpf.strip():
        cpf = desc_cpf.strip()
        rows = db.select("tb_clientes", raw_params={"desc_cpf": f"eq.{cpf}"})
        candidatos = [r for r in (rows or []) if r.get("id_cliente") != id_cliente]
    if not candidatos and desc_nome and desc_nome.strip():
        nome = desc_nome.strip()
        rows = db.select("tb_clientes", raw_params={"desc_nome": f"eq.{nome}"})
        candidatos = [r for r in (rows or []) if r.get("id_cliente") != id_cliente]
    return candidatos


def tb_get_documentos_cliente(id_cliente: int) -> list:
    """Lista documentos salvos de um cliente, mais recente primeiro."""
    try:
        rows = _db().select(
            "tb_documentos_cliente",
            filtros={"id_cliente": id_cliente},
            order="created_at.desc",
        )
        return rows or []
    except Exception:
        return []


def tb_save_documento_cliente(id_cliente: int, nome_arquivo: str,
                               tipo_doc: str, storage_path: str) -> dict:
    """Insere registro de documento na tabela tb_documentos_cliente."""
    row = {
        "id_cliente": id_cliente,
        "nome_arquivo": nome_arquivo,
        "tipo_doc": tipo_doc,
        "storage_path": storage_path,
    }
    return _db().upsert_returning("tb_documentos_cliente", row)


def tb_delete_documento_cliente(id_doc: int) -> None:
    """Remove registro de documento pelo id."""
    _db().delete("tb_documentos_cliente", {"id": id_doc})


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "migrar-clientes":
        migrar_clientes_do_json()
    elif cmd == "migrar-tudo":
        migrar_tudo_do_json()
    elif cmd == "listar-clientes":
        clientes = carregar_clientes()
        print(f"Total: {len(clientes)} clientes")
        for uc, c in list(clientes.items())[:5]:
            print(f"  {uc}: {c.get('nome', '?')}")
    else:
        print("Uso:")
        print("  python db.py migrar-clientes   -> envia clientes.json para o Supabase")
        print("  python db.py migrar-tudo       -> envia TODOS os JSONs para o Supabase")
        print("  python db.py listar-clientes   -> lista primeiros 5 clientes do Supabase")

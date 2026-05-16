"""
CONTALEV — Launcher v5
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
· Microsoft Edge em modo --app (janela standalone, sem abas)
· Perfil dedicado + AppUserModelID  → ícone CONTALEV na barra
· Sem CMD visível · Flask sobe em paralelo
· Fallback: Chrome --app  →  navegador padrão
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import sys, os, subprocess, socket, time, http.client, traceback

_DIR      = os.path.dirname(os.path.abspath(__file__))
URL       = "http://localhost:5000"
ICO       = os.path.join(_DIR, "contalev.ico")
PROFILE   = os.path.join(_DIR, ".webview_storage")
APP_ID    = "CONTALEV.Sistema.v2"   # AppUserModelID — agrupa janela sob ícone próprio
LOG       = os.path.join(_DIR, "launcher.log")


def _log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


# ═══════════════════════════════════════════════
#  Windows: AppUserModelID (taskbar grouping)
# ═══════════════════════════════════════════════

def _set_app_user_model_id():
    """Diz ao Windows: minha janela pertence ao grupo CONTALEV, não ao Chrome/Edge."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


# ═══════════════════════════════════════════════
#  Flask
# ═══════════════════════════════════════════════

def _porta_aberta():
    try:
        socket.create_connection(("localhost", 5000), timeout=0.2).close()
        return True
    except OSError:
        return False


def _iniciar_flask():
    kw = {}
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kw = dict(startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW)
    subprocess.Popen(
        [sys.executable, os.path.join(_DIR, "app.py")],
        cwd=_DIR, **kw
    )


def _flask_respondendo():
    try:
        conn = http.client.HTTPConnection("localhost", 5000, timeout=0.5)
        conn.request("GET", "/static/favicon.ico")
        r = conn.getresponse(); r.read(); conn.close()
        return True
    except Exception:
        try: conn.close()
        except Exception: pass
        return False


def _aguardar_flask(timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _porta_aberta() and _flask_respondendo():
            return True
        time.sleep(0.05)
    return False


# ═══════════════════════════════════════════════
#  Localiza Edge / Chrome
# ═══════════════════════════════════════════════

def _encontrar_browser_app_mode():
    """Retorna caminho do navegador para modo --app. Edge tem prioridade."""
    cands = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def _abrir_app(browser_exe):
    """Abre o navegador em modo --app com perfil dedicado."""
    os.makedirs(PROFILE, exist_ok=True)
    args = [
        browser_exe,
        f"--app={URL}",
        f"--user-data-dir={PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=TranslateUI",
        "--force-device-scale-factor=0.85",   # 0.8 = 80%, 0.9 = 90%, 1.0 = 100%
    ]
    # Sem STARTUPINFO: queremos que a janela do Edge apareça normalmente.
    subprocess.Popen(args, cwd=_DIR)


# ═══════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════

def main():
    _log("═" * 50)
    _log(f"Launcher v5 iniciando (Python {sys.version.split()[0]})")
    _set_app_user_model_id()
    _log(f"AppUserModelID definido: {APP_ID}")

    if not _porta_aberta():
        _log("Flask não está rodando, iniciando subprocess...")
        _iniciar_flask()
    else:
        _log("Flask já estava rodando")

    t0 = time.time()
    ok = _aguardar_flask(timeout=60)
    _log(f"Aguardar Flask: {'OK' if ok else 'TIMEOUT'} ({time.time()-t0:.1f}s)")
    if not ok:
        _log("Fallback: webbrowser.open() após timeout")
        import webbrowser
        webbrowser.open(URL)
        return

    browser = _encontrar_browser_app_mode()
    _log(f"Browser detectado: {browser}")
    if browser:
        try:
            _abrir_app(browser)
            _log("Browser --app iniciado com sucesso")
            return
        except Exception as e:
            _log(f"FALHA ao abrir browser em --app: {e}")
            _log(traceback.format_exc())

    _log("Fallback final: webbrowser.open()")
    import webbrowser
    webbrowser.open(URL)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"EXCEÇÃO NÃO TRATADA: {e}")
        _log(traceback.format_exc())

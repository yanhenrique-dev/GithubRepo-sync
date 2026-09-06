#!/usr/bin/env python3
"""RepoRefresh na bandeja do sistema (Linux).

Sobe o uvicorn, abre o navegador e fica como ícone vermelho na bandeja.
Fechar pelo menu (Sair) = parar o servidor. Segunda execução só abre o navegador.

Uso:  ./tray.py [porta]   (ou REPOREFRESH_PORT=8000 ./tray.py)
"""
from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

_VENV_PY = Path(__file__).resolve().parent / ".venv" / "bin" / "python"
if _VENV_PY.exists() and Path(sys.executable).resolve() != _VENV_PY.resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])

import socket
import subprocess
import time
import webbrowser

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "bin" / "python"
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable
def _parse_port() -> int:
    raw = os.getenv("REPOREFRESH_PORT")
    if raw is None and len(sys.argv) > 1 and sys.argv[1].lstrip("+-").isdigit():
        raw = sys.argv[1]
    if raw is None:
        return 8000
    try:
        port = int(raw)
    except (TypeError, ValueError):
        raise SystemExit(f"Porta inválida: {raw!r}")
    if not 1024 <= port <= 65535:
        raise SystemExit(f"Porta fora de 1024-65535: {port}")
    return port


PORT = _parse_port()
URL = f"http://127.0.0.1:{PORT}/"
_RUN_DIR = Path(os.getenv("XDG_RUNTIME_DIR", Path.home() / ".cache" / "reporefresh"))
_RUN_DIR.mkdir(parents=True, exist_ok=True)
LOCK = _RUN_DIR / f"reporefresh-{PORT}.lock"
LOG = Path(f"/tmp/reporefresh-{PORT}.log")
TRAY_LOG = Path(f"/tmp/reporefresh-{PORT}-tray.log")


def _tlog(msg: str) -> None:
    try:
        with open(TRAY_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass
ICON = ROOT / "static" / "tray-red.png"


def port_open() -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        try:
            s.connect(("127.0.0.1", PORT))
            return True
        except OSError:
            return False


def lock_alive() -> bool:
    try:
        pid = int(LOCK.read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        try:
            LOCK.unlink()
        except OSError:
            pass
        return False


def claim_lock(pid: int) -> bool:
    """Cria o lock com O_EXCL: dois inícios simultâneos, só um vence."""
    try:
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        if lock_alive():
            return False
        try:  # stale foi limpo: tenta de novo uma vez
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(str(pid))
    return True


def stop_proc(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def start_server() -> subprocess.Popen:
    logfh = open(LOG, "a", encoding="utf-8")
    return subprocess.Popen(
        [PY, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(ROOT),
        stdout=logfh,
        stderr=subprocess.STDOUT,
    )


def wait_ready(proc: subprocess.Popen, timeout: float = 30) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if proc.poll() is not None:
            return False
        if port_open():
            return True
        time.sleep(0.3)
    return port_open()


def _ensure_shortcut() -> None:
    """Na primeira execução, cria o atalho no menu de aplicativos."""
    try:
        apps = Path.home() / ".local" / "share" / "applications"
        apps.mkdir(parents=True, exist_ok=True)
        dest = apps / "reporefresh.desktop"
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=RepoRefresh\n"
            "Comment=Updater local de repos GitHub (bandeja do sistema)\n"
            f"Exec={ROOT / 'reporefresh.sh'}\n"
            f"Icon={ROOT / 'static' / 'tray-red.png'}\n"
            "Terminal=false\n"
            "Categories=Development;\n"
            "StartupNotify=false\n"
        )
        if not dest.exists() or dest.read_text(encoding="utf-8") != content:
            dest.write_text(content, encoding="utf-8")
    except OSError:
        pass  # sem atalho não impede o app de rodar


def main() -> int:
    _ensure_shortcut()
    _tlog("inicio")
    if lock_alive() or port_open():
        _tlog("já rodando: só abrir navegador")
        webbrowser.open(URL)  # já rodando: só abre
        return 0
    try:
        from PIL import Image
        import pystray
        from pystray import Menu, MenuItem
    except ImportError:
        print("Falta pystray/pillow: .venv/bin/pip install pystray pillow", file=sys.stderr)
        return 1

    proc = start_server()
    if not claim_lock(proc.pid):
        proc.terminate()
        _tlog("outro venceu a corrida: só abrir navegador")
        webbrowser.open(URL)  # outro venceu a corrida: só abre
        return 0
    if not wait_ready(proc):
        _tlog("servidor não subiu")
        print(f"Servidor não subiu — veja {LOG}", file=sys.stderr)
        proc.terminate()
        LOCK.unlink(missing_ok=True)
        return 1
    _tlog("servidor ok, abrindo navegador")
    webbrowser.open(URL)

    def restart(icon, _item):
        nonlocal proc
        stop_proc(proc)
        proc = start_server()
        LOCK.write_text(str(proc.pid))
        wait_ready(proc)

    def quit_app(icon, _item):
        icon.stop()

    icon = pystray.Icon(
        "RepoRefresh",
        Image.open(ICON),
        f"RepoRefresh :{PORT}",
        menu=Menu(
            MenuItem("Abrir no navegador", lambda _i, _it: webbrowser.open(URL)),
            MenuItem("Reiniciar servidor", restart),
            MenuItem("Sair (para o servidor)", quit_app),
        ),
    )

    def _on_signal(signum, _frame):
        _tlog(f"sinal {signum}: parando servidor")
        stop_proc(proc)
        LOCK.unlink(missing_ok=True)
        try:
            icon.stop()
        finally:
            raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    try:
        icon.run()
    except Exception as exc:  # sem bandeja (ex.: backend ausente): segura o servidor no foreground
        _tlog(f"sem bandeja: {exc}")
        print(f"Sem bandeja ({exc}); servidor segue no ar em {URL} — Ctrl+C para parar.",
              file=sys.stderr)
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
    finally:
        stop_proc(proc)
        LOCK.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

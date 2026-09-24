#!/usr/bin/env python3
"""RepoRefresh na bandeja do sistema (Linux).

Sobe o uvicorn, abre o navegador e fica como ícone vermelho na bandeja.
Fechar pelo menu (Sair) = parar o servidor. Segunda execução só abre o navegador.

Uso:  ./tray.py [porta]   (ou REPOREFRESH_PORT=8000 ./tray.py)
"""
from __future__ import annotations

import ipaddress
import os
import signal
import sys
from pathlib import Path

_VENV_PY = Path(__file__).resolve().parent / ".venv" / "bin" / "python"
if _VENV_PY.exists() and sys.prefix == sys.base_prefix:
    # Fora de qualquer venv (ex.: python do sistema no menu): re-exec no venv.
    # (Comparar executáveis quebra quando o sistema tem o mesmo Python 3.14.)
    os.execv(str(_VENV_PY), [str(_VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])

import shlex
import socket
import subprocess
import time
import urllib.request
import webbrowser

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)
VENV_PY = ROOT / ".venv" / "bin" / "python"
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable
def _parse_port() -> int:
    invoked_as_tray = Path(sys.argv[0]).name in {"tray.py", "reporefresh.sh"}
    if invoked_as_tray and len(sys.argv) > 1:
        raw = sys.argv[1]
    else:
        raw = os.getenv("REPOREFRESH_PORT", os.getenv("ALLDOWN_PORT"))
    if raw is None:
        return 8000
    try:
        port = int(raw)
    except (TypeError, ValueError):
        raise SystemExit(f"Porta inválida: {raw!r}")
    if not 1024 <= port <= 65535:
        raise SystemExit(f"Porta fora de 1024-65535: {port}")
    return port


def _parse_host() -> str:
    host = os.getenv("ALLDOWN_HOST", "127.0.0.1").strip() or "127.0.0.1"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError as exc:
        raise SystemExit(f"Host inválido: {host!r}") from exc
    if not ip.is_loopback and host not in {"0.0.0.0", "::"}:
        raise SystemExit(f"Host remoto não permitido: {host}")
    if not ip.is_loopback and os.getenv("ALLDOWN_ALLOW_REMOTE", "0").strip() != "1":
        raise SystemExit("Host remoto exige ALLDOWN_ALLOW_REMOTE=1")
    return host


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


BIND_HOST = _parse_host()
PORT = _parse_port()
CONNECT_HOST = "127.0.0.1" if BIND_HOST in {"0.0.0.0", "::"} else BIND_HOST
URL = f"http://{_url_host(CONNECT_HOST)}:{PORT}/"

_RUN_DIR = Path(os.getenv("XDG_RUNTIME_DIR", Path.home() / ".cache" / "reporefresh"))
if _RUN_DIR.exists() and _RUN_DIR.is_symlink():
    raise SystemExit(f"Diretório de execução seguro é obrigatório: {_RUN_DIR}")
_RUN_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
try:
    _RUN_DIR.chmod(0o700)
except OSError:
    pass
LOCK = _RUN_DIR / f"reporefresh-{PORT}.lock"
LOG = _RUN_DIR / f"reporefresh-{PORT}.log"
TRAY_LOG = _RUN_DIR / f"reporefresh-{PORT}-tray.log"


def _open_log(path: Path):
    if path.parent.is_symlink():
        raise OSError(f"diretório de log não pode ser symlink: {path.parent}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    return os.fdopen(os.open(str(path), flags, 0o600), "a", encoding="utf-8")


def _tlog(msg: str) -> None:
    try:
        with _open_log(TRAY_LOG) as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except (OSError, subprocess.SubprocessError):
        pass
ICON = ROOT / "static" / "tray-red.png"


def port_open() -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        try:
            s.connect((CONNECT_HOST, PORT))
        except OSError:
            return False
    try:
        with urllib.request.urlopen(f"http://{_url_host(CONNECT_HOST)}:{PORT}/api/health", timeout=0.5) as response:
            body = response.read(4096)
            return response.status == 200 and b'"ok":true' in body.replace(b" ", b"")
    except (OSError, ValueError):
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
        fd = os.open(
            str(LOCK),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except FileExistsError:
        if lock_alive():
            return False
        try:  # stale foi limpo: tenta de novo uma vez
            fd = os.open(
            str(LOCK),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        except FileExistsError:
            return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        os.fchmod(fh.fileno(), 0o600)
        fh.write(str(pid))
    return True


def stop_proc(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def start_server() -> subprocess.Popen:
    with _open_log(LOG) as logfh:
        return subprocess.Popen(
            [PY, "-m", "uvicorn", "app:app", "--host", BIND_HOST, "--port", str(PORT)],
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
            f"Exec={shlex.quote(str(ROOT / 'reporefresh.sh'))}\n"
            f"Icon={shlex.quote(str(ROOT / 'static' / 'tray-red.png'))}\n"
            "Terminal=false\n"
            "Categories=Development;\n"
            "StartupNotify=false\n"
        )
        if not dest.exists() or dest.read_text(encoding="utf-8") != content:
            dest.write_text(content, encoding="utf-8")
    except OSError:
        pass  # sem atalho não impede o app de rodar


def _notify(msg: str) -> None:
    """Erro visível: no menu não há terminal, stderr morre calado."""
    try:
        subprocess.run(["notify-send", "RepoRefresh", msg], timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def main() -> int:
    _ensure_shortcut()
    _tlog("inicio")
    try:
        return _run()
    except Exception:
        import traceback
        _tlog("FATAL:\n" + traceback.format_exc())
        _notify(f"Falha ao iniciar — veja {TRAY_LOG}")
        return 1


def _run() -> int:
    if lock_alive() or port_open():
        _tlog("já rodando: só abrir navegador")
        webbrowser.open(URL)  # já rodando: só abre
        return 0
    try:
        import pystray
        from PIL import Image
        from pystray import Menu, MenuItem
    except Exception as exc:  # ImportError ou backend sem display no import
        _tlog(f"sem pystray/pillow: {exc}")
        _notify("Falta pystray/pillow no .venv")
        print("Falta pystray/pillow: .venv/bin/pip install pystray pillow", file=sys.stderr)
        return 1

    proc = start_server()
    if not claim_lock(proc.pid):
        stop_proc(proc)
        _tlog("outro venceu a corrida: só abrir navegador")
        webbrowser.open(URL)  # outro venceu a corrida: só abre
        return 0
    if not wait_ready(proc):
        _tlog("servidor não subiu")
        print(f"Servidor não subiu — veja {LOG}", file=sys.stderr)
        stop_proc(proc)
        LOCK.unlink(missing_ok=True)
        return 1
    _tlog("servidor ok, abrindo navegador")
    webbrowser.open(URL)

    def restart(icon, _item):
        nonlocal proc
        LOCK.write_text(str(os.getpid()))
        stop_proc(proc)
        try:
            new_proc = start_server()
            if not wait_ready(new_proc):
                stop_proc(new_proc)
                _notify("Servidor não reiniciou — veja o log")
                return
            proc = new_proc
            LOCK.write_text(str(proc.pid))
            _tlog("servidor reiniciado")
        except OSError as exc:
            _tlog(f"falha ao reiniciar: {exc}")
            _notify("Falha ao reiniciar servidor")

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

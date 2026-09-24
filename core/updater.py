"""Download, backup .bak com timestamp e troca atômica da pasta."""
from __future__ import annotations

import errno
import ipaddress
import os
import re
import shutil
import socket
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from .state import clear_local_sha, load_state, save_state, set_local_sha, state_lock

# Hosts p/ os quais o GITHUB_TOKEN pode ser enviado. Redirect p/ qualquer
# outro host perde o Authorization (evita vazar token p/ host arbitrário).
_ALLOWED_TOKEN_HOSTS = frozenset({"api.github.com", "codeload.github.com"})
_ALLOWED_DOWNLOAD_HOSTS = frozenset({
    "api.github.com",
    "codeload.github.com",
    "github.com",
    "www.github.com",
    "objects.githubusercontent.com",
    "raw.githubusercontent.com",
})
_TRUSTED_DOWNLOAD_HOSTS = frozenset({"codeload.github.com"})
_BLOCKED_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "metadata.google.internal"})
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal")
_MAX_BYTES = 500 * 1024 * 1024  # 500 MB: sem teto, zip gigante esgota disco
_DOWNLOAD_TIMEOUT = 300.0  # 5 min totais: servidor lento não prende para sempre
_MAX_ENTRIES = 50000  # zip-bomb: entradas demais nem começam
_MAX_TOTAL_UNCOMPRESSED = 2 * 1024 * 1024 * 1024  # 2 GB somados

_FORBIDDEN_BASES = frozenset({
    "/", "/bin", "/boot", "/dev", "/etc", "/lib", "/lib64",
    "/proc", "/root", "/run", "/sbin", "/sys", "/usr", "/var",
})


def is_forbidden_base(base: Path) -> bool:
    try:
        resolved = base.resolve()
    except (OSError, RuntimeError):
        return True
    return any(
        resolved == Path(item) or (item != "/" and Path(item) in resolved.parents)
        for item in _FORBIDDEN_BASES
    )

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

_MAX_REDIRECTS = 10


def validate_name(name: str) -> str:
    """Nome de repo local seguro: sem `/`, `..`, `*` ou absoluto."""
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name) or name in (".", ".."):
        raise ValueError(f"nome inválido: {name!r}")
    return name


def _is_within(base: Path, target: Path) -> bool:
    """True se target resolvido está dentro de base (ou é a base)."""
    b = base.resolve()
    try:
        t = target.resolve()
    except (OSError, RuntimeError):
        return False
    return t == b or b in t.parents


def _confine(base: Path, leaf: str) -> Path:
    """Junta base+leaf e garante que continua dentro da base."""
    try:
        t = (base.resolve() / leaf).resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"caminho inválido: {leaf!r}") from exc
    if not _is_within(base, t):
        raise ValueError(f"caminho escapa a base: {leaf!r}")
    return t


def _target_in_base(base: Path, name: str) -> Path:
    validate_name(name)
    return _confine(base, name)


# Lock por repo: updates/rollbacks concorrentes do mesmo `name` serializam.
_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}


def _lock_for(name: str) -> threading.RLock:
    with _guard:
        lk = _locks.get(name)
        if lk is None:
            lk = _locks[name] = threading.RLock()
        return lk


def _stamp() -> str:
    # Microssegundos + uuid: duas trocas no mesmo segundo nunca colidem.
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid.uuid4().hex[:8]


def _is_generated_backup(name: str, repo_name: str, zip_only: bool) -> bool:
    stem = f"{repo_name}.zip" if zip_only else repo_name
    pattern = rf"^{re.escape(stem)}\.bak-(?:\d{{8}}-\d{{6}}(?:-\d{{6}})?(?:-[0-9a-f]{{6,8}})?)$"
    return re.fullmatch(pattern, name) is not None


def _unique_backup(base: Path, name: str, suffix: str = "") -> Path:
    for _ in range(20):
        cand = base / f"{name}{suffix}.bak-{_stamp()}"
        if not cand.exists() and not cand.is_symlink():
            _confine(base, cand.name)  # defesa em profundidade
            return cand
    raise RuntimeError("não foi possível gerar backup único")


def _unique_swap_path(base: Path, name: str, suffix: str = "") -> Path:
    for _ in range(20):
        cand = base / f".{name}{suffix}.alldown-old-{_stamp()}"
        if not cand.exists() and not cand.is_symlink():
            _confine(base, cand.name)
            return cand
    raise RuntimeError("não foi possível gerar caminho temporário")


def _remove_path(p: Path) -> None:
    if p.is_symlink() or p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)


def _move_atomic(src: Path | str, dst: Path | str) -> None:
    """Move no mesmo filesystem; nunca copia parcialmente entre discos."""
    try:
        os.replace(str(src), str(dst))
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            raise OSError("troca cross-filesystem não é atômica") from exc
        raise


def _headers_for(host: str, token: str) -> dict[str, str]:
    h = {"User-Agent": "reporefresh"}
    if token and host.lower() in _ALLOWED_TOKEN_HOSTS:
        h["Authorization"] = f"Bearer {token}"
    return h


def _dir_bytes(path: Path) -> int:
    """Tamanho somado de arquivos (sem seguir symlinks)."""
    total = 0
    try:
        for root, _dirs, files in os.walk(path, followlinks=False):
            for f in files:
                try:
                    fp = Path(root) / f
                    if not fp.is_symlink():
                        total += fp.stat().st_size
                except OSError:
                    continue
    except OSError:
        pass
    return total


def download_zip(
    url: str,
    token: str = "",
    stats: dict | None = None,
    tmp_parent: Path | None = None,
) -> Path:
    _check_https_host(url)
    tmpdir = Path(tempfile.mkdtemp(prefix=".alldown-", dir=str(tmp_parent) if tmp_parent else None))
    tmp = tmpdir / "src.zip"
    try:
        cur = url
        deadline = time.monotonic() + _DOWNLOAD_TIMEOUT
        for _ in range(_MAX_REDIRECTS + 1):
            _check_https_host(cur, "Redirect")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError(f"Download passou de {_DOWNLOAD_TIMEOUT:.0f}s")
            host = (urlsplit(cur).hostname or "").lower()
            headers = _headers_for(host, token)
            with httpx.stream(
                "GET", cur, headers=headers, timeout=max(0.1, min(60.0, remaining)), follow_redirects=False
            ) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("location")
                    if not loc:
                        raise ValueError("Redirect sem Location")
                    cur = urljoin(cur, loc)
                    continue
                resp.raise_for_status()
                try:
                    announced = int(resp.headers.get("content-length", "0") or 0)
                except ValueError:
                    announced = 0
                if announced > _MAX_BYTES:
                    raise ValueError(f"Download grande demais ({announced} bytes)")
                total = 0
                t0 = time.monotonic()
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_bytes(65536):
                        fh.write(chunk)
                        total += len(chunk)
                        if total > _MAX_BYTES:
                            raise ValueError(f"Download passou de {_MAX_BYTES} bytes")
                        if time.monotonic() - t0 > _DOWNLOAD_TIMEOUT:
                            raise ValueError(f"Download passou de {_DOWNLOAD_TIMEOUT:.0f}s")
                if stats is not None:
                    stats["download_bytes"] = total
                    stats["download_secs"] = max(time.monotonic() - t0, 0.001)
                break
        else:
            raise ValueError("Redirects demais")
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    if total < 4 or not zipfile.is_zipfile(tmp):
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise ValueError("Download não é um .zip válido")
    return tmp


def _check_resolved_host(host: str, what: str) -> None:
    if host in _TRUSTED_DOWNLOAD_HOSTS:
        return
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(f"{what} não pôde ser resolvido") from exc
    if not addresses:
        raise ValueError(f"{what} não pôde ser resolvido")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global or ip.is_multicast or ip.is_unspecified or ip.is_link_local:
            raise ValueError(f"{what} resolve para IP privado/bloqueado")


def _check_https_host(url: str, what: str = "URL") -> str:
    u = urlsplit(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host:
        raise ValueError(f"{what} inválida (só https)")
    try:
        port = u.port
    except ValueError as exc:
        raise ValueError(f"{what} com porta inválida") from exc
    if port not in (None, 443):
        raise ValueError(f"{what} com porta não permitida")
    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise ValueError(f"{what} com host bloqueado")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if host not in _ALLOWED_DOWNLOAD_HOSTS:
            raise ValueError(f"{what} com host não permitido")
        _check_resolved_host(host, what)
        return host
    if not ip.is_global or ip.is_multicast or ip.is_unspecified or ip.is_link_local:
        raise ValueError(f"{what} com IP privado/bloqueado")
    if host not in _ALLOWED_DOWNLOAD_HOSTS:
        raise ValueError(f"{what} com host não permitido")
    return host


def _check_zip_entry(filename: str) -> None:
    if not filename or "\x00" in filename:
        raise ValueError(f"entrada de zip inválida: {filename!r}")
    norm = filename.replace("\\", "/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm):
        raise ValueError(f"entrada absoluta no zip: {filename!r}")
    if ".." in norm.split("/"):
        raise ValueError(f"path traversal no zip: {filename!r}")


def extract_root(zip_path: Path, dest: Path) -> Path:
    """Extrai e retorna a pasta raiz real (zips do GitHub vêm com 1 nível extra).

    Cada entrada é validada (Zip Slip): `..`, absoluto ou drive -> ValueError
    e nada é escrito fora de `dest`.
    """
    dest.mkdir(parents=True, exist_ok=True)
    base = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if len(infos) > _MAX_ENTRIES:
            raise ValueError(f"Zip com entradas demais ({len(infos)})")
        if sum(i.file_size for i in infos) > _MAX_TOTAL_UNCOMPRESSED:
            raise ValueError("Zip grande demais descomprimido")
        for info in infos:
            _check_zip_entry(info.filename)
            target = (base / info.filename).resolve()
            if not _is_within(base, target):
                raise ValueError(f"entrada escapa o destino: {info.filename!r}")
        written = 0
        for info in infos:
            target = base / info.filename
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as fh:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > _MAX_TOTAL_UNCOMPRESSED:
                            raise ValueError("Zip grande demais descomprimido")
                        fh.write(chunk)
    children = [p for p in dest.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return dest


def _cleanup_download(zip_path: Path, base: Path) -> None:
    parent = zip_path.parent
    if parent != base and parent.name.startswith(".alldown-"):
        shutil.rmtree(parent, ignore_errors=True)


def update_one(
    base: Path,
    name: str,
    owner: str,
    repo: str,
    branch: str,
    zip_url: str,
    token: str = "",
    make_backup: bool = True,
    stats: dict | None = None,
) -> dict:
    target = _target_in_base(base, name)
    with _lock_for(name):
        if target.is_symlink():
            raise ValueError(f"{name} é symlink")
        if target.exists() and not target.is_dir():
            raise ValueError(f"{name} existe e não é pasta")

        zip_path = download_zip(zip_url, token, stats=stats, tmp_parent=base)
        work: Path | None = None
        try:
            work = Path(tempfile.mkdtemp(prefix=f".{name}.alldown-", dir=str(base)))
            root = extract_root(zip_path, work / "extracted")
            old_bytes = _dir_bytes(target) if target.is_dir() else None
            new_bytes = _dir_bytes(root)

            backup: str | None = None
            old_swap: Path | None = None
            if target.exists():
                if make_backup:
                    bkp = _unique_backup(base, name)
                    _move_atomic(target, bkp)
                    backup = str(bkp)
                else:
                    old_swap = _unique_swap_path(base, name)
                    _move_atomic(target, old_swap)

            try:
                _move_atomic(root, target)
            except Exception:
                try:
                    if target.exists() or target.is_symlink():
                        _remove_path(target)
                    restore = backup or (str(old_swap) if old_swap else None)
                    if restore:
                        _move_atomic(Path(restore), target)
                except Exception:
                    pass
                raise
            try:
                with state_lock(base):
                    state = load_state(base)
                    entry = state.get(name, {})
                    if not isinstance(entry, dict):
                        entry = {}
                    entry["dir_backup_path"] = backup
                    entry["backup_path"] = backup
                    entry["updated_at"] = _stamp()
                    state[name] = entry
                    remote_sha = stats.get("remote_sha") if stats else None
                    if isinstance(remote_sha, str) and remote_sha:
                        set_local_sha(state, name, remote_sha, zip_only=False)
                    save_state(base, state)
            except Exception:
                try:
                    if target.exists() or target.is_symlink():
                        _remove_path(target)
                    restore = backup or (str(old_swap) if old_swap else None)
                    if restore:
                        _move_atomic(Path(restore), target)
                except Exception:
                    pass
                raise
            if old_swap is not None:
                _remove_path(old_swap)
            return {"name": name, "backup": backup, "path": str(target),
                    "old_bytes": old_bytes, "new_bytes": new_bytes}
        finally:
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)
            _cleanup_download(zip_path, base)


def _speed_of(stats: dict) -> float | None:
    dl_b = stats.get("download_bytes") or 0
    dl_s = stats.get("download_secs") or 0
    return round(dl_b / dl_s, 1) if dl_b and dl_s else None


def replace_zip_file(
    base: Path,
    name: str,
    src_zip: Path,
    make_backup: bool = True,
    stats: dict | None = None,
) -> dict:
    """Modo só-zip: troca o .zip sem encostar na pasta. Puro local, testável."""
    validate_name(name)
    with _lock_for(name):
        if not zipfile.is_zipfile(src_zip):
            raise ValueError("Arquivo baixado não é um .zip válido")
        target = _confine(base, f"{name}.zip")
        if target.is_symlink():
            raise ValueError(f"{name}.zip é symlink")
        if target.exists() and not target.is_file():
            raise ValueError(f"{name}.zip existe e não é arquivo")
        backup: str | None = None
        old_swap: Path | None = None
        if target.exists():
            if make_backup:
                bkp = _unique_backup(base, name, suffix=".zip")
                _move_atomic(target, bkp)
                backup = str(bkp)
            else:
                old_swap = _unique_swap_path(base, name, suffix=".zip")
                _move_atomic(target, old_swap)
        try:
            _move_atomic(src_zip, target)
        except Exception:
            try:
                if target.exists() or target.is_symlink():
                    _remove_path(target)
                restore = backup or (str(old_swap) if old_swap else None)
                if restore:
                    _move_atomic(Path(restore), target)
            except Exception:
                pass
            raise
        try:
            with state_lock(base):
                state = load_state(base)
                entry = state.get(name, {})
                if not isinstance(entry, dict):
                    entry = {}
                entry["zip_backup_path"] = backup
                entry["backup_path"] = backup
                entry["updated_at"] = _stamp()
                state[name] = entry
                remote_sha = stats.get("remote_sha") if stats else None
                if isinstance(remote_sha, str) and remote_sha:
                    set_local_sha(state, name, remote_sha, zip_only=True)
                save_state(base, state)
        except Exception:
            try:
                if target.exists() or target.is_symlink():
                    _remove_path(target)
                restore = backup or (str(old_swap) if old_swap else None)
                if restore:
                    _move_atomic(Path(restore), target)
            except Exception:
                pass
            raise
        if old_swap is not None:
            _remove_path(old_swap)
        return {"name": name, "backup": backup, "path": str(target)}


def update_zip_only(
    base: Path,
    name: str,
    zip_url: str,
    token: str = "",
    make_backup: bool = True,
    stats: dict | None = None,
) -> dict:
    validate_name(name)
    target = _confine(base, f"{name}.zip")
    old_bytes = target.stat().st_size if target.is_file() and not target.is_symlink() else None
    zip_path = download_zip(zip_url, token, stats=stats, tmp_parent=base)
    try:
        if not zipfile.is_zipfile(zip_path):
            raise ValueError("Download não é um .zip válido")
        out = replace_zip_file(base, name, zip_path, make_backup=make_backup, stats=stats)
        out["old_bytes"] = old_bytes
        out["new_bytes"] = (stats or {}).get("download_bytes")
        return out
    finally:
        _cleanup_download(zip_path, base)


def _list_backups(base: Path, name: str, zip_only: bool) -> list[Path]:
    if not base.is_dir():
        return []
    try:
        entries = list(base.iterdir())
    except OSError:
        return []
    out: list[Path] = []
    for path in entries:
        if path.is_symlink() or not _is_generated_backup(path.name, name, zip_only):
            continue
        if zip_only and not path.is_file():
            continue
        if not zip_only and not path.is_dir():
            continue
        if not _is_within(base, path):
            continue
        out.append(path)
    return sorted(out, key=lambda item: item.name, reverse=True)


def _restore_backup(
    base: Path,
    name: str,
    candidates: list[Path],
    zip_only: bool,
) -> tuple[str, str, Path | None, list[Path]]:
    target = _confine(base, f"{name}.zip" if zip_only else name)
    if target.is_symlink():
        raise ValueError(f"{target.name} é symlink")
    if target.exists() and ((zip_only and not target.is_file()) or (not zip_only and not target.is_dir())):
        raise ValueError(f"{target.name} tem tipo inesperado")
    original = candidates[-1]
    old_target: Path | None = None
    if target.exists():
        old_target = _unique_swap_path(base, name, suffix=".zip" if zip_only else "")
        _move_atomic(target, old_target)
    try:
        _move_atomic(original, target)
    except Exception:
        try:
            if target.exists() or target.is_symlink():
                _remove_path(target)
            if old_target is not None:
                _move_atomic(old_target, target)
        except Exception:
            pass
        raise
    return str(original), str(target), old_target, candidates[:-1]


def rollback_one(base: Path, name: str, zip_only: bool | None = None) -> dict:
    """Volta ao ORIGINAL (backup mais antigo), não ao intermediário.

    Com N updates há N .baks (v0, v1, ...); restaurar o mais novo finge
    que reverteu. Depois de voltar ao original, os .baks restantes são
    descartados (estados intermediários sem sentido).
    """
    validate_name(name)
    with _lock_for(name):
        modes = [bool(zip_only), not bool(zip_only)] if zip_only is not None else [False, True]
        candidates: list[Path] = []
        selected_mode = False
        for mode in modes:
            candidates = _list_backups(base, name, zip_only=mode)
            if candidates:
                selected_mode = mode
                break
        if not candidates:
            raise ValueError(f"Sem backup para {name}")
        zip_only = selected_mode
        restored, path, old_target, stale = _restore_backup(base, name, candidates, zip_only)
        try:
            with state_lock(base):
                state = load_state(base)
                entry = state.get(name, {})
                if not isinstance(entry, dict):
                    entry = {}
                clear_local_sha(state, name, zip_only=zip_only)
                entry = state.get(name, {})
                if not isinstance(entry, dict):
                    entry = {}
                entry.pop("dir_backup_path" if not zip_only else "zip_backup_path", None)
                entry.pop("backup_path", None)
                entry["rolled_back_at"] = _stamp()
                state[name] = entry
                save_state(base, state)
        except Exception:
            try:
                if Path(path).exists() or Path(path).is_symlink():
                    _move_atomic(Path(path), Path(restored))
                if old_target is not None:
                    _move_atomic(old_target, Path(path))
            except Exception:
                pass
            raise
        try:
            if old_target is not None:
                _remove_path(old_target)
            for backup in stale:
                _remove_path(backup)
        except OSError:
            pass
        return {"name": name, "restored_from": restored, "path": path, "zip_only": zip_only}

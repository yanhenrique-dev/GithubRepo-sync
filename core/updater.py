"""Download, backup .bak com timestamp e troca atômica da pasta."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from .state import load_state, save_state

# Hosts p/ os quais o GITHUB_TOKEN pode ser enviado. Redirect p/ qualquer
# outro host perde o Authorization (evita vazar token p/ host arbitrário).
_ALLOWED_TOKEN_HOSTS = frozenset({"api.github.com", "codeload.github.com"})

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

_MAX_REDIRECTS = 10


def validate_name(name: str) -> str:
    """Nome de repo local seguro: sem `/`, `..`, `*` ou absoluto."""
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name) or name in (".", ".."):
        raise ValueError(f"nome inválido: {name!r}")
    return name


def _confine(base: Path, leaf: str) -> Path:
    """Junta base+leaf e garante que continua dentro da base."""
    b = base.resolve()
    t = (b / leaf).resolve()
    if t != b and b not in t.parents:
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
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid.uuid4().hex[:8]


def _unique_backup(base: Path, name: str, suffix: str = "") -> Path:
    for _ in range(20):
        cand = base / f"{name}{suffix}.bak-{_stamp()}"
        if not cand.exists() and not cand.is_symlink():
            _confine(base, cand.name)  # defesa em profundidade
            return cand
    raise RuntimeError("não foi possível gerar backup único")


def _remove_path(p: Path) -> None:
    if p.is_symlink() or p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)


def _move_atomic(src: Path | str, dst: Path | str) -> None:
    """os.replace (sem a semântica 'mover P/ DENTRO' do shutil.move);
    cai p/ shutil.move se for cross-device (tmp em outro fs)."""
    try:
        os.replace(str(src), str(dst))
    except OSError:
        # dst garantidamente não existe aqui: shutil.move não cai no
        # modo "mover para dentro do diretório".
        if Path(dst).exists() or Path(dst).is_symlink():
            raise
        shutil.move(str(src), str(dst))


def _headers_for(host: str, token: str) -> dict[str, str]:
    h = {"User-Agent": "reporefresh"}
    if token and host.lower() in _ALLOWED_TOKEN_HOSTS:
        h["Authorization"] = f"Bearer {token}"
    return h


def download_zip(url: str, token: str = "") -> Path:
    u = urlsplit(url)
    if u.scheme not in ("https", "http") or not u.hostname:
        raise ValueError("URL inválida")
    tmpdir = Path(tempfile.mkdtemp(prefix="alldown-"))
    tmp = tmpdir / "src.zip"
    try:
        cur = url
        for _ in range(_MAX_REDIRECTS + 1):
            host = (urlsplit(cur).hostname or "").lower()
            headers = _headers_for(host, token)
            with httpx.stream(
                "GET", cur, headers=headers, timeout=60, follow_redirects=False
            ) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("location")
                    if not loc:
                        raise ValueError("Redirect sem Location")
                    nxt = urljoin(cur, loc)
                    nu = urlsplit(nxt)
                    if nu.scheme not in ("https", "http") or not nu.hostname:
                        raise ValueError("Redirect inválido")
                    cur = nxt
                    continue
                resp.raise_for_status()
                total = 0
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_bytes(65536):
                        fh.write(chunk)
                        total += len(chunk)
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
        for info in infos:
            _check_zip_entry(info.filename)
            target = (base / info.filename).resolve()
            if target != base and base not in target.parents:
                raise ValueError(f"entrada escapa o destino: {info.filename!r}")
        for info in infos:
            target = base / info.filename
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as fh:
                    shutil.copyfileobj(src, fh)
    children = [p for p in dest.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return dest


def update_one(base: Path, name: str, owner: str, repo: str, branch: str, zip_url: str, token: str = "", make_backup: bool = True) -> dict:
    target = _target_in_base(base, name)
    with _lock_for(name):
        if target.exists() and not target.is_dir() and not target.is_symlink():
            raise ValueError(f"{name} existe e não é pasta")

        zip_path = download_zip(zip_url, token)
        try:
            work = Path(tempfile.mkdtemp(prefix="alldown-x-"))
            try:
                root = extract_root(zip_path, work / "extracted")

                backup: str | None = None
                if (target.exists() or target.is_symlink()) and make_backup:
                    bkp = _unique_backup(base, name)
                    _move_atomic(target, bkp)
                    backup = str(bkp)
                elif not make_backup and (target.exists() or target.is_symlink()):
                    # Sem backup: remove o alvo antes (os.replace não
                    # sobrescreve pasta não-vazia).
                    _remove_path(target)

                try:
                    _move_atomic(root, target)
                except Exception:
                    # Falha no meio da troca: tenta devolver o backup.
                    try:
                        if target.exists() or target.is_symlink():
                            _remove_path(target)
                        if backup is not None:
                            _move_atomic(Path(backup), target)
                    except Exception:
                        pass
                    raise

                state = load_state(base)
                entry = state.get(name, {})
                entry["backup_path"] = backup
                entry["updated_at"] = _stamp()
                state[name] = entry
                save_state(base, state)
                return {"name": name, "backup": backup, "path": str(target)}
            finally:
                shutil.rmtree(work, ignore_errors=True)
        finally:
            shutil.rmtree(zip_path.parent, ignore_errors=True)


def replace_zip_file(base: Path, name: str, src_zip: Path) -> dict:
    """Modo só-zip: troca o .zip sem encostar na pasta. Puro local, testável."""
    validate_name(name)
    with _lock_for(name):
        if not zipfile.is_zipfile(src_zip):
            raise ValueError("Arquivo baixado não é um .zip válido")
        target = _confine(base, f"{name}.zip")
        backup: str | None = None
        if target.exists() or target.is_symlink():
            bkp = _unique_backup(base, name, suffix=".zip")
            _move_atomic(target, bkp)
            backup = str(bkp)
        try:
            _move_atomic(src_zip, target)
        except Exception:
            try:
                if target.exists() or target.is_symlink():
                    _remove_path(target)
                if backup is not None:
                    _move_atomic(Path(backup), target)
            except Exception:
                pass
            raise

        state = load_state(base)
        entry = state.get(name, {})
        entry["backup_path"] = backup
        entry["updated_at"] = _stamp()
        state[name] = entry
        save_state(base, state)
        return {"name": name, "backup": backup, "path": str(target)}


def update_zip_only(base: Path, name: str, zip_url: str, token: str = "", make_backup: bool = True) -> dict:
    validate_name(name)
    with _lock_for(name):
        zip_path = download_zip(zip_url, token)
        try:
            # Reuso interno sem relockar duas vezes (RLock permite, mas evita
            # revalidar/relockar à toa): troca direta aqui.
            if not zipfile.is_zipfile(zip_path):
                raise ValueError("Download não é um .zip válido")
            target = _confine(base, f"{name}.zip")
            backup: str | None = None
            if (target.exists() or target.is_symlink()) and make_backup:
                bkp = _unique_backup(base, name, suffix=".zip")
                _move_atomic(target, bkp)
                backup = str(bkp)
            try:
                _move_atomic(zip_path, target)
            except Exception:
                try:
                    if target.exists() or target.is_symlink():
                        _remove_path(target)
                    if backup is not None:
                        _move_atomic(Path(backup), target)
                except Exception:
                    pass
                raise
            state = load_state(base)
            entry = state.get(name, {})
            entry["backup_path"] = backup
            entry["updated_at"] = _stamp()
            state[name] = entry
            save_state(base, state)
            return {"name": name, "backup": backup, "path": str(target)}
        finally:
            shutil.rmtree(zip_path.parent, ignore_errors=True)


def _list_backups(base: Path, prefix: str) -> list[Path]:
    """Lista sem glob (name pode conter metacaracteres): só startswith + confine."""
    try:
        entries = list(base.iterdir())
    except OSError:
        return []
    out = []
    b = base.resolve()
    for p in entries:
        if not p.name.startswith(prefix):
            continue
        try:
            r = p.resolve()
        except OSError:
            continue
        if r != b and b not in r.parents:
            continue
        out.append(p)
    return sorted(out, key=lambda p: p.name, reverse=True)


def rollback_one(base: Path, name: str) -> dict:
    validate_name(name)
    with _lock_for(name):
        target = _confine(base, name)
        candidates = _list_backups(base, f"{name}.bak-")
        if candidates:
            newest = candidates[0]
            if target.exists() or target.is_symlink():
                _remove_path(target)
            _move_atomic(newest, target)
            restored = str(newest)
            path = str(target)
        else:
            ztarget = _confine(base, f"{name}.zip")
            zcands = _list_backups(base, f"{name}.zip.bak-")
            if not zcands:
                raise ValueError(f"Sem backup para {name}")
            newest = zcands[0]
            if ztarget.exists() or ztarget.is_symlink():
                _remove_path(ztarget)
            _move_atomic(newest, ztarget)
            restored = str(newest)
            path = str(ztarget)
        # Rollback invalida o sha conhecido: o conteúdo voltou no tempo.
        state = load_state(base)
        entry = state.get(name, {})
        entry.pop("local_sha", None)
        entry.pop("backup_path", None)
        entry["rolled_back_at"] = _stamp()
        state[name] = entry
        save_state(base, state)
        return {"name": name, "restored_from": restored, "path": path}

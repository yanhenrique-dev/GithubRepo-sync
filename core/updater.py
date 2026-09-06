"""Download, backup .bak com timestamp e troca atômica da pasta."""
from __future__ import annotations

import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import httpx

from .state import load_state, save_state


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def download_zip(url: str, token: str = "") -> Path:
    headers = {"User-Agent": "reporefresh"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    tmp = Path(tempfile.mkdtemp(prefix="alldown-")) / "src.zip"
    with httpx.stream("GET", url, headers=headers, timeout=60, follow_redirects=True) as resp:
        resp.raise_for_status()
        total = 0
        with tmp.open("wb") as fh:
            for chunk in resp.iter_bytes(65536):
                fh.write(chunk)
                total += len(chunk)
    if total < 4 or not zipfile.is_zipfile(tmp):
        raise ValueError("Download não é um .zip válido")
    return tmp


def extract_root(zip_path: Path, dest: Path) -> Path:
    """Extrai e retorna a pasta raiz real (zips do GitHub vêm com 1 nível extra)."""
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    children = [p for p in dest.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return dest


def update_one(base: Path, name: str, owner: str, repo: str, branch: str, zip_url: str, token: str = "") -> dict:
    target = base / name
    if target.exists() and not target.is_dir():
        raise ValueError(f"{name} existe e não é pasta")

    zip_path = download_zip(zip_url, token)
    try:
        work = Path(tempfile.mkdtemp(prefix="alldown-x-"))
        try:
            root = extract_root(zip_path, work / "extracted")

            backup: str | None = None
            if target.exists():
                backup = str(base / f"{name}.bak-{_stamp()}")
                shutil.move(str(target), backup)

            shutil.move(str(root), str(target))

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
    if not zipfile.is_zipfile(src_zip):
        raise ValueError("Arquivo baixado não é um .zip válido")
    target = base / f"{name}.zip"
    backup: str | None = None
    if target.exists():
        backup = str(base / f"{name}.zip.bak-{_stamp()}")
        shutil.move(str(target), backup)
    shutil.move(str(src_zip), str(target))

    state = load_state(base)
    entry = state.get(name, {})
    entry["backup_path"] = backup
    entry["updated_at"] = _stamp()
    state[name] = entry
    save_state(base, state)
    return {"name": name, "backup": backup, "path": str(target)}


def update_zip_only(base: Path, name: str, zip_url: str, token: str = "") -> dict:
    zip_path = download_zip(zip_url, token)
    try:
        return replace_zip_file(base, name, zip_path)
    finally:
        shutil.rmtree(zip_path.parent, ignore_errors=True)


def rollback_one(base: Path, name: str) -> dict:
    target = base / name
    candidates = sorted(base.glob(f"{name}.bak-*"), reverse=True)
    if candidates:
        newest = candidates[0]
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(newest), str(target))
        return {"name": name, "restored_from": str(newest), "path": str(target)}
    ztarget = base / f"{name}.zip"
    zcands = sorted(base.glob(f"{name}.zip.bak-*"), reverse=True)
    if not zcands:
        raise ValueError(f"Sem backup para {name}")
    newest = zcands[0]
    if ztarget.exists():
        ztarget.unlink()
    shutil.move(str(newest), str(ztarget))
    return {"name": name, "restored_from": str(newest), "path": str(ztarget)}

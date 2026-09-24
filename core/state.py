"""Estado local: repos.json (mapeamento) + .alldown/state.json (SHAs)."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

_state_guard = threading.Lock()
_state_locks: dict[str, threading.RLock] = {}
MAX_JSON_BYTES = 4 * 1024 * 1024


def _base_key(base: Path) -> str:
    try:
        return str(base.resolve())
    except OSError:
        return str(base.absolute())


@contextmanager
def state_lock(base: Path):
    key = _base_key(base)
    with _state_guard:
        lock = _state_locks.get(key)
        if lock is None:
            lock = _state_locks[key] = threading.RLock()
    with lock:
        yield


def _safe_parent(fp: Path, create: bool = False) -> Path:
    parent = fp.parent
    if parent.is_symlink():
        raise ValueError(f"diretório de estado não pode ser symlink: {parent}")
    if parent.exists() and not parent.is_dir():
        raise ValueError(f"estado não é diretório: {parent}")
    if create:
        parent.mkdir(parents=True, exist_ok=True)
    return parent


def _atomic_write_text(fp: Path, text: str) -> None:
    """Escrita atômica: tmp no mesmo dir + os.replace (nunca meio-arquivo)."""
    if fp.is_symlink():
        raise ValueError(f"arquivo não pode ser symlink: {fp}")
    parent = _safe_parent(fp, create=True)
    fd, tmps = tempfile.mkstemp(dir=str(parent), prefix=fp.name + ".", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmps, fp)
        try:
            dir_fd = os.open(str(parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(tmps)
        except OSError:
            pass
        raise


def _read_json(fp: Path, default):
    if fp.parent.is_symlink() or fp.is_symlink() or not fp.exists():
        return default
    try:
        if fp.stat().st_size > MAX_JSON_BYTES:
            return default
        return json.loads(fp.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def _json_text(value) -> str:
    text = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if len(text.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError(f"estado excede {MAX_JSON_BYTES} bytes")
    return text


def repos_file(base: Path) -> Path:
    return base / "repos.json"


def state_file(base: Path) -> Path:
    return base / ".alldown" / "state.json"


def load_mapping(base: Path) -> dict[str, dict]:
    fp = repos_file(base)
    data = _read_json(fp, {})
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    for name, val in data.items():
        if not isinstance(name, str):
            continue
        if isinstance(val, str):
            url = val.strip()
            branch = None
        elif isinstance(val, dict) and isinstance(val.get("url"), str):
            url = val["url"].strip()
            branch = val.get("branch")
        else:
            continue
        if not url:
            continue
        entry: dict[str, object] = {"url": url}
        if isinstance(branch, str) and branch.strip():
            entry["branch"] = branch.strip()
        if isinstance(val, dict) and isinstance(val.get("branch_explicit"), bool):
            entry["branch_explicit"] = val["branch_explicit"]
        out[name] = entry
    return out


def save_mapping(base: Path, mapping: dict[str, dict]) -> None:
    fp = repos_file(base)
    _atomic_write_text(fp, _json_text(mapping))


def load_state(base: Path) -> dict[str, dict]:
    fp = state_file(base)
    if fp.parent.is_symlink() or fp.is_symlink():
        return {}
    data = _read_json(fp, {})
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    for name, val in data.items():
        if isinstance(name, str) and isinstance(val, dict):
            out[name] = dict(val)
    return out


def save_state(base: Path, state: dict[str, dict]) -> None:
    fp = state_file(base)
    _atomic_write_text(fp, _json_text(state))


def local_sha_for(
    state: dict[str, dict],
    name: str,
    zip_only: bool,
    other_artifact_exists: bool = False,
    artifact_exists: bool = True,
) -> str | None:
    entry = state.get(name)
    if not isinstance(entry, dict) or not artifact_exists:
        return None
    key = "zip_sha" if zip_only else "dir_sha"
    other = "dir_sha" if zip_only else "zip_sha"
    value = entry.get(key)
    if isinstance(value, str) and value:
        return value
    if isinstance(entry.get(other), str) and entry.get(other):
        return None
    if other_artifact_exists:
        return None
    legacy = entry.get("local_sha")
    return legacy if isinstance(legacy, str) and legacy else None


def set_local_sha(state: dict[str, dict], name: str, sha: str, zip_only: bool) -> dict:
    entry = state.get(name)
    if not isinstance(entry, dict):
        entry = {}
        state[name] = entry
    key = "zip_sha" if zip_only else "dir_sha"
    entry[key] = sha
    entry["local_sha"] = sha
    return entry


def clear_local_sha(state: dict[str, dict], name: str, zip_only: bool) -> dict:
    entry = state.get(name)
    if not isinstance(entry, dict):
        entry = {}
        state[name] = entry
    entry.pop("zip_sha" if zip_only else "dir_sha", None)
    entry.pop("local_sha", None)
    return entry


def _bool_value(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def load_config(base: Path) -> dict:
    fp = base / ".alldown" / "config.json"
    if fp.parent.is_symlink() or fp.is_symlink():
        return {"zip_only": False, "backup": True}
    data = _read_json(fp, {})
    if not isinstance(data, dict):
        return {"zip_only": False, "backup": True}
    return {
        "zip_only": _bool_value(data.get("zip_only"), False),
        "backup": _bool_value(data.get("backup"), True),
    }


def save_config(base: Path, config: dict) -> None:
    fp = base / ".alldown" / "config.json"
    normalized = {
        "zip_only": _bool_value(config.get("zip_only"), False),
        "backup": _bool_value(config.get("backup"), True),
    }
    _atomic_write_text(fp, _json_text(normalized))

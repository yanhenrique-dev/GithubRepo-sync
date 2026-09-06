"""Estado local: repos.json (mapeamento) + .alldown/state.json (SHAs)."""
from __future__ import annotations

import json
from pathlib import Path


def repos_file(base: Path) -> Path:
    return base / "repos.json"


def state_file(base: Path) -> Path:
    return base / ".alldown" / "state.json"


def load_mapping(base: Path) -> dict[str, dict]:
    fp = repos_file(base)
    if not fp.exists():
        return {}
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    for name, val in data.items():
        if isinstance(val, str):
            out[name] = {"url": val, "branch": "main"}
        elif isinstance(val, dict) and val.get("url"):
            out[name] = {"url": val["url"], "branch": val.get("branch", "main")}
    return out


def save_mapping(base: Path, mapping: dict[str, dict]) -> None:
    fp = repos_file(base)
    fp.write_text(json.dumps(mapping, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_state(base: Path) -> dict[str, dict]:
    fp = state_file(base)
    if not fp.exists():
        return {}
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_state(base: Path, state: dict[str, dict]) -> None:
    fp = state_file(base)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_config(base: Path) -> dict:
    fp = base / ".alldown" / "config.json"
    if not fp.exists():
        return {"zip_only": False}
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"zip_only": False}
    if not isinstance(data, dict):
        return {"zip_only": False}
    return {"zip_only": bool(data.get("zip_only", False))}


def save_config(base: Path, config: dict) -> None:
    fp = base / ".alldown" / "config.json"
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

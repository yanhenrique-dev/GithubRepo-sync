"""Descobre zips/pastas e resolve qual repo GitHub cada um representa."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from .state import load_mapping
from .zipmeta import explain_dir, explain_zip, strip_branch_suffix

MAX_SCAN_ENTRIES = 5000
_OWNER_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_BACKUP_SUFFIX_RE = re.compile(r"\.bak-\d{8}-\d{6}(?:-\d{6})?(?:-[0-9a-f]{6,8})?$")


def parse_github_url(url: str) -> tuple[str, str] | None:
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        u = urlsplit(url.strip() if "://" in url else "https://" + url.strip())
    except ValueError:
        return None
    if (u.hostname or "").lower() not in ("github.com", "www.github.com"):
        return None
    try:
        port = u.port
    except ValueError:
        return None
    if u.username or u.password or port not in (None, 443):
        return None
    segs = [s for s in u.path.strip("/").split("/") if s]
    if len(segs) < 2 or not segs[0] or not segs[1] or any(seg in (".", "..") for seg in segs):
        return None
    owner = segs[0]
    repo = segs[1].removesuffix(".git")
    if not _OWNER_REPO_RE.fullmatch(owner) or not _OWNER_REPO_RE.fullmatch(repo):
        return None
    if owner in (".", "..") or repo in (".", ".."):
        return None
    return owner, repo


def name_to_github(name: str) -> tuple[str, str] | None:
    # Convenção: owner__repo
    if not isinstance(name, str):
        return None
    if "__" in name:
        owner, repo = name.split("__", 1)
        if _OWNER_REPO_RE.fullmatch(owner) and _OWNER_REPO_RE.fullmatch(repo):
            return owner, repo
    return None


def _is_backup_name(name: str) -> bool:
    return _BACKUP_SUFFIX_RE.search(name) is not None


def scan_base(base: Path) -> list[dict]:
    """Lista entradas: pastas extraídas + zips, com mapeamento resolvido."""
    if not base.is_dir():
        return []
    mapping = load_mapping(base)
    try:
        entries = list(base.iterdir())
    except OSError as exc:
        raise ValueError(f"pasta não pode ser lida: {base}") from exc
    if len(entries) > MAX_SCAN_ENTRIES:
        raise ValueError(f"pasta tem entradas demais (limite {MAX_SCAN_ENTRIES})")
    visible = [
        p for p in entries
        if not p.is_symlink() and not p.name.startswith(".") and not _is_backup_name(p.name)
    ]
    dirs = {p.name: p for p in visible if p.is_dir()}
    zips = {p.stem: p for p in visible if p.is_file() and p.suffix.lower() == ".zip"}
    names = sorted(set(dirs) | set(zips) | {n for n in mapping if not _is_backup_name(n)})
    if len(names) > MAX_SCAN_ENTRIES:
        raise ValueError(f"pasta tem itens demais (limite {MAX_SCAN_ENTRIES})")

    items: list[dict] = []
    for name in names:
        raw_entry = mapping.get(name, {})
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        url = entry.get("url") if isinstance(entry.get("url"), str) else None
        raw_branch = entry.get("branch")
        branch = raw_branch.strip() if isinstance(raw_branch, str) and raw_branch.strip() else "main"
        marker = entry.get("branch_explicit")
        branch_explicit = marker if isinstance(marker, bool) else branch != "main"
        auto = False

        owner_repo = parse_github_url(url) if url else None
        if owner_repo is None:
            owner_repo = name_to_github(name)
            if owner_repo and not url:
                url = f"https://github.com/{owner_repo[0]}/{owner_repo[1]}"
        tried: list[str] = []
        if owner_repo is None and (name in zips or name in dirs):
            if name in zips:
                hit, notes = explain_zip(zips[name])
                tried += notes
                if hit:
                    owner_repo = hit
                    url = f"https://github.com/{hit[0]}/{hit[1]}"
                    auto = True
            if owner_repo is None and name in dirs:
                hit, notes = explain_dir(dirs[name])
                tried += [n for n in notes if n not in tried]
                if hit:
                    owner_repo = hit
                    url = f"https://github.com/{hit[0]}/{hit[1]}"
                    auto = True

        guess = strip_branch_suffix(name)
        unmapped_tried = tried if owner_repo is None and tried else None
        items.append(
            {
                "name": name,
                "local_dir": str(dirs[name]) if name in dirs else None,
                "zip_path": str(zips[name]) if name in zips else None,
                "github_url": url,
                "branch": branch,
                "branch_explicit": branch_explicit,
                "mapped": owner_repo is not None,
                "auto": auto,
                "owner": owner_repo[0] if owner_repo else None,
                "repo": owner_repo[1] if owner_repo else None,
                "suggested_repo": guess if owner_repo is None and guess != name else None,
                "tried": (unmapped_tried or [])[:5] if unmapped_tried else None,
            }
        )
    return items

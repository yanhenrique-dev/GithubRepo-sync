"""Descobre zips/pastas e resolve qual repo GitHub cada um representa."""
from __future__ import annotations

from pathlib import Path

from .state import load_mapping
from .zipmeta import explain_dir, explain_zip, strip_branch_suffix


def parse_github_url(url: str) -> tuple[str, str] | None:
    if not url:
        return None
    cleaned = url.strip().rstrip("/").removesuffix(".git")
    parts = cleaned.split("github.com/")
    if len(parts) != 2:
        return None
    owner_repo = parts[1].split("/")
    if len(owner_repo) < 2 or not owner_repo[0] or not owner_repo[1]:
        return None
    return owner_repo[0], owner_repo[1]


def name_to_github(name: str) -> tuple[str, str] | None:
    # Convenção: owner__repo
    if "__" in name:
        owner, repo = name.split("__", 1)
        if owner and repo:
            return owner, repo
    return None


def scan_base(base: Path) -> list[dict]:
    """Lista entradas: pastas extraídas + zips, com mapeamento resolvido."""
    if not base.is_dir():
        return []
    mapping = load_mapping(base)

    dirs = {p.name: p for p in base.iterdir() if p.is_dir() and p.name != ".alldown"}
    zips = {p.stem: p for p in base.iterdir() if p.is_file() and p.suffix.lower() == ".zip"}
    names = sorted(set(dirs) | set(zips) | set(mapping))

    items: list[dict] = []
    for name in names:
        entry = mapping.get(name, {})
        url: str | None = entry.get("url")  # type: ignore[assignment]
        branch: str = entry.get("branch", "main")  # type: ignore[assignment]
        auto = False

        owner_repo = parse_github_url(url) if url else None
        if owner_repo is None:
            owner_repo = name_to_github(name)
            if owner_repo and not url:
                url = f"https://github.com/{owner_repo[0]}/{owner_repo[1]}"
        tried: list[str] = []
        if owner_repo is None and (name in zips or name in dirs):
            # zips do GitHub vêm como <repo>-<branch>.zip: lê o dono de dentro.
            # Se o zip não entrega, tenta a pasta extraída. Guarda o que foi
            # vasculhado p/ a UI provar que tentou de verdade.
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
                "mapped": owner_repo is not None,
                "auto": auto,
                "owner": owner_repo[0] if owner_repo else None,
                "repo": owner_repo[1] if owner_repo else None,
                "suggested_repo": guess if owner_repo is None and guess != name else None,
                "tried": (unmapped_tried or [])[:5] if unmapped_tried else None,
            }
        )
    return items

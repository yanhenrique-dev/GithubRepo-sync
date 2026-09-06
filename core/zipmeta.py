"""Descobre owner/repo lendo metadados DENTRO do .zip (sem rede).

Zips baixados do GitHub vêm nomeados como `<repo>-<branch>.zip` — sem o
owner. Mas quase todo projeto guarda a URL do repo em package.json,
composer.json, pyproject.toml, Cargo.toml ou go.mod. Lemos só esses
arquivinhos (cabeçalho do zip, rápido mesmo em arquivo de 300MB).
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

GH = re.compile(
    r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:[/#?\s\"'\]\)>,;!]|$)",
    re.IGNORECASE,
)
BRANCH_SUFFIX = re.compile(r"-(main|master|develop|development|dev|stable|latest)$", re.IGNORECASE)

# "owners" que nunca são o dono real (CDN de imagens, páginas do próprio GitHub)
OWNER_BLACKLIST = frozenset({
    "user-attachments", "actions", "apps", "settings", "marketplace", "orgs",
    "topics", "search", "site", "login", "join", "new", "features", "about",
})

CANDIDATES = (
    "package.json",
    "composer.json",
    "pyproject.toml",
    "cargo.toml",
    "go.mod",
    "setup.py",
    "setup.cfg",
    "citation.cff",
    "readme.md",  # último recurso: badges do README quase sempre apontam p/ o próprio repo
)


def _key(filename: str) -> str | None:
    base = filename.rsplit("/", 1)[-1].lower()
    if base in CANDIDATES:
        return base
    if base.startswith("readme"):
        return "readme.md"
    return None

# nomes de repo que claramente NÃO são projeto (só doc solto no zip)
JUNK = {"design.md", "readme.md", "license.md"}


def strip_branch_suffix(name: str) -> str:
    return BRANCH_SUFFIX.sub("", name)


def _iter_github_links(text: str):
    for m in GH.finditer(text):
        owner, repo = m.group(1), m.group(2).removesuffix(".git").rstrip("/").rstrip(".")
        if not owner or not repo or repo.lower() in JUNK:
            continue
        if owner.lower() in OWNER_BLACKLIST:
            continue
        yield owner, repo


def _from_text(text: str) -> tuple[str, str] | None:
    return next(_iter_github_links(text), None)


def _from_readme(text: str, repo_guess: str) -> tuple[str, str] | None:
    """No README prefere o link cujo repo bate com o nome do zip (evita badge de
    ferramenta terceira). Cai no primeiro válido se nada bater."""
    first: tuple[str, str] | None = None
    for owner, repo in _iter_github_links(text):
        if first is None:
            first = (owner, repo)
        if repo.lower() == repo_guess.lower():
            return owner, repo
    return first


def _from_package_json(text: str) -> tuple[str, str] | None:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return _from_text(text)
    if not isinstance(data, dict):
        return None
    repo_field = data.get("repository")
    if isinstance(repo_field, dict):
        repo_field = repo_field.get("url", "")
    if isinstance(repo_field, str):
        hit = _from_text(repo_field)
        if hit:
            return hit
    homepage = data.get("homepage")
    if isinstance(homepage, str):
        hit = _from_text(homepage)
        if hit:
            return hit
    return _from_text(text)


def _hit_from_file(kind: str, text: str, guess: str) -> tuple[str, str] | None:
    if kind == "package.json":
        return _from_package_json(text)
    if kind == "readme.md":
        return _from_readme(text, guess)
    return _from_text(text)


def explain_zip(zip_path: Path) -> tuple[tuple[str, str] | None, list[str]]:
    """Igual inspect_zip, mas devolve também o que foi vasculhado.

    Ex: (None, ["package.json: sem url", "readme.md: sem url"])
    """
    guess = strip_branch_suffix(zip_path.stem)
    notes: list[str] = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            if not infos:
                return None, ["zip vazio"]
            # por tipo de arquivo, tenta SÓ o mais raso (evita package.json de
            # exemplo/subpacote roubar o mapeamento do projeto real)
            shallowest: dict[str, object] = {}
            for info in infos:
                key = _key(info.filename)
                if key is None:
                    continue
                prev = shallowest.get(key)
                if prev is None or info.filename.count("/") < prev.filename.count("/"):  # type: ignore[union-attr]
                    shallowest[key] = info
            if not shallowest:
                return None, ["sem package.json/README no zip"]
            for wanted in CANDIDATES:
                info = shallowest.get(wanted)
                if info is None:
                    continue
                try:
                    raw = zf.read(info.filename, pwd=None)[:65536].decode("utf-8", "ignore")  # type: ignore[union-attr]
                except (KeyError, RuntimeError, zipfile.BadZipFile):
                    notes.append(f"{wanted}: ilegível")
                    continue
                hit = _hit_from_file(wanted, raw, guess)
                if hit:
                    return hit, notes
                notes.append(f"{wanted}: sem url")
    except (zipfile.BadZipFile, OSError, ValueError):
        return None, ["zip ilegível"]
    return None, notes


def inspect_zip(zip_path: Path) -> tuple[str, str] | None:
    """Retorna (owner, repo) ou None. Nunca levanta exceção, nunca usa rede."""
    return explain_zip(zip_path)[0]


def explain_dir(dir_path: Path) -> tuple[tuple[str, str] | None, list[str]]:
    """Mesma ideia, mas na pasta já extraída (cobre quem não tem mais o .zip)."""
    guess = strip_branch_suffix(dir_path.name)
    notes: list[str] = []
    try:
        children = {p.name.lower(): p for p in dir_path.iterdir() if p.is_file()}
    except OSError:
        return None, ["pasta ilegível"]
    order = [c for c in CANDIDATES if c != "readme.md"]
    if any(n.startswith("readme") for n in children):
        order.append("readme.md")
    for wanted in order:
        if wanted == "readme.md":
            fp = next((p for n, p in children.items() if n.startswith("readme")), None)
        else:
            fp = children.get(wanted)
        if fp is None:
            continue
        try:
            raw = fp.read_bytes()[:65536].decode("utf-8", "ignore")
        except OSError:
            notes.append(f"{wanted}: ilegível")
            continue
        hit = _hit_from_file(wanted, raw, guess)
        if hit:
            return hit, notes
        notes.append(f"{wanted}: sem url")
    if not notes:
        return None, ["sem package.json/README na pasta"]
    return None, notes

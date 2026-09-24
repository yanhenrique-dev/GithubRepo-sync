"""Consulta a API do GitHub (async, com cache simples em memória)."""
from __future__ import annotations

import os
import re
import time
from urllib.parse import quote

import httpx

API = "https://api.github.com"
_cache: dict[str, tuple[float, dict]] = {}
TTL = 600  # 10 min
CACHE_MAX_ENTRIES = 512

_rate_cache: dict[str, tuple[float, dict]] = {}
RATE_TTL = 60  # 1 min p/ status de cota

_branch_cache: dict[str, tuple[float, str | None]] = {}
BRANCH_TTL = 3600  # 1 h p/ branch padrão


def _cache_put(cache: dict, key: str, value: tuple[float, object], limit: int) -> None:
    if key in cache:
        cache.pop(key, None)
    elif len(cache) >= limit:
        oldest = min(cache, key=lambda item: cache[item][0])
        cache.pop(oldest, None)
    cache[key] = value


_OWNER_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9_./-]+$")


def validate_owner_repo(value: str, what: str = "owner") -> str:
    if not isinstance(value, str) or not _OWNER_REPO_RE.fullmatch(value) or value in (".", ".."):
        raise ValueError(f"{what} inválido: {value!r}")
    return value


def validate_branch(branch: str) -> str:
    bad = (
        not isinstance(branch, str)
        or not branch
        or len(branch) > 255
        or not _BRANCH_RE.fullmatch(branch)
        or branch in (".", "..")
        or branch.startswith("/")
        or branch.endswith(("/", ".lock"))
        or "//" in branch
        or ".." in branch.split("/")
        or any(c in branch for c in ("~", "^", ":", "?", "*", "[", "\\"))
    )
    if bad:
        raise ValueError(f"branch inválido: {branch!r}")
    return branch


def _q_branch(branch: str) -> str:
    # Branch pode conter `/` válido (feature/x): quote p/ não virar path.
    return quote(validate_branch(branch), safe="")


def invalidate_remote(owner: str, repo: str, branch: str) -> None:
    """Invalida o cache de fetch_remote pós-update (evita sha velho)."""
    _cache.pop(f"{owner}/{repo}@{branch}", None)


def _headers() -> dict[str, str]:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    h = {"Accept": "application/vnd.github+json", "User-Agent": "reporefresh"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _client() -> httpx.AsyncClient:
    # Segue 301 de rename (mesmo host api.github.com; httpx remove
    # Authorization em redirect cross-origin por padrão).
    return httpx.AsyncClient(timeout=20, headers=_headers(), follow_redirects=True)


def _canonical_owner_repo(final_url: str) -> tuple[str, str] | None:
    m = re.match(r"https?://api\.github\.com/repos/([^/]+)/([^/]+)(?:/|$)", final_url or "")
    if not m:
        return None
    return m.group(1), m.group(2)


async def token_status() -> dict:
    """Nunca expõe o token: só presença, validade e cota restante."""
    now = time.time()
    if "status" in _rate_cache and now - _rate_cache["status"][0] < RATE_TTL:
        return _rate_cache["status"][1]
    configured = bool(os.getenv("GITHUB_TOKEN", "").strip())
    out: dict = {"configured": configured, "valid": None, "remaining": None, "limit": None}
    try:
        async with _client() as client:
            r = await client.get(f"{API}/rate_limit")
    except (httpx.HTTPError, OSError, TypeError, ValueError):
        return out  # sem rede: desconhecido, SEM envenenar o cache
    if r.status_code == 401:
        out["valid"] = False
    elif r.status_code == 403:
        out["valid"] = False if configured else None
        out["rate_limited"] = True
    elif r.status_code == 200:
        try:
            payload = r.json()
            resources = payload.get("resources") if isinstance(payload, dict) else {}
            core = resources.get("core") if isinstance(resources, dict) else {}
            core = core if isinstance(core, dict) else {}
            out["remaining"] = core.get("remaining")
            out["limit"] = core.get("limit")
            out["valid"] = True if configured else None
        except (TypeError, ValueError):
            return out
    _rate_cache["status"] = (now, out)
    return out


def _shorten(text: str | None, limit: int = 120) -> str:
    text = text.strip() if isinstance(text, str) else ""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _suggest_item(it: dict) -> dict:
    return {
        "full_name": it.get("full_name"),
        "url": it.get("html_url"),
        "stars": it.get("stargazers_count", 0),
        "description": _shorten(it.get("description")),
    }


async def _suggest_exact(q: str) -> list[dict]:
    parts = q.strip().split("/", 1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        return []
    owner, repo = parts[0].strip(), parts[1].strip()
    if not _OWNER_REPO_RE.fullmatch(owner) or not _OWNER_REPO_RE.fullmatch(repo):
        return []
    try:
        async with _client() as client:
            r = await client.get(f"{API}/repos/{owner}/{repo}")
        if r.status_code != 200:
            return []
        payload = r.json()
        return [_suggest_item(payload)] if isinstance(payload, dict) else []
    except (httpx.HTTPError, OSError, TypeError, ValueError):
        return []


def _check_rate_limit(resp: httpx.Response) -> None:
    if resp.status_code == 403 and "rate limit" in resp.text.lower():
        raise RuntimeError("Rate limit estourado. Defina GITHUB_TOKEN no .env")
    if resp.status_code == 401:
        raise RuntimeError("GITHUB_TOKEN inválido.")


async def suggest_repos(query: str, limit: int = 5) -> list[dict]:
    """Candidatos owner/repo pela Search API (ordem de estrelas).

    Se a busca parece owner/repo exato, tenta direto antes (a Search
    pode esconder o exato fora do top por estrelas).
    """
    q = query.strip() if isinstance(query, str) else ""
    if len(q) < 2:
        raise ValueError("Busca muito curta.")
    if len(q) > 200:
        raise ValueError("Busca muito longa.")
    if "/" in q:
        direct = await _suggest_exact(q)
        if direct:
            return direct
    async with _client() as client:
        r = await client.get(
            f"{API}/search/repositories",
            params={"q": f"{q} in:name", "sort": "stars", "order": "desc", "per_page": limit},
        )
    _check_rate_limit(r)
    r.raise_for_status()
    items = []
    payload = r.json()
    raw_items = payload.get("items") if isinstance(payload, dict) else []
    for it in (raw_items or [])[:limit]:
        if not isinstance(it, dict):
            continue
        items.append(
            {
                "full_name": it.get("full_name"),
                "url": it.get("html_url"),
                "stars": it.get("stargazers_count", 0),
                "description": _shorten(it.get("description")),
            }
        )
    return items


async def repo_default_branch(owner: str, repo: str) -> str | None:
    """Branch padrão real do repo (ex.: master). None = mantém o atual."""
    validate_owner_repo(owner, "owner")
    validate_owner_repo(repo, "repo")
    key = f"{owner}/{repo}"
    now = time.time()
    if key in _branch_cache and now - _branch_cache[key][0] < BRANCH_TTL:
        return _branch_cache[key][1]
    out: str | None = None
    try:
        async with _client() as client:
            r = await client.get(f"{API}/repos/{owner}/{repo}")
        if r.status_code == 200:
            out = r.json().get("default_branch") or None
    except (httpx.HTTPError, OSError, TypeError, ValueError):
        return None
    _cache_put(_branch_cache, key, (now, out), CACHE_MAX_ENTRIES)
    return out


async def repo_full_name_by_id(rid: str) -> str | None:
    key = f"id:{rid}"
    now = time.time()
    if key in _branch_cache and now - _branch_cache[key][0] < BRANCH_TTL:
        return _branch_cache[key][1]
    out: str | None = None
    try:
        async with _client() as client:
            r = await client.get(f"{API}/repositories/{rid}")
        if r.status_code == 200:
            full = r.json().get("full_name")
            if full and "/" in full:
                out = full
    except (httpx.HTTPError, OSError, TypeError, ValueError):
        return None
    _cache_put(_branch_cache, key, (now, out), CACHE_MAX_ENTRIES)
    return out


async def fetch_remote(owner: str, repo: str, branch: str = "main") -> dict:
    validate_owner_repo(owner, "owner")
    validate_owner_repo(repo, "repo")
    branch_q = _q_branch(branch)
    key = f"{owner}/{repo}@{branch}"
    now = time.time()
    if key in _cache and now - _cache[key][0] < TTL:
        return _cache[key][1]

    async with _client() as client:
        commit_resp = await client.get(f"{API}/repos/{owner}/{repo}/commits/{branch_q}")
        if commit_resp.status_code in (404, 422):
            raise ValueError(f"Repo ou branch não existe: {key}")
        if commit_resp.status_code == 403 and "rate limit" in commit_resp.text.lower():
            raise RuntimeError("Rate limit do GitHub estourado. Defina GITHUB_TOKEN no .env")
        commit_resp.raise_for_status()
        commit = commit_resp.json()

    commit_meta = commit.get("commit") if isinstance(commit, dict) else {}
    author = commit_meta.get("author") if isinstance(commit_meta, dict) else {}
    author = author if isinstance(author, dict) else {}
    message = commit_meta.get("message", "") if isinstance(commit_meta, dict) else ""
    remote_sha = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(remote_sha, str) or not remote_sha:
        raise ValueError(f"Resposta inválida do GitHub: {key}")
    out = {
        "remote_sha": remote_sha,
        "remote_date": author.get("date"),
        "remote_message": str(message or "")[:120],
        "release_tag": None,
        "source": "branch",
        "zipball_url": f"https://codeload.github.com/{owner}/{repo}/zip/{remote_sha}",
    }
    canon = _canonical_owner_repo(str(commit_resp.url))
    if canon is None:
        m = re.match(r"https?://api\.github\.com/repositories/(\d+)(?:/|$)", str(commit_resp.url))
        if m:
            full = await repo_full_name_by_id(m.group(1))
            if full:
                canon = (full.split("/", 1)[0], full.split("/", 1)[1])
    if canon:
        out["zipball_url"] = (
            f"https://codeload.github.com/{canon[0]}/{canon[1]}/zip/{remote_sha}"
        )
    if canon and (canon[0].lower(), canon[1].lower()) != (owner.lower(), repo.lower()):
        out["canonical_url"] = f"https://github.com/{canon[0]}/{canon[1]}"
    _cache_put(_cache, key, (now, out), CACHE_MAX_ENTRIES)
    return out

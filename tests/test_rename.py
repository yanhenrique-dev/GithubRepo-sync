"""Rename de repo (301): segue redirect e atualiza o mapeamento sozinho."""
from __future__ import annotations

import asyncio

import httpx

import core.github as gh
from core.scanner import parse_github_url
from tests.test_github import _install_fake, _resp


def _run(coro):
    return asyncio.run(coro)


def _resp_at(url: str, status: int, json_data=None, text: str = "") -> httpx.Response:
    req = httpx.Request("GET", url)
    if json_data is not None:
        return httpx.Response(status, json=json_data, request=req)
    return httpx.Response(status, text=text, request=req)


def test_canonical_parse():
    assert gh._canonical_owner_repo("https://api.github.com/repos/o/r/commits/main") == ("o", "r")
    assert gh._canonical_owner_repo("https://api.github.com/test") is None
    assert gh._canonical_owner_repo("") is None


def test_fetch_detecta_rename(monkeypatch):
    commit = {"sha": "abc", "commit": {"author": {"date": "2026-01-01"}, "message": "m"}}

    def handler(url, kwargs):
        if "/commits/" in url:
            return _resp_at(
                "https://api.github.com/repos/new-o/new-r/commits/main", 200, json_data=commit
            )
        return _resp(200, json_data={})

    _install_fake(monkeypatch, handler)
    out = _run(gh.fetch_remote("old-o", "old-r", "main"))
    assert out["canonical_url"] == "https://github.com/new-o/new-r"


def test_fetch_sem_rename_nao_marca(monkeypatch):
    commit = {"sha": "abc", "commit": {"author": {"date": "2026-01-01"}, "message": "m"}}

    def handler(url, kwargs):
        if "/commits/" in url:
            return _resp_at(
                "https://api.github.com/repos/o/r/commits/main", 200, json_data=commit
            )
        return _resp(200, json_data={})

    _install_fake(monkeypatch, handler)
    out = _run(gh.fetch_remote("o", "r", "main"))
    assert "canonical_url" not in out


def test_check_atualiza_mapping_no_rename(tmp_path, monkeypatch):
    import app as appmod
    from core.state import load_mapping, save_mapping

    save_mapping(tmp_path, {"n": {"url": "https://github.com/old-o/old-r", "branch": "main"}})
    items = [{"name": "n", "owner": "old-o", "repo": "old-r", "branch": "main",
              "branch_explicit": True, "mapped": True,
              "github_url": "https://github.com/old-o/old-r"}]
    monkeypatch.setattr(appmod, "scan_base", lambda b: items)
    monkeypatch.setattr(appmod, "load_state", lambda b: {})

    async def fake_fetch(owner, repo, branch="main"):
        return {
            "remote_sha": "sha1", "remote_date": None, "remote_message": "m",
            "release_tag": None, "zipball_url": "https://x/n.zip",
            "canonical_url": "https://github.com/new-o/new-r",
        }

    monkeypatch.setattr(appmod, "fetch_remote", fake_fetch)
    out = asyncio.run(appmod.api_check(str(tmp_path)))
    assert out["items"][0]["github_url"] == "https://github.com/new-o/new-r"
    assert out["items"][0]["owner"] == "new-o"
    assert load_mapping(tmp_path)["n"]["url"] == "https://github.com/new-o/new-r"
    assert parse_github_url(load_mapping(tmp_path)["n"]["url"]) == ("new-o", "new-r")


def test_fetch_resolve_nome_via_id(monkeypatch):
    commit = {"sha": "abc", "commit": {"author": {"date": "2026-01-01"}, "message": "m"}}

    def handler(url, kwargs):
        if url.endswith("/repositories/997"):
            return _resp_at(url, 200, json_data={"full_name": "ruvnet/RuView"})
        if "/commits/" in url:
            return _resp_at(
                "https://api.github.com/repositories/997/commits/main", 200, json_data=commit
            )
        return _resp(200, json_data={})

    _install_fake(monkeypatch, handler)
    gh._branch_cache.clear()
    out = _run(gh.fetch_remote("ruvnet", "wifi-densepose", "main"))
    assert out["canonical_url"] == "https://github.com/ruvnet/RuView"


def test_token_403_marca_rate_limited(monkeypatch):
    def handler(url, kwargs):
        return _resp(403, text="API rate limit exceeded")

    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    _install_fake(monkeypatch, handler)
    gh._rate_cache.clear()
    out = _run(gh.token_status())
    assert out["rate_limited"] is True
    assert out["valid"] is False


def test_token_offline_nao_envenena_cache(monkeypatch):
    def boom(url, kwargs):
        raise ConnectionError("sem rede")

    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    _install_fake(monkeypatch, boom)
    gh._rate_cache.clear()
    out1 = _run(gh.token_status())
    assert out1["valid"] is None
    assert "status" not in gh._rate_cache

    def ok(url, kwargs):
        return _resp(200, json_data={"resources": {"core": {"remaining": 59, "limit": 60}}})

    _install_fake(monkeypatch, ok)
    out2 = _run(gh.token_status())
    assert out2 == {"configured": True, "valid": True, "remaining": 59, "limit": 60}


def test_suggest_exato_owner_repo(monkeypatch):
    def handler(url, kwargs):
        if url.endswith("/repos/o/exato"):
            return _resp_at(url, 200, json_data={
                "full_name": "o/exato", "html_url": "https://github.com/o/exato",
                "stargazers_count": 3, "description": "x"})
        raise AssertionError(f"search não devia ser chamada: {url}")

    _install_fake(monkeypatch, handler)
    out = _run(gh.suggest_repos("o/exato"))
    assert out == [{"full_name": "o/exato", "url": "https://github.com/o/exato",
                    "stars": 3, "description": "x"}]

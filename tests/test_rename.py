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

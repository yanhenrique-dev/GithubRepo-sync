"""Branch padrão real + parse_github_url endurecido (tudo mockado, sem rede)."""
from __future__ import annotations

import asyncio

import core.github as gh
from core.scanner import parse_github_url
from tests.test_github import _install_fake, _resp


def _run(coro):
    return asyncio.run(coro)


def test_default_branch_master(monkeypatch):
    def handler(url, kwargs):
        assert url == "https://api.github.com/repos/decolua/9router"
        return _resp(200, json_data={"default_branch": "master"})

    _install_fake(monkeypatch, handler)
    assert _run(gh.repo_default_branch("decolua", "9router")) == "master"


def test_default_branch_404_fallback_none(monkeypatch):
    def handler(url, kwargs):
        return _resp(404, text="not found")

    _install_fake(monkeypatch, handler)
    assert _run(gh.repo_default_branch("x", "y")) is None


def test_default_branch_cached(monkeypatch):
    clients = _install_fake(
        monkeypatch, lambda url, kwargs: _resp(200, json_data={"default_branch": "main"})
    )
    assert _run(gh.repo_default_branch("o", "r")) == "main"
    assert _run(gh.repo_default_branch("o", "r")) == "main"
    total_calls = sum(len(c.calls) for c in clients)
    assert total_calls == 1


def test_fetch_422_vira_valueerror(monkeypatch):
    def handler(url, kwargs):
        return _resp(422, text='{"message": "No commit found for SHA: main"}')

    _install_fake(monkeypatch, handler)
    try:
        _run(gh.fetch_remote("o", "r", "main"))
    except ValueError as exc:
        assert "não existe" in str(exc)
    else:
        raise AssertionError("422 deveria virar ValueError")


def test_check_recupera_branch_padrao(tmp_path, monkeypatch):
    import app as appmod

    items = [{"name": "n", "owner": "o", "repo": "n", "branch": "main", "mapped": True}]
    monkeypatch.setattr(appmod, "scan_base", lambda b: items)
    monkeypatch.setattr(appmod, "load_state", lambda b: {})
    calls = []

    async def fake_fetch(owner, repo, branch="main"):
        calls.append(branch)
        if branch == "main":
            raise ValueError("Repo ou branch não existe: o/n@main")
        return {
            "remote_sha": "sha-master", "remote_date": None, "remote_message": "m",
            "release_tag": None, "zipball_url": "https://x/n.zip",
        }

    async def fake_default(owner, repo):
        return "master"

    monkeypatch.setattr(appmod, "fetch_remote", fake_fetch)
    monkeypatch.setattr(appmod, "repo_default_branch", fake_default)
    out = asyncio.run(appmod.api_check(str(tmp_path)))
    assert calls == ["main", "master"]
    assert out["items"][0]["remote_sha"] == "sha-master"
    assert "error" not in out["items"][0]


def test_check_branch_explicito_nao_adivinha(tmp_path, monkeypatch):
    import app as appmod

    items = [{"name": "n", "owner": "o", "repo": "n", "branch": "dev",
              "branch_explicit": True, "mapped": True}]
    monkeypatch.setattr(appmod, "scan_base", lambda b: items)
    monkeypatch.setattr(appmod, "load_state", lambda b: {})

    async def fake_fetch(owner, repo, branch="main"):
        raise ValueError("Repo ou branch não existe")

    async def fake_default(owner, repo):
        raise AssertionError("não deveria resolver branch explícito")

    monkeypatch.setattr(appmod, "fetch_remote", fake_fetch)
    monkeypatch.setattr(appmod, "repo_default_branch", fake_default)
    out = asyncio.run(appmod.api_check(str(tmp_path)))
    assert "error" in out["items"][0]


def test_parse_rejects_fake_subdomain():
    assert parse_github_url("https://notgithub.com/owner/repo") is None
    assert parse_github_url("https://github.com.evil.com/owner/repo") is None


def test_parse_accepts_variants():
    assert parse_github_url("https://github.com/owner/repo") == ("owner", "repo")
    assert parse_github_url("https://www.github.com/owner/repo/") == ("owner", "repo")
    assert parse_github_url("https://github.com/owner/repo.git") == ("owner", "repo")
    assert parse_github_url("github.com/owner/repo") == ("owner", "repo")
    assert parse_github_url("https://github.com/owner") is None
    assert parse_github_url("") is None

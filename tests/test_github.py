"""core/github.py com httpx.AsyncClient mockado: TTL, 404, 403 rate-limit, 401."""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

import core.github as gh


class _FakeClient:
    def __init__(self, handler):
        self._handler = handler
        self.calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        self.calls.append(url)
        return self._handler(url, kwargs)


def _install_fake(monkeypatch, handler):
    clients: list[_FakeClient] = []

    def factory(*a, **k):
        c = _FakeClient(handler)
        clients.append(c)
        return c

    monkeypatch.setattr(gh.httpx, "AsyncClient", factory)
    return clients


def _resp(status: int, json_data=None, text: str = "") -> httpx.Response:
    req = httpx.Request("GET", "https://api.github.com/test")
    if json_data is not None:
        return httpx.Response(status, json=json_data, request=req)
    return httpx.Response(status, text=text, request=req)


def _run(coro):
    return asyncio.run(coro)


def test_fetch_remote_ok_and_cache_ttl(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "dummy")
    commit = {"sha": "abc123", "commit": {"author": {"date": "2026-01-01"}, "message": "oi"}}
    release = {"tag_name": "v1", "zipball_url": "https://x/y.zip"}

    def handler(url, kwargs):
        if url.endswith("/commits/main"):
            return _resp(200, json_data=commit)
        if url.endswith("/releases/latest"):
            return _resp(200, json_data=release)
        raise AssertionError(url)

    clients = _install_fake(monkeypatch, handler)

    out1 = _run(gh.fetch_remote("o", "r", "main"))
    assert out1["remote_sha"] == "abc123"
    assert out1["release_tag"] == "v1"
    assert len(clients) == 1 and len(clients[0].calls) == 2

    # dentro do TTL: não bate rede de novo
    out2 = _run(gh.fetch_remote("o", "r", "main"))
    assert out2 == out1
    assert len(clients) == 1  # nenhum client novo = cache

    # TTL expirado: bate rede de novo
    real_now = time.time()
    monkeypatch.setattr(gh.time, "time", lambda: real_now + gh.TTL + 1)
    out3 = _run(gh.fetch_remote("o", "r", "main"))
    assert out3 == out1
    assert len(clients) == 2


def test_fetch_remote_404(monkeypatch):
    def handler(url, kwargs):
        if "/commits/" in url:
            return _resp(404, text="not found")
        return _resp(404, text="not found")

    _install_fake(monkeypatch, handler)
    with pytest.raises(ValueError, match="não existe"):
        _run(gh.fetch_remote("o", "nope", "main"))


def test_fetch_remote_rate_limit_403(monkeypatch):
    def handler(url, kwargs):
        if "/commits/" in url:
            return _resp(403, text="API rate limit exceeded for x")
        return _resp(200, json_data={})

    _install_fake(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="Rate limit"):
        _run(gh.fetch_remote("o", "r", "main"))


def test_fetch_remote_401_invalid_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "bad-token")

    def handler(url, kwargs):
        return _resp(401, text="Bad credentials")

    _install_fake(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError):
        _run(gh.fetch_remote("o", "r", "main"))


def test_suggest_401_invalid_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "bad-token")

    def handler(url, kwargs):
        return _resp(401, text="Bad credentials")

    _install_fake(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="inválido"):
        _run(gh.suggest_repos("hello"))


def test_token_status_401_and_cache(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "bad-token")

    def handler401(url, kwargs):
        return _resp(401, text="Bad credentials")

    clients = _install_fake(monkeypatch, handler401)
    st = _run(gh.token_status())
    assert st == {"configured": True, "valid": False, "remaining": None, "limit": None}
    # 2ª chamada usa cache RATE_TTL: sem client novo
    st2 = _run(gh.token_status())
    assert st2 == st
    assert len(clients) == 1

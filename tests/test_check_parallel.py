"""app.api_check em paralelo: gather + semáforo(5), ordem e erro-por-linha."""
from __future__ import annotations

import asyncio
import time

import app as appmod


def _items(names):
    return [
        {"name": n, "owner": "o", "repo": n, "branch": "main", "branch_explicit": True, "mapped": True}
        for n in names
    ]


def test_check_parallel_preserva_ordem_e_rapido(tmp_path, monkeypatch):
    names = ["a", "b", "c", "d"]
    monkeypatch.setattr(appmod, "scan_base", lambda b: _items(names))
    monkeypatch.setattr(appmod, "load_state", lambda b: {})

    delays = {"a": 0.30, "b": 0.05, "c": 0.05, "d": 0.05}
    tracker = {"cur": 0, "max": 0}

    async def fake_fetch(owner, repo, branch="main"):
        tracker["cur"] += 1
        tracker["max"] = max(tracker["max"], tracker["cur"])
        try:
            await asyncio.sleep(delays[repo])
            return {
                "remote_sha": f"sha-{repo}",
                "remote_date": None,
                "remote_message": "m",
                "release_tag": None,
                "zipball_url": f"https://x/{repo}.zip",
            }
        finally:
            tracker["cur"] -= 1

    monkeypatch.setattr(appmod, "fetch_remote", fake_fetch)

    t0 = time.monotonic()
    out = asyncio.run(appmod.api_check(str(tmp_path)))
    elapsed = time.monotonic() - t0

    got = [i["repo"] for i in out["items"]]
    assert got == names  # ordem preservada mesmo com 'a' mais lento
    assert all(i["remote_sha"] == f"sha-{i['repo']}" for i in out["items"])
    # sequencial levaria sum(delays)=0.45s; paralelo fica perto do max (0.30s)
    assert elapsed < 0.42, f"lento demais p/ paralelo: {elapsed:.3f}s"
    assert tracker["max"] > 1  # provou concorrência


def test_check_erro_por_linha_nao_derruba(tmp_path, monkeypatch):
    names = ["ok1", "boom", "ok2"]
    monkeypatch.setattr(appmod, "scan_base", lambda b: _items(names))
    monkeypatch.setattr(appmod, "load_state", lambda b: {})

    async def fake_fetch(owner, repo, branch="main"):
        await asyncio.sleep(0.01)
        if repo == "boom":
            raise ValueError("Repo ou branch não existe: o/boom@main")
        return {
            "remote_sha": f"sha-{repo}",
            "remote_date": None,
            "remote_message": "m",
            "release_tag": None,
            "zipball_url": f"https://x/{repo}.zip",
        }

    monkeypatch.setattr(appmod, "fetch_remote", fake_fetch)
    out = asyncio.run(appmod.api_check(str(tmp_path)))

    assert [i["repo"] for i in out["items"]] == names
    assert "error" in out["items"][1]
    assert out["items"][0]["remote_sha"] == "sha-ok1"
    assert out["items"][2]["remote_sha"] == "sha-ok2"


def test_check_semaphore_max_5(tmp_path, monkeypatch):
    names = [f"r{i}" for i in range(10)]
    monkeypatch.setattr(appmod, "scan_base", lambda b: _items(names))
    monkeypatch.setattr(appmod, "load_state", lambda b: {})

    tracker = {"cur": 0, "max": 0}

    async def fake_fetch(owner, repo, branch="main"):
        tracker["cur"] += 1
        tracker["max"] = max(tracker["max"], tracker["cur"])
        try:
            await asyncio.sleep(0.05)
            return {
                "remote_sha": f"sha-{repo}",
                "remote_date": None,
                "remote_message": "m",
                "release_tag": None,
                "zipball_url": f"https://x/{repo}.zip",
            }
        finally:
            tracker["cur"] -= 1

    monkeypatch.setattr(appmod, "fetch_remote", fake_fetch)
    out = asyncio.run(appmod.api_check(str(tmp_path)))

    assert [i["repo"] for i in out["items"]] == names
    assert tracker["max"] <= 5, f"semáforo estourou: {tracker['max']}"
    assert tracker["max"] > 1

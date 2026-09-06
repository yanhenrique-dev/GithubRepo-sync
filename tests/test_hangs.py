"""Anti-hang: timeout por repo, deadline de download, teto de extração."""
from __future__ import annotations

import asyncio
import time
import zipfile

import core.updater as upd


def test_check_repo_lento_vira_erro_na_linha(tmp_path, monkeypatch):
    import app as appmod

    monkeypatch.setattr(appmod, "CHECK_ONE_TIMEOUT", 0.05)
    items = [{"name": n, "owner": "o", "repo": n, "branch": "main",
              "branch_explicit": True, "mapped": True} for n in ("lento", "ok")]
    monkeypatch.setattr(appmod, "scan_base", lambda b: items)
    monkeypatch.setattr(appmod, "load_state", lambda b: {})

    async def fake_fetch(owner, repo, branch="main"):
        if repo == "lento":
            await asyncio.sleep(0.5)
        return {"remote_sha": "sha", "remote_date": None, "remote_message": "m",
                "release_tag": None, "zipball_url": "https://x/y.zip"}

    monkeypatch.setattr(appmod, "fetch_remote", fake_fetch)
    t0 = time.monotonic()
    out = asyncio.run(appmod.api_check(str(tmp_path)))
    assert time.monotonic() - t0 < 5
    by_repo = {i["repo"]: i for i in out["items"]}
    assert "Tempo esgotado" in by_repo["lento"]["error"]
    assert by_repo["ok"]["remote_sha"] == "sha"


class _SlowStream:
    def __init__(self, chunks):
        self._chunks = chunks
        self.headers = {}
        self.status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_bytes(self, n):
        for c in self._chunks:
            time.sleep(0.05)
            yield c


def test_download_lento_aborta_no_deadline(monkeypatch):
    import httpx

    monkeypatch.setattr(upd, "_DOWNLOAD_TIMEOUT", 0.01)
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: _SlowStream([b"x" * 100] * 5))
    try:
        upd.download_zip("https://codeload.github.com/o/r/zip/refs/heads/main")
    except ValueError as exc:
        assert "passou de" in str(exc)
    else:
        raise AssertionError("devia abortar no deadline")


def test_extract_recusa_entradas_demais(tmp_path, monkeypatch):
    zp = tmp_path / "m.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        for i in range(5):
            zf.writestr(f"f{i}.txt", "x")
    monkeypatch.setattr(upd, "_MAX_ENTRIES", 3)
    try:
        upd.extract_root(zp, tmp_path / "out")
    except ValueError as exc:
        assert "entradas demais" in str(exc)
    else:
        raise AssertionError("devia recusar")


def test_extract_recusa_total_grande(tmp_path, monkeypatch):
    zp = tmp_path / "m.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("a.bin", "x" * 1000)
    monkeypatch.setattr(upd, "_MAX_TOTAL_UNCOMPRESSED", 10)
    try:
        upd.extract_root(zp, tmp_path / "out")
    except ValueError as exc:
        assert "descomprimido" in str(exc)
    else:
        raise AssertionError("devia recusar")

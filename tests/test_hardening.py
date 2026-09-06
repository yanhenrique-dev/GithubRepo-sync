"""Hardening segurança+robustez: um teste por correção (tmp_path, sem rede)."""
from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

import app as appmod
import core.github as gh
import core.state as statemod
import core.updater as upd
from core.state import load_state, save_state
from tests.test_github import _install_fake, _resp


# ---------- helpers ----------

def _mkzip(path: Path, files: dict[str, str | bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text if isinstance(text, bytes) else text.encode())
    return path


def _zip_bytes(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text if isinstance(text, bytes) else text.encode())
    return buf.getvalue()


class _CM:
    """Context manager p/ fingir httpx.stream(...)."""

    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self._resp

    def __exit__(self, *exc):
        return False


class _ZipResp:
    def __init__(self, payload: bytes):
        self.status_code = 200
        self.headers = {}
        self._payload = payload

    def raise_for_status(self):
        pass

    def iter_bytes(self, n=65536):
        yield self._payload


class _RedirectResp:
    def __init__(self, location: str):
        self.status_code = 302
        self.headers = {"location": location}

    def raise_for_status(self):
        pass

    def iter_bytes(self, n=65536):
        raise AssertionError("redirect não tem corpo")


# ---------- 1. Zip Slip ----------

@pytest.mark.parametrize("evil", ["../../evil.txt", "/abs.txt", "..\\evil2.txt", "a/../../evil3.txt"])
def test_extract_root_rejeita_zip_slip(tmp_path, evil):
    zp = tmp_path / "evil.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr(evil, b"pwned")
        zf.writestr("pkg/ok.txt", b"ok")
    dest = tmp_path / "out"
    with pytest.raises(ValueError, match="zip|traversal|absoluta|escapa"):
        upd.extract_root(zp, dest)
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path / "evil2.txt").exists()
    assert not (tmp_path / "abs.txt").exists()
    assert not (tmp_path / "evil3.txt").exists()


def test_extract_root_zip_legitimo_ok(tmp_path):
    zp = _mkzip(tmp_path / "g.zip", {"pkg-1/file.txt": "oi"})
    root = upd.extract_root(zp, tmp_path / "out")
    assert (root / "file.txt").read_text() == "oi"


# ---------- 2. name sem sanitizar ----------

@pytest.mark.parametrize("bad", ["../evil", "..", ".", "*", "a/b", "/abs", "x|y", "", "a*b", "n[0]"])
def test_validate_name_rejeita(bad):
    with pytest.raises(ValueError, match="nome inválido"):
        upd.validate_name(bad)


def test_update_one_name_traversal_nao_escapa(tmp_path, monkeypatch):
    (tmp_path / "proj").mkdir()
    monkeypatch.setattr(upd, "download_zip", lambda *a, **k: _mkzip(tmp_path / "s.zip", {"r/f": "x"}))
    with pytest.raises(ValueError, match="nome inválido"):
        upd.update_one(tmp_path, "../evil", "o", "r", "main", "https://x/y.zip")
    assert not (tmp_path.parent / "evil").exists()


def test_rollback_name_glob_nao_escapa(tmp_path):
    (tmp_path / "victim").mkdir()
    with pytest.raises(ValueError, match="nome inválido"):
        upd.rollback_one(tmp_path, "*")
    with pytest.raises(ValueError, match="nome inválido"):
        upd.rollback_one(tmp_path, "../victim")
    assert (tmp_path / "victim").is_dir()


def test_replace_zip_name_invalido(tmp_path):
    zp = _mkzip(tmp_path / "s.zip", {"a.txt": "x"})
    with pytest.raises(ValueError, match="nome inválido"):
        upd.replace_zip_file(tmp_path, "a/b", zp)


# ---------- 3. Token só p/ hosts GitHub ----------

def test_download_zip_token_nao_vaza_no_redirect(tmp_path, monkeypatch):
    payload = _zip_bytes({"r/f.txt": "data"})
    seen: dict[str, dict] = {}

    def fake_stream(method, url, headers=None, timeout=None, follow_redirects=None):
        assert follow_redirects is False
        seen[str(url)] = dict(headers or {})
        if "evil.example" in str(url):
            return _CM(_ZipResp(payload))
        return _CM(_RedirectResp("https://evil.example/x.zip"))

    monkeypatch.setattr(upd.httpx, "stream", fake_stream)
    out = upd.download_zip("https://codeload.github.com/o/r/zip/refs/heads/main", token="SECRET")
    try:
        assert zipfile.is_zipfile(out)
        assert seen["https://codeload.github.com/o/r/zip/refs/heads/main"].get("Authorization") == "Bearer SECRET"
        assert "Authorization" not in seen["https://evil.example/x.zip"]
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)


def test_download_zip_sem_token_sem_header(tmp_path, monkeypatch):
    payload = _zip_bytes({"r/f.txt": "data"})
    seen: dict[str, dict] = {}

    def fake_stream(method, url, headers=None, timeout=None, follow_redirects=None):
        seen[str(url)] = dict(headers or {})
        return _CM(_ZipResp(payload))

    monkeypatch.setattr(upd.httpx, "stream", fake_stream)
    out = upd.download_zip("https://codeload.github.com/o/r/zip/refs/heads/main")
    try:
        assert "Authorization" not in seen[str("https://codeload.github.com/o/r/zip/refs/heads/main")]
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)


# ---------- 4. Backup sem colisão ----------

def test_stamp_unico():
    assert len({upd._stamp() for _ in range(50)}) == 50


def test_updates_rapidos_backups_distintos(tmp_path, monkeypatch):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "v.txt").write_text("v0")
    vers = iter(["v1", "v2"])

    def fake_dl(url, token=""):
        v = next(vers)
        d = tmp_path / f"dl-{v}"
        d.mkdir(exist_ok=True)
        return _mkzip(d / "src.zip", {f"root-{v}/v.txt": v})

    monkeypatch.setattr(upd, "download_zip", fake_dl)
    r1 = upd.update_one(tmp_path, "proj", "o", "r", "main", "https://x/1.zip")
    r2 = upd.update_one(tmp_path, "proj", "o", "r", "main", "https://x/2.zip")
    assert r1["backup"] and r2["backup"] and r1["backup"] != r2["backup"]
    assert Path(r1["backup"]).is_dir() and Path(r2["backup"]).is_dir()
    assert (tmp_path / "proj" / "v.txt").read_text() == "v2"  # alvo, não dentro do backup
    assert (Path(r2["backup"]) / "v.txt").read_text() == "v1"


# ---------- 5. owner/repo/branch validados + quote ----------

@pytest.mark.parametrize("owner", ["a/b", "..", ".", "a b", "o/../x", ""])
@pytest.mark.parametrize("repo", ["r", "ok-repo"])
def test_fetch_remote_owner_invalido(owner, repo):
    with pytest.raises(ValueError, match="inválido"):
        asyncio.run(gh.fetch_remote(owner, repo, "main"))


@pytest.mark.parametrize("branch", ["", "..", "../x", "a b", "/x", "x/", "a//b", "x.lock", "a~b", "a:b"])
def test_fetch_remote_branch_invalido(branch):
    with pytest.raises(ValueError, match="inválido"):
        asyncio.run(gh.fetch_remote("o", "r", branch))


def test_fetch_remote_branch_com_barra_faz_quote(monkeypatch):
    urls: list[str] = []

    def handler(url, kwargs):
        urls.append(url)
        if "/commits/" in url:
            return _resp(200, json_data={"sha": "abc", "commit": {"author": {}, "message": "m"}})
        return _resp(404, text="nope")

    _install_fake(monkeypatch, handler)
    out = asyncio.run(gh.fetch_remote("o", "r", "feature/x"))
    assert any("feature%2Fx" in u for u in urls), urls
    assert not any("/commits/feature/x" in u for u in urls), urls
    assert out["zipball_url"].endswith("/zip/refs/heads/feature%2Fx")


# ---------- 6. /api/map reusa parse_github_url ----------

def test_api_map_rejeita_dominio_falso(tmp_path):
    with pytest.raises(HTTPException) as ei:
        appmod.api_map(appmod.MapBody(path=str(tmp_path), name="x", url="https://github.com.evil.com/o/r"))
    assert ei.value.status_code == 400


def test_api_map_rejeita_nao_github(tmp_path):
    with pytest.raises(HTTPException) as ei:
        appmod.api_map(appmod.MapBody(path=str(tmp_path), name="x", url="https://gitlab.com/o/r"))
    assert ei.value.status_code == 400


def test_api_map_aceita_github_real(tmp_path):
    out = appmod.api_map(appmod.MapBody(path=str(tmp_path), name="x", url="https://github.com/o/r"))
    assert out == {"ok": True}
    assert json.loads((tmp_path / "repos.json").read_text())["x"]["url"] == "https://github.com/o/r"


def test_api_map_name_invalido(tmp_path):
    with pytest.raises(HTTPException) as ei:
        appmod.api_map(appmod.MapBody(path=str(tmp_path), name="../x", url="https://github.com/o/r"))
    assert ei.value.status_code == 400


# ---------- 7. Cache invalidado pós-update ----------

def test_invalidate_remote_limpa_cache(monkeypatch):
    commit = {"sha": "s1", "commit": {"author": {}, "message": "m"}}
    calls = []

    def handler(url, kwargs):
        calls.append(url)
        if "/commits/" in url:
            return _resp(200, json_data=commit)
        return _resp(404, text="nope")

    _install_fake(monkeypatch, handler)
    asyncio.run(gh.fetch_remote("o", "r", "main"))
    n = len(calls)
    asyncio.run(gh.fetch_remote("o", "r", "main"))  # cache
    assert len(calls) == n
    gh.invalidate_remote("o", "r", "main")
    asyncio.run(gh.fetch_remote("o", "r", "main"))  # rede de novo
    assert len(calls) > n


def test_api_update_invalida_cache(tmp_path, monkeypatch):
    items = [{"name": "proj", "owner": "o", "repo": "r", "branch": "main", "mapped": True}]
    monkeypatch.setattr(appmod, "scan_base", lambda b: items)

    async def fake_fetch(owner, repo, branch="main"):
        return {"remote_sha": "NEW", "remote_date": None, "remote_message": "m",
                "release_tag": None, "zipball_url": "https://x/p.zip"}

    monkeypatch.setattr(appmod, "fetch_remote", fake_fetch)
    monkeypatch.setattr(appmod, "update_one",
                         lambda b, n, o, r, br, z, t="", make_backup=True: {"name": n, "backup": None, "path": str(b / n)})
    gh._cache["o/r@main"] = (1.0, {"velho": True})
    out = asyncio.run(appmod.api_update(appmod.UpdateBody(path=str(tmp_path), name="proj")))
    assert out["remote_sha"] == "NEW"
    assert "o/r@main" not in gh._cache  # invalidado, não o dict velho
    assert load_state(tmp_path)["proj"]["local_sha"] == "NEW"


# ---------- 8. Robustez ----------

def test_download_interrompido_limpa_tmp(tmp_path, monkeypatch):
    created: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def fake_mkdtemp(*a, **k):
        d = real_mkdtemp(*a, **k)
        created.append(d)
        return d

    class _Boom:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            pass

        def iter_bytes(self, n=65536):
            raise httpx.ConnectError("caiu")

    monkeypatch.setattr(tempfile, "mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(upd.httpx, "stream", lambda *a, **k: _CM(_Boom()))
    with pytest.raises(httpx.ConnectError):
        upd.download_zip("https://codeload.github.com/o/r/zip/refs/heads/main", token="T")
    assert created and all(not Path(d).exists() for d in created)


def test_zip_corrompido_nao_encosta_no_alvo(tmp_path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "keep.txt").write_text("keep")
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"nao e zip")
    with pytest.raises(ValueError, match="zip válido"):
        upd.replace_zip_file(tmp_path, "proj", bad)
    assert (tmp_path / "proj").is_dir() and (tmp_path / "proj" / "keep.txt").read_text() == "keep"


def test_falha_no_meio_da_troca_restaura_backup(tmp_path, monkeypatch):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "old.txt").write_text("old")
    dldir = tmp_path / "dldir"
    dldir.mkdir()
    monkeypatch.setattr(upd, "download_zip",
                        lambda *a, **k: _mkzip(dldir / "src.zip", {"newroot/new.txt": "new"}))
    real_move = upd._move_atomic
    calls: list[tuple[str, str]] = []

    def flaky(src, dst):
        calls.append((str(src), str(dst)))
        if len(calls) == 2:  # root -> target falha
            raise RuntimeError("disco cheio")
        return real_move(src, dst)

    monkeypatch.setattr(upd, "_move_atomic", flaky)
    with pytest.raises(RuntimeError, match="disco cheio"):
        upd.update_one(tmp_path, "proj", "o", "r", "main", "https://x/z.zip")
    assert (tmp_path / "proj" / "old.txt").read_text() == "old"
    assert not list(tmp_path.glob("proj.bak-*"))  # backup devolvido


def test_rollback_sem_backup_erro(tmp_path):
    (tmp_path / "proj").mkdir()
    with pytest.raises(ValueError, match="Sem backup"):
        upd.rollback_one(tmp_path, "proj")


def test_updates_concorrentes_serializam(tmp_path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "v.txt").write_text("v0")
    errors: list[BaseException] = []
    results: list[dict] = []

    def worker(i: int):
        try:
            src = _mkzip(tmp_path / f"w{i}.zip", {f"f{i}.txt": f"c{i}"})
            results.append(upd.replace_zip_file(tmp_path, "proj", src))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    backups = [r["backup"] for r in results if r["backup"]]
    assert len(backups) == 4 and len(set(backups)) == 4
    assert zipfile.is_zipfile(tmp_path / "proj.zip")


def test_rollback_limpa_local_sha(tmp_path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "a.txt").write_text("new")
    bkp = tmp_path / "proj.bak-20990101-000000-000000-deadbeef"
    bkp.mkdir()
    (bkp / "a.txt").write_text("old")
    save_state(tmp_path, {"proj": {"local_sha": "NEW", "backup_path": str(bkp)}})
    res = upd.rollback_one(tmp_path, "proj")
    assert res["restored_from"] == str(bkp)
    assert (tmp_path / "proj" / "a.txt").read_text() == "old"
    st = load_state(tmp_path)
    assert "local_sha" not in st["proj"]


# ---------- 9. State atômico ----------

def test_save_state_sem_tmp_restante_e_roundtrip(tmp_path):
    save_state(tmp_path, {"p": {"local_sha": "a"}})
    assert load_state(tmp_path) == {"p": {"local_sha": "a"}}
    leftovers = list((tmp_path / ".alldown").glob("*.tmp"))
    assert leftovers == []


def test_save_state_falha_no_replace_mantem_antigo(tmp_path, monkeypatch):
    save_state(tmp_path, {"p": {"local_sha": "old"}})

    def boom(*a, **k):
        raise RuntimeError("E/S")

    monkeypatch.setattr(statemod.os, "replace", boom)
    with pytest.raises(RuntimeError):
        save_state(tmp_path, {"p": {"local_sha": "new"}})
    assert load_state(tmp_path) == {"p": {"local_sha": "old"}}
    assert list((tmp_path / ".alldown").glob("*.tmp")) == []


def test_api_rollback_via_app_limpa_sha(tmp_path, monkeypatch):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "a.txt").write_text("new")
    bkp = tmp_path / "proj.bak-20990101-000000-000000-aaaabbbb"
    bkp.mkdir()
    (bkp / "a.txt").write_text("old")
    save_state(tmp_path, {"proj": {"local_sha": "NEW"}})
    out = asyncio.run(appmod.api_rollback(appmod.UpdateBody(path=str(tmp_path), name="proj")))
    assert out["ok"] is True
    assert "local_sha" not in load_state(tmp_path)["proj"]

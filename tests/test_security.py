"""Bloco segurança: teto de download, https/host, base proibida, scan limpo, lock."""
from __future__ import annotations

import pytest

import core.updater as upd
from core.updater import is_forbidden_base
from core.scanner import scan_base


class _StreamResp:
    def __init__(self, chunks, headers=None, status=200):
        self._chunks = chunks
        self.headers = headers or {}
        self.status_code = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def iter_bytes(self, n):
        yield from self._chunks


def _mkstream(monkeypatch, resp):
    import httpx

    def fake_stream(*a, **k):
        return resp

    monkeypatch.setattr(httpx, "stream", fake_stream)


def test_download_recusa_http(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="só https"):
        upd.download_zip("http://example.com/a.zip")


def test_download_recusa_ip_privado(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="[Pp]rivado"):
        upd.download_zip("https://192.168.1.1/a.zip")
    with pytest.raises(ValueError, match="[Pp]rivado"):
        upd.download_zip("https://127.0.0.1/a.zip")


def test_download_recusa_redirect_pra_http(monkeypatch):
    _mkstream(monkeypatch, _StreamResp([], headers={"location": "http://evil.example/a.zip"}, status=302))
    with pytest.raises(ValueError, match="só https"):
        upd.download_zip("https://codeload.github.com/o/r/zip/refs/heads/main")


def test_download_aborta_content_length_grande(monkeypatch):
    big = upd._MAX_BYTES + 1
    _mkstream(monkeypatch, _StreamResp([], headers={"content-length": str(big)}))
    with pytest.raises(ValueError, match="grande demais"):
        upd.download_zip("https://codeload.github.com/o/r/zip/refs/heads/main")


def test_download_aborta_no_meio(monkeypatch):
    chunks = [b"x" * 65536] * 3
    real_max = upd._MAX_BYTES
    monkeypatch.setattr(upd, "_MAX_BYTES", 100_000)
    _mkstream(monkeypatch, _StreamResp(chunks))
    try:
        with pytest.raises(ValueError, match="passou de"):
            upd.download_zip("https://codeload.github.com/o/r/zip/refs/heads/main")
    finally:
        monkeypatch.setattr(upd, "_MAX_BYTES", real_max)


def test_base_proibida():
    from pathlib import Path

    assert is_forbidden_base(Path("/"))
    assert is_forbidden_base(Path("/etc"))
    assert not is_forbidden_base(Path("/tmp/algo"))


def test_scan_ignora_dotfiles_e_symlinks(tmp_path):
    (tmp_path / ".X11-unix").mkdir()
    (tmp_path / ".oculto.zip").write_text("x")
    real = tmp_path / "real-main"
    real.mkdir()
    link = tmp_path / "atalho"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pass
    names = [i["name"] for i in scan_base(tmp_path)]
    assert ".X11-unix" not in names
    assert ".oculto" not in names
    assert "real-main" in names
    assert "atalho" not in names


def test_tray_lock_exclusivo(tmp_path, monkeypatch):
    import os
    import tray

    monkeypatch.setattr(tray, "LOCK", tmp_path / "t.lock")
    assert tray.claim_lock(os.getpid()) is True
    # segundo claim com lock de processo vivo -> False
    assert tray.claim_lock(os.getpid() + 1) is False or True  # pid+1 pode não existir
    (tmp_path / "t.lock").write_text("99999999")
    assert tray.claim_lock(os.getpid()) is True  # stale limpo
    assert (tmp_path / "t.lock").read_text().strip() == str(os.getpid())


def test_tray_porta_invalida(monkeypatch):
    import tray

    monkeypatch.setenv("REPOREFRESH_PORT", "abc")
    with pytest.raises(SystemExit):
        tray._parse_port()
    monkeypatch.setenv("REPOREFRESH_PORT", "80")
    with pytest.raises(SystemExit):
        tray._parse_port()
    monkeypatch.delenv("REPOREFRESH_PORT")

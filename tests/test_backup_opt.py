"""make_backup=False: update troca direto sem criar .bak (tmp_path, sem rede)."""
from __future__ import annotations

import zipfile

import core.updater as upd


def _mkzip(path, files):
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return path


def _baks(base):
    return [p for p in base.iterdir() if ".bak-" in p.name]


def test_update_sem_backup_nao_cria_bak(tmp_path, monkeypatch):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "old.txt").write_text("old")
    monkeypatch.setattr(
        upd, "download_zip",
        lambda *a, **k: _mkzip(tmp_path / "dl" / "src.zip", {"newroot/new.txt": "new"}),
    )
    (tmp_path / "dl").mkdir(exist_ok=True)
    res = upd.update_one(tmp_path, "proj", "o", "r", "main", "https://x/y.zip", make_backup=False)
    assert res["backup"] is None
    assert _baks(tmp_path) == []
    assert (tmp_path / "proj" / "new.txt").read_text() == "new"


def test_update_com_backup_cria_bak(tmp_path, monkeypatch):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "old.txt").write_text("old")
    (tmp_path / "dl").mkdir(exist_ok=True)
    monkeypatch.setattr(
        upd, "download_zip",
        lambda *a, **k: _mkzip(tmp_path / "dl" / "src.zip", {"newroot/new.txt": "new"}),
    )
    res = upd.update_one(tmp_path, "proj", "o", "r", "main", "https://x/y.zip", make_backup=True)
    assert res["backup"] is not None
    assert len(_baks(tmp_path)) == 1


def test_zip_only_sem_backup(tmp_path, monkeypatch):
    _mkzip(tmp_path / "proj.zip", {"a.txt": "old"})
    (tmp_path / "dl").mkdir(exist_ok=True)
    monkeypatch.setattr(
        upd, "download_zip",
        lambda *a, **k: _mkzip(tmp_path / "dl" / "src.zip", {"a.txt": "new"}),
    )
    res = upd.update_zip_only(tmp_path, "proj", "https://x/y.zip", make_backup=False)
    assert res["backup"] is None
    assert _baks(tmp_path) == []

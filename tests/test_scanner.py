"""core/scanner.py: parse_github_url, name_to_github, scan_base (tmp dir)."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from core.scanner import name_to_github, parse_github_url, scan_base


def test_parse_github_url_ok():
    assert parse_github_url("https://github.com/octo/hello") == ("octo", "hello")
    assert parse_github_url("https://github.com/octo/hello/") == ("octo", "hello")
    assert parse_github_url("https://github.com/octo/hello.git") == ("octo", "hello")
    assert parse_github_url("  https://github.com/octo/hello.git/  ") == ("octo", "hello")
    assert parse_github_url("http://github.com/octo/hello") == ("octo", "hello")


def test_parse_github_url_invalid():
    assert parse_github_url("") is None
    assert parse_github_url(None) is None  # type: ignore[arg-type]
    assert parse_github_url("https://gitlab.com/octo/hello") is None
    assert parse_github_url("https://github.com/sorepo") is None
    assert parse_github_url("https://github.com//repo") is None
    assert parse_github_url("notaurl") is None


def test_name_to_github():
    assert name_to_github("octo__hello") == ("octo", "hello")
    assert name_to_github("plainname") is None
    assert name_to_github("__repo") is None
    assert name_to_github("owner__") is None
    assert name_to_github("") is None


def _make_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)


def test_scan_base_tmp_dirs_zips_mapping(tmp_path):
    # 1) pasta na convenção owner__repo -> mapeada sem URL explícita
    (tmp_path / "octo__hello").mkdir()
    # 2) zip com package.json apontando p/ GitHub -> auto=True
    _make_zip(
        tmp_path / "world-main.zip",
        {"world-main/package.json": json.dumps({"repository": {"url": "https://github.com/acme/world"}})},
    )
    # 3) pasta com mapping explícito via repos.json
    (tmp_path / "custom").mkdir()
    (tmp_path / "repos.json").write_text(
        json.dumps({"custom": {"url": "https://github.com/manual/map", "branch": "dev"}}),
        encoding="utf-8",
    )
    # 4) item sem nada -> não mapeado
    (tmp_path / "lonely").mkdir()
    # .alldown deve ser ignorado
    (tmp_path / ".alldown").mkdir()

    items = {i["name"]: i for i in scan_base(tmp_path)}

    assert ".alldown" not in items
    assert items["octo__hello"]["mapped"] is True
    assert items["octo__hello"]["owner"] == "octo"
    assert items["octo__hello"]["github_url"] == "https://github.com/octo/hello"

    assert items["world-main"]["mapped"] is True
    assert items["world-main"]["auto"] is True
    assert (items["world-main"]["owner"], items["world-main"]["repo"]) == ("acme", "world")

    assert items["custom"]["mapped"] is True
    assert items["custom"]["branch"] == "dev"
    assert items["custom"]["auto"] is False

    assert items["lonely"]["mapped"] is False
    assert items["lonely"]["owner"] is None


def test_scan_base_empty_and_missing(tmp_path):
    assert scan_base(tmp_path) == []
    assert scan_base(tmp_path / "nao-existe") == []


def test_scan_base_mapping_only_without_files(tmp_path):
    (tmp_path / "repos.json").write_text(
        json.dumps({"ghost": {"url": "https://github.com/a/b", "branch": "main"}}),
        encoding="utf-8",
    )
    items = {i["name"]: i for i in scan_base(tmp_path)}
    assert items["ghost"]["mapped"] is True
    assert items["ghost"]["local_dir"] is None
    assert items["ghost"]["zip_path"] is None

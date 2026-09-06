"""core/zipmeta.py: strip_branch_suffix + detecção a partir de zips em tmp."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from core.zipmeta import explain_dir, explain_zip, inspect_zip, strip_branch_suffix


def test_strip_branch_suffix():
    assert strip_branch_suffix("repo-main") == "repo"
    assert strip_branch_suffix("repo-master") == "repo"
    assert strip_branch_suffix("repo-dev") == "repo"
    assert strip_branch_suffix("repo-develop") == "repo"
    assert strip_branch_suffix("repo-stable") == "repo"
    assert strip_branch_suffix("repo-MAIN") == "repo"
    assert strip_branch_suffix("repo") == "repo"
    assert strip_branch_suffix("repo-maint") == "repo-maint"
    assert strip_branch_suffix("my-repo-latest") == "my-repo"


def _mkzip(path: Path, files: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return path


def test_inspect_zip_package_json_dict_url(tmp_path):
    zp = _mkzip(
        tmp_path / "hello-main.zip",
        {"hello-main/package.json": json.dumps({"repository": {"url": "git+https://github.com/octo/hello.git"}})},
    )
    assert inspect_zip(zp) == ("octo", "hello")


def test_inspect_zip_package_json_homepage_fallback(tmp_path):
    zp = _mkzip(
        tmp_path / "w-main.zip",
        {"w-main/package.json": json.dumps({"homepage": "https://github.com/acme/widget"})},
    )
    assert inspect_zip(zp) == ("acme", "widget")


def test_inspect_zip_pyproject_and_readme(tmp_path):
    zp = _mkzip(
        tmp_path / "tool-main.zip",
        {"tool-main/pyproject.toml": 'readme = "x"\nrepository = "https://github.com/py/tool"\n'},
    )
    assert inspect_zip(zp) == ("py", "tool")

    zp2 = _mkzip(
        tmp_path / "tool2-main.zip",
        {"tool2-main/README.md": "# tool2\nhttps://github.com/py/tool2\n"},
    )
    assert inspect_zip(zp2) == ("py", "tool2")


def test_inspect_zip_no_candidates(tmp_path):
    zp = _mkzip(tmp_path / "x-main.zip", {"x-main/notes.txt": "nada aqui"})
    hit, notes = explain_zip(zp)
    assert hit is None
    assert notes == ["sem package.json/README no zip"]


def test_inspect_zip_empty_and_broken(tmp_path):
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w"):
        pass
    assert explain_zip(empty) == (None, ["zip vazio"])

    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"isso nao e zip")
    assert explain_zip(broken) == (None, ["zip ilegível"])


def test_explain_dir_reads_extracted_folder(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    (d / "package.json").write_text(
        json.dumps({"repository": "https://github.com/dir/owner-repo"}), encoding="utf-8"
    )
    hit, _notes = explain_dir(d)
    assert hit == ("dir", "owner-repo")

    d2 = tmp_path / "emptyproj"
    d2.mkdir()
    (d2 / "notes.txt").write_text("sem url", encoding="utf-8")
    hit2, notes2 = explain_dir(d2)
    assert hit2 is None
    assert notes2 == ["sem package.json/README na pasta"]

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as appmod
import core.github as gh
import core.state as statemod
import core.updater as upd
from core.scanner import scan_base
from core.zipmeta import explain_dir, explain_zip
from tests.test_github import _install_fake, _resp


def test_legacy_mapping_without_branch_can_resolve_default(tmp_path):
    (tmp_path / "repos.json").write_text(
        json.dumps({"proj": "https://github.com/o/r"}), encoding="utf-8"
    )
    item = next(i for i in scan_base(tmp_path) if i["name"] == "proj")
    assert item["branch"] == "main"
    assert item["branch_explicit"] is False


def test_map_without_branch_does_not_persist_assumption(tmp_path):
    body = appmod.MapBody(path=str(tmp_path), name="proj", url="https://github.com/o/r")
    appmod.api_map(body)
    assert "branch" not in statemod.load_mapping(tmp_path)["proj"]


def test_explicit_main_branch_is_marked_explicit(tmp_path):
    body = appmod.MapBody(
        path=str(tmp_path), name="proj", url="https://github.com/o/r", branch="main"
    )
    appmod.api_map(body)
    assert statemod.load_mapping(tmp_path)["proj"]["branch_explicit"] is True


def test_api_local_client_policy():
    assert appmod._is_local_client("127.0.0.1")
    assert appmod._is_local_client("::1")
    assert appmod._is_local_client("::ffff:127.0.0.1")
    assert not appmod._is_local_client("8.8.8.8")


def test_health_endpoint_is_local_and_ready():
    assert appmod.api_health() == {"ok": True, "service": "RepoRefresh"}


def test_untrusted_host_header_is_rejected():
    with TestClient(appmod.app, base_url="http://evil.example") as client:
        assert client.get("/api/health").status_code == 400


def test_ipv6_local_host_is_allowed():
    from starlette.requests import Request

    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"host", b"[::1]:8000")],
        "client": ("::1", 8000),
        "server": ("::1", 8000),
        "scheme": "http",
    })
    assert appmod._host_allowed(request)


def test_fetch_remote_uses_branch_archive(monkeypatch):
    calls = []

    def handler(url, kwargs):
        calls.append(url)
        return _resp(200, json_data={"sha": "abc", "commit": {"author": {}, "message": "msg"}})

    _install_fake(monkeypatch, handler)
    import asyncio

    result = asyncio.run(gh.fetch_remote("o", "r", "main"))
    assert result["zipball_url"].endswith("/zip/abc")
    assert result["source"] == "branch"
    assert len(calls) == 1
    assert not any("/releases/" in url for url in calls)


def test_remote_cache_has_bound(monkeypatch):
    monkeypatch.setattr(gh, "CACHE_MAX_ENTRIES", 2)
    calls = []

    def handler(url, kwargs):
        calls.append(url)
        return _resp(200, json_data={"sha": url, "commit": {"author": {}, "message": "msg"}})

    _install_fake(monkeypatch, handler)
    import asyncio

    asyncio.run(gh.fetch_remote("o", "r1", "main"))
    asyncio.run(gh.fetch_remote("o", "r2", "main"))
    asyncio.run(gh.fetch_remote("o", "r3", "main"))
    assert len(gh._cache) == 2
    assert len(calls) == 3


def test_system_subtrees_are_forbidden():
    assert upd.is_forbidden_base(Path("/etc/ssh"))
    assert upd.is_forbidden_base(Path("/root/project"))
    assert upd.is_forbidden_base(Path("/var/lib/app"))
    assert not upd.is_forbidden_base(Path("/tmp/algo"))


def test_download_blocks_localhost_aliases():
    with pytest.raises(ValueError, match="host"):
        upd.download_zip("https://localhost/a.zip")
    with pytest.raises(ValueError, match="IP privado/bloqueado"):
        upd.download_zip("https://0.0.0.0/a.zip")


def test_download_blocks_dns_rebinding_to_private_ip(monkeypatch):
    monkeypatch.setattr(
        upd.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(ValueError, match="privado/bloqueado"):
        upd.download_zip("https://github.com/a.zip")


def test_download_rejects_untrusted_host():
    with pytest.raises(ValueError, match="host não permitido"):
        upd.download_zip("https://evil.example/a.zip")


def test_zip_metadata_reads_only_bounded_prefix(tmp_path):
    path = tmp_path / "repo-main.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "repo-main/README.md",
            b"x" * 65536 + b" https://github.com/owner/repo",
        )
    assert explain_zip(path)[0] is None


def test_dir_metadata_reads_only_bounded_prefix(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    (path / "README.md").write_bytes(b"x" * 65536 + b" https://github.com/owner/repo")
    assert explain_dir(path)[0] is None


def test_state_symlink_is_not_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "state.json").write_text('{"p":{"local_sha":"bad"}}', encoding="utf-8")
    link = tmp_path / ".alldown"
    link.symlink_to(outside, target_is_directory=True)
    assert statemod.load_state(tmp_path) == {}
    with pytest.raises(ValueError):
        statemod.save_state(tmp_path, {"p": {"local_sha": "new"}})


def test_scanner_ignores_generated_backups(tmp_path):
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo.bak-20260101-000001").mkdir()
    (tmp_path / "repo.zip.bak-20260101-000001").write_bytes(b"x")
    assert [item["name"] for item in scan_base(tmp_path)] == ["repo"]


def test_scanner_keeps_legitimate_bak_name(tmp_path):
    (tmp_path / "api.bak-tools").mkdir()
    assert [item["name"] for item in scan_base(tmp_path)] == ["api.bak-tools"]


def test_tray_formats_ipv6_url_host():
    import tray

    assert tray._url_host("::1") == "[::1]"


def test_rollback_ignores_manual_backup_prefix(tmp_path):
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo.bak-manual").mkdir()
    with pytest.raises(ValueError, match="Sem backup"):
        upd.rollback_one(tmp_path, "repo")
    assert (tmp_path / "repo").is_dir()


def test_rollback_falls_back_to_other_artifact_mode(tmp_path):
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "old.txt").write_text("old")
    backup = tmp_path / "repo.bak-20260101-000001"
    backup.mkdir()
    (backup / "old.txt").write_text("original")
    (tmp_path / "repo" / "old.txt").write_text("current")
    result = upd.rollback_one(tmp_path, "repo", zip_only=True)
    assert result["zip_only"] is False
    assert (tmp_path / "repo" / "old.txt").read_text() == "original"


def test_rollback_keeps_backup_when_state_save_fails(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "old.txt").write_text("current")
    backup = tmp_path / "repo.bak-20260101-000001"
    backup.mkdir()
    (backup / "old.txt").write_text("original")

    def fail_state(*args, **kwargs):
        raise OSError("state")

    monkeypatch.setattr(upd, "save_state", fail_state)
    with pytest.raises(OSError, match="state"):
        upd.rollback_one(tmp_path, "repo")
    assert backup.exists()
    assert (tmp_path / "repo" / "old.txt").read_text() == "current"


def test_artifact_shas_are_independent(tmp_path):
    statemod.set_local_sha(statemod.load_state(tmp_path), "repo", "dir-sha", zip_only=False)
    statemod.set_local_sha(statemod.load_state(tmp_path), "repo", "zip-sha", zip_only=True)
    state = {
        "repo": {
            "dir_sha": "dir-sha",
            "zip_sha": "zip-sha",
        }
    }
    assert statemod.local_sha_for(state, "repo", zip_only=False) == "dir-sha"
    assert statemod.local_sha_for(state, "repo", zip_only=True) == "zip-sha"
    assert statemod.local_sha_for(state, "repo", zip_only=False, artifact_exists=False) is None
    legacy = {"repo": {"local_sha": "legacy"}}
    assert statemod.local_sha_for(legacy, "repo", zip_only=False, other_artifact_exists=True) is None
    assert statemod.local_sha_for(legacy, "repo", zip_only=True, other_artifact_exists=True) is None


def test_resolved_default_branch_is_persisted(tmp_path, monkeypatch):
    import asyncio

    statemod.save_mapping(tmp_path, {"repo": {"url": "https://github.com/o/r"}})
    item = {
        "name": "repo", "owner": "o", "repo": "r", "branch": "main",
        "branch_explicit": False, "mapped": True,
    }
    monkeypatch.setattr(appmod, "scan_base", lambda base: [item])
    calls = []

    async def fake_fetch(owner, repo, branch="main"):
        calls.append(branch)
        if branch == "main":
            raise ValueError("branch inexistente")
        return {"remote_sha": "sha", "remote_date": None, "remote_message": "msg",
                "release_tag": None, "source": "branch", "zipball_url": "https://codeload.github.com/o/r/zip/refs/heads/master"}

    async def fake_default(owner, repo):
        return "master"

    monkeypatch.setattr(appmod, "fetch_remote", fake_fetch)
    monkeypatch.setattr(appmod, "repo_default_branch", fake_default)
    result = asyncio.run(appmod.api_check(str(tmp_path)))
    assert result["items"][0]["remote_sha"] == "sha"
    assert result["items"][0]["branch"] == "master"
    assert calls == ["main", "master"]
    assert statemod.load_mapping(tmp_path)["repo"]["branch"] == "master"
    assert statemod.load_mapping(tmp_path)["repo"]["branch_explicit"] is False


def test_resolved_branch_does_not_overwrite_new_explicit_mapping(tmp_path):
    statemod.save_mapping(
        tmp_path,
        {"repo": {"url": "https://github.com/o/r", "branch": "dev", "branch_explicit": True}},
    )
    item = {
        "name": "repo", "github_url": "https://github.com/o/r", "branch": "main",
        "branch_explicit": False,
    }
    appmod._persist_resolved_branch(tmp_path, item, "master")
    assert statemod.load_mapping(tmp_path)["repo"]["branch"] == "dev"


def test_rename_does_not_overwrite_new_mapping(tmp_path, monkeypatch):
    import asyncio

    statemod.save_mapping(tmp_path, {"repo": {"url": "https://github.com/new/r"}})
    item = {
        "name": "repo", "owner": "old", "repo": "r", "branch": "main",
        "branch_explicit": True, "mapped": True,
        "github_url": "https://github.com/old/r",
    }
    monkeypatch.setattr(appmod, "scan_base", lambda base: [item])

    async def fake_fetch(owner, repo, branch="main"):
        return {"remote_sha": "sha", "remote_date": None, "remote_message": "msg",
                "release_tag": None, "source": "branch",
                "zipball_url": "https://codeload.github.com/new/r/zip/sha",
                "canonical_url": "https://github.com/renamed/r"}

    monkeypatch.setattr(appmod, "fetch_remote", fake_fetch)
    asyncio.run(appmod.api_check(str(tmp_path)))
    assert statemod.load_mapping(tmp_path)["repo"]["url"] == "https://github.com/new/r"


def test_config_does_not_coerce_string_to_true(tmp_path):
    (tmp_path / ".alldown").mkdir()
    (tmp_path / ".alldown" / "config.json").write_text(
        '{"zip_only":"false","backup":"0"}', encoding="utf-8"
    )
    assert statemod.load_config(tmp_path) == {"zip_only": False, "backup": True}


def test_config_symlink_is_not_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "config.json").write_text('{"zip_only":true}', encoding="utf-8")
    (tmp_path / ".alldown").symlink_to(outside, target_is_directory=True)
    assert statemod.load_config(tmp_path) == {"zip_only": False, "backup": True}


def test_no_backup_update_restores_old_content_on_swap_failure(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "old.txt").write_text("old")
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("repo-new/new.txt", "new")
    monkeypatch.setattr(upd, "download_zip", lambda *args, **kwargs: source)
    real_move = upd._move_atomic
    calls = 0

    def flaky(src, dst):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("falha simulada")
        return real_move(src, dst)

    monkeypatch.setattr(upd, "_move_atomic", flaky)
    with pytest.raises(OSError, match="falha simulada"):
        upd.update_one(tmp_path, "repo", "o", "r", "main", "https://example.com/repo.zip", make_backup=False)
    assert (tmp_path / "repo" / "old.txt").read_text() == "old"


def test_update_restores_content_when_state_save_fails(tmp_path, monkeypatch):
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "old.txt").write_text("old")
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("repo-new/new.txt", "new")
    monkeypatch.setattr(upd, "download_zip", lambda *args, **kwargs: source)

    def fail_state(*args, **kwargs):
        raise OSError("state")

    monkeypatch.setattr(upd, "save_state", fail_state)
    with pytest.raises(OSError, match="state"):
        upd.update_one(tmp_path, "repo", "o", "r", "main", "https://example.com/repo.zip", make_backup=False)
    assert (tmp_path / "repo" / "old.txt").read_text() == "old"

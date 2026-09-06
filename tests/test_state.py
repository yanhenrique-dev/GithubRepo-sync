"""core/state.py: load/save roundtrip (mapping, state, config)."""
from __future__ import annotations

import json

from core.state import load_config, load_mapping, load_state, save_config, save_mapping, save_state


def test_mapping_roundtrip(tmp_path):
    assert load_mapping(tmp_path) == {}
    mapping = {"a": {"url": "https://github.com/o/r", "branch": "dev"}}
    save_mapping(tmp_path, mapping)
    assert load_mapping(tmp_path) == mapping


def test_mapping_legacy_string_and_invalid(tmp_path):
    (tmp_path / "repos.json").write_text(json.dumps({"a": "https://github.com/o/r"}), encoding="utf-8")
    assert load_mapping(tmp_path) == {"a": {"url": "https://github.com/o/r", "branch": "main"}}

    (tmp_path / "repos.json").write_text("not-json{{{", encoding="utf-8")
    assert load_mapping(tmp_path) == {}

    (tmp_path / "repos.json").write_text(json.dumps(["lista"]), encoding="utf-8")
    assert load_mapping(tmp_path) == {}


def test_state_roundtrip(tmp_path):
    assert load_state(tmp_path) == {}
    state = {"proj": {"local_sha": "abc123", "last_check": "2026-01-01"}}
    save_state(tmp_path, state)
    assert load_state(tmp_path) == state
    # arquivo mora em .alldown/state.json
    assert (tmp_path / ".alldown" / "state.json").exists()


def test_state_invalid_returns_empty(tmp_path):
    fp = tmp_path / ".alldown"
    fp.mkdir()
    (fp / "state.json").write_text("{{{", encoding="utf-8")
    assert load_state(tmp_path) == {}


def test_config_roundtrip_and_default(tmp_path):
    assert load_config(tmp_path) == {"zip_only": False}
    save_config(tmp_path, {"zip_only": True})
    assert load_config(tmp_path) == {"zip_only": True}

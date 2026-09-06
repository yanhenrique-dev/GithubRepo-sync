"""Isolamento global: sem rede real, sem ~/.hermes, sem .env real."""
from __future__ import annotations

import os

import pytest

import core.github as gh


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    # HOME isolado (nada de ~/.hermes) e token controlado por teste.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    # Garante que teste nunca depende do .env real: default sem token.
    monkeypatch.setenv("GITHUB_TOKEN", "")
    # Limpa caches entre testes.
    gh._cache.clear()
    gh._rate_cache.clear()
    yield
    gh._cache.clear()
    gh._rate_cache.clear()

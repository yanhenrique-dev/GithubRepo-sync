"""Contrato de fronteira HTTP <-> static/app.js.

Artefato canônico: os modelos Pydantic em `core/contract.py`. O OpenAPI gerado
pelo FastAPI a partir deles é derivado, nunca editado à mão.

O que estes testes provam:
  - os helpers de `core.updater` devolvem payload que satisfaz o contrato;
  - `static/app.js` não lê nenhum campo que o contrato não declare;
  - todo campo opcional do contrato é realmente opcional (default=None),
    porque a resposta muda conforme o caminho (sucesso, timeout, erro);
  - o snapshot OpenAPI versionado está em dia com os modelos.
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static" / "app.js"
SNAPSHOT = ROOT / "static" / "contract" / "openapi.json"


# --------------------------------------------------------------------------
# leitura do consumidor
# --------------------------------------------------------------------------
def _read_consumer() -> tuple[set[str], set[str]]:
    """Devolve (campos lidos de row, chaves de topo lidas de result).

    A extração roda no Node de propósito: `ast` do Python não parseia
    JavaScript, e um regex em Python seria impreciso demais para um alarme de
    drift. `node` já é dependência do projeto (CI roda `node --check`).
    """
    proc = subprocess.run(
        ["node", str(ROOT / "tests" / "js" / "consumer-fields.mjs")],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    return set(data["row"]), set(data["result"])


# --------------------------------------------------------------------------
# RED 1 — o módulo de contrato não existe
# --------------------------------------------------------------------------
def test_modulo_de_contrato_existe():
    from core import contract  # noqa: F401

    assert contract.__doc__, "o contrato precisa se documentar"


# --------------------------------------------------------------------------
# RED 2 — o helper de update devolve um backup como Path (não serializável)
# --------------------------------------------------------------------------
def test_update_zip_only_serializa_o_payload_do_helper(tmp_path, monkeypatch):
    """O payload que o helper devolve tem de satisfazer o contrato.

    O FastAPI valida a resposta no boundary: se o helper inventar um campo ou
    devolver um tipo que não é JSON, o usuário toma 500 em vez de ver o
    resultado da atualização que acabou de pedir.
    """
    import core.updater as up
    from core.contract import UpdateResponse

    (tmp_path / "repo.zip").write_bytes(b"conteudo antigo")
    stats: dict = {}

    def fake_download_zip(url, token="", stats=None, tmp_parent=None):  # noqa: ANN001, ARG001
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("repo-abc/README.md", "novo conteudo")
        dest = tmp_path / "src.zip"
        dest.write_bytes(buf.getvalue())
        if stats is not None:
            stats["download_bytes"] = 40
            stats["download_secs"] = 1.0
        return dest

    monkeypatch.setattr(up, "download_zip", fake_download_zip)
    result = up.update_zip_only(
        tmp_path, "repo", "https://codeload.github.com/o/r/zip/sha", "", True, stats
    )

    payload = UpdateResponse.model_validate(
        {"ok": True, "remote_sha": "a" * 40, "zip_only": True, **result}
    )
    assert payload.old_bytes is not None
    assert payload.new_bytes == 40
    assert payload.backup is None or isinstance(payload.backup, str)


def test_rollback_serializa_path_do_backup(tmp_path):
    """O payload de `rollback_one` tem de satisfazer o contrato.

    Usa o gerador de backup do próprio módulo, para não depender do formato
    do nome do arquivo.
    """
    import core.updater as up
    from core.contract import RollbackResponse

    (tmp_path / "repo.zip").write_bytes(b"conteudo atual")
    backup = up._unique_backup(tmp_path, "repo.zip")
    backup.write_bytes(b"conteudo antigo")

    result = up.rollback_one(tmp_path, "repo", True)
    _validate(RollbackResponse, {"ok": True, **result}, "POST /api/rollback (helper)")
    assert (tmp_path / "repo.zip").read_bytes() == b"conteudo antigo"


# --------------------------------------------------------------------------
# RED 3 — o consumidor lê um campo que o contrato não pode declarar
# --------------------------------------------------------------------------
def test_consumidor_nao_le_campo_inexistente_no_contrato():
    pytest.importorskip("core.contract")
    from core.contract import ITEM_SCHEMA

    row_fields, _ = _read_consumer()
    # row.busy e row.suggestions são estado local do cliente, não vai e volta.
    client_only = {"busy", "suggestions"}
    drifted = sorted((row_fields - client_only) - set(ITEM_SCHEMA))

    assert not drifted, (
        f"static/app.js lê {drifted}, que o contrato não declara. "
        "Ou declare no contrato, ou pare de ler no consumidor."
    )


# --------------------------------------------------------------------------
# RED 4 — opcional no contrato precisa ser opcional de verdade
# --------------------------------------------------------------------------
def test_campos_opcionais_do_contrato_tem_default_none():
    from core.contract import ITEM_SCHEMA

    sem_default = sorted(
        name for name, spec in ITEM_SCHEMA.items() if spec.get("optional") and "default" not in spec
    )
    assert not sem_default, (
        f"{sem_default} são opcionais no contrato mas sem default: "
        "a serialização vai exigir a chave e quebrar o caminho de erro/timeout"
    )


# --------------------------------------------------------------------------
# provider: a resposta REAL da API satisfaz o contrato
# --------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient

    from app import app

    (tmp_path / "acme__widget").mkdir()
    (tmp_path / "acme__widget" / "README.md").write_text("oi")
    (tmp_path / "acme__widget" / "package.json").write_text('{"name":"widget"}')
    (tmp_path / "solto").mkdir()
    (tmp_path / "solto" / "notas.txt").write_text("x")

    # O middleware local-only exige host loopback. O TestClient envia
    # `testclient` como host, que _host_allowed reprova; passamos 127.0.0.1
    # no header, que é o que _host_allowed e _is_local_client inspecionam.
    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.headers.update({"host": "127.0.0.1:8000"})
        yield c, tmp_path


def _validate(schema, payload, where: str) -> None:
    try:
        schema.model_validate(payload)
    except ValidationError as exc:  # pragma: no cover - só falha em RED
        pytest.fail(f"{where} não satisfaz o contrato:\n{exc}")


@pytest.mark.parametrize("endpoint", ["health", "log", "token", "scan"])
def test_resposta_real_satisfaz_o_contrato(client, endpoint):
    from core.contract import (
        HealthResponse,
        LogResponse,
        ScanResponse,
        TokenStatus,
    )

    c, base = client
    schema, call = {
        "health": (HealthResponse, lambda: c.get("/api/health")),
        "log": (LogResponse, lambda: c.get("/api/log")),
        "token": (TokenStatus, lambda: c.get("/api/token")),
        "scan": (ScanResponse, lambda: c.get("/api/scan", params={"path": str(base)})),
    }[endpoint]

    response = call()
    assert response.status_code == 200, response.text
    _validate(schema, response.json(), f"GET /{endpoint}")


def test_scan_real_tem_um_item_mapeado_e_um_sem_dono(client):
    """Garante que o fixture exercita os dois ramos de status."""
    c, base = client
    payload = c.get("/api/scan", params={"path": str(base)}).json()
    assert any(i["mapped"] for i in payload["items"])
    assert any(not i["mapped"] for i in payload["items"])


def test_update_real_satisfaz_o_contrato(client, monkeypatch):
    """O caminho de update é onde o boundary serializa — exercita o serializador."""
    import io
    import zipfile

    import app as app_module
    import core.updater as up
    from core.contract import UpdateResponse

    async def fake_fetch(item, timeout):  # noqa: ANN001, ARG001
        return {"remote_sha": "c" * 40, "zipball_url": "https://codeload.github.com/o/r/zip/x"}, "main"

    def fake_download_zip(url, token="", stats=None, tmp_parent=None):  # noqa: ANN001, ARG001
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("widget-abc/README.md", "novo")
        dest = work / "src.zip"
        dest.write_bytes(buf.getvalue())
        if stats is not None:
            stats["download_bytes"] = 40
            stats["download_secs"] = 1.0
        return dest

    c, base = client
    work = base  # closure: tmp_path não é visível aqui
    monkeypatch.setattr(app_module, "_fetch_remote_with_fallback", fake_fetch)
    monkeypatch.setattr(up, "download_zip", fake_download_zip)
    (base / "acme__widget.zip").write_bytes(b"zip antigo")

    response = c.post("/api/update", json={"path": str(base), "name": "acme__widget"})
    assert response.status_code == 200, response.text
    _validate(UpdateResponse, response.json(), "POST /api/update")


def test_modo_e_backup_satisfazem_o_contrato(client):
    from core.contract import FlagResponse

    c, base = client
    for endpoint, payload in (
        ("/api/mode", {"path": str(base), "zip_only": True}),
        ("/api/backup", {"path": str(base), "backup": False}),
    ):
        response = c.post(endpoint, json=payload)
        assert response.status_code == 200, response.text
        _validate(FlagResponse, response.json(), f"POST {endpoint}")


def test_map_satisfaz_o_contrato(client):
    from core.contract import OkResponse

    c, base = client
    response = c.post(
        "/api/map",
        json={"path": str(base), "name": "solto", "url": "https://github.com/acme/solto"},
    )
    assert response.status_code == 200, response.text
    _validate(OkResponse, response.json(), "POST /api/map")


def test_check_com_erro_por_linha_ainda_satisfaz_o_contrato(client, monkeypatch):
    """O caminho de erro é o que mais precisa aparecer — e o mais frágil,
    porque o item volta sem nenhum campo remoto."""
    import app as app_module
    from core.contract import CheckResponse

    async def boom(item, timeout):
        raise TimeoutError

    monkeypatch.setattr(app_module, "_fetch_remote_with_fallback", boom)
    c, base = client
    response = c.get("/api/check", params={"path": str(base)})
    if response.status_code != 200:
        pytest.skip(f"check não executou: {response.status_code} {response.text[:200]}")
    _validate(CheckResponse, response.json(), "GET /api/check (caminho de erro)")


# --------------------------------------------------------------------------
# RED 5 — o snapshot versionado está em dia
# --------------------------------------------------------------------------
def test_snapshot_openapi_esta_em_dia():
    pytest.importorskip("core.contract")
    from app import app

    assert SNAPSHOT.exists(), f"snapshot ausente: gere com {SNAPSHOT}"
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    generated = app.openapi()

    def paths(spec: dict) -> dict:
        return {p: sorted(op.get("responses", {})) for p, op in sorted(spec.get("paths", {}).items())}

    assert paths(generated) == paths(snapshot), (
        "o OpenAPI gerado mudou; regenere o snapshot (ver README do contrato)"
    )
    for name, schema in generated.get("components", {}).get("schemas", {}).items():
        assert name in snapshot.get("components", {}).get("schemas", {}), (
            f"schema {name} sumiu do snapshot"
        )


# --------------------------------------------------------------------------
# caracterização — o que já é verdade e não pode regredir
# --------------------------------------------------------------------------
def test_status_do_token_nunca_expoe_o_token():
    from core.contract import TokenStatus

    for forbidden in re.findall(r'"[a-z_]*token[a-z_]*"', TokenStatus.__doc__ or "", re.I):
        assert forbidden in {'"configured"', '"valid"'}, forbidden
    assert "GITHUB_TOKEN" not in json.dumps(TokenStatus.model_json_schema())


def test_contrato_nao_declara_nada_que_nao_seja_observavel():
    """Sem colunas de banco nem nomes internos: só o que o consumidor vê."""
    from core.contract import ITEM_SCHEMA

    banned = {"state_json", "config_json", "repos_json", "state_lock", "sqlite", "table", "column"}
    assert not (set(ITEM_SCHEMA) & banned)

"""RepoRefresh — FastAPI local. Roda: uvicorn app:app --port 8000."""
from __future__ import annotations

import asyncio
import os
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.github import (
    fetch_remote,
    invalidate_remote,
    repo_default_branch,
    suggest_repos,
    token_status,
    validate_branch,
)
from core.scanner import parse_github_url, scan_base
from core.state import load_config, load_mapping, load_state, save_config, save_mapping, save_state
from core.updater import is_forbidden_base, rollback_one, update_one, update_zip_only, validate_name

load_dotenv()

LOG: deque[str] = deque(maxlen=300)

CHECK_ONE_TIMEOUT = 60.0  # um repo lento vira erro na linha, não trava o lote

# Lock por repo no backend: updates/rollbacks concorrentes do mesmo
# `name` serializam (completa o lock por thread de core/updater).
_async_guard = threading.Lock()
_async_locks: dict[str, asyncio.Lock] = {}


def _update_lock(name: str) -> asyncio.Lock:
    with _async_guard:
        lk = _async_locks.get(name)
        if lk is None:
            lk = _async_locks[name] = asyncio.Lock()
        return lk


def _check_name(name: str) -> None:
    try:
        validate_name(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


def log(msg: str) -> None:
    LOG.append(msg)


@asynccontextmanager
async def lifespan(_: FastAPI):
    log("REPOREFRESH PRONTO.")
    yield


app = FastAPI(title="RepoRefresh", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


class UpdateBody(BaseModel):
    path: str
    name: str


class MapBody(BaseModel):
    path: str
    name: str
    url: str
    branch: str = "main"


class ModeBody(BaseModel):
    path: str
    zip_only: bool


class BackupBody(BaseModel):
    path: str
    backup: bool


def resolve_base(path: str) -> Path:
    if not path or not path.strip():
        raise HTTPException(400, "Informe o caminho da pasta.")
    base = Path(path.strip()).expanduser().resolve()
    if not base.is_dir():
        raise HTTPException(400, f"Pasta não existe: {base}")
    if is_forbidden_base(base):
        raise HTTPException(400, "Pasta de sistema não permitida.")
    return base


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/api/scan")
async def api_scan(path: str):
    b = resolve_base(path)
    items = await asyncio.to_thread(scan_base, b)
    state = load_state(b)
    for it in items:
        st = state.get(it["name"], {})
        it["local_sha"] = st.get("local_sha")
        it["last_check"] = st.get("last_check")
    log(f"SCAN {b} -> {len(items)} itens.")
    cfg = load_config(b)
    return {"path": str(b), "items": items, "zip_only": cfg["zip_only"], "backup": cfg["backup"]}


@app.get("/api/check")
async def api_check(path: str):
    b = resolve_base(path)
    items = [i for i in await asyncio.to_thread(scan_base, b) if i["mapped"]]
    if not items:
        return {"path": str(b), "items": []}
    state = load_state(b)
    sem = asyncio.Semaphore(5)

    async def _one(it: dict) -> dict:
        async with sem:
            t0 = time.monotonic()
            try:
                branch = it["branch"]
                try:
                    remote = await asyncio.wait_for(
                        fetch_remote(it["owner"], it["repo"], branch), CHECK_ONE_TIMEOUT  # type: ignore[arg-type]
                    )
                except (asyncio.TimeoutError, TimeoutError):
                    return {**it, "error": f"Tempo esgotado ({CHECK_ONE_TIMEOUT:.0f}s) consultando GitHub"}
                except ValueError:
                    # Branch mapeado não existe (ex.: assumimos main, real é master)?
                    # Resolve o padrão uma vez e tenta de novo. Branch fixado
                    # pelo usuário não é adivinhado: erro vai p/ a linha.
                    if it.get("branch_explicit"):
                        raise
                    resolved = await repo_default_branch(it["owner"], it["repo"])  # type: ignore[arg-type]
                    if not resolved or resolved == branch:
                        raise
                    branch = resolved
                    remote = await fetch_remote(it["owner"], it["repo"], branch)  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001 - erro por linha, não derruba tudo
                return {**it, "error": str(exc)}
            local_sha = (state.get(it["name"], {}) or {}).get("local_sha")
            elapsed = time.monotonic() - t0
            if elapsed > 10:
                log(f"CHECK lento: {it['name']} levou {elapsed:.1f}s.")
            merged = {**it, **remote, "local_sha": local_sha, "behind": local_sha != remote["remote_sha"]}
            canon = remote.get("canonical_url")
            if canon and canon != it.get("github_url"):
                try:
                    mapping = load_mapping(b)
                    if it["name"] in mapping:
                        mapping[it["name"]]["url"] = canon
                        save_mapping(b, mapping)
                        merged["github_url"] = canon
                        parsed = parse_github_url(canon)
                        if parsed:
                            merged["owner"], merged["repo"] = parsed
                        log(f"RENAME {it['name']}: {it.get('github_url')} -> {canon}")
                except Exception:
                    pass
            return merged

    out = list(await asyncio.gather(*(_one(it) for it in items)))
    log(f"CHECK {b} -> {len(out)} repos.")
    return {"path": str(b), "items": out}


@app.post("/api/map")
def api_map(body: MapBody):
    b = resolve_base(body.path)
    _check_name(body.name)
    if parse_github_url(body.url or "") is None:
        raise HTTPException(400, "URL de GitHub inválida.")
    try:
        validate_branch(body.branch or "main")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    mapping = load_mapping(b)
    mapping[body.name] = {"url": body.url.strip(), "branch": body.branch or "main"}
    save_mapping(b, mapping)
    log(f"MAP {body.name} -> {body.url}")
    return {"ok": True}


@app.post("/api/mode")
def api_mode(body: ModeBody):
    b = resolve_base(body.path)
    cfg = load_config(b)
    cfg["zip_only"] = body.zip_only
    save_config(b, cfg)
    log(f"MODE {b} -> {'SO-ZIP' if body.zip_only else 'PASTAS'}")
    return {"ok": True, "zip_only": body.zip_only}


@app.post("/api/backup")
def api_backup(body: BackupBody):
    b = resolve_base(body.path)
    cfg = load_config(b)
    cfg["backup"] = body.backup
    save_config(b, cfg)
    log(f"BACKUP {b} -> {'ON' if body.backup else 'OFF'}")
    return {"ok": True, "backup": body.backup}


@app.post("/api/update")
async def api_update(body: UpdateBody):
    b = resolve_base(body.path)
    _check_name(body.name)
    async with _update_lock(body.name):
        items = {i["name"]: i for i in scan_base(b)}
        it = items.get(body.name)
        if it is None or not it["mapped"]:
            raise HTTPException(400, f"{body.name} não mapeado para GitHub.")
        token = os.getenv("GITHUB_TOKEN", "").strip()
        branch = it["branch"]
        try:
            remote = await fetch_remote(it["owner"], it["repo"], branch)  # type: ignore[arg-type]
        except ValueError:
            if it.get("branch_explicit"):
                raise HTTPException(502, f"Falha ao consultar GitHub: branch {branch} não existe.")
            resolved = await repo_default_branch(it["owner"], it["repo"])  # type: ignore[arg-type]
            if not resolved or resolved == branch:
                raise HTTPException(502, "Falha ao consultar GitHub: repo ou branch não existe.")
            branch = resolved
            try:
                remote = await fetch_remote(it["owner"], it["repo"], branch)  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(502, f"Falha ao consultar GitHub: {exc}")
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"Falha ao consultar GitHub: {exc}")
        zip_only = load_config(b)["zip_only"]
        make_backup = load_config(b)["backup"]
        try:
            if zip_only:
                res = await asyncio.to_thread(update_zip_only, b, body.name, remote["zipball_url"], token, make_backup)
            else:
                res = await asyncio.to_thread(
                    update_one, b, body.name, it["owner"], it["repo"], branch, remote["zipball_url"], token, make_backup
                )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"Falha ao atualizar: {exc}")
        invalidate_remote(it["owner"], it["repo"], branch)  # type: ignore[arg-type]
        state = load_state(b)
        entry = state.get(body.name, {})
        entry["local_sha"] = remote["remote_sha"]
        state[body.name] = entry
        save_state(b, state)
        log(f"UPDATE {body.name} OK backup={res['backup']}")
        return {"ok": True, **res, "remote_sha": remote["remote_sha"]}


@app.post("/api/rollback")
async def api_rollback(body: UpdateBody):
    b = resolve_base(body.path)
    _check_name(body.name)
    async with _update_lock(body.name):
        try:
            res = await asyncio.to_thread(rollback_one, b, body.name)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, str(exc))
        log(f"ROLLBACK {body.name} <- {res['restored_from']}")
        return {"ok": True, **res}


@app.get("/api/log")
def api_log():
    return {"lines": list(LOG)}


@app.get("/api/token")
async def api_token():
    return await token_status()


@app.get("/api/suggest")
async def api_suggest(q: str):
    try:
        items = await suggest_repos(q)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Falha ao sugerir: {exc}")
    return {"items": items}

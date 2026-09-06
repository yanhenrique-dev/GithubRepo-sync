"""RepoRefresh — FastAPI local. Roda: uvicorn app:app --port 8000."""
from __future__ import annotations

import asyncio
import os
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.github import fetch_remote, suggest_repos, token_status
from core.scanner import scan_base
from core.state import load_config, load_mapping, load_state, save_config, save_mapping, save_state
from core.updater import rollback_one, update_one, update_zip_only

load_dotenv()

LOG: deque[str] = deque(maxlen=300)


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


def resolve_base(path: str) -> Path:
    if not path or not path.strip():
        raise HTTPException(400, "Informe o caminho da pasta.")
    base = Path(path.strip()).expanduser().resolve()
    if not base.is_dir():
        raise HTTPException(400, f"Pasta não existe: {base}")
    return base


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/api/scan")
def api_scan(path: str):
    b = resolve_base(path)
    items = scan_base(b)
    state = load_state(b)
    for it in items:
        st = state.get(it["name"], {})
        it["local_sha"] = st.get("local_sha")
        it["last_check"] = st.get("last_check")
    log(f"SCAN {b} -> {len(items)} itens.")
    return {"path": str(b), "items": items, "zip_only": load_config(b)["zip_only"]}


@app.get("/api/check")
async def api_check(path: str):
    b = resolve_base(path)
    items = [i for i in scan_base(b) if i["mapped"]]
    if not items:
        return {"path": str(b), "items": []}
    state = load_state(b)
    out = []
    for it in items:
        try:
            remote = await fetch_remote(it["owner"], it["repo"], it["branch"])  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 - erro por linha, não derruba tudo
            out.append({**it, "error": str(exc)})
            continue
        local_sha = (state.get(it["name"], {}) or {}).get("local_sha")
        out.append({**it, **remote, "local_sha": local_sha, "behind": local_sha != remote["remote_sha"]})
    log(f"CHECK {b} -> {len(out)} repos.")
    return {"path": str(b), "items": out}


@app.post("/api/map")
def api_map(body: MapBody):
    b = resolve_base(body.path)
    if not body.url or "github.com" not in body.url:
        raise HTTPException(400, "URL de GitHub inválida.")
    mapping = load_mapping(b)
    mapping[body.name] = {"url": body.url.strip(), "branch": body.branch or "main"}
    save_mapping(b, mapping)
    log(f"MAP {body.name} -> {body.url}")
    return {"ok": True}


@app.post("/api/mode")
def api_mode(body: ModeBody):
    b = resolve_base(body.path)
    save_config(b, {"zip_only": body.zip_only})
    log(f"MODE {b} -> {'SO-ZIP' if body.zip_only else 'PASTAS'}")
    return {"ok": True, "zip_only": body.zip_only}


@app.post("/api/update")
async def api_update(body: UpdateBody):
    b = resolve_base(body.path)
    items = {i["name"]: i for i in scan_base(b)}
    it = items.get(body.name)
    if it is None or not it["mapped"]:
        raise HTTPException(400, f"{body.name} não mapeado para GitHub.")
    token = os.getenv("GITHUB_TOKEN", "").strip()
    try:
        remote = await fetch_remote(it["owner"], it["repo"], it["branch"])  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Falha ao consultar GitHub: {exc}")
    zip_only = load_config(b)["zip_only"]
    try:
        if zip_only:
            res = await asyncio.to_thread(update_zip_only, b, body.name, remote["zipball_url"], token)
        else:
            res = await asyncio.to_thread(
                update_one, b, body.name, it["owner"], it["repo"], it["branch"], remote["zipball_url"], token
            )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Falha ao atualizar: {exc}")
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

"""RepoRefresh — FastAPI local. Roda: uvicorn app:app --port 8000."""
from __future__ import annotations

import asyncio
import ipaddress
import os
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.github import (
    fetch_remote,
    invalidate_remote,
    repo_default_branch,
    suggest_repos,
    token_status,
    validate_branch,
)
from core.scanner import parse_github_url, scan_base
from core.state import (
    load_config,
    load_mapping,
    load_state,
    local_sha_for,
    save_config,
    save_mapping,
    save_state,
    set_local_sha,
    state_lock,
)
from core.updater import (
    _speed_of,
    is_forbidden_base,
    rollback_one,
    update_one,
    update_zip_only,
    validate_name,
)

load_dotenv()

LOG: deque[str] = deque(maxlen=300)

CHECK_ONE_TIMEOUT = 60.0  # um repo lento vira erro na linha, não trava o lote
UPDATE_REMOTE_TIMEOUT = 30.0
MAX_CHECK_ITEMS = 1000

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
    LOG.append(str(msg).replace("\r", " ").replace("\n", " ")[:1000])


@asynccontextmanager
async def lifespan(_: FastAPI):
    log("REPOREFRESH PRONTO.")
    yield


app = FastAPI(title="RepoRefresh", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


def _host_allowed(request: Request) -> bool:
    if os.getenv("ALLDOWN_ALLOW_REMOTE", "0").strip() == "1":
        return True
    return request.url.hostname in {"127.0.0.1", "localhost", "::1"}


def _is_local_client(host: str | None) -> bool:
    if host == "testclient":
        return True
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        return bool(ip.is_loopback)
    except ValueError:
        return False


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and parsed.netloc == request.headers.get("host")


@app.middleware("http")
async def local_only(request: Request, call_next):
    if not _host_allowed(request):
        response = JSONResponse({"detail": "Host não permitido."}, status_code=400)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response
    cross_site = request.headers.get("sec-fetch-site", "").lower() == "cross-site"
    if request.method not in {"GET", "HEAD", "OPTIONS"} and (cross_site or not _same_origin(request)):
        return JSONResponse({"detail": "Origem não permitida."}, status_code=403)
    if os.getenv("ALLDOWN_ALLOW_REMOTE", "0").strip() != "1":
        client_host = request.client.host if request.client else None
        if not _is_local_client(client_host):
            response = JSONResponse({"detail": "API disponível apenas localmente."}, status_code=403)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            return response
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'"
    )
    return response


class UpdateBody(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    name: str = Field(min_length=1, max_length=255)


class MapBody(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2048)
    branch: str | None = Field(default=None, max_length=255)


class ModeBody(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    zip_only: bool


class BackupBody(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    backup: bool


def resolve_base(path: str) -> Path:
    if not isinstance(path, str) or not path.strip():
        raise HTTPException(400, "Informe o caminho da pasta.")
    try:
        base = Path(path.strip()).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(400, f"Caminho inválido: {path!r}") from exc
    if not base.is_dir():
        raise HTTPException(400, f"Pasta não existe: {base}")
    if is_forbidden_base(base):
        raise HTTPException(400, "Pasta de sistema não permitida.")
    return base


def _artifact_exists(item: dict, zip_only: bool) -> bool:
    raw_path = item.get("zip_path") if zip_only else item.get("local_dir")
    if not isinstance(raw_path, str) or not raw_path:
        return False
    try:
        path = Path(raw_path)
        if path.is_symlink():
            return False
        return path.is_file() if zip_only else path.is_dir()
    except OSError:
        return False


def _can_rollback(base: Path, state: dict[str, dict], name: str, zip_only: bool) -> bool:
    entry = state.get(name)
    if not isinstance(entry, dict):
        return False
    keys = ("zip_backup_path", "backup_path") if zip_only else ("dir_backup_path", "backup_path")
    for key in keys:
        raw_path = entry.get(key)
        if not isinstance(raw_path, str) or not raw_path:
            continue
        try:
            path = Path(raw_path)
            if not path.is_absolute():
                path = base / path
            if not path.is_symlink() and path.exists():
                return True
        except OSError:
            continue
    return False


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/api/scan")
async def api_scan(path: str):
    b = resolve_base(path)
    try:
        items = await asyncio.to_thread(scan_base, b)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    with state_lock(b):
        cfg = load_config(b)
        state = load_state(b)
    for it in items:
        st = state.get(it["name"], {})
        selected_exists = _artifact_exists(it, cfg["zip_only"])
        other_exists = _artifact_exists(it, not cfg["zip_only"])
        it["local_sha"] = local_sha_for(
            state, it["name"], cfg["zip_only"], other_exists, selected_exists
        )
        it["can_rollback"] = _can_rollback(b, state, it["name"], cfg["zip_only"])
        it["last_check"] = st.get("last_check") if isinstance(st, dict) else None
    log(f"SCAN {b} -> {len(items)} itens.")
    return {"path": str(b), "items": items, "zip_only": cfg["zip_only"], "backup": cfg["backup"]}


@app.get("/api/check")
async def api_check(path: str):
    b = resolve_base(path)
    try:
        items = [i for i in await asyncio.to_thread(scan_base, b) if i["mapped"]]
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if len(items) > MAX_CHECK_ITEMS:
        raise HTTPException(400, f"Limite de {MAX_CHECK_ITEMS} repos por check excedido.")
    if not items:
        return {"path": str(b), "items": []}
    with state_lock(b):
        check_config = load_config(b)
    check_zip_only = check_config["zip_only"]
    sem = asyncio.Semaphore(5)

    async def _one(it: dict) -> dict:
        async with sem:
            t0 = time.monotonic()
            try:
                remote, resolved_branch = await _fetch_remote_with_fallback(it, CHECK_ONE_TIMEOUT)
                remote = {**remote, "branch": resolved_branch}
                _persist_resolved_branch(b, it, resolved_branch)
            except TimeoutError:
                return {**it, "error": f"Tempo esgotado ({CHECK_ONE_TIMEOUT:.0f}s) consultando GitHub"}
            except Exception as exc:  # noqa: BLE001 - erro por linha, não derruba tudo
                return {**it, "error": str(exc)}
            with state_lock(b):
                current_state = load_state(b)
            mode = check_zip_only
            selected_exists = _artifact_exists(it, mode)
            other_exists = _artifact_exists(it, not mode)
            local_sha = local_sha_for(
                current_state, it["name"], mode, other_exists, selected_exists
            )
            elapsed = time.monotonic() - t0
            if elapsed > 10:
                log(f"CHECK lento: {it['name']} levou {elapsed:.1f}s.")
            merged = {
                **it,
                **remote,
                "local_sha": local_sha,
                "behind": local_sha != remote["remote_sha"] if selected_exists else None,
                "can_rollback": _can_rollback(b, current_state, it["name"], mode),
            }
            canon = remote.get("canonical_url")
            if canon and canon != it.get("github_url"):
                try:
                    with state_lock(b):
                        mapping = load_mapping(b)
                        current = mapping.get(it["name"])
                        if isinstance(current, dict) and current.get("url") == it.get("github_url"):
                            current["url"] = canon
                            save_mapping(b, mapping)
                    merged["github_url"] = canon
                    parsed = parse_github_url(canon)
                    if parsed:
                        merged["owner"], merged["repo"] = parsed
                    log(f"RENAME {it['name']}: {it.get('github_url')} -> {canon}")
                except (OSError, TypeError, ValueError) as exc:
                    log(f"RENAME {it['name']} não persistido: {exc}")
            return merged

    out = list(await asyncio.gather(*(_one(it) for it in items)))
    checked_at = datetime.now(UTC).isoformat()
    try:
        with state_lock(b):
            latest_state = load_state(b)
            changed = False
            for item in out:
                if item.get("error"):
                    continue
                entry = latest_state.get(item["name"], {})
                if not isinstance(entry, dict):
                    entry = {}
                entry["last_check"] = checked_at
                latest_state[item["name"]] = entry
                changed = True
            if changed:
                save_state(b, latest_state)
    except (OSError, ValueError) as exc:
        log(f"CHECK estado não persistido: {exc}")
    log(f"CHECK {b} -> {len(out)} repos.")
    return {"path": str(b), "items": out}


@app.post("/api/map")
def api_map(body: MapBody):
    b = resolve_base(body.path)
    _check_name(body.name)
    if parse_github_url(body.url or "") is None:
        raise HTTPException(400, "URL de GitHub inválida.")
    branch = body.branch.strip() if isinstance(body.branch, str) else None
    if branch:
        try:
            validate_branch(branch)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    with state_lock(b):
        mapping = load_mapping(b)
        entry: dict[str, object] = {"url": body.url.strip()}
        if branch:
            entry["branch"] = branch
            entry["branch_explicit"] = True
        mapping[body.name] = entry
        save_mapping(b, mapping)
    log(f"MAP {body.name} -> {body.url.strip()}")
    return {"ok": True}


def _set_config_flag(path: str, key: str, value: bool, label: str) -> dict:
    b = resolve_base(path)
    with state_lock(b):
        cfg = load_config(b)
        cfg[key] = value
        save_config(b, cfg)
    log(f"{label} {b} -> {value}")
    return {"ok": True, key: value}


@app.post("/api/mode")
def api_mode(body: ModeBody):
    return _set_config_flag(body.path, "zip_only", body.zip_only, "MODE")


@app.post("/api/backup")
def api_backup(body: BackupBody):
    return _set_config_flag(body.path, "backup", body.backup, "BACKUP")


async def _fetch_remote_with_fallback(item: dict, timeout: float) -> tuple[dict, str]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    async def remaining() -> float:
        value = deadline - loop.time()
        if value <= 0:
            raise TimeoutError
        return value

    branch = item["branch"]
    try:
        remote = await asyncio.wait_for(
            fetch_remote(item["owner"], item["repo"], branch), await remaining()
        )
    except ValueError:
        if item.get("branch_explicit"):
            raise
        resolved = await asyncio.wait_for(
            repo_default_branch(item["owner"], item["repo"]), await remaining()
        )
        if not resolved or resolved == branch:
            raise
        branch = resolved
        remote = await asyncio.wait_for(
            fetch_remote(item["owner"], item["repo"], branch), await remaining()
        )
    return remote, branch


def _persist_resolved_branch(base: Path, item: dict, branch: str) -> None:
    if item.get("branch_explicit") or branch == item.get("branch"):
        return
    try:
        with state_lock(base):
            mapping = load_mapping(base)
            current = mapping.get(item["name"])
            if not isinstance(current, dict):
                return
            if item.get("github_url") and current.get("url") != item.get("github_url"):
                return
            if current.get("branch_explicit") is True:
                return
            current_branch = current.get("branch")
            if current_branch and current_branch != item.get("branch"):
                return
            current["branch"] = branch
            current["branch_explicit"] = False
            save_mapping(base, mapping)
    except (OSError, ValueError) as exc:
        log(f"BRANCH {item['name']} não persistida: {exc}")


@app.post("/api/update")
async def api_update(body: UpdateBody):
    b = resolve_base(body.path)
    _check_name(body.name)
    async with _update_lock(body.name):
        try:
            items = {i["name"]: i for i in await asyncio.to_thread(scan_base, b)}
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        it = items.get(body.name)
        if it is None or not it["mapped"]:
            raise HTTPException(400, f"{body.name} não mapeado para GitHub.")
        token = os.getenv("GITHUB_TOKEN", "").strip()
        try:
            remote, branch = await _fetch_remote_with_fallback(it, UPDATE_REMOTE_TIMEOUT)
            _persist_resolved_branch(b, it, branch)
        except TimeoutError:
            raise HTTPException(504, "Tempo esgotado consultando GitHub.")
        except ValueError:
            raise HTTPException(502, f"Falha ao consultar GitHub: branch {it['branch']} não existe.")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"Falha ao consultar GitHub: {exc}")
        with state_lock(b):
            config = load_config(b)
            zip_only = config["zip_only"]
            make_backup = config["backup"]
        try:
            stats: dict = {"remote_sha": remote["remote_sha"]}
            if zip_only:
                res = await asyncio.to_thread(
                    update_zip_only,
                    b,
                    body.name,
                    remote["zipball_url"],
                    token,
                    make_backup,
                    stats,
                )
            else:
                res = await asyncio.to_thread(
                    update_one,
                    b,
                    body.name,
                    it["owner"],
                    it["repo"],
                    branch,
                    remote["zipball_url"],
                    token,
                    make_backup,
                    stats,
                )
            res.update(stats)
            res["speed_bps"] = _speed_of(stats)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"Falha ao atualizar: {exc}")
        invalidate_remote(it["owner"], it["repo"], branch)  # type: ignore[arg-type]
        with state_lock(b):
            state = load_state(b)
            if local_sha_for(state, body.name, zip_only) != remote["remote_sha"]:
                set_local_sha(state, body.name, remote["remote_sha"], zip_only=zip_only)
                save_state(b, state)
        log(f"UPDATE {body.name} OK backup={res['backup']} "
            f"dl={res.get('download_bytes') or '?'}B "
            f"{res.get('speed_bps') or '?'}B/s "
            f"old={res.get('old_bytes') or '?'}B new={res.get('new_bytes') or '?'}B")
        return {"ok": True, **res, "remote_sha": remote["remote_sha"], "zip_only": zip_only}


@app.post("/api/rollback")
async def api_rollback(body: UpdateBody):
    b = resolve_base(body.path)
    _check_name(body.name)
    async with _update_lock(body.name):
        try:
            res = await asyncio.to_thread(rollback_one, b, body.name, load_config(b)["zip_only"])
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, str(exc))
        log(f"ROLLBACK {body.name} <- {res['restored_from']}")
        return {"ok": True, **res}


@app.get("/api/health")
def api_health():
    return {"ok": True, "service": "RepoRefresh"}


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

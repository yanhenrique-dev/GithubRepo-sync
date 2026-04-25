#!/usr/bin/env python3
"""
update_repos.py — Atualiza repositórios GitHub locais (ZIPs)
Versão 2.1 | Corrigida e funcional
"""

import os
import sys
import json
import time
import argparse
import hashlib
import logging
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from enum import Enum

# ─── dependência opcional: rich ───────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import (
        Progress, SpinnerColumn, BarColumn, TextColumn,
        DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
    )
    from rich.prompt import Confirm, Prompt
    from rich.text import Text
    from rich.layout import Layout
    from rich.live import Live
    from rich import box
    from rich.style import Style
    from rich.rule import Rule
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# ─── repositórios ─────────────────────────────────────────────────────────────
REPO_MAP: dict[str, str] = {
    "ccSource-main.zip":           "jengzang/ccSource",
    "claw-code-main.zip":          "ultraworkers/claw-code",
    "flai-master.zip":             "yurilq/flai",
    "hermes-agent-main.zip":       "NousResearch/hermes-agent",
    "langflow-main.zip":           "langflow-ai/langflow",
    "megathread_pirata-main.zip":  "piratarialink/megathread_pirata",
    "OBLITERATUS-main.zip":        "elder-plinius/OBLITERATUS",
    "obsidian-skills-main.zip":    "kepano/obsidian-skills",
    "openclaude-main.zip":         "Gitlawb/openclaude",
    "opensquad-master.zip":        "renatoasse/opensquad",
    "paperclip-master.zip":        "paperclipai/paperclip",
    "paul-main.zip":               "ChristopherKahler/paul",
    "project-nomad-main.zip":      "Crosstalk-Solutions/project-nomad",
    "RuView-main.zip":             "ruvnet/RuView",
    "superpowers-main.zip":        "obra/superpowers",
    "Paul for Opencode.zip":       "citypaul/.dotfiles",
}

GITHUB_API      = "https://api.github.com/repos"
CACHE_FILE      = ".repo_cache.json"
MAX_CACHE_AGE   = 300          # 5 min
MAX_RETRIES     = 3
MAX_WORKERS     = 4            # downloads paralelos
CONNECT_TIMEOUT = 10
DOWNLOAD_TIMEOUT = 120


# ─── status de cada repo ──────────────────────────────────────────────────────
class RepoStatus(Enum):
    PENDING    = "pending"
    CHECKING   = "checking"
    UP_TO_DATE = "up_to_date"
    OUTDATED   = "outdated"
    NEW        = "novo"
    NOT_FOUND  = "not_found"
    ERROR      = "error"
    DOWNLOADING= "downloading"
    DONE       = "done"
    SKIPPED    = "skipped"


@dataclass
class RepoEntry:
    zip_filename: str
    repo_full_name: str
    status: RepoStatus = RepoStatus.PENDING
    local_date: Optional[datetime] = None
    remote_date: Optional[datetime] = None
    diff_days: float = 0.0
    error_msg: str = ""
    md5: str = ""
    file_size: int = 0
    selected: bool = False


# ─── configuração / logging ───────────────────────────────────────────────────
def setup_logging(verbose: bool, log_file: Optional[str]) -> logging.Logger:
    logger = logging.getLogger("update_repos")
    logger.setLevel(logging.DEBUG if verbose else logging.WARNING)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


# ─── cache ────────────────────────────────────────────────────────────────────
class Cache:
    def __init__(self, path: str = CACHE_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._data: dict = {}
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, 'r') as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {}

    def get(self, key: str):
        with self._lock:
            entry = self._data.get(key)
            if entry and time.time() - entry.get("ts", 0) < MAX_CACHE_AGE:
                return entry.get("data")
        return None

    def set(self, key: str, data: dict):
        with self._lock:
            self._data[key] = {"data": data, "ts": time.time()}
            try:
                with open(self._path, 'w') as f:
                    json.dump(self._data, f)
            except Exception:
                pass

    def invalidate(self, key: str):
        with self._lock:
            self._data.pop(key, None)


# ─── cliente GitHub ───────────────────────────────────────────────────────────
class GitHubClient:
    def __init__(self, token: Optional[str], cache: Cache, logger: logging.Logger):
        self._token   = token
        self._cache   = cache
        self._logger  = logger
        self._lock    = threading.Lock()
        self._rate_remaining = 60

    def _build_request(self, url: str) -> urllib.request.Request:
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github.v3+json")
        req.add_header("User-Agent", "update-repos/2.1")
        if self._token:
            req.add_header("Authorization", f"token {self._token}")
        return req

    def get_repo_info(self, repo: str) -> Optional[dict]:
        cached = self._cache.get(repo)
        if cached:
            return cached

        url = f"{GITHUB_API}/{repo}"
        for attempt in range(MAX_RETRIES):
            try:
                req = self._build_request(url)
                with urllib.request.urlopen(req, timeout=CONNECT_TIMEOUT) as resp:
                    with self._lock:
                        self._rate_remaining = int(resp.headers.get("X-RateLimit-Remaining", 60))
                    data = json.loads(resp.read().decode())
                    result = {
                        "pushed_at":      data.get("pushed_at", ""),
                        "updated_at":     data.get("updated_at", ""),
                        "default_branch": data.get("default_branch", "main"),
                        "size_kb":        data.get("size", 0),
                        "stars":          data.get("stargazers_count", 0),
                    }
                    self._cache.set(repo, result)
                    return result

            except urllib.error.HTTPError as e:
                if e.code == 404:
                    self._logger.warning("Repo not found: %s", repo)
                    return None
                if e.code == 403:
                    reset = e.headers.get("X-RateLimit-Reset", "?")
                    self._logger.error("Rate limit hit, reset at %s", reset)
                    return None
                if e.code in (500, 502, 503) and attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
            except Exception as exc:
                self._logger.error("Error fetching %s: %s", repo, exc)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1)
        return None

    @property
    def rate_remaining(self) -> int:
        with self._lock:
            return self._rate_remaining


# ─── downloader ───────────────────────────────────────────────────────────────
class Downloader:
    def __init__(self, token: Optional[str], logger: logging.Logger):
        self._token  = token
        self._logger = logger

    def download(self, url: str, output_path: str):
        """Retorna (sucesso, md5)"""
        for attempt in range(MAX_RETRIES):
            try:
                req = urllib.request.Request(url)
                req.add_header("Accept", "application/zip")
                req.add_header("User-Agent", "update-repos/2.1")
                if self._token:
                    req.add_header("Authorization", f"token {self._token}")

                with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
                    total = int(resp.headers.get("Content-Length", 0))

                    downloaded = 0
                    hasher = hashlib.md5()
                    tmp = output_path + ".tmp"

                    with open(tmp, 'wb') as f:
                        while True:
                            chunk = resp.read(8192)
                            if not chunk:
                                break
                            f.write(chunk)
                            hasher.update(chunk)
                            downloaded += len(chunk)

                    if os.path.exists(output_path):
                        os.remove(output_path)
                    os.rename(tmp, output_path)
                    return True, hasher.hexdigest()

            except Exception as exc:
                self._logger.warning("Download attempt %d failed: %s", attempt + 1, exc)
                if os.path.exists(output_path + ".tmp"):
                    os.remove(output_path + ".tmp")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)

        return False, ""


# ─── lógica principal ─────────────────────────────────────────────────────────
def parse_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def check_entry(entry: RepoEntry, work_dir: str, client: GitHubClient) -> RepoEntry:
    entry.status = RepoStatus.CHECKING
    zip_path = Path(work_dir) / entry.zip_filename

    if not zip_path.exists():
        info = client.get_repo_info(entry.repo_full_name)
        if info:
            entry.status = RepoStatus.NEW
            entry.remote_date = parse_date(info["pushed_at"])
        else:
            entry.status = RepoStatus.NOT_FOUND
        return entry

    info = client.get_repo_info(entry.repo_full_name)
    if not info:
        entry.status = RepoStatus.ERROR
        entry.error_msg = "API error / repo not found"
        return entry

    local_ts = zip_path.stat().st_mtime
    entry.local_date  = datetime.fromtimestamp(local_ts, tz=timezone.utc)
    entry.remote_date = parse_date(info["pushed_at"])

    if not entry.remote_date:
        entry.status = RepoStatus.ERROR
        entry.error_msg = "Could not parse remote date"
        return entry

    diff = (entry.remote_date - entry.local_date).total_seconds()
    entry.diff_days = diff / 86400

    if diff > 0:
        entry.status = RepoStatus.OUTDATED
    else:
        entry.status = RepoStatus.UP_TO_DATE

    return entry


def build_download_url(repo: str, branch: str) -> str:
    return f"https://github.com/{repo}/archive/refs/heads/{branch}.zip"


# ═════════════════════════════════════════════════════════════════════════════
#  UI RICH
# ═════════════════════════════════════════════════════════════════════════════
if RICH_AVAILABLE:
    console = Console()

    STATUS_STYLE = {
        RepoStatus.PENDING:     ("⏳", "dim"),
        RepoStatus.CHECKING:    ("🔍", "cyan"),
        RepoStatus.UP_TO_DATE:  ("✅", "green"),
        RepoStatus.OUTDATED:    ("⬆️ ", "yellow"),
        RepoStatus.NEW:         ("🆕", "magenta"),
        RepoStatus.NOT_FOUND:   ("❌", "red"),
        RepoStatus.ERROR:       ("⚠️ ", "red"),
        RepoStatus.DOWNLOADING: ("📥", "blue"),
        RepoStatus.DONE:        ("✨", "bright_green"),
        RepoStatus.SKIPPED:     ("⏭️ ", "dim"),
    }

    def build_table(entries: list[RepoEntry], title: str = "Repositórios") -> Table:
        t = Table(
            title=title,
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
            border_style="blue",
            expand=True,
        )
        t.add_column("#",          style="dim", width=3, justify="right")
        t.add_column("Arquivo",    style="bold white", min_width=28)
        t.add_column("Repositório", style="blue",       min_width=28)
        t.add_column("Status",     justify="center",   min_width=14)
        t.add_column("Local",      justify="center",   min_width=19)
        t.add_column("Remoto",     justify="center",   min_width=19)
        t.add_column("Defasagem",  justify="right",    min_width=10)
        t.add_column("Sel",        justify="center",   width=4)

        for i, e in enumerate(entries, 1):
            icon, style = STATUS_STYLE.get(e.status, ("?", "white"))
            status_text = Text(f"{icon} {e.status.value}", style=style)

            local_str  = e.local_date.strftime("%Y-%m-%d %H:%M") if e.local_date else "—"
            remote_str = e.remote_date.strftime("%Y-%m-%d %H:%M") if e.remote_date else "—"

            if e.diff_days > 0:
                diff_str = f"[yellow]+{e.diff_days:.1f}d[/yellow]"
            elif e.diff_days < 0:
                diff_str = f"[green]{e.diff_days:.1f}d[/green]"
            else:
                diff_str = "—"

            sel = "☑" if e.selected else "☐"
            sel_style = "bright_green" if e.selected else "dim"

            t.add_row(
                str(i),
                e.zip_filename,
                e.repo_full_name,
                status_text,
                local_str,
                remote_str,
                diff_str,
                Text(sel, style=sel_style),
            )
        return t

    def interactive_select(outdated: list[RepoEntry]) -> list[RepoEntry]:
        for e in outdated:
            e.selected = True

        console.print(Panel(
            "[bold cyan]Selecione os repositórios para atualizar[/bold cyan]\n"
            "[dim]Comandos: [bold]número[/bold] para toggle, "
            "[bold]a[/bold] = todos, [bold]n[/bold] = nenhum, "
            "[bold]Enter[/bold] = confirmar[/dim]",
            border_style="cyan",
        ))

        while True:
            console.clear()
            console.print(build_table(outdated, "Selecione para atualizar"))

            total_sel = sum(1 for e in outdated if e.selected)
            console.print(f"\n[dim]Selecionados: [bold cyan]{total_sel}/{len(outdated)}[/bold cyan][/dim]")
            choice = Prompt.ask(
                "\n[bold cyan]>[/bold cyan] Comando (número / a / n / Enter para confirmar)",
                default="",
            ).strip().lower()

            if choice == "":
                break
            elif choice == "a":
                for e in outdated:
                    e.selected = True
            elif choice == "n":
                for e in outdated:
                    e.selected = False
            elif choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(outdated):
                    outdated[idx].selected = not outdated[idx].selected

        return [e for e in outdated if e.selected]

    def run_rich(args, entries: list[RepoEntry],
                 client: GitHubClient, downloader: Downloader, work_dir: str):

        console.print(Panel(
            f"[bold cyan]update_repos[/bold cyan] [dim]v2.1[/dim]\n"
            f"[dim]Diretório:[/dim] [white]{work_dir}[/white]  "
            f"[dim]Token:[/dim] {'[green]✓[/green]' if args.token else '[red]✗[/red]'}  "
            f"[dim]Workers:[/dim] [white]{args.workers}[/white]",
            border_style="cyan",
            title="[bold]GitHub Repo Updater[/bold]",
        ))

        # ── verificação paralela ──────────────────────────────────────────────
        console.print(Rule("[cyan]Verificando repositórios[/cyan]"))
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[cyan]{task.completed}/{task.total}[/cyan]"),
            console=console,
        ) as prog:
            task = prog.add_task("Consultando API...", total=len(entries))
            lock = threading.Lock()

            def _check(e: RepoEntry) -> RepoEntry:
                result = check_entry(e, work_dir, client)
                with lock:
                    prog.advance(task)
                    prog.update(task, description=f"[dim]{result.zip_filename[:35]}[/dim]")
                return result

            with ThreadPoolExecutor(max_workers=min(args.workers, 6)) as ex:
                futures = {ex.submit(_check, e): e for e in entries}
                entries = [f.result() for f in as_completed(futures)]

        # ── exibe tabela de resultados ────────────────────────────────────────
        console.print(build_table(entries))

        # ── summary ──────────────────────────────────────────────────────────
        outdated  = [e for e in entries if e.status in (RepoStatus.OUTDATED, RepoStatus.NEW)]
        up_to_date = [e for e in entries if e.status == RepoStatus.UP_TO_DATE]
        errors     = [e for e in entries if e.status in (RepoStatus.ERROR, RepoStatus.NOT_FOUND)]

        console.print(
            f"\n[green]✅ Atualizados:[/green] {len(up_to_date)}  "
            f"[yellow]⬆️  Defasados/Novos:[/yellow] {len(outdated)}  "
            f"[red]⚠️  Erros:[/red]    {len(errors)}  "
            f"[dim]Rate limit restante: {client.rate_remaining}[/dim]"
        )

        if not outdated:
            console.print(Panel("[bold green]Todos os arquivos estão atualizados! 🎉[/bold green]",
                                border_style="green"))
            return

        if args.check_only:
            console.print("[dim italic]Modo check-only: nenhum download realizado.[/dim italic]")
            return

        # ── seleção interativa ou automática ──────────────────────────────────
        if args.auto:
            to_download = outdated
        else:
            to_download = interactive_select(outdated)

        if not to_download:
            console.print("[yellow]Nenhum repositório selecionado.[/yellow]")
            return

        # ── downloads paralelos com barra de progresso ────────────────────────
        console.print(Rule("[cyan]Downloading[/cyan]"))
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
            expand=True,
        ) as prog:

            def _download(entry: RepoEntry):
                info = client.get_repo_info(entry.repo_full_name) or {}
                branch = info.get("default_branch", "main")
                url = build_download_url(entry.repo_full_name, branch)
                out = str(Path(work_dir) / entry.zip_filename)

                task_id = prog.add_task(
                    f"[cyan]{entry.zip_filename[:35]}[/cyan]", total=None
                )
                entry.status = RepoStatus.DOWNLOADING
                ok, md5 = downloader.download(url, out)

                if ok:
                    entry.status = RepoStatus.DONE
                    entry.md5 = md5
                    prog.update(task_id, description=f"[green]✓ {entry.zip_filename[:35]}[/green]")
                else:
                    entry.status = RepoStatus.ERROR
                    prog.update(task_id, description=f"[red]✗ {entry.zip_filename[:35]}[/red]")

                return entry

            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                list(as_completed({ex.submit(_download, e): e for e in to_download}))

        # ── relatório final ───────────────────────────────────────────────────
        console.print(Rule("[cyan]Relatório Final[/cyan]"))
        done   = [e for e in to_download if e.status == RepoStatus.DONE]
        failed = [e for e in to_download if e.status == RepoStatus.ERROR]

        for e in done:
            console.print(f"  [green]✓[/green] {e.zip_filename}  [dim]md5: {e.md5}[/dim]")
        for e in failed:
            console.print(f"  [red]✗[/red] {e.zip_filename}")

        console.print(Panel(
            f"[bold green]{len(done)} baixados com sucesso[/bold green]"
            + (f"  [red]{len(failed)} erros[/red]" if failed else ""),
            border_style="green" if not failed else "yellow",
        ))

        # salva log json
        report = {
            "timestamp": datetime.now().isoformat(),
            "done":   [{"file": e.zip_filename, "md5": e.md5} for e in done],
            "failed": [{"file": e.zip_filename} for e in failed],
        }
        report_path = Path(work_dir) / "update_report.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        console.print(f"[dim]Relatório salvo em: {report_path}[/dim]")


# ═════════════════════════════════════════════════════════════════════════════
#  UI FALLBACK (sem rich)
# ═════════════════════════════════════════════════════════════════════════════
else:
    class Colors:
        RED = '\033[91m'
        GREEN = '\033[92m'
        YELLOW = '\033[93m'
        BLUE = '\033[94m'
        CYAN = '\033[96m'
        BOLD = '\033[1m'
        END = '\033[0m'

    def run_fallback(args, entries, client, downloader, work_dir):
        print(f"\n{'='*60}")
        print(f"update_repos v2.1 | dir: {work_dir}")
        print('='*60)

        for entry in entries:
            entry = check_entry(entry, work_dir, client)
            icon = "✓" if entry.status == RepoStatus.UP_TO_DATE else \
                   "↑" if entry.status == RepoStatus.OUTDATED else "✗"
            print(f"  {icon} {entry.zip_filename} ({entry.status.value})")
            time.sleep(0.2)

        outdated = [e for e in entries if e.status == RepoStatus.OUTDATED]
        if not outdated:
            print(f"\n{Colors.GREEN}Todos atualizados!{Colors.END}")
            return

        print(f"\n{Colors.YELLOW}{len(outdated)} para atualizar:{Colors.END}")
        for e in outdated:
            print(f"  - {e.zip_filename}")

        if args.check_only:
            return

        if args.auto or input("\nBaixar? (s/n): ").lower() in "sy":
            for e in outdated:
                info = client.get_repo_info(e.repo_full_name) or {}
                branch = info.get("default_branch", "main")
                url = build_download_url(e.repo_full_name, branch)
                out = str(Path(work_dir) / e.zip_filename)
                print(f"\nBaixando {e.zip_filename}...")
                ok, md5 = downloader.download(url, out)
                print(f"  {'OK md5:' + md5 if ok else 'ERRO'}")


# ═════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════
def build_entries(args: argparse.Namespace, work_dir: str) -> list[RepoEntry]:
    repos = REPO_MAP.copy()

    if args.repos:
        want = {r.strip() for r in args.repos.split(",")}
        repos = {k: v for k, v in repos.items() if k in want or v in want}

    if args.skip:
        skip = {r.strip() for r in args.skip.split(",")}
        repos = {k: v for k, v in repos.items() if k not in skip and v not in skip}

    return [RepoEntry(zip_filename=k, repo_full_name=v) for k, v in repos.items()]


def main():
    parser = argparse.ArgumentParser(
        description="Atualiza repositórios GitHub locais (ZIPs) — v2.1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python update_repos.py                        # interativo
  python update_repos.py --auto                 # automático
  python update_repos.py --check-only           # só verifica
  python update_repos.py --repos langflow-main.zip,paul-main.zip
  python update_repos.py --skip ccSource-main.zip
  GITHUB_TOKEN=ghp_xxx python update_repos.py  # com autenticação
        """,
    )
    parser.add_argument("--auto",       action="store_true", help="Baixa sem perguntar")
    parser.add_argument("--check-only", action="store_true", help="Apenas verifica, não baixa")
    parser.add_argument("--dir",        default="",          help="Diretório de trabalho")
    parser.add_argument("--repos",      default="",          help="Repos específicos (vírgula)")
    parser.add_argument("--skip",       default="",          help="Repos para pular (vírgula)")
    parser.add_argument("--workers",    type=int, default=MAX_WORKERS, help="Downloads paralelos")
    parser.add_argument("--token",      default="",          help="GitHub token (ou GITHUB_TOKEN)")
    parser.add_argument("--log",        default="",          help="Arquivo de log")
    parser.add_argument("--no-cache",   action="store_true", help="Ignora cache")
    parser.add_argument("--verbose",    action="store_true", help="Debug logging")
    args = parser.parse_args()

    work_dir = str(Path(args.dir).resolve()) if args.dir else os.getcwd()
    token    = args.token or os.environ.get("GITHUB_TOKEN", "")
    args.token = token

    logger     = setup_logging(args.verbose, args.log or None)
    cache      = Cache(os.path.join(work_dir, CACHE_FILE))
    gh_client  = GitHubClient(token, cache, logger)
    dl_client  = Downloader(token, logger)

    entries = build_entries(args, work_dir)

    if RICH_AVAILABLE:
        run_rich(args, entries, gh_client, dl_client, work_dir)
    else:
        run_fallback(args, entries, gh_client, dl_client, work_dir)


if __name__ == "__main__":
    main()

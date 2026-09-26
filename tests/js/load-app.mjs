/* Carrega static/app.js num contexto vm com um shim minimo de DOM e expoe as
   funcoes declaradas com `function` (as `const` ficam no escopo lexico do
   script e nao sao alcancaveis de fora — por isso o contrato e testado com o
   grupo de `function`).

   Sem build, sem jsdom: e o mesmo padrao do repo (front vanilla). */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = join(HERE, "..", "..", "static", "app.js");

function makeEl(tag = "div", id = "") {
  const el = {
    tagName: String(tag).toUpperCase(),
    id,
    dataset: {},
    style: {},
    classList: {
      _s: new Set(),
      add(...c) { c.forEach((x) => this._s.add(x)); },
      remove(...c) { c.forEach((x) => this._s.delete(x)); },
      toggle(c, on) { on ? this._s.add(c) : this._s.delete(c); },
      contains(c) { return this._s.has(c); },
    },
    attrs: {},
    innerHTML: "",
    textContent: "",
    value: "",
    hidden: false,
    children: [],
    scrollTop: 0,
    scrollHeight: 0,
    clientHeight: 0,
    firstElementChild: null,
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k] ?? null; },
    removeAttribute(k) { delete this.attrs[k]; },
    toggleAttribute(k, on) { if (on) this.attrs[k] = ""; else delete this.attrs[k]; },
    hasAttribute(k) { return k in this.attrs; },
    addEventListener() {},
    removeEventListener() {},
    focus() {},
    blur() {},
    click() {},
    scrollTo() {},
    appendChild(c) { this.children.push(c); return c; },
    remove() { this.children = this.children.filter((x) => x !== this); },
    closest: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  return el;
}

/**
 * @param {object} [opts]
 * @param {object} [opts.scan]   payload devolvido por /api/scan
 * @param {object[]} [opts.check] items devolvidos por /api/check
 * @param {string} [opts.path]   valor semeado em localStorage["alldown.path"]
 * @param {boolean} [opts.autoScan] semeia localStorage["alldown.auto"]="1"
 * @param {Function} [opts.fetchImpl] substitui o stub de fetch (para simular
 *        timeout, rede caída e respostas por endpoint)
 */
export function loadApp(opts = {}) {
  const { scan = { path: "", items: [], zip_only: false, backup: true }, check = [], path = "", autoScan = false, fetchImpl = null } = opts;

  const byId = new Map();
  // todos os ids declarados no index.html real
  const html = readFileSync(join(HERE, "..", "..", "static", "index.html"), "utf8");
  for (const m of html.matchAll(/\sid="([a-z0-9-]+)"/g)) byId.set(m[1], makeEl("div", m[1]));

  const statusEl = byId.get("status");
  const statusUse = makeEl("use");
  statusEl.querySelector = (sel) => (sel === "use" ? statusUse : null);

  const pathInput = byId.get("in-path");
  const pathWrap = makeEl("label");
  pathWrap.removeAttribute = (k) => { delete pathWrap.attrs[k]; };
  pathInput.closest = () => pathWrap;

  const themeUse = makeEl("use");
  const themeBtn = makeEl("button");
  themeBtn.querySelector = () => themeUse;

  const mainEl = byId.get("conteudo");
  mainEl.querySelector = () => makeEl("div");
  mainEl.scrollTo = () => {};

  const repoList = byId.get("repo-list");
  const timers = [];
  const matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });

  const sandbox = {
    console,
    document: {
      documentElement: makeEl("html"),
      body: makeEl("body"),
      getElementById: (id) => byId.get(id) ?? null,
      querySelector: (sel) => {
        if (sel === ".mobile-scrim") return makeEl("button");
        if (sel === ".topbar__menu") return makeEl("button");
        if (sel === '[data-action="toggle-theme"] use') return themeUse;
        if (sel === '[data-action="toggle-theme"]') return themeBtn;
        return null;
      },
      querySelectorAll: () => [],
      createElement: (tag) => {
        const el = makeEl(tag);
        el.querySelector = () => makeEl("button");
        return el;
      },
      addEventListener() {},
    },
    localStorage: {
      _m: new Map(),
      getItem(k) { return this._m.has(k) ? this._m.get(k) : null; },
      setItem(k, v) { this._m.set(k, String(v)); },
      removeItem(k) { this._m.delete(k); },
    },
    location: { hash: "" },
    history: { replaceState() {} },
    matchMedia,
    ResizeObserver: class { observe() {} disconnect() {} },
    MutationObserver: class { observe() {} disconnect() {} },
    AbortController,
    setTimeout: (fn) => { timers.push(fn); return timers.length; },
    clearTimeout() {},
    setInterval: () => 0,
    URLSearchParams,
    fetch: fetchImpl ?? (async (url) => {
      const u = String(url);
      if (u.startsWith("/api/scan")) return { ok: true, status: 200, json: async () => scan };
      if (u.startsWith("/api/check")) return { ok: true, status: 200, json: async () => ({ items: check }) };
      if (u.startsWith("/api/update")) {
        return { ok: true, status: 200, json: async () => ({ ok: true, name: "x", remote_sha: "a", zip_only: false, path: "/p", backup: null, old_bytes: 1, new_bytes: 2, download_bytes: 2, speed_bps: 1 }) };
      }
      return { ok: true, status: 200, json: async () => ({ lines: [] }) };
    }),
    window: { addEventListener() {}, setTimeout: (fn) => { timers.push(fn); return timers.length; }, clearTimeout() {}, matchMedia },
  };
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;

  if (path) sandbox.localStorage.setItem("alldown.path", path);
  if (autoScan) sandbox.localStorage.setItem("alldown.auto", "1");

  vm.createContext(sandbox);
  vm.runInContext(readFileSync(APP, "utf8"), sandbox, { filename: "app.js" });

  /** executa os timers enfileirados e deixa as promises assentarem */
  async function settle(rounds = 40) {
    for (let i = 0; i < rounds; i++) {
      runTimersSync();
      await new Promise((r) => setImmediate(r));
    }
  }

  /**
   * Dispara os timers pendentes SEM deixar as promises assentarem.
   * Usado para observar o estado exatamente no momento em que uma operacao
   * comeca (ex.: o instante em que o scan entra em andamento).
   */
  function runTimersSync() {
    for (const t of timers.splice(0)) t();
  }

  return { sandbox, dom: byId, repoList, settle, runTimersSync, pathWrap, statusUse, themeUse };
}

/** fixture de item no mesmo shape que core/scanner.py devolve */
export function item(over = {}) {
  return {
    name: "acme__widget",
    local_dir: "/base/acme__widget",
    zip_path: "/base/acme__widget.zip",
    github_url: "https://github.com/acme/widget",
    branch: "main",
    branch_explicit: false,
    mapped: true,
    auto: false,
    owner: "acme",
    repo: "widget",
    suggested_repo: null,
    tried: null,
    local_sha: "aaaaaaabbbbcc",
    remote_sha: "99999998888",
    can_rollback: true,
    error: null,
    ...over,
  };
}

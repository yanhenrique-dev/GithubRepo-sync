/* AllDown — vanilla JS, sem build. */
const $ = (id) => document.getElementById(id);
const tbody = $("tbody"), logEl = $("log"), statusEl = $("status"), countEl = $("count");
const loadbar = $("loadbar"), loadfill = $("loadfill");
const pathInput = $("in-path"), autoBtn = $("btn-auto"), modeBtn = $("btn-mode");
const btnAll = $("btn-all");
let BASE = "";
let ROWS = [];
let ZIP_ONLY = false;
let scanning = false;
let debounce = null;
let autoDetect = true;
let lastScanFailed = false;
let FCHIP = "all";
let FQ = "";

/* PARTE 2/2 — animação 100% CSS/vanilla, sem mudar comportamento/rotas/IDs. */
const RM = (typeof window !== "undefined" && window.matchMedia)
  ? window.matchMedia("(prefers-reduced-motion: reduce)")
  : { matches: false };
let countPulseT = null;

function withViewTransition(commit) {
  if (!RM.matches && typeof document !== "undefined" && document.startViewTransition) {
    try {
      document.startViewTransition(() => { commit(); });
      return;
    } catch { /* fallback silencioso */ }
  }
  commit();
}

function staggerEnter() {
  if (RM.matches) return;
  const rows = tbody.querySelectorAll("tr:not(.empty)");
  const n = Math.min(rows.length, 12);
  for (let k = 0; k < n; k++) {
    const tr = rows[k];
    requestAnimationFrame(() => {
      setTimeout(() => {
        if (!tr.isConnected) return;
        tr.classList.add("enter");
        const done = () => tr.classList.remove("enter");
        tr.addEventListener("animationend", done, { once: true });
        tr.addEventListener("transitionend", done, { once: true });
        setTimeout(done, 400);
      }, k * 25);
    });
  }
}

function pulseCount(prev, next) {
  if (!countEl || RM.matches || prev === next) return;
  countEl.classList.remove("enter");
  void countEl.offsetWidth;
  countEl.classList.add("enter");
  clearTimeout(countPulseT);
  countPulseT = setTimeout(() => countEl.classList.remove("enter"), 300);
}

const CHIPS = {
  all: () => true,
  mapped: (r) => !!r.mapped,
  unmapped: (r) => !r.mapped,
  behind: (r) => r.behind === true,
  ok: (r) => r.behind === false,
  error: (r) => !!r.error,
};
const CHIP_LABEL = {
  all: "TODOS", mapped: "MAPEADOS", unmapped: "SEM DONO",
  behind: "DESATUALIZADOS", ok: "ATUALIZADOS", error: "ERROS",
};

if (!pathInput || !tbody) {
  const s = $("status");
  if (s) s.textContent = "FALHA CRÍTICA: HTML DESATUALIZADO — APERTE CTRL+SHIFT+R.";
  throw new Error("alldown: DOM desatualizado (cache velho?)");
}

function storeGet(k) {
  try { return localStorage.getItem(k); } catch { return null; }
}

function storeSet(k, v) {
  try { localStorage.setItem(k, v); } catch { /* ok */ }
}

function rearm(t, fn, ms) {
  clearTimeout(t);
  return setTimeout(fn, ms);
}

function paintToggle(btn, on, onText, offText) {
  if (!btn) return;
  btn.textContent = on ? onText : offText;
  btn.setAttribute("aria-pressed", on ? "true" : "false");
  btn.classList.toggle("btn-inv", on);
}

pathInput.value = storeGet("alldown.path") || "";
autoDetect = storeGet("alldown.autodetect") !== "0";
{
  const c = storeGet("alldown.chip");
  if (c && CHIPS[c]) FCHIP = c;
}
FQ = storeGet("alldown.q") || "";

function visibleRows() {
  const q = FQ.trim().toLowerCase();
  const pred = CHIPS[FCHIP] || CHIPS.all;
  return ROWS.filter((r) => pred(r) && (!q || r.name.toLowerCase().includes(q)));
}

function updateCounts() {
  for (const k of Object.keys(CHIPS)) {
    const el = $("c-" + k);
    if (el) el.textContent = String(ROWS.filter(CHIPS[k]).length);
  }
}

function paintChips() {
  const list = document.querySelectorAll("[data-chip]");
  list.forEach((el) => {
    el.setAttribute("aria-pressed", el.dataset.chip === FCHIP ? "true" : "false");
  });
  const si = $("in-search");
  if (si && si.value !== FQ) si.value = FQ;
}

function paintBtnAll() {
  if (!btnAll) return;
  const work = ROWS.some((r) => r.mapped && r.behind === true);
  btnAll.classList.toggle("btn-primary", work);
  btnAll.classList.toggle("btn-quiet", !work);
}

document.addEventListener("keydown", (ev) => {
  if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
  const tag = (ev.target && ev.target.tagName) || "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  const k = (ev.key || "").toLowerCase();
  if (k === "e") { ev.preventDefault(); doScan(); }
  else if (k === "c") { ev.preventDefault(); doCheck(); }
});

function setFilter(chip, announce) {
  if (chip && CHIPS[chip]) FCHIP = chip;
  storeSet("alldown.chip", FCHIP);
  storeSet("alldown.q", FQ);
  render();
  if (announce) {
    const vis = visibleRows().length;
    const active = FCHIP !== "all" || FQ.trim();
    say(active
      ? `FILTRO ${CHIP_LABEL[FCHIP]}${FQ.trim() ? ` + "${FQ.trim()}"` : ""} — ${vis} DE ${ROWS.length}.`
      : `FILTRO LIMPO — ${ROWS.length} ITENS.`);
  }
}

function clearFilter() {
  FQ = "";
  setFilter("all", true);
}

function paintAutoBtn() {
  paintToggle(autoBtn, autoDetect, "AUTO: ON", "AUTO: OFF");
}

function toggleAuto() {
  autoDetect = !autoDetect;
  storeSet("alldown.autodetect", autoDetect ? "1" : "0");
  paintAutoBtn();
  say(autoDetect ? "AUTO LIGADO — DETECTO E CHECO SOZINHO." : "AUTO DESLIGADO — TUDO MANUAL.");
  if (autoDetect && looksLikePath(pathInput.value.trim()) && pathInput.value.trim() !== BASE) doScan();
}

function paintMode() {
  paintToggle(modeBtn, ZIP_ONLY, "MODO: SÓ-ZIP", "MODO: PASTAS");
}

async function toggleMode() {
  if (!BASE) { say("ESCANEIE UMA PASTA PRIMEIRO."); return; }
  const next = !ZIP_ONLY;
  say(next ? "TROCANDO P/ SÓ-ZIP…" : "TROCANDO P/ PASTAS…");
  try {
    const j = await api("/api/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: BASE, zip_only: next }),
    });
    ZIP_ONLY = !!j.zip_only;
    paintMode();
    say(ZIP_ONLY
      ? "MODO SÓ-ZIP — UPDATE TROCA SÓ O .ZIP, PASTA INTACTA."
      : "MODO PASTAS — UPDATE REFRESCA A PASTA EXTRAÍDA.");
  } catch (e) { say(`FALHA AO TROCAR MODO: ${e.message}`); }
  refreshLog();
}

function barStart() {
  if (!loadbar) return;
  loadbar.hidden = false;
  loadbar.classList.add("run");
  loadbar.classList.remove("done");
  if (loadfill) loadfill.style.width = "";
}

function barSet(done, total) {
  if (!loadbar || !loadfill) return;
  loadbar.hidden = false;
  loadbar.classList.remove("run");
  loadbar.classList.add("done");
  loadfill.style.width = total > 0 ? Math.round((done / total) * 100) + "%" : "0%";
}

function barStop() {
  if (!loadbar) return;
  loadbar.classList.remove("run", "done");
  loadbar.hidden = true;
}

function looksLikePath(v) {
  return v.length > 1 && (v.startsWith("/") || v.startsWith("~"));
}

function say(msg) {
  statusEl.textContent = msg;
}

async function refreshLog() {
  try {
    const r = await fetch("/api/log");
    const j = await r.json();
    logEl.textContent = (j.lines || []).join("\n") + "\n";
    logEl.scrollTop = logEl.scrollHeight;
  } catch { /* log é acessório, não derruba a UI */ }
}

function short(sha) {
  return sha ? String(sha).slice(0, 7) : "—";
}

/* Nomes de pasta, URLs e erros vêm do disco/rede — nunca entram crus no HTML. */
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function statusTag(r) {
  if (r.error) return '<span class="tag tag-err">ERRO</span>';
  if (!r.mapped) return '<span class="tag tag-g">SEM MAPA</span>';
  if (r.behind === true) return '<span class="tag tag-warn">DESATUALIZADO</span>';
  if (r.behind === false) return '<span class="tag tag-ok">ATUALIZADO</span>';
  return '<span class="tag tag-g">LISTADO</span>';
}

function render() {
  updateCounts();
  paintChips();
  paintBtnAll();
  const vis = visibleRows();
  const prevCount = countEl.textContent;
  const nextCount = `${vis.length} DE ${ROWS.length}`;
  countEl.textContent = nextCount;
  pulseCount(prevCount, nextCount);
  if (!ROWS.length) {
    withViewTransition(() => {
      tbody.innerHTML = '<tr class="empty"><td colspan="5">NENHUM REPO ESCANEADO.</td></tr>';
    });
    return;
  }
  if (!vis.length) {
    withViewTransition(() => {
      tbody.innerHTML = '<tr class="empty"><td colspan="5">NADA BATE COM O FILTRO.<br><button class="btn btn-quiet" data-clear type="button">LIMPAR FILTRO</button></td></tr>';
    });
    return;
  }
  const html = vis.map((r) => {
    const i = ROWS.indexOf(r);
    const autoChip = r.auto ? ' <span class="tag tag-info">AUTO</span>' : "";
    const tried = (r.tried && r.tried.length)
      ? `<div class="mono dim">VASCULHEI E NÃO ACHEI DONO: ${esc(r.tried.join(" • ").toUpperCase())}</div>`
      : "";
    const hint = (!r.mapped && r.suggested_repo)
      ? `<div class="mono">PARECE SER O REPO “${esc(r.suggested_repo)}” — FALTA O DONO (OWNER).</div>`
      : "";
    const suggBtn = !r.mapped
      ? `<div class="mini" style="margin-top:6px"><button class="btn btn-quiet" data-suggest="${i}" type="button">SUGERIR DONOS</button></div>`
      : "";
    const suggList = (!r.mapped && r.suggestions && r.suggestions.length)
      ? `<div class="sugg">${r.suggestions.map((s, j) => `<button class="sugg-btn" data-pick="${i}:${j}" type="button" title="${esc(s.description || s.full_name)}"><b>${esc(s.full_name)}</b><span>★ ${s.stars}</span></button>`).join("")}</div>`
      : "";
    const err = r.error ? `<div class="mono">ERRO: ${esc(r.error)}</div>` : "";
    const repoCell = r.mapped
      ? `<div><strong>${esc(r.name)}</strong></div><div class="mono">${r.auto ? "AUTO: " : ""}${esc(r.github_url || "")}${autoChip}</div>${err}`
      : `<div><strong>${esc(r.name)}</strong></div>${hint}${tried}`;
    const actionCell = r.mapped
      ? `<div class="mini">
           <button class="btn btn-quiet" data-check1="${i}" type="button">CHECAR</button>
           <button class="btn btn-primary" data-upd="${i}" type="button">ATUALIZAR</button>
           <button class="btn btn-quiet btn-danger" data-rb="${i}" type="button">REVERTER</button>
         </div>`
      : `<div class="urlrow">
           <label class="mono" for="url-${i}" style="align-self:center">URL</label>
           <input class="in" id="url-${i}" data-url="${i}" type="text" inputmode="url"
             autocomplete="off" spellcheck="false" placeholder="https://github.com/owner/repo…">
           <button class="btn btn-quiet" data-save="${i}" type="button">SALVAR</button>
         </div>${suggBtn}${suggList}`;
    return `<tr class="${r.mapped ? "" : "unmapped"}">
      <td>${repoCell}</td>
      <td class="mono">${short(r.local_sha)}</td>
      <td class="mono">${short(r.remote_sha)}</td>
      <td>${statusTag(r)}</td>
      <td>${actionCell}</td>
    </tr>`;
  }).join("");
  withViewTransition(() => {
    tbody.innerHTML = html;
    staggerEnter();
  });
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
  return j;
}

async function doScan() {
  const typed = pathInput.value.trim();
  if (!typed) { say("COLE A PASTA ACIMA — DETECÇÃO É AUTOMÁTICA."); return; }
  if (scanning) return;
  scanning = true;
  setBusy(true);
  barStart();
  BASE = typed;
  storeSet("alldown.path", BASE);
  say("ESCANEANDO…");
  try {
    const j = await api(`/api/scan?path=${encodeURIComponent(BASE)}`);
    ROWS = j.items || [];
    ZIP_ONLY = !!j.zip_only;
    paintMode();
    lastScanFailed = false;
    render();
    const mapped = ROWS.filter((r) => r.mapped).length;
    if (!ROWS.length) say(`PASTA VAZIA — NADA EM ${j.path}.`);
    else if (!mapped) say(`SCAN OK — ${ROWS.length} ITENS, MAS NENHUM LIGADO AO GITHUB. COLE A URL NA LINHA OU CRIE repos.json.`);
    else say(`SCAN OK — ${mapped}/${ROWS.length} LIGADOS AO GITHUB EM ${j.path}.`);
    if (autoDetect && mapped) await doCheck();
  } catch (e) { lastScanFailed = true; say(`FALHA NO SCAN: ${e.message}`); }
  refreshLog();
  scanning = false;
  barStop();
  setBusy(false);
}

function setBusy(b) {
  for (const id of ["btn-scan", "btn-check", "btn-all"]) {
    const el = $(id);
    if (el) el.disabled = b;
  }
}

async function doCheck() {
  if (!BASE) { say("ESCANEIE UMA PASTA PRIMEIRO."); return; }
  say("CONSULTANDO GITHUB…");
  barStart();
  try {
    const j = await api(`/api/check?path=${encodeURIComponent(BASE)}`);
    const byName = Object.fromEntries((j.items || []).map((x) => [x.name, x]));
    ROWS = ROWS.map((r) => ({ ...r, ...(byName[r.name] || {}) }));
    // inclui novos mapeados que surgiram
    for (const x of (j.items || [])) {
      if (!ROWS.some((r) => r.name === x.name)) ROWS.push(x);
    }
    render();
    say(`CHECK OK — ${j.items.length} REPOS CONSULTADOS.`);
  } catch (e) { say(`FALHA NO CHECK: ${e.message}`); }
  barStop();
  refreshLog();
}

async function doUpdate(name, quiet) {
  say(`ATUALIZANDO ${name}…`);
  if (!quiet) barStart();
  try {
    const j = await api("/api/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: BASE, name }),
    });
    const ix = ROWS.findIndex((r) => r.name === name);
    if (ix >= 0) ROWS[ix] = { ...ROWS[ix], local_sha: j.remote_sha, behind: false };
    render();
    say(ZIP_ONLY
      ? `OK — ${name} ZIP TROCADO. BACKUP: ${j.backup || "SEM BACKUP (ZIP NOVO)"}.`
      : `OK — ${name} ATUALIZADO. BACKUP: ${j.backup || "SEM BACKUP (PASTA NOVA)"}.`);
  } catch (e) { say(`FALHA EM ${name}: ${e.message}`); }
  if (!quiet) barStop();
  refreshLog();
}

async function doRollback(name) {
  if (!confirm(`Reverter ${name} para o backup .bak?`)) return;
  try {
    await api("/api/rollback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: BASE, name }),
    });
    say(`OK — ${name} REVERTIDO.`);
  } catch (e) { say(`FALHA AO REVERTER: ${e.message}`); }
  refreshLog();
}

async function mapRepo(i, url) {
  url = (url || "").trim();
  if (!url.includes("github.com")) { say("URL INVÁLIDA — USE https://github.com/owner/repo."); return; }
  try {
    await api("/api/map", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: BASE, name: ROWS[i].name, url }),
    });
    ROWS[i] = { ...ROWS[i], github_url: url, mapped: true, suggestions: null };
    render();
    say(`MAPEADO — ${ROWS[i].name}. CLIQUE EM CHECAR.`);
  } catch (e) { say(`FALHA AO SALVAR: ${e.message}`); }
  refreshLog();
}

async function doSave(i) {
  const inp = document.querySelector(`[data-url="${i}"]`);
  mapRepo(i, (inp && inp.value) || "");
}

async function doSuggest(i) {
  const q = ROWS[i].suggested_repo || ROWS[i].name;
  say(`BUSCANDO DONOS P/ “${q}”…`);
  try {
    const j = await api(`/api/suggest?q=${encodeURIComponent(q)}`);
    ROWS[i] = { ...ROWS[i], suggestions: j.items || [] };
    render();
    say((j.items || []).length
      ? `${j.items.length} SUGESTÕES P/ ${ROWS[i].name} — CLIQUE P/ MAPEAR.`
      : `NENHUMA SUGESTÃO P/ ${ROWS[i].name}. COLE A URL.`);
  } catch (e) { say(`FALHA AO SUGERIR: ${e.message}`); }
}

async function refreshToken() {
  const tx = $("token-tx");
  const badge = $("token-badge");
  if (!tx) return;
  const paint = (cls, msg) => {
    tx.textContent = msg;
    if (badge) badge.className = `side-token${cls ? ` ${cls}` : ""}`;
  };
  try {
    const j = await api("/api/token");
    if (j.valid === false) paint("tok-err", "TOKEN INVÁLIDO");
    else if (j.configured && j.valid) paint("tok-ok", `TOKEN OK · ${j.remaining}/${j.limit}`);
    else if (!j.configured) paint("tok-warn", j.limit ? `SEM TOKEN · ${j.remaining}/${j.limit}` : "SEM TOKEN · 60/H");
    else paint("", "API: ?");
  } catch { paint("", "API: OFFLINE"); }
}

$("btn-scan").addEventListener("click", doScan);
$("btn-check").addEventListener("click", doCheck);
if (autoBtn) autoBtn.addEventListener("click", toggleAuto);
if (modeBtn) modeBtn.addEventListener("click", toggleMode);
$("btn-all").addEventListener("click", async () => {
  const todo = visibleRows().filter((r) => r.mapped && r.behind === true);
  if (!todo.length) { say("NADA PARA ATUALIZAR NA LISTA VISÍVEL."); return; }
  setBusy(true);
  let i = 0;
  for (const r of todo) {
    barSet(i, todo.length);
    await doUpdate(r.name, true);
    i++;
  }
  barSet(todo.length, todo.length);
  say(`LOTE OK — ${todo.length} VISÍVEIS PROCESSADOS. VEJA O LOG.`);
  setBusy(false);
  setTimeout(barStop, 1500);
  refreshLog();
});
tbody.addEventListener("click", (ev) => {
  const src = ev.target;
  if (!(src instanceof HTMLElement)) return;
  const t = src.closest("[data-clear],[data-save],[data-suggest],[data-pick],[data-upd],[data-rb],[data-check1]");
  if (!t || !tbody.contains(t)) return;
  if (t.dataset.clear !== undefined) { clearFilter(); return; }
  if (t.dataset.save !== undefined) doSave(Number(t.dataset.save));
  if (t.dataset.suggest !== undefined) doSuggest(Number(t.dataset.suggest));
  if (t.dataset.pick !== undefined) {
    const [pi, pj] = String(t.dataset.pick).split(":").map(Number);
    const s = ROWS[pi] && ROWS[pi].suggestions && ROWS[pi].suggestions[pj];
    if (s) mapRepo(pi, s.url);
    return;
  }
  if (t.dataset.upd !== undefined) doUpdate(ROWS[Number(t.dataset.upd)].name);
  if (t.dataset.rb !== undefined) doRollback(ROWS[Number(t.dataset.rb)].name);
  if (t.dataset.check1 !== undefined) doCheck();
});
$("form-path").addEventListener("submit", (e) => { e.preventDefault(); doScan(); });
$("chips").addEventListener("click", (ev) => {
  const node = ev.target;
  const el = node instanceof HTMLElement ? node : node && node.parentElement;
  const t = el && el.closest ? el.closest("[data-chip]") : null;
  if (t && $("chips").contains(t)) setFilter(t.dataset.chip, true);
});
let qdeb = null;
$("in-search").addEventListener("input", (ev) => {
  qdeb = rearm(qdeb, () => { FQ = ev.target.value; setFilter(null, true); }, 300);
});
pathInput.addEventListener("input", () => {
  clearTimeout(debounce);
  debounce = null;
  if (!autoDetect) return;
  const v = pathInput.value.trim();
  if (!looksLikePath(v)) return;
  if (v === BASE && !lastScanFailed) return;
  debounce = rearm(debounce, doScan, 700);
});
setInterval(refreshLog, 8000);
paintAutoBtn();
paintMode();
refreshToken();
render();
if (autoDetect && looksLikePath(pathInput.value.trim())) doScan();

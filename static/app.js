const $ = (id) => document.getElementById(id);
const dom = {
  sidebar: $("sidebar"),
  scrim: document.querySelector(".mobile-scrim"),
  repoList: $("repo-list"),
  pathPanel: document.querySelector(".path-panel"),
  libraryPanel: document.querySelector(".library-panel"),
  libraryView: $("library-view"),
  activityView: $("activity-view"),
  settingsView: $("settings-view"),
  pathInput: $("in-path"),
  pathCaption: $("path-caption"),
  search: $("in-search"),
  count: $("count"),
  status: $("status"),
  log: $("log"),
  tokenDot: $("token-dot"),
  tokenTitle: $("token-title"),
  tokenDetail: $("token-detail"),
  syncState: $("sync-state"),
  viewTitle: $("view-title"),
  toastRegion: $("toast-region"),
  btnScan: $("btn-scan"),
  btnCheck: $("btn-check"),
  btnAll: $("btn-all"),
  btnAuto: $("btn-auto"),
  btnMode: $("btn-mode"),
  btnBackup: $("btn-backup"),
};
const state = {
  base: "",
  rows: [],
  filter: "all",
  query: "",
  view: "library",
  auto: true,
  zipOnly: false,
  backup: true,
  busy: false,
  scanning: false,
  lastScanFailed: false,
  theme: "dark",
};
const FILTER_INFO = {
  all: { label: "Todos", test: () => true },
  behind: { label: "Atualizar", test: (row) => row.behind === true },
  ready: { label: "Em dia", test: (row) => row.behind === false },
  unmapped: { label: "Sem dono", test: (row) => !row.mapped },
  error: { label: "Erros", test: (row) => Boolean(row.error) },
};
const RM = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };

if (!dom.repoList || !dom.pathInput || !dom.status) {
  throw new Error("RepoRefresh: interface não carregada");
}

function storeGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function storeSet(key, value) {
  try { localStorage.setItem(key, value); } catch { }
}
function icon(name, className = "") {
  return `<svg class="icon ${className}" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
}
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}
function shortSha(value) {
  return value ? String(value).slice(0, 7) : "—";
}
function formatSize(bytes) {
  if (bytes == null) return "?";
  const units = ["B", "KB", "MB", "GB"];
  let value = Number(bytes);
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value >= 100 ? Math.round(value) : value.toFixed(1).replace(".", ",")} ${units[index]}`;
}
function formatSpeed(bytesPerSecond) {
  return bytesPerSecond == null ? "?" : `${formatSize(bytesPerSecond)}/s`;
}
function formatDate(value) {
  if (!value) return "sem data";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "data inválida";
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
function looksLikePath(value) {
  return value.length > 1 && (value.startsWith("/") || value.startsWith("~"));
}
function statusInfo(row) {
  if (row.error) return { key: "error", label: "Erro", detail: "Revisar atividade", cls: "is-error" };
  if (!row.mapped) return { key: "unmapped", label: "Sem dono", detail: "Mapear repositório", cls: "" };
  if (row.behind === true && !row.local_sha) return { key: "info", label: "Nunca sincronizado", detail: "Atualizar agora", cls: "is-update" };
  if (row.behind === true) return { key: "update", label: "Atualização disponível", detail: "Commit remoto", cls: "is-update" };
  if (row.behind === false) return { key: "ready", label: "Em dia", detail: "Commit verificado", cls: "is-ready" };
  return { key: "neutral", label: "Aguardando check", detail: "Comparar com GitHub", cls: "" };
}
function countRows() {
  const counts = {
    all: state.rows.length,
    behind: state.rows.filter((row) => row.behind === true).length,
    ready: state.rows.filter((row) => row.behind === false).length,
    unmapped: state.rows.filter((row) => !row.mapped).length,
    error: state.rows.filter((row) => Boolean(row.error)).length,
  };
  $("nav-count").textContent = String(counts.all);
  $("c-all").textContent = String(counts.all);
  $("c-behind").textContent = String(counts.behind);
  $("c-ok").textContent = String(counts.ready);
  $("c-unmapped").textContent = String(counts.unmapped);
  $("c-error").textContent = String(counts.error);
  $("sum-total").textContent = String(counts.all);
  $("sum-ready").textContent = String(counts.ready);
  $("sum-behind").textContent = String(counts.behind);
  $("sum-attention").textContent = String(counts.unmapped + counts.error);
  return counts;
}
function visibleRows() {
  const query = state.query.trim().toLowerCase();
  const test = FILTER_INFO[state.filter]?.test ?? FILTER_INFO.all.test;
  return state.rows.filter((row) => {
    const haystack = `${row.name || ""} ${row.owner || ""} ${row.repo || ""} ${row.github_url || ""}`.toLowerCase();
    return test(row) && (!query || haystack.includes(query));
  });
}
function initials(row) {
  const source = row.owner && row.repo ? `${row.owner}${row.repo}` : row.name || "R";
  return source.replace(/[^a-z0-9]/gi, "").slice(0, 2).toUpperCase() || "R";
}
function artifactLabel(row) {
  const values = [];
  if (row.local_dir) values.push("pasta");
  if (row.zip_path) values.push("ZIP");
  return values.length ? values.join(" + ") : "sem artefato local";
}
function renderRepoCard(row, index) {
  const status = statusInfo(row);
  const remoteName = row.owner && row.repo ? `${row.owner}/${row.repo}` : row.github_url || "GitHub";
  const branch = row.branch || "main";
  const error = row.error ? `<div class="repo-meta"><span>${icon("alert")} ${esc(row.error)}</span></div>` : "";
  const tried = row.tried && row.tried.length ? `<div class="repo-meta"><span>${icon("search")} ${esc(row.tried.join(" · "))}</span></div>` : "";
  if (!row.mapped) {
    const suggestions = row.suggestions && row.suggestions.length
      ? `<div class="suggestions">${row.suggestions.map((suggestion, suggestionIndex) => `<button class="suggestion" type="button" data-action="pick-suggestion" data-index="${index}" data-suggestion="${suggestionIndex}">${esc(suggestion.full_name || suggestion.url || "GitHub")} <span>★ ${esc(suggestion.stars ?? 0)}</span></button>`).join("")}</div>`
      : "";
    return `<article class="repo-card ${status.cls} ${row.busy ? "is-busy" : ""}" data-row-index="${index}">
      <div class="repo-main"><div class="repo-avatar">${esc(initials(row))}</div><div class="repo-copy"><div class="repo-title-line"><strong>${esc(row.name)}</strong><span class="mini-tag">sem dono</span></div><span class="repo-url">${esc(row.suggested_repo || "repositório ainda não identificado")}</span>${tried}${error}</div></div>
      <div class="repo-state state-${status.key}"><span class="state-dot"></span><span class="state-copy"><strong>${status.label}</strong><small>${status.detail}</small></span></div>
      <div class="repo-inline-form"><label class="sr-only" for="url-${index}">URL do GitHub para ${esc(row.name)}</label><input id="url-${index}" data-url-input="${index}" type="url" inputmode="url" autocomplete="off" spellcheck="false" placeholder="https://github.com/owner/repo"><button class="button button-primary" type="button" data-action="save-map" data-index="${index}">${icon("check")}Salvar</button><button class="button button-quiet" type="button" data-action="suggest" data-index="${index}">${icon("spark")}Sugerir</button></div>${suggestions}
    </article>`;
  }
  const updateLabel = row.behind === true ? "Atualizar" : "Verificar";
  const updateClass = row.behind === true ? "button-primary" : "button-quiet";
  const rollbackDisabled = row.can_rollback === false ? " disabled" : "";
  return `<article class="repo-card ${status.cls} ${row.busy ? "is-busy" : ""}" data-row-index="${index}">
    <div class="repo-main"><div class="repo-avatar">${esc(initials(row))}</div><div class="repo-copy"><div class="repo-title-line"><strong>${esc(row.name)}</strong>${row.auto ? '<span class="mini-tag is-auto">auto</span>' : ""}<span class="mini-tag is-branch">${esc(branch)}</span></div><span class="repo-url">${esc(remoteName)}</span><div class="repo-meta"><span>${icon("folder")} ${esc(artifactLabel(row))}</span><span>${icon("check")} local <code>${esc(shortSha(row.local_sha))}</code></span><span>${icon("cloud")} remoto <code>${esc(shortSha(row.remote_sha))}</code></span></div>${error}</div></div>
    <div class="repo-state state-${status.key}"><span class="state-dot"></span><span class="state-copy"><strong>${status.label}</strong><small>${status.detail}</small></span></div>
    <div class="repo-actions"><button class="button button-quiet" type="button" data-action="check-row" data-index="${index}">${icon("refresh")}Checar tudo</button><button class="button ${updateClass}" type="button" data-action="update-row" data-index="${index}">${icon("cloud")}${updateLabel}</button><button class="button button-danger" type="button" data-action="rollback-row" data-index="${index}"${rollbackDisabled}>${icon("back")}${row.can_rollback === false ? "Sem backup" : "Reverter"}</button></div>
  </article>`;
}
function renderEmpty() {
  if (!state.base) {
    return `<div class="empty-state"><div class="empty-icon">${icon("folder")}</div><strong>Escolha uma pasta para começar</strong><p>RepoRefresh procura pastas e ZIPs, detecta o repositório e mostra tudo aqui.</p></div>`;
  }
  if (!state.rows.length) {
    return `<div class="empty-state"><div class="empty-icon">${icon("scan")}</div><strong>Nenhum repositório encontrado</strong><p>Confira o caminho escolhido. A pasta pode estar vazia ou sem permissão de leitura.</p></div>`;
  }
  return `<div class="empty-state"><div class="empty-icon">${icon("search")}</div><strong>Nenhum item neste filtro</strong><p>Ajuste busca ou escolha outro grupo para continuar.</p></div>`;
}
function render() {
  const rows = visibleRows();
  const counts = countRows();
  dom.count.textContent = `${rows.length} de ${state.rows.length} ${state.rows.length === 1 ? "item" : "itens"}`;
  dom.pathCaption.textContent = state.base || "Nenhuma pasta selecionada";
  dom.search.value = state.query;
  document.querySelectorAll("[data-filter]").forEach((button) => {
    const active = button.dataset.filter === state.filter;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
  dom.repoList.innerHTML = rows.length ? rows.map((row) => renderRepoCard(row, state.rows.indexOf(row))).join("") : renderEmpty();
  dom.btnAll.classList.toggle("button-primary", counts.behind > 0);
  dom.btnAll.classList.toggle("button-quiet", counts.behind === 0);
  dom.btnAll.disabled = state.busy || counts.behind === 0;
}
function paintToggles() {
  dom.btnAuto.setAttribute("aria-pressed", state.auto ? "true" : "false");
  dom.btnAuto.querySelector("b").textContent = state.auto ? "Ativa" : "Pausada";
  dom.btnMode.setAttribute("aria-pressed", state.zipOnly ? "true" : "false");
  dom.btnMode.querySelector("b").textContent = state.zipOnly ? "Só ZIP" : "Pastas";
  dom.btnBackup.setAttribute("aria-pressed", state.backup ? "true" : "false");
  dom.btnBackup.querySelector("b").textContent = state.backup ? "Ativo" : "Desligado";
}
function setView(view) {
  state.view = view;
  dom.libraryView.hidden = view !== "library";
  dom.libraryPanel.hidden = view !== "library";
  dom.activityView.hidden = view !== "activity";
  dom.settingsView.hidden = view !== "settings";
  dom.pathPanel.hidden = view !== "library";
  document.querySelectorAll("[data-view]").forEach((item) => {
    const active = item.dataset.view === view;
    item.classList.toggle("is-active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  const titles = { library: "Biblioteca", activity: "Atividade", settings: "Preferências" };
  dom.viewTitle.textContent = titles[view] || "Biblioteca";
  closeSidebar();
  window.scrollTo({ top: 0, behavior: RM.matches ? "auto" : "smooth" });
}
function setFilter(filter) {
  if (FILTER_INFO[filter]) state.filter = filter;
  storeSet("alldown.filter", state.filter);
  render();
}
function say(message, tone = "neutral", showToast = false) {
  dom.status.dataset.tone = tone;
  dom.status.querySelector("span:last-child").textContent = message;
  if (showToast) toast(message, tone);
}
function toast(message, tone = "neutral") {
  const item = document.createElement("div");
  item.className = `toast${tone === "error" ? " is-error" : tone === "warning" ? " is-warning" : ""}`;
  item.innerHTML = `${icon(tone === "error" ? "alert" : tone === "warning" ? "activity" : "check")}<span>${esc(message)}</span>`;
  dom.toastRegion.appendChild(item);
  window.setTimeout(() => item.remove(), 4200);
}
function setBusy(value) {
  state.busy = value;
  document.body.classList.toggle("is-busy", value);
  dom.btnScan.disabled = value;
  dom.btnCheck.disabled = value || !state.base;
  dom.btnAll.disabled = value || !state.base || state.rows.filter((row) => row.behind === true).length === 0;
  dom.syncState.classList.toggle("is-warn", value);
  dom.syncState.querySelector("span:last-child").textContent = value ? "processando" : "pronto";
}
function startProgress() {
  dom.syncState.classList.add("is-warn");
  dom.syncState.querySelector("span:last-child").textContent = "processando";
}
function stopProgress() {
  if (!state.busy) {
    dom.syncState.classList.remove("is-warn");
    dom.syncState.querySelector("span:last-child").textContent = "pronto";
  }
}
async function api(path, options = {}, timeoutMs = 90000) {
  const controller = timeoutMs > 0 ? new AbortController() : null;
  const timer = controller ? window.setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const request = { ...options };
    if (!request.signal && controller) request.signal = controller.signal;
    const response = await fetch(path, request);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = payload && payload.detail;
      throw new Error(typeof detail === "string" ? detail : `HTTP ${response.status}`);
    }
    return payload;
  } catch (error) {
    if (error && error.name === "AbortError") throw new Error("Tempo esgotado");
    throw error;
  } finally {
    if (timer) window.clearTimeout(timer);
  }
}
async function postFlag(endpoint, payload, apply) {
  if (state.busy) return;
  if (!state.base) {
    say("Selecione uma pasta primeiro.", "warning", true);
    return;
  }
  setBusy(true);
  try {
    const result = await api(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.base, ...payload }),
    }, 90000);
    apply(result);
    paintToggles();
    render();
    await doScan({ allowBusy: true, path: state.base });
  } catch (error) {
    say(`Não foi possível alterar a preferência: ${error.message}`, "error", true);
  } finally {
    setBusy(false);
    refreshLog();
  }
}
async function refreshToken() {
  try {
    const result = await api("/api/token");
    if (result.rate_limited) {
      dom.tokenDot.className = "connection-dot is-warn";
      dom.tokenTitle.textContent = "Limite da API";
      dom.tokenDetail.textContent = "Aguardando reset";
    } else if (result.valid === false) {
      dom.tokenDot.className = "connection-dot is-error";
      dom.tokenTitle.textContent = "Token inválido";
      dom.tokenDetail.textContent = "Verificar GITHUB_TOKEN";
    } else if (result.configured && result.valid) {
      dom.tokenDot.className = "connection-dot is-ok";
      dom.tokenTitle.textContent = "GitHub conectado";
      dom.tokenDetail.textContent = `${result.remaining ?? "?"}/${result.limit ?? "?"} requests`;
    } else if (result.configured && result.valid === null) {
      dom.tokenDot.className = "connection-dot is-warn";
      dom.tokenTitle.textContent = "Status desconhecido";
      dom.tokenDetail.textContent = "Aguardando resposta do GitHub";
    } else {
      dom.tokenDot.className = "connection-dot is-warn";
      dom.tokenTitle.textContent = "Modo sem token";
      dom.tokenDetail.textContent = result.limit ? `${result.remaining}/${result.limit} requests` : "60 requests/hora";
    }
  } catch {
    dom.tokenDot.className = "connection-dot is-error";
    dom.tokenTitle.textContent = "API offline";
    dom.tokenDetail.textContent = "Servidor local indisponível";
  }
}
async function refreshLog() {
  try {
    const result = await api("/api/log", {}, 10000);
    dom.log.textContent = `${(result.lines || []).join("\n")}\n`;
    dom.log.scrollTop = dom.log.scrollHeight;
  } catch { }
}
async function doScan(options = {}) {
  const path = options.path || dom.pathInput.value.trim();
  if (!path) {
    say("Cole uma pasta para começar.", "warning", true);
    dom.pathInput.focus();
    return;
  }
  if (state.busy && options.allowBusy !== true) return;
  state.scanning = true;
  storeSet("alldown.path", path);
  setBusy(true);
  startProgress();
  say("Escaneando pasta…", "info");
  try {
    const result = await api(`/api/scan?path=${encodeURIComponent(path)}`, {}, 900000);
    state.base = result.path || path;
    state.rows = result.items || [];
    state.zipOnly = Boolean(result.zip_only);
    state.backup = result.backup !== false;
    state.lastScanFailed = false;
    paintToggles();
    render();
    const mapped = state.rows.filter((row) => row.mapped).length;
    if (!state.rows.length) say("Pasta vazia: nenhum repositório encontrado.", "warning");
    else if (!mapped) say(`${state.rows.length} itens detectados; nenhum vínculo GitHub ainda.`, "warning");
    else say(`${mapped} de ${state.rows.length} repositórios prontos para checagem.`, "success", true);
    if (state.auto && mapped) await doCheck(true);
  } catch (error) {
    state.lastScanFailed = true;
    dom.pathInput.value = state.base || "";
    storeSet("alldown.path", state.base || "");
    say(`Falha no scan: ${error.message}`, "error", true);
  } finally {
    state.scanning = false;
    setBusy(false);
    stopProgress();
    refreshLog();
  }
}
async function doCheck(fromScan = false) {
  if (!state.base) {
    say("Selecione uma pasta primeiro.", "warning", true);
    return;
  }
  if (state.busy && !fromScan) return;
  if (!fromScan) setBusy(true);
  startProgress();
  say("Consultando commits no GitHub…", "info");
  try {
    const result = await api(`/api/check?path=${encodeURIComponent(state.base)}`, {}, 900000);
    const checkedItems = result.items || [];
    const previousByName = Object.fromEntries(state.rows.map((row) => [row.name, row]));
    const unmappedRows = state.rows.filter((row) => !row.mapped);
    state.rows = [
      ...unmappedRows,
      ...checkedItems.map((item) => {
        const merged = { ...(previousByName[item.name] || {}), ...item };
        merged.error = item.error || null;
        if (item.error) merged.behind = null;
        return merged;
      }),
    ];
    render();
    const errors = checkedItems.filter((item) => item.error).length;
    const updates = checkedItems.filter((item) => item.behind === true).length;
    const message = errors
      ? `Check concluído com ${errors} ${errors === 1 ? "erro" : "erros"}.`
      : updates
        ? `Check concluído: ${updates} ${updates === 1 ? "atualização disponível" : "atualizações disponíveis"}.`
        : "Check concluído: nada pendente.";
    say(message, errors || updates ? "warning" : "success", true);
  } catch (error) {
    say(`Falha no check: ${error.message}`, "error", true);
  } finally {
    if (!fromScan) setBusy(false);
    stopProgress();
    refreshLog();
  }
}
async function doUpdate(name, quiet = false) {
  if (state.busy && !quiet) return false;
  const row = state.rows.find((item) => item.name === name);
  if (!row || !row.mapped || (!quiet && row.behind !== true)) return false;
  if (!quiet) setBusy(true);
  row.busy = true;
  render();
  startProgress();
  say(`Atualizando ${name}…`, "info");
  try {
    const result = await api("/api/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.base, name }),
    }, 900000);
    row.local_sha = result.remote_sha;
    row.behind = false;
    row.error = null;
    row.can_rollback = Boolean(result.backup);
    if (result.zip_only) row.zip_path = result.path;
    else row.local_dir = result.path;
    render();
    const transfer = `${formatSize(result.download_bytes)} · ${formatSpeed(result.speed_bps)}`;
    const packageSize = `${formatSize(result.old_bytes)} → ${formatSize(result.new_bytes)}`;
    say(`${name} atualizado. ${transfer}. ${packageSize}.`, "success", true);
    return true;
  } catch (error) {
    row.error = error.message;
    say(`Falha em ${name}: ${error.message}`, "error", true);
    return false;
  } finally {
    row.busy = false;
    render();
    if (!quiet) setBusy(false);
    stopProgress();
    refreshLog();
  }
}
async function doRollback(name) {
  if (state.busy) return;
  const row = state.rows.find((item) => item.name === name);
  if (!row || !window.confirm(`Reverter ${name} para o backup mais antigo?`)) return;
  setBusy(true);
  row.busy = true;
  render();
  say(`Revertendo ${name}…`, "info");
  try {
    const result = await api("/api/rollback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.base, name }),
    }, 900000);
    row.local_sha = null;
    row.behind = null;
    row.error = null;
    row.can_rollback = false;
    render();
    say(`${name} revertido${result.zip_only ? " no modo ZIP" : ""}.`, "success", true);
  } catch (error) {
    say(`Falha ao reverter: ${error.message}`, "error", true);
  } finally {
    row.busy = false;
    render();
    setBusy(false);
    refreshLog();
  }
}
async function mapRepo(index, url) {
  if (state.busy) return;
  const row = state.rows[index];
  url = String(url || "").trim();
  if (!row || !url) {
    say("Informe uma URL do GitHub.", "warning", true);
    return;
  }
  setBusy(true);
  try {
    await api("/api/map", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.base, name: row.name, url }),
    }, 90000);
    row.suggestions = null;
    row.error = null;
    say(`${row.name} mapeado. Atualizando biblioteca…`, "success", true);
    await doScan({ allowBusy: true, path: state.base });
  } catch (error) {
    say(`Falha ao mapear: ${error.message}`, "error", true);
  } finally {
    setBusy(false);
    refreshLog();
  }
}
async function suggestRepo(index) {
  if (state.busy) return;
  const row = state.rows[index];
  if (!row) return;
  const query = row.suggested_repo || row.name;
  say(`Buscando donos para ${query}…`, "info");
  try {
    const result = await api(`/api/suggest?q=${encodeURIComponent(query)}`, {}, 30000);
    row.suggestions = result.items || [];
    render();
    say(row.suggestions.length ? `${row.suggestions.length} sugestões encontradas.` : "Nenhuma sugestão encontrada.", row.suggestions.length ? "success" : "warning", true);
  } catch (error) {
    say(`Falha ao buscar sugestões: ${error.message}`, "error", true);
  }
}
async function updateAll() {
  const rows = visibleRows().filter((row) => row.mapped && row.behind === true);
  if (!rows.length) {
    say("Nenhuma atualização disponível nesta lista.", "info", true);
    return;
  }
  setBusy(true);
  let succeeded = 0;
  let failed = 0;
  for (const row of rows) {
    const ok = await doUpdate(row.name, true);
    if (ok) succeeded += 1;
    else failed += 1;
  }
  setBusy(false);
  say(failed ? `${succeeded} atualizados, ${failed} com falha.` : `${succeeded} repositórios atualizados.`, failed ? "warning" : "success", true);
  refreshLog();
}
function toggleTheme() {
  state.theme = state.theme === "dark" ? "light" : "dark";
  document.body.dataset.theme = state.theme;
  $("theme-label").textContent = state.theme === "dark" ? "Escuro" : "Claro";
  storeSet("alldown.theme", state.theme);
}
function syncSidebarAccessibility() {
  const mobile = window.matchMedia ? window.matchMedia("(max-width: 860px)").matches : false;
  const open = dom.sidebar.classList.contains("is-open");
  dom.sidebar.inert = Boolean(mobile && !open);
  dom.sidebar.setAttribute("aria-hidden", mobile && !open ? "true" : "false");
}
function toggleSidebar() {
  const open = !dom.sidebar.classList.contains("is-open");
  dom.sidebar.classList.toggle("is-open", open);
  dom.scrim.classList.toggle("is-visible", open);
  const menu = document.querySelector(".mobile-menu");
  menu?.setAttribute("aria-expanded", open ? "true" : "false");
  menu?.setAttribute("aria-label", open ? "Fechar menu" : "Abrir menu");
  syncSidebarAccessibility();
}
function closeSidebar() {
  dom.sidebar.classList.remove("is-open");
  dom.scrim.classList.remove("is-visible");
  const menu = document.querySelector(".mobile-menu");
  menu?.setAttribute("aria-expanded", "false");
  menu?.setAttribute("aria-label", "Abrir menu");
  syncSidebarAccessibility();
}
function focusScan() {
  setView("library");
  window.setTimeout(() => dom.pathInput.focus(), 40);
}
function handleAction(action, element) {
  const index = Number(element.dataset.index);
  const busyActions = new Set(["check-row", "update-row", "rollback-row", "save-map", "suggest", "pick-suggestion", "refresh"]);
  if (state.busy && busyActions.has(action)) return;
  if (action === "toggle-sidebar") toggleSidebar();
  if (action === "close-sidebar") closeSidebar();
  if (action === "toggle-theme") toggleTheme();
  if (action === "focus-scan") focusScan();
  if (action === "refresh-token") refreshToken();
  if (action === "refresh-log") refreshLog();
  if (action === "refresh") {
    if (state.base) doCheck();
    else focusScan();
  }
  if (action === "check-row") doCheck();
  if (action === "update-row") {
    const row = state.rows[index];
    if (row?.behind === true) doUpdate(row.name);
    else doCheck();
  }
  if (action === "rollback-row") doRollback(state.rows[index]?.name);
  if (action === "save-map") {
    const input = dom.repoList.querySelector(`[data-url-input="${index}"]`);
    mapRepo(index, input?.value);
  }
  if (action === "suggest") suggestRepo(index);
  if (action === "pick-suggestion") {
    const suggestion = state.rows[index]?.suggestions?.[Number(element.dataset.suggestion)];
    if (suggestion) mapRepo(index, suggestion.url);
  }
}
function init() {
  state.query = storeGet("alldown.query") || "";
  const storedFilter = storeGet("alldown.filter");
  if (FILTER_INFO[storedFilter]) state.filter = storedFilter;
  state.theme = storeGet("alldown.theme") === "light" ? "light" : "dark";
  document.body.dataset.theme = state.theme;
  document.querySelectorAll(".sidebar svg, .topbar svg, .button svg, .icon-button svg").forEach((svg) => svg.setAttribute("aria-hidden", "true"));
  $("theme-label").textContent = state.theme === "dark" ? "Escuro" : "Claro";
  state.auto = storeGet("alldown.auto") !== "0";
  dom.pathInput.value = storeGet("alldown.path") || "";
  paintToggles();
  render();
  setBusy(false);
  setView("library");
  syncSidebarAccessibility();
  refreshToken();
  refreshLog();
  window.setInterval(refreshLog, 8000);
  if (state.auto && looksLikePath(dom.pathInput.value.trim())) window.setTimeout(doScan, 120);
}
$("form-path").addEventListener("submit", (event) => {
  event.preventDefault();
  doScan();
});
dom.search.addEventListener("input", (event) => {
  state.query = event.target.value;
  storeSet("alldown.query", state.query);
  render();
});
$("filters").addEventListener("click", (event) => {
  const button = event.target.closest("[data-filter]");
  if (button) setFilter(button.dataset.filter);
});
dom.btnScan.addEventListener("click", doScan);
dom.btnCheck.addEventListener("click", () => doCheck());
dom.btnAll.addEventListener("click", updateAll);
dom.btnAuto.addEventListener("click", () => {
  state.auto = !state.auto;
  storeSet("alldown.auto", state.auto ? "1" : "0");
  paintToggles();
  say(state.auto ? "Detecção automática ativada." : "Detecção automática pausada.", "info", true);
  if (state.auto && looksLikePath(dom.pathInput.value.trim()) && dom.pathInput.value.trim() !== state.base) doScan();
});
dom.btnMode.addEventListener("click", () => {
  const next = !state.zipOnly;
  postFlag("/api/mode", { zip_only: next }, (result) => {
    state.zipOnly = Boolean(result.zip_only);
    say(state.zipOnly ? "Modo somente ZIP ativado." : "Modo pasta ativado.", "success", true);
  });
});
dom.btnBackup.addEventListener("click", () => {
  const next = !state.backup;
  postFlag("/api/backup", { backup: next }, (result) => {
    state.backup = Boolean(result.backup);
    say(state.backup ? "Backup ativado." : "Backup desligado.", "success", true);
  });
});
dom.pathInput.addEventListener("input", () => {
  if (!state.auto || !looksLikePath(dom.pathInput.value.trim())) return;
  if (dom.pathInput.value.trim() === state.base && !state.lastScanFailed) return;
  window.clearTimeout(state.pathTimer);
  state.pathTimer = window.setTimeout(doScan, 700);
});
dom.repoList.addEventListener("click", (event) => {
  const element = event.target.closest("[data-action]");
  if (element) handleAction(element.dataset.action, element);
});
document.addEventListener("click", (event) => {
  const viewButton = event.target.closest("[data-view]");
  if (viewButton) {
    setView(viewButton.dataset.view);
    return;
  }
  const actionButton = event.target.closest("[data-action]");
  if (actionButton && !dom.repoList.contains(actionButton)) handleAction(actionButton.dataset.action, actionButton);
});
window.addEventListener("resize", syncSidebarAccessibility);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeSidebar();
    return;
  }
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  const tag = event.target?.tagName || "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if (event.key.toLowerCase() === "e") {
    event.preventDefault();
    doScan();
  }
  if (event.key.toLowerCase() === "c") {
    event.preventDefault();
    doCheck();
  }
});
init();

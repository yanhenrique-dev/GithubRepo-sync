/* ==========================================================================
   RepoRefresh — aplicação
   Toda a UI é montada só com os primitives de components.css.
   Contrato de atributos: data-component / data-variant / data-size / data-state.
   ========================================================================== */
const $ = (id) => document.getElementById(id);

const dom = {
  root: document.documentElement,
  sidebar: $("sidebar"),
  scrim: document.querySelector(".mobile-scrim"),
  pageThumb: $("page-thumb"),
  main: $("conteudo"),
  repoList: $("repo-list"),
  libraryView: $("library-view"),
  activityView: $("activity-view"),
  settingsView: $("settings-view"),
  pathInput: $("in-path"),
  pathError: $("path-error"),
  pathCaption: $("path-caption"),
  search: $("in-search"),
  count: $("count"),
  status: $("status"),
  statusText: $("status-text"),
  statusIcon: $("status").querySelector("use"),
  statusProgress: $("status-progress"),
  log: $("log"),
  tokenDot: $("token-dot"),
  tokenTitle: $("token-title"),
  tokenDetail: $("token-detail"),
  syncDot: $("sync-dot"),
  syncLabel: $("sync-label"),
  viewTitle: $("view-title"),
  themeColor: $("theme-color"),
  themeLabel: $("theme-label"),
  themeIcon: document.querySelector('[data-action="toggle-theme"] use'),
  toastRegion: $("toast-region"),
  btnScan: $("btn-scan"),
  btnCheck: $("btn-check"),
  btnAll: $("btn-all"),
  btnAuto: $("btn-auto"),
  btnMode: $("btn-mode"),
  btnBackup: $("btn-backup"),
  labelAuto: $("label-auto"),
  labelMode: $("label-mode"),
  labelBackup: $("label-backup"),
  filters: $("filters"),
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
  confirmRollback: null,
  confirmUpdate: null,
  theme: "dark",
  pathTimer: null,
};

const FILTER_INFO = {
  all: { label: "Todos", test: () => true },
  behind: { label: "Atualizar", test: (row) => row.behind === true },
  ready: { label: "Em dia", test: (row) => row.behind === false },
  unmapped: { label: "Sem dono", test: (row) => !row.mapped },
  error: { label: "Erros", test: (row) => Boolean(row.error) },
};

const VIEWS = ["library", "activity", "settings"];
const VIEW_TITLES = { library: "Biblioteca", activity: "Atividade", settings: "Preferências" };
const THEME_COLORS = { dark: "#161616", light: "#fafafa" };
const REDUCED_MOTION =
  typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : { matches: false };

const TONE_ICON = { success: "check", warning: "alert", danger: "alert", info: "activity" };

if (!dom.repoList || !dom.pathInput || !dom.status || !dom.pathError || !dom.themeColor) {
  throw new Error("RepoRefresh: interface não carregada");
}

/* ------------------------------------------------------------------ utils */
function storeGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function storeSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* modo privado */ }
}
function icon(name, size) {
  const attr = size ? ` data-size="${size}"` : "";
  return `<svg class="icon"${attr} aria-hidden="true"><use href="#i-${name}"></use></svg>`;
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
  const value = Number(bytes);
  // NaN, Infinity e negativo são indício de dado ruim na API: mostra "?"
  // em vez de vazar "NaN B" / "-5,0 B" para a tela.
  if (!Number.isFinite(value) || value < 0) return "?";
  const units = ["B", "KB", "MB", "GB"];
  let amount = value;
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  // Bytes são contagens inteiras: "0 B", não "0,0 B".
  const rendered = index === 0 || amount >= 100
    ? String(Math.round(amount))
    : amount.toFixed(1).replace(".", ",");
  return `${rendered} ${units[index]}`;
}
function formatSpeed(bytesPerSecond) {
  const size = formatSize(bytesPerSecond);
  return size === "?" ? "?" : `${size}/s`;
}
function looksLikePath(value) {
  return value.length > 1 && (value.startsWith("/") || value.startsWith("~"));
}

/* ------------------------------------------------------- estado de uma row */
function statusInfo(row) {
  if (row.error) return { tone: "danger", label: "Erro", detail: "Revisar atividade" };
  if (!row.mapped) return { tone: "neutral", label: "Sem dono", detail: "Mapear repositório" };
  if (row.behind === true && !row.local_sha) return { tone: "info", label: "Nunca sincronizado", detail: "Atualizar agora" };
  if (row.behind === true) return { tone: "warning", label: "Atualizar", detail: "Commit remoto" };
  if (row.behind === false) return { tone: "success", label: "Em dia", detail: "Commit verificado" };
  return { tone: "neutral", label: "Aguardando check", detail: "Comparar com GitHub" };
}

function initials(row) {
  const source = row.owner && row.repo ? `${row.owner}${row.repo}` : row.name || "R";
  return source.replace(/[^a-z0-9]/gi, "").slice(0, 2).toUpperCase() || "R";
}

/* Tag de estado. O tone vem SEMPRE de statusInfo — os dois ramos de renderRow
   usam este helper, para que "Erro" nunca saia na cor de "info". */
function statusTag(status) {
  const variant = status.tone === "neutral" ? "" : ` data-variant="${status.tone}"`;
  return `<span data-component="tag"${variant} title="${esc(status.detail)}">${esc(status.label)}</span>`;
}

function artifactLabel(row) {
  const values = [];
  if (row.local_dir) values.push("pasta");
  if (row.zip_path) values.push("ZIP");
  return values.length ? values.join(" + ") : "sem artefato";
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

/* ------------------------------------------------------------------ render */
function renderIdentityCell(row, rowIndex) {
  const remoteName = row.owner && row.repo ? `${row.owner}/${row.repo}` : row.github_url || "GitHub";
  const note = row.error
    ? `<span class="repo-note" data-tone="danger">${icon("alert", "small")} ${esc(row.error)}</span>`
    : row.mapped
      ? row.remote_message
        ? `<span class="repo-note">${icon("cloud", "small")} ${esc(row.remote_message)}</span>`
        : ""
      : row.suggested_repo
        ? `<span class="repo-note">${icon("spark", "small")} ${esc(row.suggested_repo)}</span>`
        : "";
  return `<div class="cell-stack">
      <div data-slot="data-table-identity">
        <span data-component="avatar-v2" data-size="normal" data-tone="gray">${esc(initials(row))}</span>
        <span data-slot="data-table-identity-copy">
          <span data-slot="data-table-identity-name">${esc(row.name)}</span>
          <span data-slot="data-table-identity-subtitle">${esc(remoteName)}</span>
        </span>
      </div>
      ${note}
    </div>`;
}

function renderMapForm(row, index) {
  const suggestions =
    row.suggestions && row.suggestions.length
      ? `<div class="map-suggestions">${row.suggestions
          .map(
            (suggestion, suggestionIndex) =>
              `<button class="map-suggestion" type="button" data-action="pick-suggestion" data-index="${index}" data-suggestion="${suggestionIndex}">
                <span class="map-suggestion__name">${esc(suggestion.full_name || suggestion.url || "GitHub")}</span>
                <span class="map-suggestion__stars">${esc(suggestion.stars ?? 0)} estrelas</span>
              </button>`
          )
          .join("")}</div>`
      : "";
  const tried =
    row.tried && row.tried.length
      ? `<span class="repo-note">${icon("search", "small")} ${esc(row.tried.join(" · "))}</span>`
      : "";
  return `<tr class="map-row" data-map-index="${index}"><td colspan="7">
      <div class="map-form">
        <label class="text-input-v2" data-component="text-input-v2" for="url-${index}">
          <span data-slot="text-input-v2-value">
            <input id="url-${index}" data-url-input="${index}" type="url" inputmode="url" autocomplete="off" spellcheck="false" placeholder="https://github.com/dono/repo…" aria-label="URL do GitHub para ${esc(row.name)}" data-slot="text-input-v2-input">
          </span>
        </label>
        <button class="button-v2" data-component="button-v2" data-variant="contrast" data-size="normal" type="button" data-action="save-map" data-index="${index}" data-icon>
          ${icon("check")}<span>Salvar</span>
        </button>
        <button class="button-v2" data-component="button-v2" data-variant="neutral" data-size="normal" type="button" data-action="suggest" data-index="${index}" data-icon>
          ${icon("spark")}<span>Sugerir</span>
        </button>
      </div>
      ${tried ? `<div class="map-suggestions">${tried}</div>` : ""}
      ${suggestions}
    </td></tr>`;
}

function renderRow(row, index) {
  const status = statusInfo(row);
  const branch = row.branch || "main";

  if (!row.mapped) {
    return `<tr data-row-index="${index}"${row.busy ? ' data-busy="true"' : ""}>
        <td>${renderIdentityCell(row, index)}</td>
        <td><span data-component="tag">—</span></td>
        <td>${esc(artifactLabel(row))}</td>
        <td><code>—</code></td>
        <td><code>—</code></td>
        <td>${statusTag(status)}</td>
        <td data-align="end"></td>
      </tr>${renderMapForm(row, index)}`;
  }

  const updating = state.confirmUpdate === row.name;
  const reverting = state.confirmRollback === row.name;
  const updateVariant = updating ? "warning" : row.behind === true ? "contrast" : "ghost";
  const updateTitle = updating
    ? "Clique de novo para confirmar a atualização"
    : row.behind === true
      ? "Atualizar para o commit remoto"
      : "Checar atualizações";

  const hint = updating
    ? '<p class="rollback-hint">Atualizar baixa o commit remoto e substitui o conteúdo local. Clique de novo para confirmar.</p>'
    : reverting
      ? '<p class="rollback-hint">Reverter troca o estado atual pelo backup. Clique de novo para confirmar.</p>'
      : "";

  return `<tr data-row-index="${index}"${row.busy ? ' data-busy="true"' : ""}>
      <td>${renderIdentityCell(row, index)}</td>
      <td>${row.auto ? `<span data-component="tag">${esc(branch)}</span>` : `<span data-component="tag" data-high-contrast>${esc(branch)}</span>`}</td>
      <td>${esc(artifactLabel(row))}</td>
      <td><code>${esc(shortSha(row.local_sha))}</code></td>
      <td><code>${esc(shortSha(row.remote_sha))}</code></td>
      <td>${statusTag(status)}</td>
      <td data-align="end">
        <div class="repo-actions">
          <button data-component="icon-button-v2" data-variant="ghost" data-size="normal" type="button" data-action="check-row" data-index="${index}" title="Checar atualizações" aria-label="Checar ${esc(row.name)}">${icon("refresh")}</button>
          <button data-component="icon-button-v2" data-variant="${updateVariant}" data-size="normal" type="button" data-action="update-row" data-index="${index}" title="${esc(updateTitle)}" aria-label="${updating ? "Confirmar atualização" : "Atualizar"} de ${esc(row.name)}">${icon("cloud")}</button>
          <button data-component="icon-button-v2" data-variant="ghost" data-size="normal" type="button" data-action="rollback-row" data-index="${index}"${row.can_rollback === false ? " disabled" : ""} title="${row.can_rollback === false ? "Sem backup disponível" : reverting ? "Clique de novo para confirmar a reversão" : "Reverter para o backup"}" aria-label="Reverter ${esc(row.name)}">${icon("back")}</button>
        </div>
        ${hint}
      </td>
    </tr>`;
}

function renderLoading() {
  const cells = Array.from({ length: 7 }, () => "<td><span data-component=\"skeleton\" data-shape=\"text\"></span></td>").join("");
  return Array.from({ length: 4 }, () => `<tr>${cells}</tr>`).join("");
}

function renderEmpty() {
  let body;
  if (!state.base) {
    body = `<div data-component="empty-state">
        <span data-slot="empty-state-icon">${icon("folder", "large")}</span>
        <p data-slot="empty-state-title">Escolha uma pasta para começar</p>
        <p data-slot="empty-state-body">O RepoRefresh procura pastas e ZIPs, detecta o repositório e mostra tudo aqui.</p>
        <div data-slot="empty-state-actions">
          <button class="button-v2" data-component="button-v2" data-variant="contrast" data-size="normal" type="button" data-action="focus-scan" data-icon>${icon("scan")}<span>Selecionar pasta</span></button>
        </div>
      </div>`;
  } else if (!state.rows.length) {
    body = `<div data-component="empty-state">
        <span data-slot="empty-state-icon">${icon("scan", "large")}</span>
        <p data-slot="empty-state-title">Nenhum repositório encontrado</p>
        <p data-slot="empty-state-body">Confira o caminho escolhido. A pasta pode estar vazia ou sem permissão de leitura.</p>
      </div>`;
  } else {
    body = `<div data-component="empty-state">
        <span data-slot="empty-state-icon">${icon("search", "large")}</span>
        <p data-slot="empty-state-title">Nenhum item neste filtro</p>
        <p data-slot="empty-state-body">Ajuste a busca ou escolha outro grupo para continuar.</p>
        <div data-slot="empty-state-actions">
          <button class="button-v2" data-component="button-v2" data-variant="neutral" data-size="normal" type="button" data-action="reset-filter" data-icon>${icon("x")}<span>Limpar filtro</span></button>
        </div>
      </div>`;
  }
  return `<tr class="empty-row"><td colspan="7">${body}</td></tr>`;
}

function focusedRepoAction() {
  const active = document.activeElement;
  if (!active || !dom.repoList.contains(active)) return null;
  if (active.dataset.action == null || active.dataset.index == null) return null;
  return { action: active.dataset.action, index: active.dataset.index };
}

function restoreRepoFocus(focus) {
  if (!focus) return;
  const target = dom.repoList.querySelector(`[data-action="${focus.action}"][data-index="${focus.index}"]`);
  if (target) target.focus({ preventScroll: true });
}

function render() {
  const focus = focusedRepoAction();
  const rows = visibleRows();
  const counts = countRows();
  const order = new Map();
  state.rows.forEach((row, rowIndex) => {
    if (!order.has(row)) order.set(row, rowIndex);
  });

  dom.count.textContent = `${rows.length} de ${state.rows.length}`;
  dom.pathCaption.textContent = state.base || "Nenhuma pasta";
  if (dom.search.value !== state.query) dom.search.value = state.query;

  dom.filters.querySelectorAll("[data-filter]").forEach((button) => {
    const active = button.dataset.filter === state.filter;
    button.toggleAttribute("data-pressed", active);
    button.setAttribute("aria-checked", active ? "true" : "false");
  });

  let html;
  if (state.busy && !state.rows.length && state.scanning) {
    html = renderLoading();
  } else if (rows.length) {
    html = rows.map((row) => renderRow(row, order.get(row) ?? -1)).join("");
  } else {
    html = renderEmpty();
  }

  dom.repoList.innerHTML = html;
  restoreRepoFocus(focus);

  dom.btnAll.disabled = state.busy || !state.base || counts.behind === 0;
}

/* ------------------------------------------------------------------ theme */
function applyTheme(theme, persist = true) {
  state.theme = theme === "light" ? "light" : "dark";
  dom.root.dataset.colorScheme = state.theme;
  dom.themeColor.setAttribute("content", THEME_COLORS[state.theme]);
  dom.themeLabel.textContent = state.theme === "dark" ? "Escuro" : "Claro";
  dom.themeIcon.setAttribute("href", state.theme === "dark" ? "#i-moon" : "#i-sun");
  if (persist) storeSet("alldown.theme", state.theme);
}

/* ------------------------------------------------------------- hash router */
function parseHashState() {
  const raw = String(location.hash || "").replace(/^#\/?/, "");
  if (!raw) return {};
  const [viewPart, queryPart] = raw.split("?");
  const params = new URLSearchParams(queryPart || "");
  const view = VIEWS.includes(viewPart) ? viewPart : null;
  const filterParam = params.get("filter");
  const filter = filterParam && FILTER_INFO[filterParam] ? filterParam : null;
  return { view, filter, query: params.get("q") };
}

function writeHashState() {
  const params = new URLSearchParams();
  if (state.filter !== "all") params.set("filter", state.filter);
  if (state.query) params.set("q", state.query);
  const query = params.toString();
  const next = `#/${state.view}${query ? `?${query}` : ""}`;
  if (location.hash !== next) history.replaceState(null, "", next);
}

function setView(view, options = {}) {
  if (!VIEWS.includes(view)) return;
  state.view = view;
  dom.libraryView.hidden = view !== "library";
  dom.activityView.hidden = view !== "activity";
  dom.settingsView.hidden = view !== "settings";
  document.querySelectorAll("[data-view]").forEach((item) => {
    if (!item.classList.contains("nav-item")) return;
    const active = item.dataset.view === view;
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  dom.viewTitle.textContent = VIEW_TITLES[view] || "Biblioteca";
  closeSidebar();
  dom.main.scrollTo({ top: 0, behavior: REDUCED_MOTION.matches ? "auto" : "smooth" });
  if (options.write !== false) writeHashState();
}

function setFilter(filter, options = {}) {
  if (!FILTER_INFO[filter]) return;
  state.filter = filter;
  storeSet("alldown.filter", state.filter);
  render();
  if (options.write !== false) writeHashState();
}

function applyHashState() {
  const parsed = parseHashState();
  let changed = false;
  if (parsed.view && parsed.view !== state.view) {
    state.view = parsed.view;
    changed = true;
  }
  if (parsed.filter && parsed.filter !== state.filter) {
    state.filter = parsed.filter;
    storeSet("alldown.filter", state.filter);
    changed = true;
  }
  if (parsed.query != null && parsed.query !== state.query) {
    state.query = parsed.query;
    storeSet("alldown.query", state.query);
    changed = true;
  }
  if (changed) {
    setView(state.view, { write: false });
    render();
  }
}

/* ------------------------------------------------------------------ status */
function setPathError(message) {
  dom.pathError.textContent = message;
  dom.pathError.hidden = false;
  dom.pathInput.setAttribute("aria-invalid", "true");
  dom.pathInput.closest("[data-component=text-input-v2]").setAttribute("data-invalid", "");
}

function clearPathError() {
  dom.pathError.textContent = "";
  dom.pathError.hidden = true;
  dom.pathInput.removeAttribute("aria-invalid");
  dom.pathInput.closest("[data-component=text-input-v2]").removeAttribute("data-invalid");
}

function say(message, tone = "info", showToast = false) {
  dom.status.dataset.tone = tone;
  dom.statusText.textContent = message;
  dom.statusIcon.setAttribute("href", `#i-${TONE_ICON[tone] || "check"}`);
  if (showToast) toast(message, tone);
}

function toast(message, tone = "info") {
  const item = document.createElement("div");
  item.setAttribute("data-component", "toast-v2");
  item.setAttribute("data-tone", tone);
  item.innerHTML = `
    <div data-slot="toast-v2-header">
      <span data-slot="toast-v2-icon">${icon(TONE_ICON[tone] || "check")}</span>
      <div data-slot="toast-v2-content">
        <p data-slot="toast-v2-title">${esc(message.length > 90 ? `${message.slice(0, 88)}…` : message)}</p>
      </div>
    </div>
    <button data-component="icon-button-v2" data-variant="ghost-muted" data-size="small" type="button" data-slot="toast-v2-close" aria-label="Fechar notificação">${icon("x", "small")}</button>`;

  const dismiss = () => {
    item.setAttribute("data-state", "closed");
    window.setTimeout(() => item.remove(), REDUCED_MOTION.matches ? 0 : 140);
  };

  item.querySelector("[data-slot=toast-v2-close]").addEventListener("click", dismiss);
  dom.toastRegion.appendChild(item);
  while (dom.toastRegion.children.length > 4) dom.toastRegion.firstElementChild.remove();
  window.setTimeout(dismiss, 4600);
}

function setBusy(value) {
  state.busy = value;
  dom.btnScan.disabled = value;
  dom.btnCheck.disabled = value || !state.base;
  setVariant(dom.btnAll, value || !state.base || state.rows.every((row) => row.behind !== true) ? "neutral" : "contrast");
  dom.syncDot.dataset.tone = value ? "busy" : "ok";
  dom.syncLabel.textContent = value ? "processando" : "pronto";
  dom.statusProgress.hidden = !value;
  // O render precisa acompanhar a virada de busy: sem isso nao aparece o
  // esqueleto durante a espera da rede (/api/scan tem timeout de 900 s) e,
  // pior, um scan que volte vazio deixa a tabela presa no skeleton.
  render();
}

/* Troca data-variant preservando os outros atributos do botão. */
function setVariant(element, variant) {
  if (element.dataset.variant !== variant) element.dataset.variant = variant;
}

/* -------------------------------------------------------------------- api */

/* Erro tipado. `code` faz parte do contrato entre a camada de rede e quem
   chama: é o que permite distinguir "recusa definitiva" de "não deu para
   saber", que em um app que apaga diretório não é a mesma coisa.
     TIMEOUT — o cliente desistiu, mas o servidor pode ter concluído
     NETWORK — servidor fora do ar; estado no disco é desconhecido
     HTTP    — o servidor respondeu e recusou; nada foi feito
*/
class ApiError extends Error {
  constructor(message, code, status = 0) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }

  /* Indeterminado = não sabemos o que aconteceu no disco. Numa operação
     destrutiva, tratar isso como falha mente para o usuário. */
  get indeterminate() {
    return this.code === "TIMEOUT" || this.code === "NETWORK";
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
      throw new ApiError(
        typeof detail === "string" ? detail : `HTTP ${response.status}`,
        "HTTP",
        response.status
      );
    }
    return payload;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error && error.name === "AbortError") throw new ApiError("Tempo esgotado", "TIMEOUT");
    throw new ApiError(`Servidor local não respondeu: ${error.message}`, "NETWORK");
  } finally {
    if (timer) window.clearTimeout(timer);
  }
}

/* Reconsulta o GitHub para descobrir o que de fato aconteceu depois de um
   erro indeterminado. Devolve "desconhecido" quando nem a reconsulta
   responde — aí, e só aí, cabe dizer que não se sabe. */
async function settleByRecheck(name) {
  try {
    const result = await api(`/api/check?path=${encodeURIComponent(state.base)}`, {}, 60000);
    const found = (result.items || []).find((entry) => entry.name === name);
    if (!found) return { known: false };
    if (found.error) return { known: true, done: false, reason: found.error };
    if (found.behind === false) return { known: true, done: true };
    if (found.behind === true) return { known: true, done: false, reason: "o commit remoto ainda não é o local" };
    return { known: false };
  } catch {
    return { known: false };
  }
}

async function refreshToken() {
  const dot = dom.tokenDot;
  const fail = (title, detail) => {
    dot.dataset.tone = "error";
    dom.tokenTitle.textContent = title;
    dom.tokenDetail.textContent = detail;
  };
  try {
    const result = await api("/api/token", {}, 8000);
    if (result.rate_limited) {
      dot.dataset.tone = "warn";
      dom.tokenTitle.textContent = "Limite da API";
      dom.tokenDetail.textContent = "aguardando reset";
    } else if (result.valid === false) {
      fail("Token inválido", "verificar GITHUB_TOKEN");
    } else if (result.configured && result.valid) {
      dot.dataset.tone = "ok";
      dom.tokenTitle.textContent = "GitHub conectado";
      dom.tokenDetail.textContent = `${result.remaining ?? "?"}/${result.limit ?? "?"} requests`;
    } else if (result.configured && result.valid === null) {
      dot.dataset.tone = "warn";
      dom.tokenTitle.textContent = "Status desconhecido";
      dom.tokenDetail.textContent = "aguardando GitHub";
    } else {
      dot.dataset.tone = "warn";
      dom.tokenTitle.textContent = "Modo sem token";
      dom.tokenDetail.textContent = result.limit ? `${result.remaining}/${result.limit} requests` : "60 requests/hora";
    }
  } catch {
    fail("API offline", "servidor local indisponível");
  }
}

async function refreshLog() {
  try {
    const result = await api("/api/log", {}, 10000);
    dom.log.textContent = `${(result.lines || []).join("\n")}\n`;
    dom.log.parentElement.scrollTop = dom.log.parentElement.scrollHeight;
  } catch {
    /* o log é best-effort */
  }
}

async function doScan(options = {}) {
  const path = options.path || dom.pathInput.value.trim();
  if (!path) {
    setPathError("Informe a pasta de repositórios.");
    say("Informe a pasta de repositórios.", "warning", true);
    dom.pathInput.focus();
    return;
  }
  if (state.busy && options.allowBusy !== true) return;
  state.scanning = true;
  state.confirmRollback = null;
  state.confirmUpdate = null;
  storeSet("alldown.path", path);
  setBusy(true);
  say("Escaneando pasta…", "info");
  try {
    const result = await api(`/api/scan?path=${encodeURIComponent(path)}`, {}, 900000);
    state.base = result.path || path;
    state.rows = result.items || [];
    state.zipOnly = Boolean(result.zip_only);
    state.backup = result.backup !== false;
    state.lastScanFailed = false;
    clearPathError();
    paintSwitches();
    render();
    const mapped = state.rows.filter((row) => row.mapped).length;
    if (!state.rows.length) say("Pasta vazia: nenhum repositório encontrado.", "warning");
    else if (!mapped) say(`${state.rows.length} itens detectados; nenhum vínculo GitHub ainda.`, "warning");
    else say(`${mapped} de ${state.rows.length} repositórios prontos para checagem.`, "success", true);
    if (state.auto && mapped) await doCheck(true);
  } catch (error) {
    state.lastScanFailed = true;
    // A falha não pode pisar no que o usuário já digitou depois desta tentativa.
    if (dom.pathInput.value.trim() === path) {
      dom.pathInput.value = state.base || "";
      storeSet("alldown.path", state.base || "");
      dom.pathInput.focus();
    }
    setPathError(`Falha no scan: ${error.message}`);
    say(`Falha no scan: ${error.message}`, "danger", true);
  } finally {
    state.scanning = false;
    setBusy(false);
    refreshLog();
  }
}

async function doCheck(fromScan = false) {
  if (!state.base) {
    say("Selecione uma pasta primeiro.", "warning", true);
    return;
  }
  if (state.busy && !fromScan) return;
  state.confirmRollback = null;
  state.confirmUpdate = null;
  if (!fromScan) setBusy(true);
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
    if (errors) say(`Check concluído com ${errors} ${errors === 1 ? "erro" : "erros"}.`, "warning", true);
    else if (updates) say(`Check concluído: ${updates} ${updates === 1 ? "atualização disponível" : "atualizações disponíveis"}.`, "warning", true);
    else say("Check concluído: nada pendente.", "success", true);
  } catch (error) {
    say(`Falha no check: ${error.message}`, "danger", true);
  } finally {
    if (!fromScan) setBusy(false);
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
    // Tempo esgotado não é sinônimo de fracasso: o servidor pode ter
    // concluído a troca depois de o cliente desistir. Reconsulta antes de
    // dizer que falhou.
    if (error instanceof ApiError && error.indeterminate) {
      const verdict = await settleByRecheck(name);
      if (verdict.known && verdict.done) {
        row.local_sha = row.remote_sha;
        row.behind = false;
        row.error = null;
        render();
        say(`${name} foi atualizado, mas a resposta se perdeu. O estado em disco confere.`, "success", true);
        return true;
      }
      if (verdict.known) {
        row.error = verdict.reason;
        render();
        say(`Falha em ${name}: ${verdict.reason}`, "danger", true);
        return false;
      }
      row.error = error.message;
      render();
      say(
        `${name}: deu tempo esgotado e não deu para confirmar o estado. Reexecute o check antes de tentar de novo.`,
        "warning",
        true
      );
      return false;
    }
    row.error = error.message;
    say(`Falha em ${name}: ${error.message}`, "danger", true);
    return false;
  } finally {
    row.busy = false;
    render();
    if (!quiet) {
      setBusy(false);
      refreshLog();
    }
  }
}

async function doRollback(name) {
  if (state.busy) return;
  const row = state.rows.find((item) => item.name === name);
  if (!row) return;
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
    say(`Falha ao reverter: ${error.message}`, "danger", true);
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
  const clean = String(url || "").trim();
  if (!row || !clean) {
    say("Informe uma URL do GitHub.", "warning", true);
    return;
  }
  setBusy(true);
  try {
    await api("/api/map", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.base, name: row.name, url: clean }),
    }, 90000);
    row.suggestions = null;
    row.error = null;
    say(`${row.name} mapeado. Atualizando biblioteca…`, "success", true);
    await doScan({ allowBusy: true, path: state.base });
  } catch (error) {
    say(`Falha ao mapear: ${error.message}`, "danger", true);
  } finally {
    setBusy(false);
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
    say(
      row.suggestions.length ? `${row.suggestions.length} sugestões encontradas.` : "Nenhuma sugestão encontrada.",
      row.suggestions.length ? "success" : "warning",
      true
    );
  } catch (error) {
    say(`Falha ao buscar sugestões: ${error.message}`, "danger", true);
  }
}

async function updateAll() {
  const rows = visibleRows().filter((row) => row.mapped && row.behind === true);
  if (!rows.length) {
    say("Nenhuma atualização disponível nesta lista.", "info", true);
    return;
  }
  state.confirmRollback = null;
  setBusy(true);
  let succeeded = 0;
  let failed = 0;
  for (const row of rows) {
    const ok = await doUpdate(row.name, true);
    if (ok) succeeded += 1;
    else failed += 1;
  }
  setBusy(false);
  say(
    failed ? `${succeeded} atualizados, ${failed} com falha.` : `${succeeded} repositórios atualizados.`,
    failed ? "warning" : "success",
    true
  );
  refreshLog();
}

/* --------------------------------------------------------------- switches */
function paintSwitches() {
  const paint = (button, label, on, onText, offText) => {
    button.toggleAttribute("data-checked", on);
    button.setAttribute("aria-checked", on ? "true" : "false");
    label.textContent = on ? onText : offText;
  };
  paint(dom.btnAuto, dom.labelAuto, state.auto, "Ativa", "Pausada");
  paint(dom.btnMode, dom.labelMode, state.zipOnly, "Só ZIP", "Pastas");
  paint(dom.btnBackup, dom.labelBackup, state.backup, "Ativo", "Desligado");
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
    paintSwitches();
    render();
    await doScan({ allowBusy: true, path: state.base });
  } catch (error) {
    say(`Não foi possível alterar a preferência: ${error.message}`, "danger", true);
  } finally {
    setBusy(false);
    refreshLog();
  }
}

/* ---------------------------------------------------------------- sidebar */
function syncSidebarAccessibility() {
  const mobile = window.matchMedia ? window.matchMedia("(max-width: 767px)").matches : false;
  const open = dom.sidebar.dataset.open === "true";
  dom.sidebar.inert = Boolean(mobile && !open);
  dom.sidebar.setAttribute("aria-hidden", mobile && !open ? "true" : "false");
}

function toggleSidebar() {
  const open = dom.sidebar.dataset.open !== "true";
  dom.sidebar.dataset.open = open ? "true" : "false";
  dom.scrim.dataset.visible = open ? "true" : "false";
  const menu = document.querySelector(".topbar__menu");
  menu?.setAttribute("aria-expanded", open ? "true" : "false");
  menu?.setAttribute("aria-label", open ? "Fechar menu" : "Abrir menu");
  syncSidebarAccessibility();
}

function closeSidebar() {
  if (dom.sidebar.dataset.open !== "true") return;
  dom.sidebar.dataset.open = "false";
  dom.scrim.dataset.visible = "false";
  const menu = document.querySelector(".topbar__menu");
  menu?.setAttribute("aria-expanded", "false");
  menu?.setAttribute("aria-label", "Abrir menu");
  syncSidebarAccessibility();
}

function focusScan() {
  setView("library");
  window.setTimeout(() => dom.pathInput.focus(), 40);
}

/* ------------------------------------------------------------ scroll thumb */
function initScrollThumb() {
  const viewport = dom.main.querySelector("[data-slot=scroll-view-viewport]");
  const thumb = dom.pageThumb;
  if (!viewport || !thumb) return;

  const sync = () => {
    const { scrollTop, scrollHeight, clientHeight } = viewport;
    const scrollable = scrollHeight - clientHeight;
    if (scrollable <= 2) {
      thumb.dataset.visible = "false";
      thumb.style.height = "0px";
      return;
    }
    const ratio = clientHeight / scrollHeight;
    const height = Math.max(24, Math.round(clientHeight * ratio));
    const offset = Math.round((scrollTop / scrollable) * (clientHeight - height));
    thumb.dataset.visible = "true";
    thumb.style.height = `${height}px`;
    thumb.style.transform = `translateY(${offset}px)`;
  };

  viewport.addEventListener("scroll", sync, { passive: true });
  new ResizeObserver(sync).observe(viewport);
  new MutationObserver(sync).observe(viewport, { childList: true, subtree: true });
  sync();
}

/* ------------------------------------------------------------------ ações */
const BUSY_ACTIONS = new Set(["check-row", "update-row", "rollback-row", "save-map", "suggest", "pick-suggestion", "refresh", "refresh-log"]);

function handleAction(action, element) {
  const index = Number(element.dataset.index);
  if (state.busy && BUSY_ACTIONS.has(action)) return;
  if (action !== "update-row" && state.confirmUpdate) {
    state.confirmUpdate = null;
    render();
  }

  if (action === "toggle-sidebar") toggleSidebar();
  if (action === "close-sidebar") closeSidebar();
  if (action === "toggle-theme") applyTheme(state.theme === "dark" ? "light" : "dark");
  if (action === "focus-scan") focusScan();
  if (action === "refresh-token") refreshToken();
  if (action === "refresh-log") refreshLog();
  if (action === "reset-filter") {
    state.filter = "all";
    state.query = "";
    storeSet("alldown.filter", "all");
    storeSet("alldown.query", "");
    render();
    writeHashState();
  }
  if (action === "refresh" || action === "check-row") {
    if (state.base) doCheck();
    else focusScan();
  }
  if (action === "update-row") {
    const row = state.rows[index];
    if (row?.behind === true) {
      if (state.confirmUpdate !== row.name) {
        state.confirmUpdate = row.name;
        state.confirmRollback = null;
        render();
        say(`Confirme a atualização de ${row.name}: clique no botão de novo.`, "warning", true);
        return;
      }
      state.confirmUpdate = null;
      doUpdate(row.name);
    } else {
      doCheck();
    }
  }
  if (action === "rollback-row") {
    const name = state.rows[index]?.name;
    if (!name) return;
    if (state.confirmRollback !== name) {
      state.confirmRollback = name;
      state.confirmUpdate = null;
      render();
      say(`Confirme a reversão de ${name}: clique no botão de novo.`, "warning", true);
      return;
    }
    state.confirmRollback = null;
    doRollback(name);
  }
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

/* -------------------------------------------------------------------- init */
function init() {
  state.query = storeGet("alldown.query") || "";
  const storedFilter = storeGet("alldown.filter");
  if (FILTER_INFO[storedFilter]) state.filter = storedFilter;
  const initialHash = parseHashState();
  if (initialHash.view) state.view = initialHash.view;
  if (initialHash.filter) state.filter = initialHash.filter;
  if (initialHash.query != null) state.query = initialHash.query;

  applyTheme(storeGet("alldown.theme") || dom.root.dataset.colorScheme || "dark", false);
  state.auto = storeGet("alldown.auto") !== "0";
  dom.pathInput.value = storeGet("alldown.path") || "";

  paintSwitches();
  render();
  setBusy(false);
  setView(state.view);
  syncSidebarAccessibility();
  initScrollThumb();
  refreshToken();
  refreshLog();

  let logTimer = null;
  function scheduleLogRefresh() {
    if (logTimer) clearTimeout(logTimer);
    logTimer = setTimeout(() => {
      const active = document.visibilityState === "visible" && state.view === "activity";
      (active ? refreshLog() : Promise.resolve()).finally(scheduleLogRefresh);
    }, 8000);
  }
  scheduleLogRefresh();

  if (state.auto && looksLikePath(dom.pathInput.value.trim())) window.setTimeout(doScan, 120);
}

$("form-path").addEventListener("submit", (event) => {
  event.preventDefault();
  window.clearTimeout(state.pathTimer);
  doScan();
});

let searchTimer = null;
dom.search.addEventListener("input", (event) => {
  state.query = event.target.value;
  storeSet("alldown.query", state.query);
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    render();
    writeHashState();
  }, 150);
});

dom.filters.addEventListener("click", (event) => {
  const button = event.target.closest("[data-filter]");
  if (button) setFilter(button.dataset.filter);
});

dom.filters.addEventListener("keydown", (event) => {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  const buttons = Array.from(dom.filters.querySelectorAll("[data-filter]"));
  const current = buttons.indexOf(document.activeElement);
  if (current === -1) return;
  event.preventDefault();
  const next = (current + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
  buttons[next].focus();
  setFilter(buttons[next].dataset.filter);
});

dom.btnCheck.addEventListener("click", () => doCheck());
dom.btnAll.addEventListener("click", updateAll);

dom.btnAuto.addEventListener("click", () => {
  state.auto = !state.auto;
  storeSet("alldown.auto", state.auto ? "1" : "0");
  paintSwitches();
  say(state.auto ? "Detecção automática ativada." : "Detecção automática pausada.", "info", true);
  const value = dom.pathInput.value.trim();
  if (state.auto && looksLikePath(value) && value !== state.base) doScan();
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
  clearPathError();
  const value = dom.pathInput.value.trim();
  if (!state.auto || !looksLikePath(value)) return;
  if (value === state.base && !state.lastScanFailed) return;
  window.clearTimeout(state.pathTimer);
  state.pathTimer = window.setTimeout(doScan, 700);
});

dom.pathInput.addEventListener("blur", () => {
  const value = dom.pathInput.value.trim();
  if (!value || looksLikePath(value)) return;
  setPathError("O caminho deve começar com / ou ~");
  say("Caminho inválido: deve começar com / ou ~", "warning", true);
});

dom.repoList.addEventListener("click", (event) => {
  const element = event.target.closest("[data-action]");
  if (!element) return;
  event.stopPropagation();
  handleAction(element.dataset.action, element);
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
window.addEventListener("hashchange", applyHashState);

document.querySelector(".skip-link")?.addEventListener("click", (event) => {
  event.preventDefault();
  const viewport = dom.main.querySelector("[data-slot=scroll-view-viewport]");
  viewport?.scrollTo({ top: 0 });
  dom.main.focus({ preventScroll: true });
});
window.addEventListener("beforeunload", (event) => {
  const dirty = Array.from(dom.repoList.querySelectorAll("[data-url-input]")).some(
    (input) => String(input.value || "").trim() !== ""
  );
  if (dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (state.confirmRollback || state.confirmUpdate) {
      state.confirmRollback = null;
      state.confirmUpdate = null;
      render();
      say("Ação cancelada.", "info");
    }
    closeSidebar();
    return;
  }
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  const tag = event.target?.tagName || "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  const key = event.key.toLowerCase();
  if (key === "e") {
    event.preventDefault();
    doScan();
  }
  if (key === "c") {
    event.preventDefault();
    doCheck();
  }
});

init();

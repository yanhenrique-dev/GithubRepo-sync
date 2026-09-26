/* Journeys cobertas:
   J1 — "quero o estado real de cada repositório na tabela, inclusive quando um
        item sem dono também tem erro" (cor do tag tem de acompanhar o estado)
   J3 — "quero ver que algo está acontecendo enquanto o scan roda, para não
        concluir que a página travou" (o /api/scan tem timeout de 900 s)

   Contrato testado: funções `function` de static/app.js via contexto vm. */
import test from "node:test";
import assert from "node:assert/strict";
import { loadApp, item } from "./load-app.mjs";

/* ------------------------------------------------------------------ RED */
test("J1: item sem dono QUE TAMBÉM tem erro mostra o tag em danger, não info", () => {
  const { sandbox: s } = loadApp({});
  const row = item({ mapped: false, owner: null, repo: null, github_url: null, error: "Falha ao ler" });

  // o que o statusInfo decide
  assert.equal(s.statusInfo(row).tone, "danger", "premissa: statusInfo classifica como danger");

  // o que o render efetivamente emite na coluna Estado
  const html = s.renderRow(row, 0);
  const stateTag = html.match(/<td><span data-component="tag"[^>]*>[^<]*<\/span><\/td>/);
  assert.ok(stateTag, `tag de estado não encontrado em:\n${html}`);
  assert.match(
    stateTag[0],
    /data-variant="danger"/,
    `tag de erro saiu na cor errada:\n${stateTag[0]}`
  );
  assert.match(stateTag[0], />Erro</, "o rótulo deve continuar sendo 'Erro'");
});

test("J3: o esqueleto de loading aparece enquanto o scan está em andamento", () => {
  const scan = { path: "/base", items: [], zip_only: false, backup: true };
  const { repoList, runTimersSync } = loadApp({ scan, path: "/base", autoScan: true });

  runTimersSync(); // dispara doScan; o fetch ainda não assentou

  assert.match(
    repoList.innerHTML,
    /data-component="skeleton"/,
    `nenhum esqueleto renderizado durante o scan:\n${repoList.innerHTML.slice(0, 200)}`
  );
});

/* ------------------------------------------- GREEN desde o inicio (caracterização) */
test("J1: statusInfo respeita a precedência erro > sem dono > behind > em dia", () => {
  const { sandbox: s } = loadApp({});
  const cases = [
    [item({ error: "boom" }), "danger", "Erro"],
    [item({ error: "boom", mapped: false, owner: null, repo: null }), "danger", "Erro"],
    [item({ mapped: false, owner: null, repo: null, github_url: null }), "neutral", "Sem dono"],
    [item({ behind: true, local_sha: null }), "info", "Nunca sincronizado"],
    [item({ behind: true }), "warning", "Atualizar"],
    [item({ behind: false }), "success", "Em dia"],
    [item({ behind: null }), "neutral", "Aguardando check"],
  ];
  for (const [row, tone, label] of cases) {
    assert.equal(s.statusInfo(row).tone, tone, `tone para ${label}`);
    assert.equal(s.statusInfo(row).label, label);
  }
});

test("item mapeado: coluna Estado usa a cor que o statusInfo pediu", () => {
  const { sandbox: s } = loadApp({});
  const html = s.renderRow(item({ behind: true }), 0);
  assert.match(html, /data-variant="warning"[^>]*>Atualizar</);
});

test("item sem dono: expõe o formulário de mapeamento logo abaixo da linha", () => {
  const { sandbox: s } = loadApp({});
  const row = item({ mapped: false, owner: null, repo: null, github_url: null, zip_path: null, local_dir: "/base/x" });
  const html = s.renderRow(row, 0);
  assert.match(html, /class="map-row"/, "faltou a linha de mapeamento");
  assert.match(html, /data-url-input="0"/, "faltou o campo de URL");
  assert.match(html, /data-action="save-map"/);
  assert.match(html, /data-action="suggest"/);
});

test("sem backup disponível, o botão de reverter sai desabilitado", () => {
  const { sandbox: s } = loadApp({});
  const html = s.renderRow(item({ can_rollback: false }), 0);
  const rollback = html.match(/<button[^>]*data-action="rollback-row"[^>]*>/);
  assert.ok(rollback);
  assert.match(rollback[0], /\sdisabled/, "botão de reverter deveria estar desabilitado");
});

test("com backup disponível, o botão de reverter fica habilitado", () => {
  const { sandbox: s } = loadApp({});
  const html = s.renderRow(item({ can_rollback: true }), 0);
  const rollback = html.match(/<button[^>]*data-action="rollback-row"[^>]*>/);
  assert.ok(rollback);
  assert.doesNotMatch(rollback[0], /\sdisabled/);
});

test("SHA aparece abreviado em 7 caracteres e travão quando falta", () => {
  const { sandbox: s } = loadApp({});
  const html = s.renderRow(item({ local_sha: "0123456789abcdef", remote_sha: null }), 0);
  assert.match(html, /<code>0123456<\/code>/);
  assert.match(html, /<code>—<\/code>/, "SHA remoto ausente deve virar travão");
});

test("branch fixada no mapeamento recebe tag de alto contraste", () => {
  const { sandbox: s } = loadApp({});
  assert.match(s.renderRow(item({ auto: false }), 0), /data-high-contrast>main</);
  assert.match(s.renderRow(item({ auto: true }), 0), /<span data-component="tag">main<\/span>/);
});

/* ------------------------------------------------------------- escaping */
test("nomes de repositório hostis não escapam do HTML", () => {
  const { sandbox: s } = loadApp({});
  const nasty = '<img src=x onerror=alert(1)>';
  const html = s.renderRow(item({ name: nasty }), 0);

  assert.doesNotMatch(html, /<img/, "tag inerte vazou para o HTML");
  assert.match(html, /&lt;img/, "o payload deveria estar escapado como texto");
  // nenhum atributo pode conter < ou > cru
  for (const m of html.matchAll(/="([^"]*)"/g)) {
    assert.ok(!/[<>]/.test(m[1]), `valor de atributo com marcação crua: ${m[1]}`);
  }
});

test("branch e nome com aspas não quebram os atributos", () => {
  const { sandbox: s } = loadApp({});
  const html = s.renderRow(item({ name: 'a"b', branch: 'c"d', branch_explicit: true }), 0);
  for (const m of html.matchAll(/="([^"]*)"/g)) {
    assert.ok(!/[<>]/.test(m[1]), `valor de atributo com marcação crua: ${m[1]}`);
  }
  assert.match(html, /&quot;/);
});

/* --------------------------------------------------------- empty states */
test("sem pasta escolhida, o empty state oferece escolher a pasta", () => {
  const { sandbox: s } = loadApp({});
  const html = s.renderEmpty();
  assert.match(html, /Escolha uma pasta para começar/);
  assert.match(html, /data-action="focus-scan"/);
});

test("pasta escolhida mas sem itens, o empty state explica o motivo", async () => {
  // renderEmpty() lê state.base, que é const e não pode ser setado de fora.
  // Então dirigimos o caminho real: doScan com lista vazia.
  const scan = { path: "/base", items: [], zip_only: false, backup: true };
  const { repoList, settle } = loadApp({ scan, path: "/base", autoScan: true });
  await settle();

  assert.match(repoList.innerHTML, /Nenhum repositório encontrado/);
  assert.doesNotMatch(repoList.innerHTML, /Escolha uma pasta/);
});

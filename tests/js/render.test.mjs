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
  // ancora pelo conteúdo, não por posição: a célula de branch também é um tag
  const erroTag = html.match(/<span data-component="tag"[^>]*>Erro<\/span>/);
  assert.ok(erroTag, `tag "Erro" não encontrado em:\n${html}`);
  assert.match(
    erroTag[0],
    /data-variant="danger"/,
    `tag de erro saiu na cor errada:\n${erroTag[0]}`
  );
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

/* --------------------------------------------- rascunho sobrevive ao re-render */
/** payload de scan com uma linha sem dono, que e quem recebe o formulario de mapear */
function scanComSemDono(nomes = ["aaa", "bbb"]) {
  return {
    path: "/base",
    items: nomes.map((n) =>
      item({ name: n, mapped: false, owner: null, repo: null, github_url: null })
    ),
    zip_only: false,
    backup: true,
  };
}

test("o que foi digitado no formulário de mapeamento sobrevive ao re-render", async () => {
  const { sandbox: s, repoList, settle } = loadApp({
    scan: scanComSemDono(["aaa"]),
    path: "/base",
    autoScan: true,
  });
  await settle();

  const input = repoList.__inputs[0];
  assert.ok(input, `premissa: o scan sem dono tem que renderizar o formulário:\n${repoList.innerHTML.slice(0, 300)}`);

  // o usuário digita a URL e continua com o cursor no meio dela
  const digitado = "https://github.com/acme/widget";
  input.value = digitado;
  input.selectionStart = 7;
  input.selectionEnd = 7;
  s.document.activeElement = input;

  s.render(); // qualquer evento dispara isto: busca, filtro, setBusy, update

  const depois = repoList.__inputs[0];
  assert.equal(depois.value, digitado, "o texto digitado foi apagado pelo re-render");
  assert.equal(depois.focused, 1, "o foco não voltou para o input");
  assert.equal(depois.selectionStart, 7, "o cursor não voltou ao lugar");
  assert.equal(depois.selectionEnd, 7);
});

test("o rascunho acompanha a LINHA, não a posição", async () => {
  // Se o rascunho fosse chaveado pelo índice, digitar em "aaa" e depois filtrar
  // para "bbb" jogaria a URL na linha errada — o pior tipo de bug aqui, porque
  // "Salvar" gravaria o repositório na pessoa errada.
  const { sandbox: s, repoList, settle } = loadApp({
    scan: scanComSemDono(["aaa", "bbb"]),
    path: "/base",
    autoScan: true,
  });
  await settle();

  const primeiro = repoList.__inputs.find((el) => el.label === "aaa");
  assert.ok(primeiro, `premissa: as duas linhas têm formulário:\n${repoList.innerHTML.slice(0, 300)}`);
  primeiro.value = "https://github.com/acme/aaa";
  s.document.activeElement = primeiro;

  s.setFilter("all"); // força re-render com as duas linhas visíveis

  const deNovo = repoList.__inputs;
  assert.equal(deNovo.find((el) => el.label === "aaa").value, "https://github.com/acme/aaa");
  assert.equal(deNovo.find((el) => el.label === "bbb").value, "", "o rascunho vazou para a linha errada");
});

test("re-render repetido não duplica nem degrada o rascunho", async () => {
  const { sandbox: s, repoList, settle } = loadApp({
    scan: scanComSemDono(["aaa"]),
    path: "/base",
    autoScan: true,
  });
  await settle();
  repoList.__inputs[0].value = "https://github.com/acme/widget";

  for (let i = 0; i < 5; i++) s.render();

  assert.equal(repoList.__inputs.length, 1, "o re-render duplicou inputs");
  assert.equal(repoList.__inputs[0].value, "https://github.com/acme/widget");
});

/* ------------------------------------------- o lote nao reconstroi a tabela toda */
/** scan + check de N repos pendentes: e o unico jeito de `behind` ser true
 *  (o ScannedItem do contrato nao tem `behind` — so o CheckItem tem). */
function cenarioLote(n = 4) {
  const nomes = Array.from({ length: n }, (_, i) => `repo${i}`);
  return {
    scan: {
      path: "/base",
      items: nomes.map((name) => item({ name, local_sha: "1111111", remote_sha: "2222222" })),
      zip_only: false,
      backup: true,
    },
    check: nomes.map((name) =>
      item({ name, behind: true, local_sha: "1111111", remote_sha: "2222222" })
    ),
  };
}

test("o lote nao reconstroi o <tbody> tres vezes por repo", async () => {
  // Antes: cada doUpdate pintava 3x (busy, sucesso, finally) e cada pintura
  // reescrevia as N linhas. O render do meio — seguido imediatamente pelo do
  // finally, sem nada visível no meio — foi eliminado.
  const { scan, check } = cenarioLote(4);
  const { sandbox: s, repoList, settle } = loadApp({ scan, check, path: "/base", autoScan: true });
  await settle();

  const base = repoList.__renders;
  await s.updateAll();
  // Overhead fixo do lote: os dois renders de setBusy (abre e fecha o busy).
  const overhead = 2;
  const porRepo = (repoList.__renders - base - overhead) / 4;

  assert.ok(
    porRepo <= 2,
    `o lote ainda pinta o <tbody> ${porRepo.toFixed(1)}x por repo dentro do loop ` +
      `(${repoList.__renders - base} reconstrucoes no total; o alvo e 2, o anterior era 3)`
  );
});

test("depois do lote, o DOM e identico ao que um render completo produziria", async () => {
  // Este e o invariante que importa para o render cirúrgico: se a linha foi
  // corrigida na mao e algum campo ficou defasado, o HTML final diverge do que
  // render() produziria com o mesmo estado. O lote termina com setBusy(false),
  // que faz o render completo — entao a comparacao tem de fechar.
  const { scan, check } = cenarioLote(3);
  const { sandbox: s, repoList, settle } = loadApp({ scan, check, path: "/base", autoScan: true });
  await settle();

  await s.updateAll();
  const depoisDoLote = repoList.innerHTML;
  s.render();
  assert.equal(
    repoList.innerHTML,
    depoisDoLote,
    "o DOM ficou defasado em relacao ao render completo — totals/summary nao foram repintados"
  );
});

test("renderRowInPlace devolve false quando a linha nao esta na vista", () => {
  // A queda para o render() completo e o que mantem o lote correto quando o
  // cirúrgico nao se aplica (linha filtrada, tbody vazio, sem replaceWith).
  const { sandbox: s } = loadApp({});
  assert.equal(s.renderRowInPlace(item({ name: "nao-existe" }), 99), false);
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

/* Journeys cobertas:
   J4 — "quero saber a verdade depois de um tempo esgotado, não um 'erro'
        que pode ser mentira" (o /api/update tem timeout de 900 s e pode ter
        concluído no servidor mesmo com o cliente desistindo)

   J5 — "quero ver o motivo real da falha, não 'HTTP 500'"

   Contrato testado: funções `function` de static/app.js via contexto vm. */
import test from "node:test";
import assert from "node:assert/strict";
import { loadApp, item } from "./load-app.mjs";

const json = (payload, status = 200) => ({ ok: status < 400, status, json: async () => payload });
const abort = () => { const e = new Error("aborted"); e.name = "AbortError"; throw e; };
const offline = () => { throw new TypeError("Failed to fetch"); };

/* ------------------------------------------------------------------ RED */
test("J4: api() classifica tempo esgotado como erro TIPO, com código", async () => {
  const { sandbox: s } = loadApp({ fetchImpl: abort });
  await assert.rejects(
    () => s.api("/api/update", {}, 1000),
    (error) => {
      assert.equal(error.name, "ApiError", "erro não tipado: o chamador não consegue decidir");
      assert.equal(error.code, "TIMEOUT");
      return true;
    }
  );
});

test("J4: api() distingue servidor fora do ar de recusa do servidor", async () => {
  const { sandbox: s } = loadApp({ fetchImpl: offline });
  await assert.rejects(
    () => s.api("/api/scan", {}, 1000),
    (error) => {
      assert.equal(error.code, "NETWORK");
      return true;
    }
  );
});

test("J4: timeout e rede são INDETERMINADOS; recusa do servidor não é", async () => {
  const timeout = loadApp({ fetchImpl: abort }).sandbox;
  const network = loadApp({ fetchImpl: offline }).sandbox;
  const refused = loadApp({ fetchImpl: () => json({ detail: "Falha ao atualizar: disco cheio" }, 502) }).sandbox;

  const indeterminate = [];
  for (const [s, call] of [[timeout, "/api/update"], [network, "/api/update"], [refused, "/api/update"]]) {
    try { await s.api(call, {}, 1000); } catch (e) { indeterminate.push(e.indeterminate); }
  }
  assert.equal(indeterminate[0], true, "timeout é indeterminado: o servidor pode ter concluído");
  assert.equal(indeterminate[1], true, "rede caída é indeterminada");
  assert.equal(indeterminate[2], false, "o servidor respondeu 502: a recusa é definitiva");
});

test("J4: update que deu tempo esgotado NÃO é reportado como falha sem reconsultar", async () => {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(String(url).split("?")[0]);
    if (String(url).startsWith("/api/update")) return abort();
    if (String(url).startsWith("/api/scan")) {
      return json({ path: "/base", items: [item({ behind: true, local_sha: "old1", remote_sha: "new1" })], zip_only: false, backup: true });
    }
    if (String(url).startsWith("/api/check")) {
      // o servidor na verdade concluiu: local ja e igual ao remoto
      return json({ path: "/base", items: [item({ behind: false, local_sha: "aaaaaaabbbbcc", remote_sha: "aaaaaaabbbbcc" })] });
    }
    return json({ lines: [] });
  };

  const scan = { path: "/base", items: [item({ behind: true, local_sha: "old1", remote_sha: "new1" })], zip_only: false, backup: true };
  const { sandbox: s, dom, settle } = loadApp({ fetchImpl, scan, path: "/base", autoScan: true });
  await settle(); // o scan inicial (com auto) já chama /api/check
  calls.length = 0; // mede só o que o doUpdate faz
  dom.get("status-text").textContent = "";

  const ok = await s.doUpdate("acme__widget", true);
  await settle();

  const updates = calls.filter((u) => u.startsWith("/api/update")).length;
  const checks = calls.filter((u) => u.startsWith("/api/check")).length;
  assert.equal(updates, 1, `o update nem chegou a ser tentado; chamadas: ${[...new Set(calls)].join(", ")}`);
  assert.equal(checks, 1, `esperava UMA reconsulta ao GitHub depois do timeout; houve ${checks}`);
  assert.equal(ok, true, `a operação TEM de ser reportada como concluída; status diz: "${dom.get("status-text").textContent}"`);
});

test("J4: se a reconsulta mostra que NÃO concluiu, aí sim é falha", async () => {
  const fetchImpl = async (url) => {
    if (String(url).startsWith("/api/update")) return abort();
    if (String(url).startsWith("/api/check")) {
      return json({ path: "/base", items: [item({ behind: true, local_sha: "old1", remote_sha: "new1" })] });
    }
    return json({ lines: [] });
  };
  const scan = { path: "/base", items: [item({ behind: true, local_sha: "old1", remote_sha: "new1" })], zip_only: false, backup: true };
  const { sandbox: s, settle } = loadApp({ fetchImpl, scan, path: "/base", autoScan: true });
  await settle();
  const ok = await s.doUpdate("acme__widget", true);
  await settle();
  assert.equal(ok, false, "reconsulta confirmou que ficou para trás: é falha");
});

/* ------------------------------------------- GREEN desde o inicio (caracterização) */
test("J5: erro do servidor mostra o detail, não 'HTTP 500'", async () => {
  const { sandbox: s } = loadApp({ fetchImpl: () => json({ detail: "Falha ao consultar GitHub: branch main nao existe." }, 502) });
  await assert.rejects(
    () => s.api("/api/update", { method: "POST" }, 1000),
    (error) => {
      assert.match(error.message, /branch main nao existe/);
      assert.equal(error.status, 502);
      return true;
    }
  );
});

test("J5: erro HTTP carrega o status para o chamador decidir", async () => {
  const { sandbox: s } = loadApp({ fetchImpl: () => json({}, 504) });
  await assert.rejects(
    () => s.api("/api/update", { method: "POST" }, 1000),
    (error) => {
      assert.equal(error.code, "HTTP");
      assert.equal(error.status, 504);
      return true;
    }
  );
});

test("J5: corpo sem detail cai no HTTP <status>", async () => {
  const { sandbox: s } = loadApp({ fetchImpl: () => json({}, 500) });
  await assert.rejects(
    () => s.api("/api/x", {}, 1000),
    (error) => {
      assert.match(error.message, /HTTP 500/);
      return true;
    }
  );
});

test("resposta bem-sucedida não vira erro", async () => {
  const { sandbox: s } = loadApp({ fetchImpl: () => json({ ok: true, configured: false }) });
  const payload = await s.api("/api/token", {}, 1000);
  assert.equal(payload.ok, true);
});

/* Journeys cobertas:
   J2 — "quero que o tamanho dos pacotes apareça legível, para julgar o custo de
        um update sem ruído" (Nada de "NaN", nada de "0,0 B", nada de negativo.)

   Contrato testado: as funções declaradas com `function` em static/app.js são
   alcançáveis pelo contexto vm. Zero build, zero jsdom. */
import test from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./load-app.mjs";

const { formatSize, formatSpeed, shortSha, looksLikePath } = loadApp({}).sandbox;

/* ------------------------------------------------------------------ RED */
test("formatSize: bytes são inteiros, nunca decimais", () => {
  assert.equal(formatSize(0), "0 B");
  assert.equal(formatSize(1), "1 B");
  assert.equal(formatSize(512), "512 B");
});

test("formatSize: valor não numérico devolve '?', nunca 'NaN'", () => {
  assert.equal(formatSize(NaN), "?");
  assert.equal(formatSize("abc"), "?");
  assert.equal(formatSize(Infinity), "?");
});

test("formatSize: tamanho negativo devolve '?', nunca '-5,0 B'", () => {
  assert.equal(formatSize(-5), "?");
});

test("formatSpeed: propaga os mesmos casos de borda do formatSize", () => {
  assert.equal(formatSpeed(0), "0 B/s");
  assert.equal(formatSpeed(NaN), "?");
  assert.equal(formatSpeed(-1), "?");
});

/* ------------------------------------------- GREEN desde o inicio (caracterização) */
test("formatSize: sobe de unidade e mantem uma casa abaixo de 100", () => {
  assert.equal(formatSize(1023), "1023 B");
  assert.equal(formatSize(1024), "1,0 KB");
  assert.equal(formatSize(1536), "1,5 KB");
  assert.equal(formatSize(1048576), "1,0 MB");
  assert.equal(formatSize(1234567), "1,2 MB");
});

test("formatSize: acima de 100 na unidade, arredonda para inteiro", () => {
  assert.equal(formatSize(123456789), "118 MB");
});

test("formatSize: ausência de informação é '?'", () => {
  assert.equal(formatSize(null), "?");
  assert.equal(formatSize(undefined), "?");
  assert.equal(formatSpeed(null), "?");
});

test("formatSpeed: anexa /s à unidade", () => {
  assert.equal(formatSpeed(1024), "1,0 KB/s");
});

test("shortSha: 7 caracteres, e travão quando não há SHA", () => {
  assert.equal(shortSha("0123456789abcdef"), "0123456");
  assert.equal(shortSha("abc"), "abc");
  assert.equal(shortSha(null), "—");
  assert.equal(shortSha(undefined), "—");
  assert.equal(shortSha(""), "—");
});

test("looksLikePath: só aceita caminho absoluto ou home", () => {
  assert.equal(looksLikePath("/home/x"), true);
  assert.equal(looksLikePath("~/x"), true);
  assert.equal(looksLikePath("./x"), false);
  assert.equal(looksLikePath("C:\\x"), false);
  assert.equal(looksLikePath(""), false);
  assert.equal(looksLikePath("/"), false);
});

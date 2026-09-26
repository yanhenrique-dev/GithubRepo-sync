/* Extrai, do consumidor `static/app.js`, os campos de item e de topo que ele lê.

   Contrato de saída: JSON em stdout —
     { "row": ["name", ...], "result": ["path", ...] }

   Usado por tests/test_contract.py para provar que o consumidor não lê nada
   que `core/contract.py` não declare. Roda com `node`, que já é dependência
   do projeto (o CI roda `node --check static/app.js`). Sem dependências. */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(HERE, "..", "..", "static", "app.js"), "utf8");

/** nomes declarados no topo do módulo: serve para distinguir
    result.<campo de resposta> de result.<variável local>. */
const topLevel = new Set();
for (const m of src.matchAll(/^(?:const|let|var)\s+([A-Za-z_$][\w$]*)/gm)) topLevel.add(m[1]);
for (const m of src.matchAll(/^function\s+([A-Za-z_$][\w$]*)/gm)) topLevel.add(m[1]);

const row = new Set();
const result = new Set();

// \brow\.<ident> — ignora indexações como row[0] e métodos como row.map()
for (const m of src.matchAll(/\brow\.([a-z_][a-z0-9_]*)/g)) row.add(m[1]);
// \bresult\.<ident> onde result é a resposta da API
for (const m of src.matchAll(/\bresult\.([a-z_][a-z0-9_]*)/g)) {
  if (topLevel.has("result")) result.add(m[1]);
}

const json = JSON.stringify({ row: [...row].sort(), result: [...result].sort() });
process.stdout.write(`${json}\n`);

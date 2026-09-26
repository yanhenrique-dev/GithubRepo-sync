# Contrato de fronteira

`core/contract.py` é o **artefato canônico** do formato das respostas HTTP.
O OpenAPI servido em `/openapi.json` é derivado dele pelo FastAPI — nunca
editado à mão. `static/contract/openapi.json` é um snapshot versionado,
conferido por teste.

```
core/contract.py          <- autoridade (modelos Pydantic)
      |
      +-> app.py response_model=   <- o boundary valida a resposta
      +-> /openapi.json            <- derivado, gerado
      +-> static/contract/openapi.json  <- snapshot, conferido por teste
      +-> tests/test_contract.py    <- provider responde certo? consumidor le o que existe?
```

## Regra de ouro

> Um teste passa porque **os dois lados speakam o mesmo idioma**, não porque
> cada um passou no seu próprio teste.

## O alarme de drift

O que realmente quebra produção é renomear um campo num dos lados. Dois
testes cobrem isso:

| Teste | Falha quando |
|---|---|
| `test_consumidor_nao_le_campo_inexistente_no_contrato` | `static/app.js` lê um campo que o contrato não declara |
| `test_snapshot_openapi_esta_em_dia` | os modelos mudaram e o snapshot não foi regerado |

O primeiro é o que importa. Ele extrai, via Node, todo `row.<campo>` e
`result.<campo>` lido pelo `app.js` e compara com `ITEM_SCHEMA`:

```
$ # renomeando can_rollback -> can_reverter no contrato
E  AssertionError: static/app.js lê ['can_rollback'], que o contrato não
   declara. Ou declare no contrato, ou pare de ler no consumidor.
```

## Por que Node na extração

`app.js` é um script clássico, sem `export`, e o projeto é sem build — não há
como `importá-lo` num teste. Três alternativas foram descartadas:

- `ast` do Python: **não parseia JavaScript** (SyntaxError em `—` do comentário).
- Regex em Python: frágil demais para um alarme de drift.
- `jsdom`: dependência nova num projeto que hoje tem zero `node_modules`.

Então a extração roda em Node (`tests/js/consumer-fields.mjs`), que já é
dependência do projeto — o CI roda `node --check static/app.js`.

## Mudando o contrato

A ordem importa. **Contrato antes da implementação**, sempre:

1. Proponha a mudança e o impacto de compatibilidade no docstring de
   `core/contract.py`.
2. Mude `core/contract.py`.
3. Regenere o snapshot:
   ```bash
   .venv/bin/python -c "import json; from app import app; \
     open('static/contract/openapi.json','w').write(\
     json.dumps(app.openapi(), indent=2, ensure_ascii=False, sort_keys=True)+'\n')"
   ```
4. Ajuste o provider (`core/*.py`) e o consumidor (`static/app.js`).
5. Rode a verificação dos dois lados:
   ```bash
   .venv/bin/python -m pytest tests/ -q
   node --test tests/js/*.test.mjs
   ```

Mudança **aditiva** (campo novo opcional) não quebra consumidor antigo.
Mudança **quebradora** (renomear, remover, mudar tipo) precisa de plano de
migração — `branch_explicit` e `local_sha` já têm esse cuidado documentado
no contrato.

## Notas de modelagem

**`ScannedItem` e `CheckedItem` são separados.** O caminho de erro por linha
de `/api/check` devolve o item sem nenhum campo remoto:

```python
except TimeoutError:
    return {**it, "error": f"Tempo esgotado (...)"}
```

Se `remote_sha` fosse obrigatório, a serialização quebraria justamente no
caminho de erro — o que o usuário mais precisa ver. Por isso todo campo de
check tem `default=None`, e existe um teste que cobre exatamente esse caso.

**`Path` → `str` no boundary.** `core.updater` devolve `Path` em vários
pontos (`rollback_one`, `replace_zip_file`). O FastAPI não serializa `Path`
em JSON e estoura `ResponseValidationError`, respondendo 500 numa operação
que o usuário acabou de pedir. `UpdateResponse` e `RollbackResponse` têm
`field_validator` para converter.

**`busy` e `suggestions` não estão no contrato** — são estado local do
cliente, nunca vão e volta. O teste do consumidor os exclui de propósito.

## O que o contrato deliberadamente não sabe

Nada de coluna de banco, nome de tabela ou classe interna. Só o que o
consumidor consegue observar. `test_contrato_nao_declara_nada_que_nao_seja_observavel`
protege isso.

## Verificação

```bash
.venv/bin/python -m pytest tests/test_contract.py -q   # 17 testes
node --test tests/js/contract-consumer.mjs               # (integrado no acima)
```

O `tests/test_contract.py` divide-se em: contrato existe · provider satisfaz o
contrato (resposta real da API, caminho de sucesso **e** de erro) · consumidor
só lê o que existe · snapshot em dia.

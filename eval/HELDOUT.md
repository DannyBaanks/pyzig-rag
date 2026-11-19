# Conjunto de VALIDACIÓN held-out (ola 4)

**Estado: congelado.** `eval/heldout_queries.tsv` (61 consultas) y sus etiquetas se
escribieron antes de ver cualquier resultado. Tras medir, NO se han tocado
`aliases`, recetas, `pyzig/search.py`, umbrales ni consultas para mejorar las
cifras. Los fallos que aparecen abajo se dejan visibles a propósito: el objetivo
es medirlos, no arreglarlos aquí.

## Cómo se escribió (reglas de ceguera)

1. Leí `README.md` completo, como pedía la tarea.
2. Extraje con `scripts/extract_heldout_titles.py` **solo** `operation_id` +
   `name` + `intent` de `corpus/pyzig.corpus.jsonl` (95 líneas). Ese script no
   toca `aliases` ni `error_signatures`.
3. De `eval/queries.tsv` miré **únicamente la cabecera** (`head -1`:
   `qid / kind / query / expected / expect`) y el código de
   `scripts/run_eval.py`. No leí el cuerpo de `eval/queries.tsv` ni ningún
   `scripts/recipes/*_queries.tsv`.
4. Redacté a mano 61 consultas como las escribiría un programador Python que
   migrara a Zig 0.16: español e inglés mezclados, jerga (`heapq`, `mmap`,
   `f-string`), typos leves (`necessita`, `cree`), y preguntas largas con
   contexto. Las etiquetas `expected` se decidieron solo con la lista de
   títulos/intenciones del paso 2.
5. Las 8 consultas `error` pegan mensajes **reales** de zig 0.16.0 generados por
   mí con snippets mínimos en `/tmp/opencode/heldout_errs/gen.py` (`zig test`),
   no copiados de `error_signatures` ni de firmas minadas. Las líneas
   `error:`/`note:` pegadas son:
   `local variable is never mutated`, `name shadows primitive 'u8'`,
   `use of undeclared identifier 'builtin'`,
   `local constant 'x' shadows local constant from outer scope`,
   `@ptrCast discards const qualifier`,
   `evaluation exceeded 1000 backwards branches`,
   `unable to resolve comptime value` + `types must be comptime-known`,
   `expected type 'u8', found 'u32'`.
6. Composición final: 43 consultas POS normales (`direct` 30, `long` 8,
   `paraphrase` 2, `typo` 3), 8 consultas `error` (POS), y 10 negativas
   (`expect=NONE`) sin receta. Una de ellas (`h52`, `setsid`/demonio) es una
   sonda deliberada de abstención sobre un `gap` documentado como NO
   DEMOSTRADO: no hay equivalencia verificada, así que la respuesta honesta
   sería `NO_RESULTS`.
7. Fuga controlada y declarada: el README (leído por instrucción) contiene una
   tabla con `operation_id`s y estados. Es contexto compartido, no consultas de
   eval ni aliases. No se usaron alias ni firmas de error para escribir ni
   etiquetar.

## Comparación dev vs held-out (sacada de los JSON)

Mismos modelo (`all-MiniLM-L6-v2`), índice (95 entradas) y código de eval.
Dev = `eval/results.json` (196 consultas: 191 POS, 3 NONE, 1 VERSION, 1 STATUS).
Held-out = `eval/heldout_results.json` (61: 51 POS, 10 NONE, sin VERSION/STATUS).

| conjunto | modo | n | P@1 | R@3 | rechazo negativas | MRR@3 |
|---|---|---:|---|---|---|---|
| dev | lexical | 196 | 0.984 (188/191) | 0.995 (190/191) | 3/3 NONE (100%) | 0.990 |
| dev | hybrid | 196 | 0.958 (183/191) | 0.979 (187/191) | 3/3 NONE (100%) | 0.965 |
| **held-out** | lexical | 61 | **0.941 (48/51)** | 1.000 (51/51) | **8/10 NONE (80%)** | 0.967 |
| **held-out** | hybrid | 61 | **1.000 (51/51)** | 1.000 (51/51) | **1/10 NONE (10%)** | 1.000 |

Nota: el campo `summary.negativas_correctas` de los JSON agrupa `NONE` +
`VERSION` (dev 4/4 en ambos modos; held-out 8/10 y 1/10). La tabla usa solo
`NONE` para que la comparación sea homogénea. P@1/R@3 se calculan solo sobre
`POS` (incluye las 8 consultas de error).

### Lectura honesta

- **El conjunto de desarrollo esquió el fallo importante**: con solo 3
  negativas, ambos modos rechazan 3/3. En held-out, el modo híbrido acierta
  **todas** las positivas (51/51, P@1 1.000) pero apenas rechaza negativas
  (**1/10**): el coseno del embedding inglés admite prácticamente cualquier consulta.
  El lexical pierde 3 positivas en top-1 pero rechaza 8/10. La afirmación del
  README de que el semántico "sigue siendo mejora no demostrada" queda
  **corroborada y matizada**: mejora P@1, empeora gravemente la abstención.
- Positivas fallidas en top-1 con lexical (las 3 siguen en top-3, de ahí
  R@3 = 1.000): `h12` (`build-exe-root-module` detrás de `build-add-import`),
  `h13` (`build-link-libc` detrás de `ffi-extern-c-function`), `h42`
  (`migrate-arraylist-unmanaged` detrás de `list-append-pop-insert`).
- Abstención: `h52` (daemon/`setsid`) devuelve el `gap` en top-1 en **ambos**
  modos; `h53` (WebSocket) devuelve `http-client-get-local` en lexical y
  `tcp-loopback-echo` en hybrid. Son los 2 fallos negativos del lexical.
- Las 8 consultas que pegan errores del compilador aciertan en ambos modos. **No sobreinterpretar**:
  las intenciones de las recetas de diagnóstico citan literalmente esos mensajes,
  y seleccioné el `expected` desde esa lista; es la subcategoría menos ciega.
- No se midió significancia estadística con 61 consultas: `NOT_DEMONSTRATED`.

## Comandos ejecutados (salida resumida, rc)

| comando | salida resumida | rc |
|---|---|---|
| `.venv/bin/python scripts/build_index.py` | `entradas=95 embeddings=onnx` | 0 |
| `.venv/bin/python scripts/extract_heldout_titles.py \| wc -l` | `95` | 0 |
| `.venv/bin/python /tmp/opencode/heldout_errs/gen.py` | 10 snippets, 10 mensajes de error reales | 0 |
| `zig test --cache-dir ... narrowing2.zig` | `error: expected type 'u8', found 'u32'` | 1 (esperado: snippet roto) |
| `.venv/bin/python scripts/run_eval.py --queries eval/heldout_queries.tsv --out eval/heldout_results.json` | lexical `P@1 0.941 / R@3 1.0 / neg 8/10`; hybrid `P@1 1.0 / R@3 1.0 / neg 1/10` | 0 |
| `.venv/bin/python scripts/run_eval.py` | dev lexical `0.984 / 0.995 / 4/4`; hybrid `0.958 / 0.979 / 4/4`; regeneró `eval/results.json` (solo cambiaron latencias/RSS) | 0 |
| `.venv/bin/python -m unittest discover -s tests -p 'test_eval_heldout.py' -v` | 4 tests OK | 0 |
| `.venv/bin/python -m unittest discover -s tests -q` | suite completa OK | 0 |
| `PYTHONPATH=. python3 -m pytest -q tests` | `88 passed in 13.72s` | 0 |

Nota de entorno: `.venv/bin/python -m pytest` no funciona aquí
(`No module named pytest`; pytest 9.1.1 está instalado solo en el `python3`
del sistema). Por eso se ejecutó la suite con `unittest` dentro del venv y con
`PYTHONPATH=. python3 -m pytest` para el reporte completo.

## Limitaciones

- 61 consultas y 10 negativas: suficiente para detectar el fallo de abstención,
  no para estimar intervalos de confianza.
- Etiquetado por una sola persona (quien escribió las consultas) y guiado por
  títulos/intenciones; puede haber ruido de etiqueta. No es una verdad de
  referencia independiente.
- Sin consultas de `VERSION` ni `STATUS` en held-out: esos comportamientos no se
  re-evalúan aquí (`NOT_DEMONSTRATED` en este conjunto).
- Algunas consultas usan nombres de API que aparecen en las intenciones (p. ej.
  `std.ArrayList`, `heapq`); es menos ciego que un usuario que nunca viera el
  corpus, aunque las aliases y las consultas de eval sí quedaron fuera.
- Latencia y RAM no se comparan: las mediciones dependen de la carga de la
  máquina; aquí solo se reportan P@1, R@3, rechazo de negativas y MRR@3.

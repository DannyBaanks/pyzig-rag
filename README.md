# pyzig-rag — memoria operativa Python ↔ Zig 0.16 (RAG + MCP)

Prototipo funcional de recuperacion de equivalencias **Python → Zig 0.16.0**: un
corpus versionado, un indice reconstruible (FTS5 + embeddings locales) y un
servidor **MCP de solo lectura** para que un agente consulte recetas
*verificadas* en lugar de redescubrir la API de `std.Io`.

> Recuperar conocimiento → comprobar compatibilidad → proponer implementacion →
> verificar comportamiento. **La recuperacion semantica nunca es prueba de
> correccion**: cada entrada declara su estado de evidencia.

## Arquitectura

```
corpus/pyzig.corpus.jsonl      fuente de verdad (git): 18 entradas (11 recetas, 1 gap,
                               3 case_fixture, 3 pipeline_entry)
scripts/make_corpus.py         regenera el corpus (entradas + hash de contenido)
pyzig/corpus.py                UNICO escritor: hash canonico, append-only, atomico
pyzig/gates.py                 gates: `zig test` por entrada → promueve evidencia
fuzz/src/                      motor Zig: generacion, chunks, comparacion, evidencia
pyzig/fuzz/                    control plane Python: contratos, oracle por lotes,
                               triage, assembler, warden y campana
pyzig/embed.py                 embeddings ONNX local (all-MiniLM-L6-v2, CPU)
pyzig/index.py                 indice derivado SQLite (FTS5 + vectores) — var/pyzig.db
pyzig/search.py                filtros exactos + fusion RRF + admision (cobertura/cosine)
pyzig/mcp_server.py            FastMCP stdio, 3 herramientas de solo lectura
eval/queries.tsv, eval/results.json   evaluacion fija (28 consultas, lexical vs hibrida
```

Decisiones (y por que):

- **SQLite + FTS5 + vectores en la misma base**: el corpus es pequeno; una base
  vectorial externa no se justifica (restriccion de no-sobreingenieria).
- **Embeddings ONNX CPU** (`all-MiniLM-L6-v2`, 384d, SHA verificado en
  `var/models/.../SHA256SUMS.txt`): local, sin GPU, sin red en uso normal. Si el
  modelo falta, `pyzig_catalog`/`pyzig_search` declaran `embed_mode=unavailable`
  y el sistema degrada a lexical **declarandolo** (nunca en silencio).
- **Admision antes de ranking** (cobertura lexica de tokens discriminativos
  >= 0.40 **o** cosine >= 0.35): evita que una consulta sin equivalente devuelva
  "el menos malo". Las negativas devuelven `NO_RESULTS`.
- **Estado de evidencia explicito**: `DEMONSTRATED` (compilo y paso sus tests
  con zig 0.16.0), `NOT_DEMONSTRATED` (entrada tipo `gap` que documenta una
  limitacion), `FUZZ_EQUIV`, `ADMITTED`, `REGRESSED`, `MANUAL_REVIEW`, `REJECTED`.
  Las entradas sin `DEMONSTRATED` rankean por debajo
  salvo que la consulta las cuba mejor que cualquier receta — entonces la
  respuesta honesta es "aqui no hay equivalencia demostrada".
- **Version como filtro exacto**: `zig_version="0.13"` ⇒ `VERSION_MISMATCH`.

## Esquema del corpus (campos minimos)

`operation_id`, `name`, `intent`, `aliases`, `source_lang`, `target_lang`,
`zig_version`, `python_version`, `platform`, `py_ref`, `zig_impl`, `zig_test`,
`apis_used`, `constraints`, `preconditions`, `postconditions`, `side_effects`,
`error_behavior`, `ownership_memory`, `differences`, `tests`, `provenance`,
`entry_type` (`recipe`|`gap`|`case_fixture`|`pipeline_entry`),
`evidence{status,runs[{cmd,exit,duration_s,stdout_sha256,zig_version,observed}]}`,
`content_sha256`. Los artefactos `case_fixture`/`pipeline_entry` llevan ademas
`fuzz.case_fixture{case_hex,case_sha256,obs_hex,obs_sha256,status,compared_fields}`
y evidencia `FUZZ_EQUIV`/`ADMITTED` con seed, hashes y snapshot del run.

Dedup: por `operation_id` y por `content_sha256` (`corpus.dedupe_report`).

## Uso

```sh
cd pyzig-rag
python3 -m venv .venv && .venv/bin/pip install fastmcp onnxruntime tokenizers numpy
sh scripts/fetch_model.sh          # una vez; sin red el indice queda lexical declarado
.venv/bin/python scripts/make_corpus.py   # (re)genera el corpus
.venv/bin/python scripts/run_gates.py    # zig test por entrada → evidencia
.venv/bin/python scripts/build_index.py  # reconstruye var/pyzig.db desde el JSONL
.venv/bin/python scripts/demo_client.py  # cliente MCP real (stdio) que consulta las 3 tools
.venv/bin/python scripts/run_eval.py     # evaluacion fija → eval/results.json
```

### Fuzzing diferencial (F0–F4)

El camino caliente es Zig; Python solo es oracle por lotes y control plane.
Un chunk son **dos procesos** (subject + oracle), nunca un proceso por caso.
Sandbox fail-closed con bubblewrap + prlimit; sin `--allow-unsandboxed` no se
ejecuta nada si bwrap falta.

```sh
.venv/bin/python scripts/fuzz.py prepare     # inyecta zig_impl y compila 11 drivers
.venv/bin/python scripts/fuzz.py diff --op zig0.16/sha256-bytes \
    --iterations 200 --chunk 100 --replay 8 --harvest-limit 50
.venv/bin/python scripts/fuzz.py triage --run var/fuzz/runs/<run>
.venv/bin/python scripts/fuzz.py assemble --run var/fuzz/runs/<run> --kind case_fixture --limit 5
.venv/bin/python scripts/fuzz.py warden admit
.venv/bin/python scripts/fuzz.py warden regress
.venv/bin/python scripts/fuzz.py campaign --seed 1337 --budget-iterations 5000 \
    --iterations 200 --harvest-limit 20
.venv/bin/python scripts/fuzz.py loop --budget-seconds 60 --no-merge
```

- `diff` genera casos con seed determinista, compara **por campos nombrados**
  (`fuzz.compared_fields`) y escribe `meta.json`/`results.jsonl`/`summary.json`
  con hashes. `equiv.jsonl` + `harvest.json` sellan los ejemplos EQUIV.
- Taxonomia: `EQUIV/DIVERGENT/UNSUPPORTED/INVALID_REFERENCE/INVALID_ACCEPTED/
  CRASH/TIMEOUT/INCONCLUSIVE/NONDETERMINISTIC`. Las divergencias conocidas se
  declaran en `pyzig/fuzz/contracts.py` (`fuzz.known_divergences`); `triage`
  separa conocidas de nuevas.
- `assemble` admite solo `case_fixture` y `pipeline_entry` (una receta nueva
  nunca se auto-mergea) y siempre pasa por `pyzig.corpus.append_entry`.
- `warden` aplica 7 invariantes (hash chain, tipo, procedencia, integridad del
  fixture, contrato del padre, run limpio/driver vigente, caso duplicado por
  op) y mueve el estado `FUZZ_EQUIV → ADMITTED → REGRESSED`. Es idempotente:
  si el veredicto no cambia no reescribe la entrada.
- **Identidad del driver** (`pyzig/fuzz/drivers.py`): fuente materializado +
  version de zig, NO el hash del binario (`zig build-exe` no es reproducible:
  recompilar el mismo fuente da otro hash). `diff` guarda `driver.json` en el
  run atado al binario que corrio; `prepare --only X` fusiona el manifest.
  Cambiar el `zig_impl` o la version de zig regresa los artefactos del op.
- `diff` resuelve el interprete del oracle a su ruta real (`.venv/bin/python`
  → `/usr/bin/python3.x`): bwrap solo monta `/usr`, `/lib` y `/lib64`.
- `campaign`/`loop` priorizan los ops con menos artefactos admitidos, respetan
  presupuesto de iteraciones/tiempo y solo auto-mergean si no hay hallazgos
  nuevos: ensamblan y pasan el warden sobre una **copia** del corpus y solo
  anaden al real lo ADMITTED (lo rechazado queda en el informe del run, nunca
  en el corpus). El exit 1 del motor significa "hubo divergencias" (las decide
  `triage`), no fallo. `loop` (`--rounds 0`) corre hasta agotar presupuesto.
- Tests herméticos: `python3 -m unittest discover -s tests` no lee ni escribe
  `var/` (pasan en un clon limpio).

### MCP (registro en cliente)

```json
{"mcp": {"pyzig-rag": {"type": "local",
  "command": ["/ruta/a/pyzig-rag/.venv/bin/python",
              "/ruta/a/pyzig-rag/pyzig/mcp_server.py"],
  "enabled": true}}}
```

Herramientas (todas read-only, sin ejecucion de codigo recuperado):

| tool | entrada | salida |
|---|---|---|
| `pyzig_search` | `intent`, `py_code?`, `zig_version="0.16.0"`, `platform="linux"`, `max_results`, `mode` | candidatos con `operation_id`, `reason` (rank lexical/vectorial), `signals{coverage,cosine}`, `status`, `constraints`, `apis_used`, `tests`, `provenance`, `warnings`; errores `NO_RESULTS`/`VERSION_MISMATCH`/`INDEX_UNAVAILABLE` |
| `pyzig_get` | `operation_id` | entrada completa (contrato, codigo, tests, evidencia) |
| `pyzig_catalog` | — | salud del indice, `embed_mode`, versiones, operaciones y estados |

Invocacion real (extracto de `scripts/demo_client.py`, salida observada):

```
herramientas: ['pyzig_catalog', 'pyzig_get', 'pyzig_search']
pyzig_search ok= True count= 3
 - zig0.16/subprocess-run-capture 0.012938 DEMONSTRATED lexical(rank 1), vectorial(rank 1)
 - zig0.16/spawn-redirect-child 0.010705 DEMONSTRATED lexical(rank 9), vectorial(rank 2)
 - zig0.16/detached-daemon-no-shell 0.010655 NOT_DEMONSTRATED lexical(rank 4), vectorial(rank 4)
pyzig_get: ejecutar proceso externo y capturar streams
  status: DEMONSTRATED | runs: 1
```

## Recetas y estado

| operation_id | estado | notas |
|---|---|---|
| `zig0.16/subprocess-run-capture` | DEMONSTRATED | exit code, limites, `error.Timeout`, `error.StreamTooLong` |
| `zig0.16/read-file-text-limited` | DEMONSTRATED | `FileNotFound` vs `StreamTooLong` |
| `zig0.16/write-file-bytes-atomic` | DEMONSTRATED | truncado, `createFileAtomic+replace`, append por concatenado |
| `zig0.16/file-exists-vs-error` | DEMONSTRATED | ausente vs `AccessDenied` |
| `zig0.16/stdout-print-flush` | DEMONSTRATED | writer+flush vs `writeStreamingAll` |
| `zig0.16/parse-kv-config` | DEMONSTRATED | `KEY=VALOR` entrecomillado, sin ejecutar codigo |
| `zig0.16/sleep-ms` | DEMONSTRATED | `std.Io.sleep` (0.16: ya no `std.time.sleep`) |
| `zig0.16/string-split-strip-format` | DEMONSTRATED | `splitScalar`/`trim`/`bufPrint` |
| `zig0.16/spawn-redirect-child` | DEMONSTRATED | `spawn` con `StdIo.file`, `wait` |
| `zig0.16/env-var-read` | DEMONSTRATED | `Environ.getPosix` / `init.environ_map` |
| `zig0.16/sha256-bytes` | DEMONSTRATED | `bytesToHex(.lower)` |
| `zig0.16/detached-daemon-no-shell` | NOT_DEMONSTRATED (`gap`) | `setsid` no envuelto por std; paridad via `sh -c 'setsid … &'` |

Todas las verificadas contra la std local de zig 0.16.0 (`lib/std`), con
comando, exit code, duracion y SHA-256 de la salida guardados en
`evidence.runs` dentro del corpus.

## Evaluacion (28 consultas fijas, separadas del corpus)

`eval/queries.tsv`: 8 directas, 11 por nombre de API, 4 parafrasis, 3 negativas
(no deben devolver equivalencia), 1 de version (0.13 ⇒ `VERSION_MISMATCH`), 1 de
estado (`gap` en top-1). `eval/results.json`:

| modo | P@1 | R@3 | negativas | status | latencia media |
|---|---|---|---|---|---|
| lexical (FTS5 + filtros + admision) | 1.0 (23/23 POS) | 1.0 | 3/3 (+1 version) | 1/1 | 0.7 ms |
| hibrido (+ embeddings, fusion RRF) | 1.0 (23/23 POS) | 1.0 | 3/3 (+1 version) | 1/1 | 97 ms |

**Lectura honesta:** con 12 entradas el lexical ya basta; el semantico no
muestra hoy una ganancia medible en acierto (si en mecanismo de admision para
parafrasis). Queda declarado como mejora *no demostrada*, no como mejora
lograda; el coste medido es ~100x de latencia. El proximo experimento util es
el ensayo controlado agente-sin-MCP vs agente-con-MCP (iteraciones, errores de
compilacion, tokens), fuera del alcance de este prototipo.

## Seguridad e integridad

- Las herramientas no ejecutan nada: solo leen el indice.
- Los `zig_impl`/`zig_test` son **datos**, no instrucciones; ningun test hace
  operaciones privilegiadas reales (usan `std.testing.tmpDir`, aislado).
- Un modelo puede proponer entradas; solo `run_gates.py` (evidencia
  independiente) promueve a `DEMONSTRATED`.
- Sin secretos en corpus ni logs; el indice se reconstruye desde el corpus.
- Persistencia fuera de temporales: `var/` (indice, modelo, artefactos de gate);
  regenerable desde `corpus/`.

## Limitaciones / pospuestas

- Sin re-ranker, sin web UI, sin escritura por MCP, sin agentes validadores.
- Corpus pequeno (12): umbrales calibrados con 28 consultas, no con 1000.
- Embeddings requieren modelo local descargado (o degradacion declarada).
- No hay equivalente para `setsid`/demonio: esa es la frontera real hoy.

## Reinicio

```sh
cd pyzig-rag
.venv/bin/python scripts/build_index.py   # reconstruye var/pyzig.db
# gates (opcional, solo si cambia zig): .venv/bin/python scripts/run_gates.py
```

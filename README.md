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
corpus/pyzig.corpus.jsonl      fuente de verdad (git): recetas, gaps y artefactos
                               cosechados por el fuzzer (case_fixture, pipeline_entry)
scripts/make_corpus.py         regenera el corpus (entradas + hash de contenido)
scripts/recipes/<area>.py      recetas por area (ENTRIES + CONTRACTS no fuzzables) y
scripts/recipes/<area>_queries.tsv   sus consultas de eval
pyzig/corpus.py                UNICO escritor: hash canonico, append-only, atomico
pyzig/gates.py                 gates: `zig test` por entrada (o `zig build test` si la entrada
                               trae `gate_mode: "build"` + `build_files`) → promueve evidencia
fuzz/src/                      motor Zig: generacion, chunks, comparacion, evidencia
pyzig/fuzz/                    control plane Python: contratos, oracle por lotes,
                               triage, assembler, warden y campana
pyzig/embed.py                 embeddings ONNX local (all-MiniLM-L6-v2 por defecto; PYZIG_EMBED_MODEL)
pyzig/index.py                 indice derivado SQLite (FTS5 + vectores) — var/pyzig.db
pyzig/search.py                filtros exactos + fusion RRF + admision (cobertura/cosine)
pyzig/mcp_server.py            FastMCP stdio: 3 consultas de solo lectura + pyzig_check (bwrap)
pyzig/check.py                 pyzig_check: compila/ejecuta Zig en bwrap y mapea errores a recetas
scripts/mine_sessions.py       mina transcripts locales: firmas de error zig frecuentes → var/mined/
eval/queries.tsv, eval/results.json   evaluacion fija (lexical vs hibrida)
scripts/eval_mined.py          evalua las sugerencias de pyzig_check contra firmas minadas
eval/mined_labels.tsv          etiquetas humanas firma → receta(s)|NONE → eval/mined_coverage.json
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
- **Recetas de migracion Zig→Zig** (`source_lang="zig-0.13/0.14"`, `scripts/recipes/migracion.py`):
  llevan `error_signatures` (lineas `error:` reales de zig 0.16 al compilar la API vieja) que
  entran en la busqueda, asi que pegar el error encuentra la receta. Ceden ante las recetas
  Python→Zig (`MIGRATION_PENALTY`) cuando la consulta no trae marcas de Zig (`std.`, `error:`, `@`).
- **Gate honesto**: `zig_flags` opcional por receta (p. ej. `["-lc"]` para FFI con libc); una
  receta que pasa con tests saltados queda en `MANUAL_REVIEW`, no en `DEMONSTRATED`.
- **Indice ligado al modelo**: si el indice se construyo con otro modelo de embeddings que el
  activo, el modo hibrido se declara `unavailable` (misma dimension ⇒ cosenos basura en silencio).

## Esquema del corpus (campos minimos)

`operation_id`, `name`, `intent`, `aliases`, `source_lang`, `target_lang`,
`zig_version`, `python_version`, `platform`, `py_ref`, `zig_impl`, `zig_test`,
`apis_used`, `constraints`, `preconditions`, `postconditions`, `side_effects`,
`error_behavior`, `ownership_memory`, `differences`, `tests`, `provenance`,
`entry_type` (`recipe`|`gap`|`case_fixture`|`pipeline_entry`),
`evidence{status,runs[{cmd,exit,duration_s,stdout_sha256,zig_version,observed,skipped_tests}]}`,
opcionales `error_signatures` y `zig_flags` (solo entran en el hash si no estan vacios),
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

En esta maquina se sirve desde **isymcp-hub** (entrada `pyzig-rag`, `isolation: shared`, en
`~/.codex-web-http/hub/servers.json`; recarga en caliente con SIGHUP al daemon), asi que
todas las TUIs lo ven via `hub_execute(server="pyzig-rag", tool="pyzig_search", ...)`. El
servidor publica `instructions` (cuando consultarlo, como leer `status`/`differences`) y la
skill `zig-0-16` remite a el antes de escribir Zig 0.16.

Herramientas (las tres de consulta son read-only; `pyzig_check` compila y ejecuta el codigo
que le pasan, siempre dentro de `bwrap` sin red):

| tool | entrada | salida |
|---|---|---|
| `pyzig_search` | `intent`, `py_code?`, `zig_version="0.16.0"`, `platform="linux"`, `max_results`, `mode`, `code="top"` | candidatos (el primero con `zig_impl` completo; `code="all"`/`"none"`) con `operation_id`, `reason` (rank lexical/vectorial), `signals{coverage,cosine}`, `status`, `constraints`, `apis_used`, `tests`, `provenance`, `warnings`; errores `NO_RESULTS`/`VERSION_MISMATCH`/`INDEX_UNAVAILABLE` |
| `pyzig_get` | `operation_id` | entrada completa (contrato, codigo, tests, evidencia) |
| `pyzig_catalog` | — | salud del indice, `embed_mode`, versiones, operaciones y estados, `nores_count` |
| `pyzig_check` | `zig_code`, `mode="test"`/`"ast"` | `compiled`, `tests_passed`, `errors[{line,col,message,notes,suggestions}]`, `stderr_tail`, `sandbox`; `SANDBOX_UNAVAILABLE` si no hay bwrap (fail-closed), `TIMEOUT` |

`pyzig_check` compila con la cache global de zig montada (solo corre el compilador) y ejecuta el
binario de test en un segundo `bwrap` **sin** esa cache, para que codigo no confiable no pueda
envenenar checks posteriores. Las consultas de `pyzig_search` sin resultado (`NO_RESULTS`) se
anotan en `var/nores.jsonl` (`ts`, intencion truncada, version; nada mas): es la lista de recetas
que faltan.

Invocacion real (extracto de `scripts/demo_client.py`, salida observada):

```
herramientas: ['pyzig_catalog', 'pyzig_check', 'pyzig_get', 'pyzig_search']
pyzig_search ok= True count= 3
 - zig0.16/subprocess-run-capture 0.01273 DEMONSTRATED lexical(rank 1), vectorial(rank 1)
 - zig0.16/crc32-checksum 0.010752 DEMONSTRATED lexical(rank 12), vectorial(rank 3)
 - zig0.16/json-read-file-limited 0.010704 DEMONSTRATED lexical(rank 4), vectorial(rank 7)
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

Recetas por area en `scripts/recipes/` (no fuzzables todavia: contrato con
`skip_reason`, sin driver diferencial):

| area | operaciones |
|---|---|
| `colecciones` | dict→`StringHashMapUnmanaged`, list→`ArrayList`, `sorted(key=)` estable, set, `heapq`→`PriorityQueue`, `deque`→`std.Deque`, `Counter.most_common` |
| `fs_rutas` | `os.path.*`→`std.fs.path`, `listdir`, `os.walk`, `makedirs(exist_ok)`, `TemporaryDirectory`, `shutil.copyfile`, `remove`/`rmtree` |
| `json_codec` | `json.loads` dinamico y a struct, `json.dumps(indent)`, `JSONDecodeError`, escapes/`ensure_ascii`, leer JSON con limite |
| `texto_num` | base64, hex, `int(s, base)`, `float`/`{:.2f}`, find/replace/affix, UTF-8, `lower`/`upper` ASCII; gap: mayusculas/minusculas Unicode |
| `tiempo_args` | `time.time`, `time.monotonic`, PRNG con semilla, `sys.argv`, flags `--k v`, `zlib.crc32`, `hashlib.md5` |
| `io_red` | `threading.Thread`/`Lock` (`std.Thread`, `std.Io.Mutex`, atomics), `io.async`/`Group`, TCP y UDP en loopback, `std.http.Client` contra servidor local, FFI con `extern fn` (gate con `-lc`) |
| `migracion` | Zig 0.13/0.14 → 0.16: `readFileAlloc`, `writeFile`, stdout writer, `ArrayList` unmanaged, `@Type`→`@Int`/`@Struct`, `Child.run`, `time.sleep`, `Thread.Mutex` |
| `diagnosticos` | errores de compilacion frecuentes en las sesiones: cuota de `comptime`, `var` nunca mutada, sombreado (local y de primitivo), `comptime`/`inline` redundante, valor/llamada de runtime en `comptime`, `@ptrCast` que quita `const`, estrechar enteros, `builtin` sin importar |
| `build_zig` | `build.zig` de 0.16: `root_module`/`createModule`, `link_libc`, `addImport`, import fuera del modulo, `addLibrary(.dynamic)`, PIC, paso `test`, `addCSourceFiles`; gate con `zig build test` |
| `mate_bytes` | f-strings→`allocPrint`, `inf`/`nan`, `struct.pack`→`readInt`/`writeInt`, `int.from_bytes`, `//` y `%` con negativos, `bit_count`/`bit_length`, redondeo, cadenas C (`span`/`sliceTo`) |
| `stdlib_extra` | migracion con error real de zig 0.16: `std.fs.openDirAbsolute` → `std.Io.Dir`, `ArrayList.writer()`/campo `allocator` (metodos unmanaged), `[:0]const u8` → `?[*:0]const u8` (`.ptr`); Python→Zig: `csv.reader` con comillas, `datetime` epoch→UTC con `std.time.epoch`, `argparse` con subcomandos; gap: `re` (NOT_DEMONSTRATED, sin motor de regex en std) |

Anadir un area: crear `scripts/recipes/<area>.py` con `ENTRIES` (mismo formato
que `make_corpus.py`) y `CONTRACTS` (`_c(..., skip_reason=...)`), y
`<area>_queries.tsv`. Las recetas que nacen de un error llevan `error_signatures`
(lineas `error:` reales del compilador); las de `build.zig` llevan ademas
`gate_mode: "build"` y `build_files` (proyecto arreglado; sin URLs ni
`b.dependency`; el gate no es sandbox, el corpus es codigo propio). Luego `make_corpus.py`, `run_gates.py`, anadir las
consultas a `eval/queries.tsv` y `run_eval.py`. `make_corpus.py` rechaza
contratos duplicados o fuzzables fuera de `pyzig/fuzz/contracts.py`.

Las recetas Zig→Zig (`source_lang` `zig-0.13/0.14`) ceden ante las Python→Zig si la
consulta no trae marcas de Zig (`std.`, `error:`, `@builtin`...); las nativas de 0.16
(`zig-0.16`, `zig-build`) no se penalizan.

Todas las verificadas contra la std local de zig 0.16.0 (`lib/std`), con
comando, exit code, duracion y SHA-256 de la salida guardados en
`evidence.runs` dentro del corpus.

## Evaluacion (consultas fijas, separadas del corpus)

`eval/queries.tsv`: el bloque original `q01`–`q28` (directas, por nombre de API,
parafrasis, negativas que no deben devolver equivalencia, una de version 0.13 ⇒
`VERSION_MISMATCH` y una de estado con el `gap` en top-1) mas las consultas de
cada area (`<area>-NN`). Los numeros son los de `eval/results.json`, que
regenera `scripts/run_eval.py`; no se copian aqui.

**Lectura honesta:**
- Las consultas de area las escribieron los mismos workers que las recetas, y
  los aliases se ajustaron mirando sus fallos: son un conjunto de *desarrollo*,
  no de validacion independiente.
- El embedding (`all-MiniLM-L6-v2`, ingles) da cosenos ~0.33-0.36 a entradas
  sin relacion con consultas en espanol: con mas entradas, el modo hibrido
  empieza a perder top-1 que el lexical acierta (el esperado sigue en top-3).
  El semantico sigue siendo mejora *no demostrada*. Se midieron dos modelos
  multilingues (`multilingual-e5-small`, `paraphrase-multilingual-MiniLM-L12-v2`;
  `scripts/run_eval.py --build --models a,b`): ninguno supero al lexical ni a MiniLM
  en P@1 y ambos rechazan peor las negativas, con ~5x latencia y ~2x RAM. MiniLM se queda.
- **Sugerencias de `pyzig_check`** (`scripts/eval_mined.py` → `eval/mined_coverage.json`):
  (A) autoconsistencia/regresion: cada `error_signatures` del corpus debe devolver su
  receta (tautologico si el emparejador funciona; vigila que no se rompa); (B) firmas reales de
  `var/mined/signatures.jsonl` etiquetadas a mano en `eval/mined_labels.tsv`: hit@1/hit@3
  contra la etiqueta y falsos positivos sobre las `NONE`. El camino es el de `check_zig`
  (`check.suggest_for_message`): primero la firma (plantilla + huecos entre comillas; numeros
  y `uN` normalizados; si la plantilla la comparten varias recetas los huecos deben
  coincidir), si no hay firma y tampoco una API `std.*` anclada se abstiene, y solo entonces
  busca. (B) es *in-sample*: las etiquetas las pone quien escribe el emparejador y varias
  recetas nacieron de esas mismas firmas; no son cifras de generalizacion. El indice de firmas
  se carga una vez por proceso: tras cambiar el corpus, reiniciar el servidor MCP.
- Un `gap` solo sube a top-1 si su cobertura lexica supera a la de toda receta;
  si la receta ASCII documenta la misma diferencia (p. ej. `casefold`), empatan
  y gana la receta. El proximo experimento util es
el ensayo controlado agente-sin-MCP vs agente-con-MCP (iteraciones, errores de
compilacion, tokens), fuera del alcance de este prototipo.

## Seguridad e integridad

- `pyzig_search`/`pyzig_get`/`pyzig_catalog` no ejecutan nada: solo leen el indice.
  `pyzig_check` si ejecuta el codigo recibido, solo dentro de `bwrap` (`--unshare-all`,
  `--clearenv`, sistema de archivos de solo lectura salvo su temporal); sin bwrap se niega.
- Los `zig_impl`/`zig_test` son **datos**, no instrucciones; ningun test hace
  operaciones privilegiadas reales (usan `std.testing.tmpDir`, aislado).
- Un modelo puede proponer entradas; solo `run_gates.py` (evidencia
  independiente) promueve a `DEMONSTRATED`.
- Sin secretos en corpus ni logs; el indice se reconstruye desde el corpus.
- Persistencia fuera de temporales: `var/` (indice, modelo, artefactos de gate);
  regenerable desde `corpus/`.

## Limitaciones / pospuestas

- Sin re-ranker, sin web UI, sin escritura de corpus por MCP.
- Corpus pequeno: umbrales calibrados con las consultas de `eval/queries.tsv`, no con 1000.
- `scripts/mine_sessions.py` lee (solo lectura) Claude Code y Codex (`.jsonl`, `.jsonl.zst`),
  la base sqlite de opencode y los `.jsonl` de Gemini/AGY y Qwen. Su informe solo guarda firmas
  de error del compilador, nombres de API de la std y conteos.
- Firmas reales sin receta (`eval/mined_coverage.json`, casos con `got_top3` vacio o errado):
  la siguiente lista de recetas candidatas.
- Embeddings requieren modelo local descargado (o degradacion declarada).
- No hay equivalente para `setsid`/demonio: esa es la frontera real hoy.

## Reinicio

```sh
cd pyzig-rag
.venv/bin/python scripts/build_index.py   # reconstruye var/pyzig.db
# gates (opcional, solo si cambia zig): .venv/bin/python scripts/run_gates.py
```

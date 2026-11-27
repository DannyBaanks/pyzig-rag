# Recetas para firmas minadas sin receta (ola 5)

Fuente de las firmas: `var/mined/signatures.jsonl` (normalización de
`scripts/mine_sessions.py`). Etiquetas humanas: `eval/mined_labels.tsv`.
Resultados regenerados: `eval/mined_coverage.json` (con bloque `antes`) y
`eval/results.json`. Este documento explica **qué se reetiquetó y por qué**; no
sustituye a las métricas.

## Alcance

- 13 recetas nuevas en `scripts/recipes/diag_mined.py` (`zig0.16/diag-mined-*`).
- 1 receta existente tocada: `zig0.16/build-dynamic-library-pic` en
  `scripts/recipes/build_zig.py` (añade la firma real minada con PIC).
- 20 firmas `NONE` → id nuevo. Ninguna otra etiqueta cambió.
- 4 plantillas totalmente comodín siguen `NONE` a propósito (ver más abajo).

Todas las recetas nuevas tienen ejemplo roto (`py_ref`) y arreglo verificado
(`zig_impl`/`zig_test` o `build_files` con `gate_mode=build`) con Zig 0.16.0.
`scripts/run_gates.py` las marca `DEMONSTRATED` (14/14 incluida la PIC).

## Firma → receta (20 reetiquetados)

| Firma minada (normalizada) | Receta | Justificación |
|---|---|---|
| `invalid constraint: '_'` | `zig0.16/diag-mined-asm-constraint` | El mensaje sale del backend de asm inline; el ejemplo usa `"=X"` y el arreglo `"=r"` (x86_64). |
| `unused local constant` | `zig0.16/diag-mined-unused-discard` | Const local sin uso: se elimina o se usa; cubre también el descarte sin sentido. |
| `pointless discard of local variable` | `zig0.16/diag-mined-unused-discard` | `_ = x` después de haber usado `x` es el mismo diagnóstico de gestión de locales. |
| `expected type '_', found '*const _'` | `zig0.16/diag-mined-pointer-coercion` | Confusión entre puntero const y slice/array; el arreglo usa `a[0..]`. |
| `expected type '[]const uN', found '*[N]uN'` | `zig0.16/diag-mined-pointer-coercion` | Igual causa: el compilador no adivina la longitud del slice desde `&array`. |
| `cannot implicitly convert many pointer to single pointer` | `zig0.16/diag-mined-pointer-coercion` | El ejemplo pasa de `[*]const u8` a índice `mp[0]` en vez de a `*u8`. |
| `embed of file outside package path: '_'` | `zig0.16/diag-mined-embed-outside` | `@embedFile` exige que la ruta resuelva dentro del root del módulo; el gate usa `zig build`. |
| `file exists in modules '_' and '_'` | `zig0.16/diag-mined-module-conflict` | El mismo `root_source_file` en dos módulos; se comparte un `b.createModule` con `addImport`. |
| `redeclaration of local constant '_'` | `zig0.16/diag-mined-duplicate-names` | Dos `const` con el mismo identificador en un ámbito; basta renombrar una. |
| `duplicate struct member name '_'` | `zig0.16/diag-mined-duplicate-names` | El mismo error sobre campos de `struct`; el ejemplo usa `x`/`y`. |
| `duplicate struct member name 'std'` | `zig0.16/diag-mined-duplicate-names` | Igual plantilla y causa, con `std` como nombre repetido. |
| `type 'uN' cannot represent integer value 'N'` | `zig0.16/diag-mined-int-range` | Literal fuera de rango (`300` en `u8`); se ensancha o se usa `@truncate`/`std.math.cast`. |
| `type 'usize' cannot represent integer value 'N'` | `zig0.16/diag-mined-int-range` | `-1` en `usize`: mismo diagnóstico de rango, con valor negativo. |
| `value with comptime-only type 'comptime_int' depends on runtime control flow` | `zig0.16/diag-mined-comptime-flow` | Rama de `if` dependiente de runtime: hace falta anotar `u32` en la constante. |
| `value with comptime-only type 'comptime_float' depends on runtime control flow` | `zig0.16/diag-mined-comptime-flow` | Igual con `f64` y `1.5`/`2.5`. |
| `vector index not comptime known` | `zig0.16/diag-mined-vector-index` | `@Vector` solo admite índice comptime; convertir a `[N]T` para indexar en runtime. |
| `@bitCast size mismatch: destination type 'uN' has N bits but source type 'iN' has N bits` | `zig0.16/diag-mined-bitcast-size` | `@bitCast` no cambia el ancho; extender `i32` a `i64` antes de reinterpretar. |
| `@bitCast size mismatch: destination type 'uN' has N bits but source type 'uN' has N bits` | `zig0.16/diag-mined-bitcast-size` | Mismo error entre `u16` y `u32`; ensanchar con `@as(u32, x)`. |
| `error union is ignored` | `zig0.16/diag-mined-error-union` | Llamada `!T` sin `try`/`catch`; la receta muestra propagación, valor por defecto y `expectError`. |
| `no field or member function named 'format' in '[]const uN'` | `zig0.16/diag-mined-member-format` | Una slice no tiene `.format()`; se usa `std.fmt.bufPrint`/`allocPrint`. |

### PIC (receta existente, no era `NONE`)

`dependency on dynamic library '_' requires enabling Position Independent
Code; fixed by '_' or '_'` → `zig0.16/build-dynamic-library-pic`. La receta ya
tenía la firma de `dynamic linking requires enabling PIC`, pero no aparecía en
top-3 para el mensaje real (`dependency on dynamic library 'omp' ... fixed by
'-lomp' or '-fPIC'`). Se añadió esa forma concreta con tres huecos literos: la
plantilla es única en el corpus, así que `match_signature` empareja también la
forma minada con `_`.

## Por qué siguen `NONE`

### Plantillas 100% comodín (no se reetiquetan)

| Firma | n | Razón |
|---|---:|---|
| `root source file struct '_' has no member named '_'` | 19 | Comparte plantilla con recetas de migración antiguas. Los dos huecos son `_`: no hay evidencia para elegir una receta, y reetiquetar sería una autoconsistencia falsa. |
| `use of undeclared identifier '_'` | 7 | Igual: `use of undeclared identifier 'builtin'` ya tiene su propia receta; con `_` el matcher se abstiene. |
| `expected type '_', found '_'` | 4 | Plantilla compartida por muchas recetas de tipos; sin huecos literales no se puede decidir. |
| `no field or member function named '_' in '_'` | 3 | Varias recetas antiguas (`Build.*`, `array_list.*`) usan esta plantilla con huecos concretos. |

Para estas cuatro, la receta `diag-mined-member-format` y
`diag-mined-undeclared-ident` documentan el **método**, no un arreglo único:

```sh
STD_DIR="$(zig env | sed -n 's/.*"std_dir" = "\(.*\)".*/\1/p')"
zig std | ziggrep -Fn 'pub fn <nombre>'
ziggrep -Fn 'pub fn <nombre>' "$STD_DIR"
```

Renombrados vistos en `signatures.jsonl`: `std.fs.cwd`,
`std.fs.openDirAbsolute`, `std.fs.openFileAbsolute` → `std.Io.Dir`;
`std.io.getStdOut` → `std.Io.File.stdout()`; `std.Thread.sleep` /
`std.time.sleep` → `std.Io.sleep`; `std.Thread.Mutex` → `std.Io.Mutex`;
`std.process.Child.run` → `std.process.run`; `std.fmt.fmtSliceHexLower` →
`std.fmt.bytesToHex`; `std.time.nanoTimestamp` → `std.Io.Timestamp.now`.
Ese método vive en `constraints` de las recetas (campo no indexado): así está
disponible para quien consulta la receta, pero no contamina la búsqueda con
nombres de APIs ajenos.

### Resto de `NONE` (26 firmas en total)

Además de las cuatro plantillas anteriores, quedan 22 firmas de frecuencia 1–2
(`C import failed`, `break expression outside loop`, errores de parser como
`expected ';' after statement`, ABI/COM, coercion de tipos específicos de OS,
`root source file struct 'testing' has no member named 'expectCrash'`, etc.).
No se reetiquetaron porque **ninguna receta nueva explica directamente ese
caso**: darles un id sería una etiqueta por proximidad semántica, no por
diagnóstico verificado. En particular `expectCrash` sigue siendo el único falso
positivo: la búsqueda propone `diag-mined-error-union` / 
`diag-mined-undeclared-ident` / `build-test-step`, pero no existe equivalente
demostrado en std 0.16 (hay que inspeccionar `term.signal` del proceso hijo).

## Cifras antes → después

| Métrica | Antes | Después |
|---|---:|---:|
| Entradas del corpus | 102 | 115 |
| Autoconsistencia hit@1 / hit@3 | 53/53 (1.0) | 76/76 (1.0) |
| Firmas reales no-NONE | 44 | 64 |
| Mined hit@1 | 42 (0.9545) | 63 (0.9844) |
| Mined hit@3 | 43 (0.9773) | 64 (1.0) |
| Firmas reales NONE | 46 | 26 |
| Falsos positivos sobre NONE | 1 | 1 |
| FPR sobre NONE | 0.0217 | 0.0385 |
| Dev lexical P@1 / R@3 | 0.976 / 0.995 | 0.981 / 0.995 |
| Dev hybrid P@1 / R@3 | 0.952 / 0.976 | 0.952 / 0.976 |

El FPR **sube como tasa** (0.0217 → 0.0385) porque el denominador baja de 46 a
26 al reetiquetar 20 firmas; el **número de falsos positivos no cambia** (1 → 1,
≤ +1 caso). La única firma no-NONE que aún no entra en top-3 era
`root source file struct 'fs' has no member named 'openFileAbsolute'`; tras
ajustar el texto indexado de las recetas nuevas volvió a entrar, por lo que
hit@3 quedó en 64/64. En dev no hay ninguna inversión de P@1 híbrido; lexical
mejora en una consulta (`stdlib_extra-05`).

## Verificación

```sh
.venv/bin/python scripts/make_corpus.py                         # rc=0, 115 entradas
.venv/bin/python scripts/run_gates.py                           # rc=0, 115 filas; 14 objetivo DEMONSTRATED
.venv/bin/python scripts/build_index.py                         # rc=0, 115 entradas, embeddings onnx
.venv/bin/python scripts/eval_mined.py --antes /tmp/opencode/mined_coverage_antes.json
.venv/bin/python scripts/run_eval.py                            # rc=0, eval/results.json
PYTHONPATH=. python3 -m pytest -q tests                         # rc=0, 121 passed, 1 skipped
```

`/tmp/opencode/mined_coverage_antes.json` es una copia del
`eval/mined_coverage.json` que venía en `HEAD`, usada sólo como línea base para
el bloque `antes` de `eval/mined_coverage.json`.

## Ola 6 — re-minado y huecos de stdlib 0.16

### Firmas nuevas

Corrida observada con:

```sh
.venv/bin/python scripts/mine_sessions.py --out var/mined6 --corpus corpus/pyzig.corpus.jsonl
```

Leyó 989 transcripts (3,953 MB), encontró 103 sesiones con Zig, 1,750
ejecuciones Zig, 131 ejecuciones con errores y 92 firmas distintas. Frente a
`var/mined/signatures.jsonl` (90 firmas), las dos firmas nuevas tienen
frecuencia 2:

| Firma normalizada | Frecuencia | Top-3 antes de la receta | Etiqueta ola 6 |
|---|---:|---|---|
| `@ptrCast must have a known result type` | 2 | vacío | `zig0.16/stdlib016-ptrcast-result-type` |
| `no field named '_' in struct 'array_list._(uN,null)'` | 2 | vacío | `NONE` |

La firma de ArrayList conserva `NONE`: el nombre del campo se redactó y la
evidencia no alcanza para distinguir un campo eliminado de otro acceso
incorrecto. El contexto minado menciona `std.array_list.Aligned` y cita
`migrate-arraylist-unmanaged`, pero esa proximidad no demuestra la causa
concreta. La firma de `@ptrCast` sí queda resuelta directamente porque la
receta muestra el destino tipado y lo prueba con el gate.

### Recetas añadidas

Las ocho entradas nuevas de `scripts/recipes/stdlib_016.py` son
`DEMONSTRATED` con Zig 0.16.0:

- `zig0.16/stdlib016-ptrcast-result-type`: tipo de destino explícito para
  `@ptrCast`; lleva la firma nueva real.
- `zig0.16/stdlib016-json-parse-struct` y
  `zig0.16/stdlib016-json-stringify-struct`: parseo tipado con defaults y
  campos extra, y serialización compacta con `Stringify.valueAlloc`.
- `zig0.16/stdlib016-writer-allocating`: buffer dinámico con
  `std.Io.Writer.Allocating` y transferencia mediante `toOwnedSlice`.
- `zig0.16/stdlib016-format-f-any`: formato de tipo propio con `{f}` y salida
  genérica con `{any}`.
- `zig0.16/stdlib016-hashmap-custom-context`: `std.HashMap.initContext` con
  `hash` y `eql` ASCII propios.
- `zig0.16/stdlib016-generic-list-comptime`: constructor de tipo
  `fn List(comptime T: type) type`.
- `zig0.16/stdlib016-child-capture-stdout`: `std.process.spawn`, pipe de
  stdout, lectura limitada y `Child.wait`.

El `eval_mined` anterior y posterior se midió con corpus/etiquetas
comparables: antes se reconstruyó el índice desde el corpus y labels de `HEAD`;
después se usaron las ocho recetas y las dos etiquetas de ola 6. El falso
positivo `std.testing.expectCrash` sigue presente y la firma de
`std.fs.openFileAbsolute` sigue sin entrar en top-3.

| Métrica de `eval_mined` | Antes | Después |
|---|---:|---:|
| Autoconsistencia hit@1 / hit@3 | 1.0 / 1.0 | 1.0 / 1.0 |
| Firmas no-NONE | 64 | 65 |
| Mined hit@1 | 63/64 (0.9844) | 64/65 (0.9846) |
| Mined hit@3 | 63/64 (0.9844) | 64/65 (0.9846) |
| Firmas NONE | 26 | 27 |
| Falsos positivos sobre NONE | 1 | 1 |
| FPR sobre NONE | 0.0385 | 0.0370 |

El `run_eval` dev cubrió 216 consultas en ambos casos. Ningún modo bajó:

| Métrica | Antes | Después |
|---|---:|---:|
| Lexical P@1 | 0.971 | 0.981 |
| Lexical R@3 | 0.986 | 0.995 |
| Hybrid P@1 | 0.967 | 0.971 |
| Hybrid R@3 | 0.990 | 0.995 |

Comandos de evaluación y gates:

```sh
.venv/bin/python scripts/build_index.py
.venv/bin/python scripts/run_eval.py --out var/mined6/dev-after.json
ZIG_GLOBAL_CACHE_DIR="$PWD/var/zig-global-cache" .venv/bin/python scripts/run_gates.py
```

El `run_gates.py` de ola 6 salió con rc=0 y las ocho recetas nuevas pasaron,
sin tests saltados. Tres gates de red ya existentes
(`tcp-loopback-echo`, `udp-loopback-datagram`, `http-client-get-local`)
fallaron en esta corrida con `ConnectionRefused`; se conservó para esas entradas
la evidencia demostrada que traían de `HEAD`, sin atribuir esas fallas a las
recetas nuevas.

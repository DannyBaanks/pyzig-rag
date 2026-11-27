# Cobertura de Fuzzing Diferencial (`pyzig-rag`)

Inventario de todas las recetas `DEMONSTRATED` del corpus (`corpus/pyzig.corpus.jsonl`)
y resultados reproducibles de las 6 recetas promovidas a fuzzables en la ola 6 (`fuzz-mas2`).

## Resumen

- Recetas `DEMONSTRATED` totales: **106**
- Recetas `DEMONSTRATED` fuzzables: **23** (17 previas + 6 nuevas en ola 6)
- Recetas `DEMONSTRATED` no fuzzables: **83**
- Notas sobre prioridades solicitadas:
  - `base64-encode-decode`, `hex-encode-decode` y `string-split-strip-format` ya eran fuzzables antes de la ola 6.
  - `bisect` no existe como receta en el corpus actual (`NOT_DEMONSTRATED` / ausente; no se anadieron recetas nuevas).
  - En las 6 recetas nuevas no se encontro ningun bug en `zig_impl`: todas las divergencias observadas corresponden a diferencias semanticas reales Python vs Zig, acotadas con predicados fail-closed en `pyzig/fuzz/triage.py`.

## Ejecuciones reproducibles (ola 6)

Todas ejecutadas en sandbox `bwrap`, 600 iteraciones por semilla (`--chunk 200 --replay 8`),
con semillas `11` y `73` y triage posterior (`scripts/fuzz.py triage`).

| operation_id | schema | seed | casos | EQUIV | divergencias | conocidas | NUEVAS | `results_sha256` |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `zig0.16/str-find-replace-affix` | `straffix` | 11 | 600 | 549 | 51 | 51 | 0 | `f0b96bae29b05e9823576c3ae08a7b4041e054acd697508256e65dafe324cb50` |
| `zig0.16/str-find-replace-affix` | `straffix` | 73 | 600 | 549 | 51 | 51 | 0 | `1f0adb047cc45f26b22b44921ad8ebd44bb6f183555fce47fe767ec15eaac043` |
| `zig0.16/parse-float-format-decimals` | `parsefloat` | 11 | 600 | 566 | 34 | 34 | 0 | `423233f733747395f66d7b3388a772ae9e685c2d370866474277afa4091d3b2f` |
| `zig0.16/parse-float-format-decimals` | `parsefloat` | 73 | 600 | 569 | 31 | 31 | 0 | `f4c826284d105ae4974b83446ef2e60d032e807135b06401ff3065304f34e67e` |
| `zig0.16/sorted-key-stable` | `sortkey` | 11 | 600 | 600 | 0 | 0 | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `zig0.16/sorted-key-stable` | `sortkey` | 73 | 600 | 600 | 0 | 0 | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `zig0.16/int-from-bytes-to-bytes-endian` | `intbytes` | 11 | 600 | 600 | 0 | 0 | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `zig0.16/int-from-bytes-to-bytes-endian` | `intbytes` | 73 | 600 | 600 | 0 | 0 | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `zig0.16/round-floor-ceil-bankers` | `roundfloat` | 11 | 600 | 528 | 72 | 72 | 0 | `a37b4968aa7828a688fd7bc3e6814f368429f395c3e2c2275daa538fea9f2dfb` |
| `zig0.16/round-floor-ceil-bankers` | `roundfloat` | 73 | 600 | 535 | 65 | 65 | 0 | `0fdbd80d926bf5abb6bc71738428694784b806f8605654f2bbc7c8212654f720` |
| `zig0.16/utf8-codepoints-validate` | `utf8cp` | 11 | 600 | 600 | 0 | 0 | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `zig0.16/utf8-codepoints-validate` | `utf8cp` | 73 | 600 | 600 | 0 | 0 | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

### Divergencias conocidas declaradas (ola 6, todas con predicado de entrada y `why`)

- `zig0.16/str-find-replace-affix` (`straffix`):
  - `straffix-find-bytes-vs-codepoints`: `std.mem.find` devuelve offset en bytes UTF-8; `str.find` devuelve indice en codepoints. El predicado verifica `subject.out == len(s[:idx].encode('utf-8'))`.
  - `straffix-replace-empty-needle`: `replaceAll` rechaza `old == ''` con `error.EmptyNeedle`; Python `str.replace('', new)` intercala `new`. El predicado exige `a == ''` y verifica la salida exacta de Python.
- `zig0.16/parse-float-format-decimals` (`parsefloat`):
  - `parsefloat-recorta-espacios-ascii`: `float()` recorta espacios ASCII en bordes; `std.fmt.parseFloat` los rechaza.
  - `parsefloat-hexfloat-zig`: `std.fmt.parseFloat` acepta hexfloats (`0x1p3`, `0x1.8p+1`); `float()` los rechaza. El predicado verifica igualdad bit a bit contra `float.fromhex(text)`.
  - `parsefloat-fmt2-shortest-decimal`: Zig `{d:.2}` redondea mitad-lejos-de-cero sobre la representacion decimal mas corta (`repr(x)`), por ejemplo `2.675 -> 2.68`, `0.125 -> 0.13`, `1849355331531703.75 -> 1849355331531703.80`; Python `f'{x:.2f}'` redondea al par sobre el binario exacto (`2.67`, `0.12`, `...75`). El predicado verifica `Decimal(repr(x)).quantize(Decimal('0.01'), ROUND_HALF_UP)` exacto.
- `zig0.16/round-floor-ceil-bankers` (`roundfloat`):
  - `roundfloat-no-finito`: `@round`/`@floor`/`@ceil`/`roundHalfEven` propagan `inf`/`-inf`/`nan` como `f64`; Python lanza `OverflowError`/`ValueError` al devolver `int`.
  - `roundfloat-menos-cero`: las operaciones IEEE-754 preservan `-0.0` (`-0`); `int` de Python solo tiene `0`.
  - `roundfloat-zig-round-empate`: `zigRound` (`@round`) redondea empates `.5` alejando de cero; `round()` de Python al par. Solo aplica a `op == 'zig_round'`; cualquier error de `roundHalfEven`, `zigFloor` o `zigCeil` queda como NUEVA.
- `zig0.16/sorted-key-stable` (`sortkey`), `zig0.16/int-from-bytes-to-bytes-endian` (`intbytes`) y `zig0.16/utf8-codepoints-validate` (`utf8cp`): 0 divergencias en 1200 casos cada una (2 semillas x 600).

## Inventario completo de recetas `DEMONSTRATED` (106)

| # | operation_id | source_lang | fuzzable | schema | nota / motivo |
|---:|---|---|---|---|---|
| 1 | `zig0.16/subprocess-run-capture` | `python` | si | `argv` | driver `drivers/argv.zig`, 6 campos, 1 divergencia(s) conocida(s) |
| 2 | `zig0.16/read-file-text-limited` | `python` | si | `read` | driver `drivers/read.zig`, 3 campos, 2 divergencia(s) conocida(s) |
| 3 | `zig0.16/write-file-bytes-atomic` | `python` | si | `write` | driver `drivers/write.zig`, 3 campos, 0 divergencia(s) conocida(s) |
| 4 | `zig0.16/file-exists-vs-error` | `python` | si | `exists` | driver `drivers/exists.zig`, 3 campos, 0 divergencia(s) conocida(s) |
| 5 | `zig0.16/stdout-print-flush` | `python` | si | `stdout` | driver `drivers/stdout.zig`, 4 campos, 0 divergencia(s) conocida(s) |
| 6 | `zig0.16/parse-kv-config` | `python` | si | `kv` | driver `drivers/kv.zig`, 6 campos, 0 divergencia(s) conocida(s) |
| 7 | `zig0.16/sleep-ms` | `python` | si | `sleep` | driver `drivers/sleep.zig`, 3 campos, 0 divergencia(s) conocida(s) |
| 8 | `zig0.16/string-split-strip-format` | `python` | si | `splitfmt` | driver `drivers/splitfmt.zig`, 4 campos, 1 divergencia(s) conocida(s) |
| 9 | `zig0.16/spawn-redirect-child` | `python` | si | `spawn` | driver `drivers/spawn.zig`, 6 campos, 0 divergencia(s) conocida(s) |
| 10 | `zig0.16/env-var-read` | `python` | si | `env` | driver `drivers/env.zig`, 4 campos, 0 divergencia(s) conocida(s) |
| 11 | `zig0.16/sha256-bytes` | `python` | si | `sha256` | driver `drivers/sha256.zig`, 3 campos, 0 divergencia(s) conocida(s) |
| 12 | `zig0.16/build-exe-root-module` | `zig-build` | no | - | Receta de `build.zig` (Zig-solo, sin equivalente Python ejecutable por caso). |
| 13 | `zig0.16/build-link-libc` | `zig-build` | no | - | Receta de `build.zig` (Zig-solo, sin equivalente Python ejecutable por caso). |
| 14 | `zig0.16/build-add-import` | `zig-build` | no | - | Receta de `build.zig` (Zig-solo, sin equivalente Python ejecutable por caso). |
| 15 | `zig0.16/build-import-outside-module` | `zig-build` | no | - | Receta de `build.zig` (Zig-solo, sin equivalente Python ejecutable por caso). |
| 16 | `zig0.16/build-shared-library` | `zig-build` | no | - | Receta de `build.zig` (Zig-solo, sin equivalente Python ejecutable por caso). |
| 17 | `zig0.16/build-dynamic-library-pic` | `zig-build` | no | - | Receta de `build.zig` (Zig-solo, sin equivalente Python ejecutable por caso). |
| 18 | `zig0.16/build-test-step` | `zig-build` | no | - | Receta de `build.zig` (Zig-solo, sin equivalente Python ejecutable por caso). |
| 19 | `zig0.16/build-c-source-files` | `zig-build` | no | - | Receta de `build.zig` (Zig-solo, sin equivalente Python ejecutable por caso). |
| 20 | `zig0.16/dict-str-int-basic` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 21 | `zig0.16/list-append-pop-insert` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 22 | `zig0.16/sorted-key-stable` | `python` | si (ola 6) | `sortkey` | driver `drivers/sortkey.zig`, 3 campos, 0 divergencia(s) conocida(s) |
| 23 | `zig0.16/set-str-membership` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 24 | `zig0.16/heapq-priority-queue` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 25 | `zig0.16/deque-popleft-appendleft` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 26 | `zig0.16/counter-most-common` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 27 | `zig0.16/diag-mined-member-format` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 28 | `zig0.16/diag-mined-undeclared-ident` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 29 | `zig0.16/diag-mined-asm-constraint` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 30 | `zig0.16/diag-mined-unused-discard` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 31 | `zig0.16/diag-mined-duplicate-names` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 32 | `zig0.16/diag-mined-int-range` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 33 | `zig0.16/diag-mined-comptime-flow` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 34 | `zig0.16/diag-mined-vector-index` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 35 | `zig0.16/diag-mined-bitcast-size` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 36 | `zig0.16/diag-mined-error-union` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 37 | `zig0.16/diag-mined-pointer-coercion` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 38 | `zig0.16/diag-mined-embed-outside` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 39 | `zig0.16/diag-mined-module-conflict` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 40 | `zig0.16/diag-eval-branch-quota` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 41 | `zig0.16/diag-never-mutated` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 42 | `zig0.16/diag-shadow-local` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 43 | `zig0.16/diag-shadow-primitive` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 44 | `zig0.16/diag-comptime-redundant` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 45 | `zig0.16/diag-inline-redundant` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 46 | `zig0.16/diag-comptime-runtime-value` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 47 | `zig0.16/diag-comptime-runtime-call` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 48 | `zig0.16/diag-ptrcast-const` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 49 | `zig0.16/diag-narrowing-intcast` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 50 | `zig0.16/diag-builtin-undeclared` | `zig-0.16` | no | - | Diagnostico de error de compilacion Zig (sin oraculo Python). |
| 51 | `zig0.16/path-join-basename-ext` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 52 | `zig0.16/listdir-names-sorted` | `python` | no | - | Efectos sobre arbol de directorios; requiere generador de fixtures FS y limpieza por caso (sin driver todavia). |
| 53 | `zig0.16/walk-tree-files` | `python` | no | - | Efectos sobre arbol de directorios; requiere generador de fixtures FS y limpieza por caso (sin driver todavia). |
| 54 | `zig0.16/makedirs-exist-ok` | `python` | no | - | Efectos sobre arbol de directorios; requiere generador de fixtures FS y limpieza por caso (sin driver todavia). |
| 55 | `zig0.16/temp-dir-scoped` | `python` | no | - | Efectos sobre arbol de directorios; requiere generador de fixtures FS y limpieza por caso (sin driver todavia). |
| 56 | `zig0.16/copyfile-replace` | `python` | no | - | Efectos sobre arbol de directorios; requiere generador de fixtures FS y limpieza por caso (sin driver todavia). |
| 57 | `zig0.16/remove-file-rmtree` | `python` | no | - | Efectos sobre arbol de directorios; requiere generador de fixtures FS y limpieza por caso (sin driver todavia). |
| 58 | `zig0.16/thread-spawn-join` | `python` | no | - | Concurrencia, red loopback o FFI `-lc`: requiere arnes con estado/sockets/enlazado C (no determinista por caso puro). |
| 59 | `zig0.16/thread-shared-counter` | `python` | no | - | Concurrencia, red loopback o FFI `-lc`: requiere arnes con estado/sockets/enlazado C (no determinista por caso puro). |
| 60 | `zig0.16/io-async-group-future` | `python` | no | - | Concurrencia, red loopback o FFI `-lc`: requiere arnes con estado/sockets/enlazado C (no determinista por caso puro). |
| 61 | `zig0.16/tcp-loopback-echo` | `python` | no | - | Concurrencia, red loopback o FFI `-lc`: requiere arnes con estado/sockets/enlazado C (no determinista por caso puro). |
| 62 | `zig0.16/udp-loopback-datagram` | `python` | no | - | Concurrencia, red loopback o FFI `-lc`: requiere arnes con estado/sockets/enlazado C (no determinista por caso puro). |
| 63 | `zig0.16/http-client-get-local` | `python` | no | - | Concurrencia, red loopback o FFI `-lc`: requiere arnes con estado/sockets/enlazado C (no determinista por caso puro). |
| 64 | `zig0.16/ffi-extern-c-function` | `python` | no | - | Concurrencia, red loopback o FFI `-lc`: requiere arnes con estado/sockets/enlazado C (no determinista por caso puro). |
| 65 | `zig0.16/json-loads-dynamic` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 66 | `zig0.16/json-loads-typed-struct` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 67 | `zig0.16/json-dumps-indent` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 68 | `zig0.16/json-invalid-input-error` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 69 | `zig0.16/json-string-escape-unicode` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 70 | `zig0.16/json-read-file-limited` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 71 | `zig0.16/format-string-alloc-print` | `python` | no | - | Formato Zig comptime fijo; sin especificador runtime arbitrario (solo los wrappers concretos serian fuzzables). |
| 72 | `zig0.16/float-special-values-isinf-isnan` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 73 | `zig0.16/struct-pack-endian-readint` | `python` | si | `packint` | driver `drivers/packint.zig`, 4 campos, 0 divergencia(s) conocida(s) |
| 74 | `zig0.16/int-from-bytes-to-bytes-endian` | `python` | si (ola 6) | `intbytes` | driver `drivers/intbytes.zig`, 4 campos, 0 divergencia(s) conocida(s) |
| 75 | `zig0.16/div-floor-mod-negative` | `python` | si | `divmod` | driver `drivers/divmod.zig`, 4 campos, 0 divergencia(s) conocida(s) |
| 76 | `zig0.16/int-bit-count-bit-length` | `python` | si | `bits` | driver `drivers/bits.zig`, 3 campos, 0 divergencia(s) conocida(s) |
| 77 | `zig0.16/round-floor-ceil-bankers` | `python` | si (ola 6) | `roundfloat` | driver `drivers/roundfloat.zig`, 3 campos, 3 divergencia(s) conocida(s) |
| 78 | `zig0.16/cstring-span-slice-to` | `python` | no | - | Punteros C con centinela (`[*:0]`/`[*c]`): riesgo de UB fuera de `sliceTo`; sin driver todavia. |
| 79 | `zig0.16/migrate-readfilealloc` | `zig-0.13/0.14` | no | - | Migracion o idioma Zig->Zig (sin equivalente Python directo). |
| 80 | `zig0.16/migrate-writefile` | `zig-0.13/0.14` | no | - | Migracion o idioma Zig->Zig (sin equivalente Python directo). |
| 81 | `zig0.16/migrate-stdout-writer` | `zig-0.13/0.14` | no | - | Migracion o idioma Zig->Zig (sin equivalente Python directo). |
| 82 | `zig0.16/migrate-arraylist-unmanaged` | `zig-0.13/0.14` | no | - | Migracion o idioma Zig->Zig (sin equivalente Python directo). |
| 83 | `zig0.16/migrate-type-builtin` | `zig-0.13/0.14` | no | - | Migracion o idioma Zig->Zig (sin equivalente Python directo). |
| 84 | `zig0.16/migrate-child-run` | `zig-0.13/0.14` | no | - | Migracion o idioma Zig->Zig (sin equivalente Python directo). |
| 85 | `zig0.16/migrate-time-sleep` | `zig-0.13/0.14` | no | - | Migracion o idioma Zig->Zig (sin equivalente Python directo). |
| 86 | `zig0.16/migrate-thread-mutex` | `zig-0.13/0.14` | no | - | Migracion o idioma Zig->Zig (sin equivalente Python directo). |
| 87 | `zig0.16/migrate-open-dir-absolute` | `zig-0.13/0.14` | no | - | Migracion o idioma Zig->Zig (sin equivalente Python directo). |
| 88 | `zig0.16/migrate-arraylist-writer` | `zig-0.16` | no | - | Migracion o idioma Zig->Zig (sin equivalente Python directo). |
| 89 | `zig0.16/cstring-sentinel-slice-ptr` | `zig-0.16` | no | - | Migracion o idioma Zig->Zig (sin equivalente Python directo). |
| 90 | `zig0.16/csv-reader-line-quoted` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 91 | `zig0.16/epoch-to-utc-ymd-hms` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 92 | `zig0.16/argparse-subcommands` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 93 | `zig0.16/base64-encode-decode` | `python` | si | `base64` | driver `drivers/base64.zig`, 3 campos, 0 divergencia(s) conocida(s) |
| 94 | `zig0.16/hex-encode-decode` | `python` | si | `hex` | driver `drivers/hex.zig`, 3 campos, 1 divergencia(s) conocida(s) |
| 95 | `zig0.16/parse-int-base-overflow` | `python` | si | `parseint` | driver `drivers/parseint.zig`, 3 campos, 3 divergencia(s) conocida(s) |
| 96 | `zig0.16/parse-float-format-decimals` | `python` | si (ola 6) | `parsefloat` | driver `drivers/parsefloat.zig`, 3 campos, 3 divergencia(s) conocida(s) |
| 97 | `zig0.16/str-find-replace-affix` | `python` | si (ola 6) | `straffix` | driver `drivers/straffix.zig`, 3 campos, 2 divergencia(s) conocida(s) |
| 98 | `zig0.16/utf8-codepoints-validate` | `python` | si (ola 6) | `utf8cp` | driver `drivers/utf8cp.zig`, 5 campos, 0 divergencia(s) conocida(s) |
| 99 | `zig0.16/ascii-case-lower-upper` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 100 | `zig0.16/epoch-now-seconds` | `python` | no | - | Depende de reloj del sistema o algoritmo PRNG distinto (Mersenne Twister vs Xoshiro256). |
| 101 | `zig0.16/monotonic-duration-measure` | `python` | no | - | Depende de reloj del sistema o algoritmo PRNG distinto (Mersenne Twister vs Xoshiro256). |
| 102 | `zig0.16/random-prng-ops` | `python` | no | - | Depende de reloj del sistema o algoritmo PRNG distinto (Mersenne Twister vs Xoshiro256). |
| 103 | `zig0.16/process-args-iterate` | `python` | no | - | Iteracion sobre `std.process.Args` del proceso (argv OS); sin driver todavia. |
| 104 | `zig0.16/argparse-flags-parse` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 105 | `zig0.16/crc32-checksum` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |
| 106 | `zig0.16/md5-hexdigest` | `python` | no | - | Fuzzable potencialmente (Python->Zig puro), pendiente de driver y modelo (sin driver diferencial todavia). |

# Pilotos A/B (pyzig-rag)

## `hard-2026-11-27-bp2` — t13 con agente real (opencode/big-pickle): EFECTO TECHO, sin efecto medible

**Resultado [CURRENT 2026-11-27, 11:25–11:56Z]:** 8 tareas t13 × brazos A/B, `--max-attempts 3`, seed 1337.

| brazo | tareas PASS | PASS al 1er intento | llamadas pyzig observadas | mediana s/intento* |
|---|---|---|---|---|
| A (sin pyzig) | 8/8 | 8/8 | 0 | ~45 |
| B (con pyzig CLI) | 8/8 | 7/8 (t13_sleep_elapsed: 1 AGENT_ERROR y PASS al 2º) | 52 (3–14 por tarea) | ~128 |

\* aproximado: diferencia entre marcas `ts` consecutivas de `attempts.jsonl` (incluye la puntuación).

- big-pickle resuelve las 8 tareas de APIs 0.16 **sin** pyzig y al primer intento: tiene shell y `zig 0.16.0`
  dentro del intento y se corrige con el compilador. Con estas tareas y este modelo **no hay margen** para
  medir mejora; el brazo B usa pyzig mucho (el registro observado funciona) pero tarda ~2.8× más.
- Efecto de pyzig sobre éxito: **NOT_DEMONSTRATED** (techo). Sobre coste: B más lento en esta muestra (n=8, un modelo).
- Siguiente paso para que el A/B discrimine: intentos sin shell/compilador (un solo disparo), o un modelo más débil.

Corridas fallidas conservadas como evidencia (no son resultados del ensayo):
- `hard-2026-11-27/`: modelo `nvidia/nemotron-3-ultra-550b-a55b:free`; 38/41 `AGENT_ERROR` por
  `Rate limit exceeded: free-models-per-day` (abortada a mano).
- `hard-2026-11-27-bigpickle/`: 48/48 rc 126 — `--agent-cmd` con ruta con espacio sin comillas internas
  (error del coordinador). Desde `09a638a`, `ab_run` aborta (rc 75) ante cuota agotada o rc 126/127.
- `smoke-bp/`: humo de 1 tarea (B) antes de la corrida buena: PASS, 3 llamadas pyzig.

## `hard-2026-11-27` — tareas difíciles t13 (ola 6): arnés listo, corrida con agente BLOQUEADA

**Estado: NOT_DEMONSTRATED.** El arnés, las 8 tareas y su verificación están listos y commiteados.
La corrida real con agente no se ha podido ejecutar: el proveedor gratuito de `opencode/big-pickle`
devolvió `Free usage limit reached` en todos los intentos (2026-11-27, 09:41–09:53Z, sondeo cada ~4 min).
Los demás modelos gratuitos de `opencode models` probados (`opencode/beam-free`,
`opencode/deepseek-v4.1-flash-free`, `opencode/flint-40b-free`, `opencode/hy4-flash-free`) dieron
el mismo límite; los `aihubmix/*-free` respondieron `The requested API endpoint does not exist` y
`kilo/kilo-auto/free` `authentication token is invalid`. **No hay ninguna observación de pyzig con
agente real en esta sección.** Ningún número de este bloque es un resultado del ensayo.

Comando previsto (no ejecutado; se lanza en segundo plano con `--cache-dir` y `--out` absolutos):

```sh
PYTHONPATH=. .venv/bin/python scripts/ab_run.py \
  --tasks t13_arraylist_evens,t13_hashmap_distinct,t13_json_items,t13_process_stdout,t13_read_whole_file,t13_sleep_elapsed,t13_thread_mutex_sum,t13_writer_rows \
  --arms A,B --seed 1337 --max-attempts 3 --timeout 400 \
  --agent-cmd "'$PWD/scripts/ab_agent_opencode.sh'" \
  --out "$PWD/ab/runs/hard-2026-11-27" --cache-dir "$PWD/var/ab/cache"
```

### Qué cambió en el arnés (verificado)

- **`observed_tool_calls` (verdad de terreno).** `scripts/pyzig_cli.py` añade una línea JSON por
  invocación (`ts`, `subcommand`, `args`, `rc`, `pid`) a `$AB_TOOL_LOG/tool-calls.jsonl`; `ab_run.py`
  fija `AB_TOOL_LOG` al directorio del intento, guarda la lista en `attempts.jsonl` junto a
  `reported_tool_calls` (lo que declara el agente) y copia el log a `tool-calls-attempt-NN.jsonl`.
  Limitación: solo registra invocaciones de `$PYZIG_CLI`; las llamadas MCP directas del agente no pasan
  por la CLI y no aparecen aquí.
- **Rutas portables.** `manifest.json`, `score.json`, `attempts.jsonl` (incl. `agent_stderr_tail`) y los
  `meta`/log copiados pasan por `ab_score.portable()`: raíz del repo → relativa, home → `~/`.
- **Tareas t13_*** (8, con `zig_test` de `std` y oráculo, sin red ni archivos externos): APIs de Zig 0.16
  que cambiaron respecto a versiones anteriores: `std.Io.Dir.readFileAlloc`, `std.ArrayList` con `.empty`
  y allocator por llamada, `std.Io.Writer` (`print`, `fixed`), `std.process.run` (en 0.16 sustituye a la
  forma `Child.run` que aparece en el enunciado), `std.json.parseFromSlice`, `std.StringHashMap`,
  `std.Thread.spawn` + `std.Io.Mutex`, `std.Io.sleep` con reloj `awake`.
  Caveat: las APIs tienen recetas en `corpus/pyzig.corpus.jsonl` (es el tratamiento B); los nombres de
  función no aparecen en el corpus (`tests/test_ab.py` lo comprueba).

### Verificación sin agente (comandos y salida resumida)

- `PYTHONPATH=. python3 -m pytest -q tests/test_ab.py tests/test_ab_scoring_fixes.py tests/test_ab_observed.py`
  → `21 passed` (tests de `test_ab_observed.py`: 6 nuevos; `test_ab.py` ya no fija 12 tareas).
- `ab_run.py --dry-run` sobre las 8 tareas (soluciones de referencia `ab/examples/solutions/good/{A,B}`):
  16/16 PASS en la pasada completa. Una primera pasada dio 2 `TIMEOUT` (brazo A, `t13_arraylist_evens` y
  `t13_hashmap_distinct`, límite de 60 s de `pyzig.check`) con la carga de la máquina en load average ~33;
  repetidos aislados pasan (`PASS`, rc 0). Se trata como fallo transitorio del entorno, no del código.
- Un intento de `TIMEOUT` cuenta como `unscored` en `ab_score` (no como fallo ni como éxito).

### Pendiente para cerrar el ensayo

1. Repetir el comando de arriba cuando el proveedor vuelva a responder (`opencode run -m opencode/big-pickle 'Reply PONG'`).
2. Publicar aquí `summary` por brazo de `score.json` y `observed_tool_calls` frente a `reported_tool_calls`.
   Sin esas cifras, la sección no afirma efecto alguno de pyzig.
3. Con n=8 pares, cualquier diferencia será descriptiva; la regla de decisión de `ab/PROTOCOL.md` §7 sigue
   siendo la del pre-registro de 12 tareas (t01–t12), que no se ha modificado.

---

## `pilot-llm-2026-11-27` — agente LLM real (opencode + big-pickle)

**Estado: piloto con agente real ejecutado. Efecto de pyzig: `NOT_DEMONSTRATED` (efecto techo, n = 4).**

Comando (desde la raíz del repo; agente `scripts/ab_agent_opencode.sh`, que corre
`opencode run -m opencode/big-pickle` en el dir temporal del intento y devuelve `./solution.zig`):

```sh
PYTHONPATH=. .venv/bin/python scripts/ab_run.py \
  --tasks t01_bisect_left,t02_gcd_lcm,t04_word_count,t06_unique_sorted \
  --arms A,B --seed 1337 --max-attempts 3 --timeout 400 \
  --agent-cmd "'$PWD/scripts/ab_agent_opencode.sh'" \
  --out ab/runs/pilot-llm-2026-11-27 --cache-dir "$PWD/var/ab/cache"
```

rc 0. Resultado (de `ab/runs/pilot-llm-2026-11-27/score.json` y `attempts.jsonl`):

| brazo | tareas | pasadas | intentos hasta pasar | errores de compilación | llamadas pyzig declaradas |
|---|---|---|---|---|---|
| A (sin pyzig) | 4 | 4 | 1 en las 4 | 0 | 0 |
| B (`$PYZIG_CLI`) | 4 | 4 | 1 en las 4 | 0 | 4, 6, 6 y 9 por tarea |

- **Sin diferencia medible**: ambos brazos resuelven todo al primer intento. Las 4 tareas son demasiado
  fáciles para este modelo (efecto techo); el piloto no puede mostrar si pyzig ayuda.
- B usa pyzig de verdad (`search`/`get`/`check`; comandos en `reported_tool_calls`), pero esas llamadas
  las **declara el propio agente** en `AB_ATTEMPT_META`; el `agent_stderr_tail` está recortado y solo
  confirma algunas. A verificó sus soluciones con `zig test` en su dir temporal (zig está instalado en
  ambos brazos).
- Tokens y latencias: `NOT_AVAILABLE` (opencode no los expone al wrapper).
- Siguiente paso para un ensayo con poder: tareas donde el modelo falle sin ayuda (APIs que cambiaron
  en 0.16: `std.Io`, `ArrayList` sin gestor, build.zig con `root_module`), más tareas y más de un modelo.

Sha256 (tras quitar rutas locales: raíz del repo → relativa, home → `~/`): `attempts.jsonl` 4e2bfd80…, `score.json` b3f0afbb…, `manifest.json` ad89a09c….

### Bugs del arnés encontrados al correrlo (arreglados antes de esta corrida)

Las dos primeras corridas dieron 0/24 COMPILE_FAIL **falsos**:
1. Con la ruta del repo con espacios, `--agent-cmd` sin comillas y `PYZIG_CLI` = `PYTHONPATH=... python ...`
   no se ejecutaban (`$PYZIG_CLI` sin comillas no re-interpreta asignaciones ni comillas). Ahora
   `PYZIG_CLI` es un wrapper ejecutable en una ruta sin espacios (e06b862).
2. Las pruebas del arnés usan `std`, pero el prompt solo pide importarlo si hace falta: una solución
   correcta sin `std` fallaba siempre. `ab_score.combine` lo añade si falta.
3. `--cache-dir` relativo rompía el `--bind` de bwrap y `pyzig.check` lo contaba como COMPILE_FAIL sin
   errores (afectaba también a `pyzig_check`): ahora se resuelve a absoluto y un fallo de bwrap devuelve
   `SANDBOX_ERROR`.
4. `--force` reusaba el `--out`: `attempts.jsonl` mezclaba filas viejas y `ab_score` puntuaba
   `attempt-NN.zig` sobrantes. Ahora aparta la corrida previa a `<out>.prev-<UTC>` (no borra).

Regresiones en `tests/test_ab_scoring_fixes.py`.

---

## `pilot-2026-11-20` — arnés con agente sintético (stub)

**Estado: piloto de arnés con agente sintético (stub). Comparación A/B de agentes LLM reales: `NOT_DEMONSTRATED`** (cubierto después por `pilot-llm-2026-11-27`).  
n = 4 tareas (diminuto): resultados **descriptivos**, sin afirmar efecto.

## Objetivo y alcance

Ejecutar un piloto del ensayo controlado definido en `ab/PROTOCOL.md`:
- 4 tareas × 2 brazos (A = sin herramientas pyzig, B = con acceso a pyzig vía CLI) × hasta 3 intentos.
- Orden aleatorizado con semilla fija.
- Registro de `agent_rc` y tratamiento de `rc != 0` como intento fallido `AGENT_ERROR` (implementado en `scripts/ab_run.py`).
- Aislamiento best-effort: cada intento corre en un directorio temporal vacío fuera del repo (cwd aislado), con el prompt por stdin; para el brazo B se expone `PYZIG_CLI` en el entorno sin documentar rutas del repo en el prompt.

## Cambios previos al piloto (verificador)

1. **(a) Prompts sin casos concretos del oráculo**: `ab/tasks/t02_gcd_lcm.json` reescrito para no listar `gcd(0, 0) == 0`, `gcd(0, 5) == 5`, `lcm(0, 5) == 0`; describe semántica de Python para ceros sin valores concretos. Revisión del resto de tareas (`ab/tasks/*.json`): no se encontraron otros casos concretos del oráculo en los prompts (solo especificaciones de comportamiento).
2. **(b) `agent_rc` y `AGENT_ERROR`**: `scripts/ab_run.py` registra `agent_rc` (int, `TIMEOUT` o `SPAWN_ERROR`) y si el agente termina con rc distinto de 0 el intento se marca `status=AGENT_ERROR`, `passed=false` (aunque el código compilara). `scripts/ab_score.py` respeta overrides `AGENT_ERROR` desde `attempts.jsonl` al re-puntuar.
3. **(c) Aislamiento**: cada intento ejecuta el agente en `tempfile.mkdtemp(..., dir=/tmp/opencode/ab-work)` fuera del repo; el `workdir` se registra en `attempts.jsonl`. No se copia el repo/corpus/ejemplos al workdir. Para B se define `PYZIG_CLI` (comando que invoca `.venv/bin/python <repo>/scripts/pyzig_cli.py` con `PYTHONPATH=<repo>`) en el entorno del proceso; el prompt de B documenta `$PYZIG_CLI`, no rutas del repo. **Limitación:** aislamiento no es un sandbox fuerte del proceso agente: un agente malicioso podría inspeccionar variables de entorno y leer rutas absolutas del repo; no se usa bwrap/namespace para el agente (solo para `pyzig_check`/scoring).

Se añadió `scripts/pyzig_cli.py` (CLI: `search|get|check`, JSON en stdout) y pruebas en `tests/test_ab.py` (`test_agent_nonzero_rc_is_recorded_as_agent_error`).

## Selección de tareas y diseño del piloto

- Tareas (4): `t01_bisect_left` (control), `t02_gcd_lcm` (control, prompt corregido), `t04_word_count` (recombinación), `t06_unique_sorted` (recombinación).
- Semilla: `1337`, `--max-attempts 3`, brazos `A,B`.
- Orden de ejecución (manifest): `t02_gcd_lcm`, `t01_bisect_left`, `t06_unique_sorted`, `t04_word_count`.
- Orden de brazos por tarea (manifest): `t02_gcd_lcm: [B,A]`, `t01_bisect_left: [A,B]`, `t06_unique_sorted: [B,A]`, `t04_word_count: [A,B]`.
- Salida: `ab/runs/pilot-2026-11-20/`.

Fuente: `ab/runs/pilot-2026-11-20/manifest.json` (validado con `python3 -m json.tool`).

## Intento de agente LLM real (`opencode run`, modelo gratis) — `NOT_DEMONSTRATED`

Se intentó cumplir la especificación "agente headless `opencode run` con un modelo GRATIS":

- `opencode --version`: `opencode v2.2.5` (rc 0). `opencode models | wc -l`: 1566; `| grep -i free | wc -l`: 307 (observado en este entorno).
- Pruebas de disponibilidad (comandos `timeout 45-120 opencode run --format default --model <m> 'Reply with exactly PONG'`, salidas resumidas):
  - `aihubmix/coding-glm-5.1-free`, `aihubmix/coding-minimax-m2.7-free`, `aihubmix/gemma-4-26b-a4b-it-free`, `aihubmix/gemma-4-31b-it-free`, `aihubmix/coding-glm-5.3-flash-free`, `aihubmix/coding-glm-5.2-free`, `aihubmix/coding-glm-5.3-free`, `aihubmix/deepseek-v4.1-flash`, `aihubmix/glm-4.7-flash-free`: salida contenía `Error: The requested API endpoint does not exist.` y `rc=0` (opencode no propagó error como código de salida).
  - `freellmapi/gpt-4o-mini` (`--format json`, timeout 90s): solo evento `step_start`, sin finalización antes del timeout (rc 124 por `timeout`).
  - `freellmapi/gpt-5-nano`, `freellmapi/gemini-2.5-flash`: rc 0 sin respuesta visible útil en formato default (solo cabecera de build) en ventana de 45s.
  - `freellmapi/llama-instant`: salidas repetidas `> build · llama-instant` sin respuesta útil (45s, rc 0).
  - `freellmapi/gemini-2.5-flash-lite`: invocó herramienta interna (`codex_run`) en la salida observada, sin respuesta final clara en 60s.
- `swarm-ext`: no instalado (`which swarm-ext` → no encontrado).

**Conclusión:** no se encontró un modelo gratis funcional para `opencode run` headless en este entorno durante la sesión. No fue posible ejecutar un piloto real con agente LLM (A vs B). Una prueba de 1 tarea × 2 brazos × 1 intento con `opencode run` no completó dentro del presupuesto de tiempo de la herramienta de shell (120s) por la latencia de agente+scoring; se canceló y se optó por un piloto sintético para validar el arnés.

## Piloto ejecutado (sintético, validación de arnés)

Para producir `ab/runs/pilot-2026-11-20/` con manifiesto y score JSON y ejercer aislamiento/registro/rc, se usó un agente stub determinista (no LLM) que lee el prompt de stdin y emite Zig inválido con `rc=0`:

```sh
# desde la raíz del worktree
PYTHONPATH=. .venv/bin/python scripts/ab_run.py \
  --tasks t01_bisect_left,t02_gcd_lcm,t04_word_count,t06_unique_sorted \
  --arms A,B --seed 1337 --max-attempts 3 --timeout 30 \
  --agent-cmd "python3 -c \"import sys; sys.stdin.read(); print('const std = @import(\\\"std\\\");')\"" \
  --out ab/runs/pilot-2026-11-20 --cache-dir /tmp/opencode/ab-cache-pilot --force
```

Salida resumida (rc 0): `mode=agent`, resumen A y B idéntico: `tasks_total=4, passed=0, pass_rate=0.0, compiles_total=12, compile_errors_total=12, error_records_total=12, tests_passed_attempts_total=0, unscored_attempts_total=0, compiles_until_pass.n=0, tokens_total="NOT_AVAILABLE"`.

## Resultados (descriptivos, n=4)

Fuente: `ab/runs/pilot-2026-11-20/score.json` y `manifest.json`.

| Brazo | tareas | pasadas | pass_rate | compilaciones (intentos observados) | errores de compilación | registros de error | intentos con tests pasados | hasta pasar (n/mean/median) | tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| A | 4 | 0 | 0.0 | 12 | 12 | 12 | 0 | n=0, mean=null, median=null | NOT_AVAILABLE |
| B | 4 | 0 | 12 | 12 | 12 | 0 | n=0, mean=null, median=null | NOT_AVAILABLE |

(Tabla derivada de los `summary` por brazo en `score.json`; B tiene las mismas cifras que A en este stub.)

- 24 intentos totales (4 tareas × 2 brazos × 3 intentos). Ningún `AGENT_ERROR`, ningún `unscored`, todos `COMPILE_FAIL` (el stub devolvió `const std = @import("std");` sin las funciones requeridas). `agent_rc=0` en los registros muestreados.
- `reported_tool_calls`: null (stub no usó `$PYZIG_CLI` en B). La capacidad de B (`PYZIG_CLI`/prompt) existe en el arnés pero **no fue ejercitada por un agente real**: `NOT_DEMONSTRATED`.
- Tiempos/latencias por intento: `NOT_DEMONSTRATED` (no se registran como métrica).

## Limitaciones y `NOT_DEMONSTRATED`

- **Efecto A/B real (H1/H0 de `PROTOCOL.md`)**: `NOT_DEMONSTRATED`. El piloto no usó agentes LLM; n=4 y todas las tareas fallaron con el mismo stub, por lo que no hay evidencia sobre compilaciones hasta pasar, tokens ni uso de herramientas.
- **Agente LLM gratis vía `opencode run`**: `NOT_DEMONSTRATED`/no disponible en este entorno (modelos probados con endpoint inexistente o sin respuesta útil; `rc=0` en varios casos de error de opencode — relevante para detección de fallos).
- **Ejecución de shell/herramientas por agente en B**: `NOT_DEMONSTRATED` (stub no invocó `$PYZIG_CLI`).
- **Aislamiento fuerte**: `NOT_DEMONSTRATED`. Solo aislamiento best-effort por cwd temporal fuera del repo; sin confinamiento del proceso agente. Posible fuga por lectura de rutas absolutas si el agente las infiere del entorno.
- **Token/coste real**: `NOT_AVAILABLE`.
- **Generalización**: n diminuto (4 tareas), piloto no representativo; no permite inferencias estadísticas.

## Comandos de verificación ejecutados (salidas resumidas, rc)

| Comando | Resumen | rc |
|---|---|---:|
| `zig version` | `0.16.0` | 0 |
| `command -v bwrap` | `/usr/bin/bwrap` | 0 |
| `PYTHONPATH=. python3 -m pytest -q tests/test_ab.py` | `10 passed in 58.29s` (tras añadir test de `AGENT_ERROR`) | 0 |
| `PYTHONPATH=. python3 -m pytest -q tests` | `117 passed, 1 skipped in 45.28s` | 0 |
| `PYTHONPATH=. .venv/bin/python scripts/build_index.py` | `indice: .../var/pyzig.db entradas=102 embeddings=onnx` | 0 |
| `PYTHONPATH=. .venv/bin/python scripts/pyzig_cli.py check` (stdin con test mínimo) | `ok=true, compiled=true, tests_passed=true` | 0 |
| `PYTHONPATH=. .venv/bin/python scripts/pyzig_cli.py search "leer archivo de texto con limite" --limit 2` | `ok=true, count=2, top=zig0.16/read-file-text-limited` (tras construir índice) | 0 |
| `python3 -m json.tool ab/runs/pilot-2026-11-20/manifest.json` / `score.json` | válidos (`manifest ok`, `score ok`) | 0 |
| `PYTHONPATH=. .venv/bin/python scripts/ab_run.py ... --out ab/runs/pilot-2026-11-20` (comando de piloto arriba) | `mode=agent`, A/B: 4 tareas, 0 pasadas, 12 compiles, 12 compile_errors, tokens NOT_AVAILABLE | 0 |

Notas: `var/pyzig.db` es artefacto regenerable (no commiteado). Las pruebas de modelos `opencode` se ejecutaron manualmente con `timeout` y se resumen en este documento (varios con `rc=0` pese a error reportado por opencode, y otros sin completar).

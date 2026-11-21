# Piloto A/B (ola 5, pyzig-rag) — `pilot-2026-11-20`

**Estado: piloto de arnés con agente sintético (stub). Comparación A/B de agentes LLM reales: `NOT_DEMONSTRATED`.**  
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

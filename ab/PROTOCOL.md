# Protocolo pre-registrado — ensayo controlado agente-sin-MCP vs agente-con-MCP

**Estado: PRE-REGISTRO (2026-11-19). No se ha ejecutado el ensayo real.**
Este documento se cierra antes de reclutar/modelo alguno. Cualquier cambio posterior
es una enmienda fechada y empieza un pre-registro nuevo; no se permiten cambios
de métrica, brazos, tasks ni regla de decisión après-coup. El `--dry-run` del
arnés solo comprueba la instalación: **no es un dato del ensayo**.

## 1. Pregunta e hipótesis

¿Reduce el MCP de pyzig el número de compilaciones que un agente necesita para
resolver tareas Python→Zig 0.16 correctamente?

- **H0 (nula):** la distribución de intentos hasta pasar es la misma en A y B.
- **H1 (pre-registrada, direccional):** el brazo B necesita **menos** compilaciones
  del arnés hasta pasar que el brazo A, y no pasa menos tareas.
- **Endpoint primario:** `compiles_until_pass` por tarea y brazo (definición en §4).
- **Endpoints secundarios (exploratorios):** tasa de paso, `compile_errors`,
  `error_records`, `tests_passed_attempts`, tokens y llamadas a herramientas
  declaradas por el agente. No se usa ninguno para la decisión principal.

La hipótesis es sobre **este** par modelo/tareas/entorno; no se generaliza a
"los MCP ayudan" en abstracto.

## 2. Brazos

| brazo | herramientas permitidas | entrega |
|---|---|---|
| **A** (control) | ninguna herramienta de pyzig. `AB_TOOLS=""`. El prompt dice explícitamente que no las invoque. | código Zig en stdout |
| **B** (tratamiento) | `pyzig_search`, `pyzig_get`, `pyzig_catalog`, `pyzig_check` por MCP. `AB_TOOLS` las enumera. El prompt pide usarlas y registrar cada llamada en `AB_ATTEMPT_META`. | código Zig en stdout |

Ambos prompts son **idénticos salvo el párrafo de herramientas**; esto se comprueba
en `tests/test_ab.py::TasksTest::test_prompts_differ_only_in_arm_instructions`.
Cada prompts se guarda como `prompt_sha256` en `attempts.jsonl`. El mismo modelo,
versión, temperatura, `max_tokens` y sistema de mensajes deben usarse en A y B:
se fijan en el `--agent-cmd`, no en el arnés. El operador debe verificar que el
proceso del brazo A **realmente** carece de las herramientas: el arnés solo
comunica la intención, no puede desactivar herramientas dentro de un agente
arbitrario (§8.1).

## 3. Tareas

`ab/tasks/*.json`: 12 tareas Python→Zig 0.16.0 con prompt en español, código
Python de referencia (`py_ref`) y un bloque `zig_test` que el arnés concatena al
final del código del agente. Cada JSON declara la firma Zig exacta, casos de
entrada/salida esperados en `oracle` y `control: true|false`.

- **Controles (3, `control: true`):** `t01_bisect_left` (`bisect.bisect_left`),
  `t02_gcd_lcm` (`math.gcd`/`math.lcm`), `t03_median_i64` (`statistics.median`).
  Verificación ejecutada: `ziggrep -il 'bisect|gcd|lcm|median|statistics'
  corpus/pyzig.corpus.jsonl` → **0 archivos**; ninguna de esas operaciones tiene
  entrada en el corpus de 95 entradas.
- **Recombinaciones (9):** `t04_word_count`, `t05_dot_product`,
  `t06_unique_sorted`, `t07_longest_true_run`, `t08_xor_fold`,
  `t09_collapse_spaces`, `t10_prefix_sums`, `t11_is_palindrome`,
  `t12_common_prefix_len`. Usan primitivas presentes en el corpus pero no copian
  ningún `zig_impl`/`zig_test` de receta: los nombres de función tampoco aparecen
  en el corpus (comprobado en `tests/test_ab.py`). Cada una se verifica con
  `zig test` 0.16.0 sobre una solución de ejemplo antes del ensayo.

El oráculo es **el bloque `zig_test`**, ejecutado por `pyzig.check.check_zig`
dentro de bwrap. `py_ref` y `oracle` documentan la intención; el verificador no
los interpreta. Ninguna tarea exige red, archivos del host ni `pub fn main`.

## 4. Métricas (definiciones operacionales)

Todas salen de `scripts/ab_score.py` → `score.json`. El puntuador **reutiliza**
`pyzig.check.check_zig(mode="test", suggest=False)`; no duplica bwrap, no mira el
índice y vuelve a compilar cada intento desde cero (así el scored es reproducible
incluso si el agente usó MCP para verificar).

Por tarea y brazo:

| clave | definición |
|---|---|
| `attempts` | número de archivos `*.zig` scoring del intento. |
| `compiles` | intentos con observación de compilación (`compiled` no nulo). |
| `compiles_until_pass` | índice **1-based** del primer intento con `ok=true`; `null` si nunca pasó en los ≤K intentos. Es el endpoint primario. |
| `passed` | `compiles_until_pass` no nulo. |
| `compile_errors` | intentos con `compiled=false` (fallo de compilación). |
| `error_records` | suma de diagnósticos `linea:col: error:` parseados por `check_zig`. Un fallo de test en runtime aporta 0. |
| `tests_passed_attempts` | intentos donde el binario de test terminó con `tests_passed=true`. |
| `runtime_failures` | intentos `TEST_FAIL` (compiló, pero los tests fallaron). |
| `unscored` | intentos sin observación (`SANDBOX_UNAVAILABLE`, `ZIG_NOT_FOUND`, `TIMEOUT`). Se excluyen de `compiles`; **nunca** se imputan como fallo ni como éxito. |
| `tokens` | `{available, measured_attempts, total, by_attempt}` leídos de `attempts.jsonl`. `available=true` solo si **todos** los intentos del par tenían token; si no, `total="NOT_AVAILABLE"`. Nunca se estiman tokens. |
| `attempts_detail[].errors` | mensajes de compilación observados (máximo los que devuelve `check_zig`). |

Por brazo, `summary` agrega las anteriores: `pass_rate`, `compiles_until_pass`
(`n`, `mean`, `median` **solo sobre tareas pasadas**), totales y disponibilidad de
tokens. `reported_tool_calls` aparece solo en `attempts.jsonl` del orquestador.

Para el análisis pareado, el valor por tarea es
`D = compiles_until_pass(A) − compiles_until_pass(B)`, con una tarea no pasada
censurada a `K+1` (K=3 por defecto). Esta regla se fija aquí; no se cambia al ver
los datos.

## 5. Aleatorización y ejecución

```
.venv/bin/python scripts/ab_run.py \
  --tasks-dir ab/tasks --arms A,B --seed 1337 --max-attempts 3 \
  --agent-cmd '<comando del agente>' \
  --out var/ab/runs/<run> --cache-dir var/build/check-cache
```

1. `random.Random(seed)` baraja el orden de las 12 tareas y, para cada una, lanza
   una moneda para decidir si corre A→B o B→A (mitiga fatiga/orden). Todo queda en
   `manifest.json`: `execution_order`, `arm_order_by_task`, `seed`.
2. Intento 1: prompt idéntico salvo el párrafo del brazo. Intentos>1: se añade el
   feedback real del verificador (`compiló`, `tests_pasados`, errores). Ese feedback
   es el mismo para A y B y no incluye sugerencias del corpus.
3. El comando del agente recibe el prompt por **stdin**, escribe código Zig en
   **stdout** y diagnósticos en stderr; `cwd` es el directorio del run. Puede
   escribir `{"tokens": {...}, "tool_calls": [...]}` en `AB_ATTEMPT_META`.
4. Cada intento se escribe y se puntúa inmediatamente; se registra en
   `attempts.jsonl` global y por tarea. Se para la tarea al primer intento que pasa.
5. Al final, `ab_score.py` re-puntúa **todos** los archivos y escribe `score.json`.
   Esa re-puntuación, no el `status` en caliente, es la fuente de las cifras.
6. `--dry-run` copia `ab/examples/solutions/good/**` y puntúa: comprueba tubería,
   no produce observaciones del ensayo. Sin `--agent-cmd`, solo se permite dry-run.

## 6. Criterio de parada

Diseño fijo: 12 tareas × 2 brazos × **≤3 intentos** por par (K=3), una sola
ejecución por par modelo/tareas. La tarea se detiene al primer paso; el run se
detiene al completar los 24 pares. Se prohíbe el "peeking" para decidir cuándo
parar, ampliar K o descartar tareas. Una interrupción del operador se anota en el
run y ese run queda fuera del análisis pre-registrado. Los cambios de seed o de K
constituyen un ensayo nuevo.

## 7. Análisis pre-registrado

1. Publicar los 24 pares con sus `compiles_until_pass` censurados y las cifras
   agregadas por brazo, sin borrar fallos ni `unscored`.
2. Endpoint primario: mediana de `D` y **test de signos bilateral** sobre los
   pares con `D≠0` (n=12 parejas, sin corrección: hay un solo endpoint primario).
3. Regla de decisión, fijada antes de ver datos: se declara **"H1 apoyada"** solo
   si las tres condiciones se cumplen a la vez:
   - mediana(`D`) ≥ 1 (B tarda al menos una compilación menos),
   - p < 0.05 en el test de signos bilateral,
   - `passed(B) >= passed(A)` (el ahorro no se compra con peor cobertura).
   En cualquier otro caso se escribe **"no demostrado con este diseño"**, sin
   afirmar equivalencia: n=12 tiene poca potencia.
4. Secundarios: tasa de paso, errores de compilación/diagnósticos, tokens y
   llamadas declaradas. Se reportan con sus `NOT_AVAILABLE`; se interpretan como
   exploratorios y no rescatan una H1 fallida.
5. Todo número del informe debe salir de `score.json`/`attempts.jsonl` con el
   comando que lo generó. Lo que no se pudo observar se escribe
   `NOT_DEMONSTRATED` / `NOT_AVAILABLE`, nunca un estimado.

## 8. Amenazas a la validez

1. **Aislamiento de herramientas no enforceado por el arnés.** `AB_TOOLS` y el
   prompt expresan la intención, pero un agente con MCP configurado globalmente
   podría consultarlo en el brazo A. Verificación: revisar `reported_tool_calls`;
   cualquier llamada en A invalida el par y exige repetirlo con el agente bien
   configurado. Además debe correrse con el modelo y los permisos fijados por el
   operador; el arnés no los controla.
2. **`pyzig_check` compila fuera del contador.** En B, una llamada MCP a
   `pyzig_check` ejecuta `zig` en su propio bwrap y no incrementa `compiles_until_pass`.
   El endpoint primario mide compilaciones del **arnés**, no del proceso mental
   completo; el ahorro puede deberse en parte a mover compilaciones fuera del
   marcador. `reported_tool_calls` es el único paliativo y depende de que el agente
   lo declare: si falta, `NOT_AVAILABLE`. No se mezcla con el endpoint primario.
3. **Fuga de respuestas.** `ab/examples/solutions/` y el corpus están en el repo;
   el agente podría leerlos aunque `cwd` sea el directorio del run. Para el ensayo
   real hay que ejecutar al agente sin acceso a esos archivos (o retirarlos de su
   workspace). El arnés no impide lecturas.
4. **Tareas in-sample.** Las tareas y las recetas fueron escritas por el mismo
   equipo; los controles cubren operaciones ausentes del corpus pero no eliminan
   el sesgo de diseño. No se reclama generalización a tareas nuevas.
5. **No determinismo del modelo.** La misma tarea puede dar soluciones distintas.
   Fijar temperatura/seed del proveedor en `--agent-cmd`; un solo run por par
   implica varianza no estimada. No se promedian réplicas.
6. **Efecto de orden y cache.** El orden se aleatoriza (§5) y ambos brazos usan la
   misma cache de zig; la primera compilación de `std` se paga una sola vez. Si se
   usan caches distintas por brazo, el run no es comparable.
7. **Feedback del mismo oráculo.** `check_zig` es a la vez quien da el feedback en
   reintentos y quien puntúa al final. Es determinista para el mismo fuente, pero
   B puede obtener diagnósticos exactos vía MCP antes de gastar un intento: eso es
   parte del tratamiento, no un error de medición, y se documenta aquí.
8. **Potencia y censura.** Con 12 pares y K=3, un "no demostrado" no implica que
   el MCP no ayude; un paso en el intento 4 se censura a 4 por igual en A y B.
9. **Tokens.** Solo existen si el agente escribe `AB_ATTEMPT_META`. Sin metadatos
   se reporta `NOT_AVAILABLE`; no se estiman ni se infieren del tamaño del prompt.

## 9. Reproducción y comprobaciones ejecutadas

Comandos corridos en este worktree (salidas resumidas; ninguno es un dato del
ensayo real):

| comando | resultado observado (rc) |
|---|---|
| `.venv/bin/python -m unittest discover -s tests -p 'test_ab.py' -v` | rc 0 — `Ran 9 tests ... OK` |
| `python3 -m pytest -q tests` | rc 0 — `93 passed` (32.34 s en la verificación final; el `.venv` local no trae `pytest`, se usa el `python3` del sistema que sí lo tiene) |
| `.venv/bin/python scripts/ab_score.py --solutions-dir ab/examples/solutions/good --cache-dir /tmp/opencode/ab-cache-good` | rc 0 — 12/12 tareas pasan en A y 12/12 en B; 24 compilaciones; 0 errores de compilación |
| `.venv/bin/python scripts/ab_score.py --solutions-dir ab/examples/solutions/broken --cache-dir /tmp/opencode/ab-cache-good` | rc 0 — 2 intentos observados: `t01` = `TEST_FAIL` (compila, tests fallan), `t02` = `COMPILE_FAIL` (1 diagnóstico); `compiles_until_pass.n = 0` |
| `.venv/bin/python scripts/ab_run.py --dry-run --out /tmp/opencode/ab-dry --cache-dir /tmp/opencode/ab-cache-good` | rc 0 — `manifest.json` + `score.json`, sin agente |
| `zig version`, `command -v bwrap` | `0.16.0`, `/usr/bin/bwrap` |
| `wc -l corpus/pyzig.corpus.jsonl` | `95` |
| `ziggrep -il 'bisect|gcd|lcm|median|statistics' corpus/pyzig.corpus.jsonl` | `0` archivos |

Para un run real, sustituir `--dry-run` por `--agent-cmd` según §5. Los ejemplos
`good/` nunca se usan como datos: solo validan que el arnés compila y puntúa.

## 10. Resultados del ensayo real

**NOT_DEMONSTRATED.** No se ha configurado ningún agente ni se ha ejecutado el
ensayo A/B. No hay cifras de compilaciones, errores, tests ni tokens de agentes
reales. Este protocolo solo pre-registra el diseño y valida el arnés con
soluciones de ejemplo.

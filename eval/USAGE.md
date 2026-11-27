# Uso real de pyzig por los agentes (snapshot de transcripts)

Pregunta: **¿los agentes que escriben o compilan Zig consultan pyzig por
iniciativa propia, y les sirve?** Este documento resume lo medido por
`scripts/usage_sessions.py` sobre los transcripts locales. Cifras crudas en
`eval/usage.json` (se regeneran; no se copian a mano en otros sitios).

## Metodo

- **Fuentes y descubrimiento:** se importa `scripts/mine_sessions.py` (no se
  modifica) y se usan sus mismos iteradores: Claude Code
  (`~/.claude/projects/**/*.jsonl`), Codex (`.jsonl` y `.jsonl.zst` con
  `zstd -dc`, sin escribir a disco), la base sqlite de OpenCode en solo
  lectura, Gemini/AGY (`chats/*.jsonl`) y Qwen (`*.jsonl`). El script no
  recorre los `brain/*/.system_generated/logs/transcript.jsonl` de AGY, que el
  minero tampoco visita (limitacion declarada abajo).
- **Sesion Zig:** la sesion tiene al menos una ejecucion
  `zig build|test|run|build-exe|build-lib|build-obj|ast-check` o una
  edicion/escritura de un fichero `.zig`.
- **Llamada a pyzig:** se detectan las tres formas observadas:
  1. herramienta directa (`pyzig_search`, `mcp__pyzig-rag__pyzig_search`,
     `pyzig-rag_pyzig_search`, ...);
  2. `hub_execute` con `server="pyzig-rag"` y `tool` en
     `pyzig_search|pyzig_get|pyzig_catalog|pyzig_check`;
  3. MCP generico de AGY (`call_mcp_tool` con `ServerName="pyzig-rag"`).
  En los `exec` JavaScript de Codex se exige que el texto declare el servidor
  `pyzig-rag`; una simple mencion de pyzig (descripcion del hub, ruta del
  repo) **no** cuenta.
- **Pedida vs espontanea:** una llamada es *pedida* si algun mensaje con rol
  de usuario **anterior** a la llamada menciona `pyzig` (sin distinguir
  mayusculas); si no, es *espontanea*. Es una definicion literal: una peticion
  indirecta ("busca la receta") cuenta como espontanea, y una mencion negativa
  ("no uses pyzig") contaria como pedida.
- **Resultado:** `NO_RESULTS` -> `no_results`; `VERSION_MISMATCH` ->
  `version_mismatch`; `compiled: false` de `pyzig_check` -> `compile_fail`;
  `SANDBOX_UNAVAILABLE`/`INDEX_UNAVAILABLE`/traceback/`ok: false` -> `error`;
  cualquier respuesta no vacia -> `results`; sin salida -> `unknown`. No se
  guarda el texto de la respuesta.
- **Oportunidad de receta:** por cada ejecucion zig con lineas `error:`, se
  normaliza la firma con `mine_sessions.normalize_msg` y se busca receta en
  `corpus/pyzig.corpus.jsonl` (`apis_used`, `aliases`, `error_signatures`),
  con respaldo en las etiquetas humanas de `eval/mined_labels.tsv` (las no
  `NONE`). Se considera **consultado** si hubo una llamada a pyzig entre esa
  ejecucion con error y la siguiente ejecucion zig de la sesion; **paso** si
  esa siguiente ejecucion no muestra lineas `error:`.

## Volumen medido

| metrica | valor |
|---|---|
| transcripts/ficheros leidos | 525 |
| sesiones (Claude/Codex/Gemini/Qwen + sesiones sqlite) | 992 |
| volumen de entrada | ~3989 MB |
| sesiones Zig | 103 |
| sesiones Zig con alguna llamada a pyzig | 1 |
| ejecuciones zig | 1773 |
| ejecuciones zig con errores | 128 |
| duracion del script (16 procesos) | ~29 s |

Fuentes: Claude 254 transcripts, Codex 253, OpenCode 2 sqlite (467 sesiones),
Gemini 2, Qwen 16. `unparsed_sessions = 0`.

## Llamadas a pyzig

| metrica | valor |
|---|---|
| llamadas totales | 1 |
| pedidas (mencion previa del usuario) | 0 |
| espontaneas | 1 |
| por herramienta | `pyzig_search`: 1 |
| resultado | `results`: 1 (NO_RESULTS: 0, error: 0, compile_fail: 0) |
| tasa NO_RESULTS de `pyzig_search` | 0.0 (n=1) |

La unica llamada fue un `pyzig_search` dentro de un `exec` de Codex, en una
sesion cuyo usuario no menciono pyzig antes. Devolvio resultados. Con n=1 no
se puede estimar una tasa: es un dato puntual, no una distribucion.

## Errores de compilacion con receta y sin consultar pyzig

| metrica | valor |
|---|---|
| oportunidades (firma con receta, por sesion) | 122 |
| de ellas, con pyzig consultado antes del siguiente build | 0 |
| sin consultar pyzig | 122 |
| sin consultar y con el siguiente build sin errores | 66 |

El total de oportunidades supera al de ejecuciones con error (128) porque una
misma ejecucion puede contener varias firmas y cada firma se cuenta una vez
por sesion. Top de firmas (las 10 primeras de `eval/usage.json`):

| firma normalizada | n | sesiones | receta | consultada | siguiente build paso |
|---|---|---|---|---|---|
| `local variable is never mutated` | 13 | 6 | `zig0.16/diag-never-mutated` | 0 | 7 |
| `dependency on libc must be explicitly specified in the build command` | 11 | 7 | `zig0.16/build-link-libc` | 0 | 5 |
| `evaluation exceeded N backwards branches` | 7 | 4 | `zig0.16/diag-eval-branch-quota` | 0 | 5 |
| `root source file struct '_' has no member named '_'` | 6 | 4 | - | 0 | 0 |
| `member function expected N argument(s), found N` | 5 | 3 | `zig0.16/migrate-readfilealloc` | 0 | 1 |
| `dependency on dynamic library '_' requires enabling Position Independent Code; fixed by '_' or '_'` | 4 | 1 | `zig0.16/build-dynamic-library-pic` | 0 | 0 |
| `invalid builtin function: '_'` | 4 | 2 | `zig0.16/migrate-type-builtin` | 0 | 1 |
| `local constant shadows declaration of '_'` | 4 | 4 | `zig0.16/diag-shadow-local` | 0 | 3 |
| `no field or member function named '_' in 'array_list._(uN,null)'` | 4 | 3 | `zig0.16/migrate-arraylist-unmanaged` | 0 | 2 |
| `struct 'array_list._(uN,null)' has no member named '_'` | 4 | 2 | `zig0.16/migrate-arraylist-unmanaged` | 0 | 0 |

## Conclusiones prudentes

1. **No hay evidencia de consulta habitual.** En este snapshot, 1 de 103
   sesiones Zig hizo una llamada a pyzig (~1 %). Es un unico caso y no permite
   afirmar una tasa estable.
2. **La unica llamada fue espontanea y devolvio resultados.** No hubo
   `NO_RESULTS` ni errores en esa muestra. No se puede atribuir mejora al
   resultado: no se midio que hiciera el agente con el.
3. **Las recetas se echan de menos, pero no se piden.** Hubo 122 oportunidades
   de firma con receta y 0 consultas a pyzig antes del siguiente build; 66 de
   esas veces el siguiente build ya pasaba. Eso sugiere que los agentes
   resuelven estos errores por su cuenta (o con otra herramienta), no que
   pyzig no sirva. El valor anadido de pyzig sigue **NOT_DEMONSTRATED** con
   estos datos.
4. **El piloto A/B no cuenta como uso organico.** Ese arnes invoca pyzig por
   CLI (`pyzig_cli`), no por MCP/hub; este medidor solo cuenta llamadas a
   herramientas MCP/hub. Sus corridas no inflan las cifras de arriba.

## Limitaciones

- **Snapshot y retencion:** los transcripts locales se podan. El informe es
  una foto del momento de la ejecucion; si una sesion se borra, deja de
  contar. Las cifras son un **limite inferior**, no un historico completo.
- **Variacion entre corridas:** dos ejecuciones consecutivas sobre los mismos
  transcripts dieron 102 frente a 103 sesiones Zig y 1761 frente a 1773
  ejecuciones Zig (y 524 frente a 525 transcripts). Las llamadas a pyzig (1) y
  las oportunidades con receta (122) no cambiaron. Los transcripts se escriben
  en vivo, asi que los conteos absolutos se mueven; la conclusion estable es la
  proporcion (1 de ~103 sesiones), no el total exacto.
- **AGY:** los `brain/*/.system_generated/logs/transcript.jsonl` no entran por
  el descubrimiento del minero; el trabajo de AGY esta subrepresentado (sus
  menciones a pyzig observadas son ejecuciones de demos/tests por bash, no
  llamadas a la herramienta).
- **CLI y demos:** `scripts/demo_client.py`, `scripts/pyzig_cli.py` o un
  `python -m ...` lanzado por bash no son llamadas MCP/hub y no se cuentan.
- **Solo sesiones Zig:** las llamadas se cuentan dentro de sesiones que
  escriben o compilan Zig. Una consulta a pyzig en una sesion sin Zig no entra
  en `pyzig_calls_total` (aunque si cuenta en `sessions_total`).
- **Clasificacion pedida/espontanea:** es literal (mencion de `pyzig` en un
  mensaje de usuario anterior). Peticiones indirectas o en otro idioma pueden
  quedar como espontaneas; una negacion cuenta como mencion.
- **Codex exec:** la deteccion en JavaScript es heuristica; exige
  `server`/`ServerName` con `pyzig-rag` y un nombre de tool pyzig, para no
  confundir la descripcion del hub o una ruta del repo con una llamada.
- **Enlace error -> siguiente build:** es una ventana heuristica. "Paso"
  significa que la siguiente ejecucion zig no imprime lineas `error:`; no
  prueba que el error concreto se arreglara ni que el build fuera el mismo.
- **Sesiones:** cada transcript de subagente cuenta como sesion; una sesion
  sqlite de OpenCode cuenta una vez. Los totales no son "personas" ni "tareas".
- **Privacidad:** el JSON solo lleva conteos, nombres de herramienta, estados,
  firmas normalizadas y `operation_id` del corpus. No lleva texto de mensajes,
  consultas literales, rutas, ids de sesion ni nombres de proyecto. Los tests
  sinteticos comprueban que nada de eso se filtra.

## Reproducir

```sh
python3 scripts/usage_sessions.py --out eval/usage.json --jobs 16
PYTHONPATH=. python3 -m pytest -q tests/test_usage.py
```

Salida observada de la ultima corrida: `sessions_with_zig=103`,
`sessions_with_pyzig=1`, `pyzig_calls_total=1`,
`pyzig_calls_spontaneous=1`, `duration_s=28.98`; tests `11 passed`.

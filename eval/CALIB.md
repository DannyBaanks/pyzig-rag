# Calibracion de la abstencion del modo hybrid (ola 5, pzsw5-abstencion)

## Problema medido

`eval/heldout_queries.tsv` (congelado): el modo `hybrid` rechaza 0/10 negativas; `lexical`, 6/10.
La admision antes era `cobertura >= 0.40  o  cosine >= 0.35` (`pyzig/search.py`).

## Diagnostico (sobre `eval/calib_queries.tsv`, 56 negativas, 62 positivas)

- Antes, `hybrid` admitia 25/56 negativas (medido con `run_queries`). Aproximadamente 20 de ellas
  entraban **solo por coseno** (cobertura maxima de la consulta < 0.40 y coseno maximo >= 0.35). MiniLM da 0.33-0.59 a consultas sin relacion
  (p. ej. "pandas agrupar un dataframe..." -> cosine 0.29-0.59 contra recetas de argv o hilos).
- Las otras 5 entran por **cobertura** pura: sus tokens genericos coinciden con una receta
  (c-neg03 "servidor/web/json", c-neg07 "expresion regular", c-neg19 "argumentos/linea/comandos",
  c-neg23 "valores/defecto", c-neg36 "contar/palabras/texto"). El coseno no las causa.
- En la receta correcta (documento esperado) de cada positiva: cobertura >= 0.40 en 61/62 y
  coseno >= 0.40 en 44/62. Con la regla nueva admite 61/62; la unica perdida es c-pos05
  (cobertura 0.333, coseno 0.259 en su receta).

## Regla elegida

`admitido = cobertura >= 0.40  o  (cosine >= 0.40  y  cobertura >= 0.33)`

- `COS_MIN` 0.35 -> 0.40: umbral de coseno mas alto.
- `COS_COV_MIN` = 0.33 (nuevo): el coseno solo admite con al menos 1/3 de los tokens
  discriminativos de la consulta en el mismo documento.
- `COV_MIN` = 0.40 sin cambios.

Se eligio mirando solo calibracion. Alternativas barridas (aproximacion por consulta, ver nota):
cobertura sola >= 0.33 admite 8 negativas; cosine >= 0.40 con cobertura >= 0.25 admite 10.
(Estas dos cifras del barrido no tienen script en el repo: `NOT_DEMONSTRATED`, el verificador no
pudo reproducirlas. Las tablas de abajo si salen de `scripts/run_eval.py`.)
La regla elegida deja 5 negativas admitidas y pierde 1 positiva (c-pos05).

## Tabla antes / despues

Medido con `run_queries` de `scripts/run_eval.py`. "Antes" = `COS_MIN=0.35`, `COS_COV_MIN=0`
(regla antigua exacta) sobre el mismo corpus de 102 entradas. Solo cambia la regla de admision.

**Calibracion (`eval/calib_queries.tsv`, 118 consultas: 56 neg, 62 pos)**

| modo | regla | P@1 | R@3 | MRR@3 | negativas rechazadas |
|---|---|---|---|---|---|
| lexical | (sin cambio) | 0.968 | 0.984 | 0.976 | 51/56 |
| hybrid | antes | 0.952 | 0.968 | 0.960 | 31/56 |
| hybrid | despues | 0.952 | 0.984 | 0.968 | 51/56 |

**Dev (`eval/queries.tsv`, 216 consultas; medido una vez al final)**

| modo | regla | P@1 | R@3 | MRR@3 | negativas | status |
|---|---|---|---|---|---|---|
| lexical | (sin cambio) | 0.976 | 0.995 | 0.986 | 4/4 | 3/3 |
| hybrid | antes | 0.952 | 0.976 | 0.962 | 4/4 | 3/3 |
| hybrid | despues | 0.976 | 0.995 | 0.986 | 4/4 | 3/3 |

**Held-out (`eval/heldout_queries.tsv`, 61 consultas; medido una vez al final)**

| modo | regla | P@1 | R@3 | MRR@3 | negativas |
|---|---|---|---|---|---|
| lexical | (sin cambio) | 0.941 | 1.000 | 0.967 | 6/10 |
| hybrid | antes | 1.000 | 1.000 | 1.000 | 0/10 |
| hybrid | despues | 1.000 | 1.000 | 1.000 | 5/10 |

La cifra "antes" del held-out (0/10 hybrid, 6/10 lexical) coincide con el brief de la ola 4. El
`eval/heldout_results.json` del HEAD se genero con un corpus de 95 entradas y no es comparable.

## Lo que NO se consigue

- **c-pos05** ("sacar texto por stdout y forzar que aparezca al momento", cobertura 1/3 sobre
  `stdout-print-flush`): antes salia con top-1 erroneo (`format-string-alloc-print`), ahora
  devuelve `NO_RESULTS`. P@1 no cambia (ya fallaba), pero es una positiva perdida en recall.
- **5 negativas siguen admitidas** (c-neg03, c-neg07, c-neg19, c-neg23, c-neg36). Entran por
  cobertura lexica con palabras genericas. Para quitarlas hace falta una senal que no sea
  cobertura por token: por ejemplo cobertura sobre `name` en vez de `body`, o exigir cobertura
  de tokens no genericos. No se implementa aqui.
- Calibracion y positivas son in-sample: las positivas se escribieron desde los titulos del
  corpus (su vocabulario coincide con el de las recetas), y los umbrales se eligieron sobre
  este mismo conjunto. Las negativas estan en espanol contra un modelo MiniLM en ingles.

## Nota sobre el metodo

El primer barrido de umbrales usaba la cobertura y el coseno **maximos de la consulta**, no los
de cada documento. Ese barrido sugeria que la regla no perdia positivas; la medicion por
documento (`run_queries` real) mostro la perdida de c-pos05. Las tablas de arriba son las
medidas reales, no las del barrido.

El held-out no influyo en la regla: se fijo con calibracion y se midio despues. Se midio
una vez el "antes" y una vez el "despues" (ambos en el mismo script, sin tocar la regla entre
medias).

## Reproducir

```sh
.venv/bin/python scripts/run_eval.py --queries eval/calib_queries.tsv --out var/calib_results.json
.venv/bin/python scripts/run_eval.py --queries eval/queries.tsv --out eval/results.json
.venv/bin/python scripts/run_eval.py --queries eval/heldout_queries.tsv --out eval/heldout_results.json
PYTHONPATH=. python3 -m pytest -q tests/test_abstencion.py
```

## Reproducibilidad

Las cifras de esta pagina salen con `.venv/bin/python` (onnxruntime + numpy del venv). Con el
`python3` del sistema sin onnxruntime el embedder queda degradado y hybrid da otras filas
(el verificador midio 0.941 / 1.000 / 0.967 y 6/10 negativas en held-out).

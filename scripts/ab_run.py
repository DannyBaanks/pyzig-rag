#!/usr/bin/env python3
"""Orquestador del ensayo controlado A/B (agente sin MCP vs agente con MCP).

El agente se invoca con un comando configurable que recibe el prompt por stdin y
debe escribir SOLO el código Zig en stdout. Los diagnósticos del agente van a
stderr. Opcionalmente el agente puede escribir un JSON en la ruta de
``AB_ATTEMPT_META`` con ``{"tokens": {"total": N}, "tool_calls": [...]}`` para
que el arnés registre tokens y llamadas a herramientas.

Cada intento corre en un directorio temporal vacío fuera del repo (aislamiento
best-effort: cwd sin acceso obvio al corpus/ejemplos; el agente podría intentar
leer rutas absolutas si las descubre). Para el brazo B se expone ``PYZIG_CLI``
(un comando que invoca ``scripts/pyzig_cli.py`` contra este repo) sin documentar
rutas del repo en el prompt.

Si el agente termina con código de retorno distinto de 0 (o timeout/spawn error),
el intento se registra como ``AGENT_ERROR`` y no cuenta como pasado, aunque el
código producido compilara.

El arnés NO puede activar/desactivar herramientas dentro de un agente arbitrario:
pasa la intención del brazo en el prompt y en ``AB_TOOLS``, y lo deja escrito en
el manifiesto. La verificación del aislamiento es responsabilidad del operador
(ver ab/PROTOCOL.md). Sin ``--agent-cmd`` hay que usar ``--dry-run``: en ese
modo se copian las soluciones de ejemplo y se puntúan, sin ejecutar ningún agente.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import random
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Any

try:  # importado como scripts.ab_run desde tests
    from .ab_score import (ARMS, DEFAULT_TASKS_DIR, load_tasks, portable,
                           score_attempt, score_solutions)
except ImportError:  # ejecutado como script: scripts/ ya está en sys.path
    from ab_score import (ARMS, DEFAULT_TASKS_DIR, load_tasks, portable,
                          score_attempt, score_solutions)

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_EXAMPLES = ROOT / "ab" / "examples" / "solutions" / "good"
DEFAULT_OUT = ROOT / "var" / "ab" / "runs"
TOOLS_B = ["pyzig_search", "pyzig_get", "pyzig_catalog", "pyzig_check"]
#: Nombre del log que ``scripts/pyzig_cli.py`` escribe dentro de ``$AB_TOOL_LOG``
#: (que es el directorio del intento). Lo que contiene es la verdad de terreno de
#: las llamadas a pyzig; ``reported_tool_calls`` es solo lo que declara el agente.
TOOL_LOG_NAME = "tool-calls.jsonl"

ARM_INSTRUCTIONS = {
    "A": (
        "Entorno A: no tienes acceso a las herramientas MCP de pyzig "
        "(pyzig_search, pyzig_get, pyzig_check, pyzig_catalog) y no debes "
        "invocarlas. Resuelve la tarea solo con tu conocimiento de Zig 0.16."
    ),
    "B": (
        "Entorno B: puedes consultar pyzig mediante la CLI disponible en la "
        "variable de entorno $PYZIG_CLI (ejecútala por shell). Comandos:\n"
        "  $PYZIG_CLI search \"<intención>\" [--mode hybrid|lexical|vector] [--limit N]\n"
        "  $PYZIG_CLI get <operation_id>\n"
        "  printf '%s' \"$ZIG_CODE\" | $PYZIG_CLI check [--mode test|ast]\n"
        "Úsala cuando ayude (buscar recetas, obtener detalles, verificar código). "
        "Registra cada invocación relevante en AB_ATTEMPT_META bajo la clave "
        "'tool_calls' como lista de cadenas."
    ),
}

COMMON_TAIL = (
    "\n\nDevuelve SOLO el código Zig por stdout, sin texto explicativo ni cercas "
    "de código markdown. Los errores del agente van por stderr."
)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_prompt(task: dict[str, Any], arm: str, feedback: str | None = None) -> str:
    """Prompt idéntico para A y B salvo el párrafo de herramientas del brazo."""
    prompt = task["prompt"] + "\n\n" + ARM_INSTRUCTIONS[arm] + COMMON_TAIL
    if feedback:
        prompt += "\n\nResultado del intento anterior del verificador del arnés:\n" + feedback
    return prompt


def _feedback(scored: dict[str, Any]) -> str:
    lines = [f"compiló={scored['compiled']}, tests_pasados={scored['tests_passed']}, "
             f"estado={scored['status']}"]
    for err in scored["errors"][:5]:
        lines.append(f"- línea {err['line']}: {err['message']}")
    if not scored["errors"] and scored["stderr_tail"]:
        lines.append("- " + scored["stderr_tail"][-600:])
    return "\n".join(lines)


def _read_meta(path: pathlib.Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _tokens_from_meta(meta: dict[str, Any]) -> dict[str, int] | None:
    tok = meta.get("tokens")
    if not isinstance(tok, dict):
        tok = {"total": meta.get("total_tokens")}
    total = tok.get("total", tok.get("total_tokens")) if isinstance(tok, dict) else None
    if not isinstance(total, int) or total < 0:
        return None
    out = {"total": total}
    for key in ("prompt", "completion", "cached"):
        if isinstance(tok.get(key), int):
            out[key] = tok[key]
    return out


def _random_plan(tasks: list[dict[str, Any]], seed: int) -> tuple[list[str], dict[str, list[str]]]:
    rng = random.Random(seed)
    order = [t["task_id"] for t in tasks]
    rng.shuffle(order)
    arm_order = {tid: (["A", "B"] if rng.random() < 0.5 else ["B", "A"])
                 for tid in order}
    return order, arm_order


def _fresh_out(out: pathlib.Path, force: bool) -> pathlib.Path | None:
    """Garantiza un ``out`` vacío. Con ``--force`` la corrida previa se aparta a
    ``<out>.prev-<UTC>`` (no se borra): si se reusara, ``attempts.jsonl`` mezclaría
    filas viejas y ``ab_score`` puntuaría ``attempt-NN.zig`` sobrantes."""
    moved = None
    if out.exists() and any(out.iterdir()):
        if not force:
            raise ValueError(f"{out} no está vacío; usa --force (lo aparta) u otro --out")
        moved = out.with_name(f"{out.name}.prev-{_now().replace(':', '').replace('-', '')}")
        out.rename(moved)
        print(f"ab_run: corrida previa apartada en {moved}", file=sys.stderr)
    out.mkdir(parents=True, exist_ok=True)
    return moved


def _isolated_base() -> pathlib.Path:
    for base in (pathlib.Path("/tmp/opencode"), pathlib.Path(tempfile.gettempdir())):
        try:
            base.mkdir(parents=True, exist_ok=True)
            return base
        except OSError:
            continue
    return pathlib.Path(tempfile.gettempdir())


def _pyzig_cli_command(dest_dir: pathlib.Path | None = None) -> str:
    """Comando para invocar scripts/pyzig_cli.py con el intérprete del repo.

    El prompt de B lo usa como ``$PYZIG_CLI search ...`` (expansión sin comillas):
    el valor no puede llevar espacios ni comillas, porque el shell lo parte en
    palabras y no re-interpreta ``PYTHONPATH=``. Con ``dest_dir`` se escribe un
    wrapper ejecutable allí (ruta sin espacios) y se devuelve su ruta.
    """
    py = str((ROOT / ".venv" / "bin" / "python").resolve())
    if not pathlib.Path(py).is_file():
        py = sys.executable
    cli = str((ROOT / "scripts" / "pyzig_cli.py").resolve())
    root = str(ROOT.resolve())
    line = f"PYTHONPATH={shlex.quote(root)} exec {shlex.quote(py)} {shlex.quote(cli)} \"$@\""
    if dest_dir is None:
        return line
    wrapper = dest_dir / "pyzig-cli"
    wrapper.write_text("#!/bin/sh\n" + line + "\n", encoding="utf-8")
    wrapper.chmod(0o755)
    return str(wrapper)


def _read_tool_log(path: pathlib.Path) -> list[dict[str, Any]]:
    """Lee las líneas JSON que el CLI de pyzig añadió durante un intento."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    calls: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            calls.append(rec)
    return calls


def _agent_failed(rc: Any) -> bool:
    if isinstance(rc, int):
        return rc != 0
    return rc in {"TIMEOUT", "SPAWN_ERROR"}


def run_agent(args: argparse.Namespace, tasks: list[dict[str, Any]],
              out: pathlib.Path, order: list[str], arm_order: dict[str, list[str]]) -> None:
    by_id = {t["task_id"]: t for t in tasks}
    global_log = out / "attempts.jsonl"
    work_base = _isolated_base() / "ab-work"
    work_base.mkdir(parents=True, exist_ok=True)
    pyzig_cli = _pyzig_cli_command(work_base)
    for tid in order:
        task = by_id[tid]
        for arm in arm_order[tid]:
            if arm not in args.arms:
                continue
            task_dir = out / arm / tid
            task_dir.mkdir(parents=True, exist_ok=True)
            feedback: str | None = None
            for attempt in range(1, args.max_attempts + 1):
                prompt = build_prompt(task, arm, feedback)
                workdir = pathlib.Path(tempfile.mkdtemp(prefix=f"{tid}-{arm}-a{attempt}-", dir=work_base))
                meta_path = workdir / f"meta-attempt-{attempt:02d}.json"
                env = dict(os.environ)
                env.update({
                    "AB_TASK_ID": tid,
                    "AB_ARM": arm,
                    "AB_ATTEMPT": str(attempt),
                    "AB_ATTEMPT_META": str(meta_path),
                    "AB_TOOLS": ",".join(TOOLS_B if arm == "B" else []),
                    "AB_PROMPT_SHA256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    # directorio del intento: el CLI de pyzig escribe aquí su log
                    "AB_TOOL_LOG": str(workdir),
                })
                if arm == "B":
                    env["PYZIG_CLI"] = pyzig_cli
                started = _now()
                agent_error = ""
                try:
                    proc = subprocess.run(
                        args.agent_cmd, shell=True, input=prompt, text=True,
                        capture_output=True, cwd=workdir, env=env, timeout=args.timeout,
                    )
                    source, rc, agent_error = proc.stdout, proc.returncode, proc.stderr
                except subprocess.TimeoutExpired as exc:
                    source, rc = (exc.stdout or "") if isinstance(exc.stdout, str) else "", "TIMEOUT"
                    agent_error = "timeout del agente"
                except OSError as exc:
                    source, rc, agent_error = "", "SPAWN_ERROR", str(exc)

                solution = task_dir / f"attempt-{attempt:02d}.zig"
                solution.write_text(source, encoding="utf-8")
                scored = score_attempt(source, task, cache_dir=args.cache_dir)
                if _agent_failed(rc):
                    scored = {**scored, "status": "AGENT_ERROR", "passed": False}
                meta = _read_meta(meta_path)
                tokens = _tokens_from_meta(meta)
                tool_calls = meta.get("tool_calls")
                if not isinstance(tool_calls, list):
                    tool_calls = None
                tool_log = workdir / TOOL_LOG_NAME
                observed_calls = _read_tool_log(tool_log)
                record = {
                    "ts": started,
                    "task_id": tid,
                    "control": task.get("control", False),
                    "arm": arm,
                    "attempt": attempt,
                    "agent_rc": rc,
                    "workdir": str(workdir),
                    "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    "prompt_chars": len(prompt),
                    "source_chars": len(source),
                    "tokens": tokens,
                    "reported_tool_calls": tool_calls,
                    "observed_tool_calls": observed_calls,
                    "tool_log_present": tool_log.is_file(),
                    "status": scored["status"],
                    "compiled": scored["compiled"],
                    "tests_passed": scored["tests_passed"],
                    "error_records": scored["error_records"],
                    "errors": [e["message"] for e in scored["errors"]],
                    "agent_stderr_tail": agent_error[-2000:],
                }
                # persist meta and tool log alongside attempt for traceability
                try:
                    meta_dst = task_dir / f"meta-attempt-{attempt:02d}.json"
                    if meta_path.is_file():
                        meta_dst.write_text(json.dumps(
                            portable(meta), ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
                    if tool_log.is_file():
                        log_lines = [json.dumps(portable(c), ensure_ascii=False)
                                     for c in observed_calls]
                        (task_dir / f"tool-calls-attempt-{attempt:02d}.jsonl").write_text(
                            "\n".join(log_lines) + "\n", encoding="utf-8")
                except OSError:
                    pass
                line = json.dumps(portable(record), ensure_ascii=False) + "\n"
                with (task_dir / "attempts.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(line)
                with global_log.open("a", encoding="utf-8") as fh:
                    fh.write(line)
                try:
                    shutil.rmtree(workdir)
                except OSError:
                    pass
                if scored["passed"]:
                    break
                if _agent_failed(rc):
                    feedback = f"El agente falló (rc={rc}). stderr_tail:\n{agent_error[-1200:]}\n\n" + _feedback(scored)
                else:
                    feedback = _feedback(scored)


def run_dry_run(args: argparse.Namespace, tasks: list[dict[str, Any]],
                out: pathlib.Path, examples: pathlib.Path) -> None:
    ids = {t["task_id"] for t in tasks}
    for arm in args.arms:
        for tid in ids:
            src = examples / arm / tid
            if not src.is_dir():
                continue
            dst = out / arm / tid
            dst.mkdir(parents=True, exist_ok=True)
            for path in sorted(src.glob("*.zig")):
                shutil.copyfile(path, dst / path.name)
            meta = src / "attempts.jsonl"
            if meta.is_file():
                shutil.copyfile(meta, dst / "attempts.jsonl")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks-dir", type=pathlib.Path, default=DEFAULT_TASKS_DIR)
    ap.add_argument("--tasks", default="", help="subconjunto de task_id separados por comas")
    ap.add_argument("--out", type=pathlib.Path, default=None,
                    help="directorio de salida (por defecto var/ab/runs/<UTC>)")
    ap.add_argument("--examples-dir", type=pathlib.Path, default=DEFAULT_EXAMPLES,
                    help="soluciones de ejemplo para --dry-run")
    ap.add_argument("--agent-cmd", default=None,
                    help="comando de shell; recibe el prompt por stdin y escribe Zig en stdout")
    ap.add_argument("--dry-run", action="store_true", help="sin agente: copia ejemplos y puntúa")
    ap.add_argument("--arms", default="A,B", help="brazos a ejecutar (por defecto A,B)")
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--timeout", type=int, default=120, help="timeout por llamada al agente (s)")
    ap.add_argument("--cache-dir", type=pathlib.Path, default=None,
                    help="cache de zig para el puntuador")
    ap.add_argument("--force", action="store_true", help="permite sobrescribir .zig existentes")
    args = ap.parse_args(argv)

    if not args.dry_run and not args.agent_cmd:
        print("ab_run: sin --agent-cmd solo se permite --dry-run", file=sys.stderr)
        return 2
    if args.max_attempts < 1:
        print("ab_run: --max-attempts debe ser >= 1", file=sys.stderr)
        return 2
    arms = tuple(a.strip().upper() for a in args.arms.split(",") if a.strip())
    if any(a not in ARMS for a in arms):
        print("ab_run: brazos válidos: A,B", file=sys.stderr)
        return 2

    try:
        tasks = load_tasks(args.tasks_dir)
        only = {x.strip() for x in args.tasks.split(",") if x.strip()}
        if only:
            tasks = [t for t in tasks if t["task_id"] in only]
            missing = only - {t["task_id"] for t in tasks}
            if missing:
                raise ValueError(f"task_id desconocidos: {sorted(missing)}")
        if not tasks:
            raise ValueError("sin tareas seleccionadas")
        out = args.out or (DEFAULT_OUT / _now().replace(":", "").replace("-", ""))
        _fresh_out(out, args.force)
        order, arm_order = _random_plan(tasks, args.seed)
        manifest = {
            "schema": 1,
            "mode": "dry-run" if args.dry_run else "agent",
            "created_at": _now(),
            "seed": args.seed,
            "max_attempts": args.max_attempts,
            "tasks": [t["task_id"] for t in tasks],
            "controls": [t["task_id"] for t in tasks if t.get("control")],
            "execution_order": order,
            "arm_order_by_task": {
                tid: [a for a in seq if a in arms] for tid, seq in arm_order.items()
            },
            "arms": list(arms),
            "agent_cmd": None if args.dry_run else args.agent_cmd,
            "tools_by_arm": {"A": [], "B": TOOLS_B},
            "examples_dir": str(args.examples_dir) if args.dry_run else None,
            "note": "El arnés NO enforcea herramientas dentro del agente; ver PROTOCOL.md.",
        }
        (out / "manifest.json").write_text(
            json.dumps(portable(manifest), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        if args.dry_run:
            run_dry_run(args, tasks, out, args.examples_dir)
        else:
            run_agent(args, tasks, out, order, arm_order)
        report = score_solutions(out, args.tasks_dir, cache_dir=args.cache_dir, arms=arms,
                                 tasks=tasks)
        (out / "score.json").write_text(
            json.dumps(portable(report), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ab_run: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"out": str(out), "mode": manifest["mode"],
                      "summary": {a: report["arms"][a]["summary"] for a in arms}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

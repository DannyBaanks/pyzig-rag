#!/usr/bin/env python3
"""Orquestador del ensayo controlado A/B (agente sin MCP vs agente con MCP).

El agente se invoca con un comando configurable que recibe el prompt por stdin y
debe escribir SOLO el código Zig en stdout. Los diagnósticos del agente van a
stderr. Opcionalmente el agente puede escribir un JSON en la ruta de
``AB_ATTEMPT_META`` con ``{"tokens": {"total": N}, "tool_calls": [...]}`` para
que el arnés registre tokens y llamadas a herramientas.

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
import shutil
import subprocess
import sys
from typing import Any

try:  # importado como scripts.ab_run desde tests
    from .ab_score import (ARMS, DEFAULT_TASKS_DIR, load_tasks, score_attempt,
                           score_solutions)
except ImportError:  # ejecutado como script: scripts/ ya está en sys.path
    from ab_score import (ARMS, DEFAULT_TASKS_DIR, load_tasks, score_attempt,
                          score_solutions)

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_EXAMPLES = ROOT / "ab" / "examples" / "solutions" / "good"
DEFAULT_OUT = ROOT / "var" / "ab" / "runs"
TOOLS_B = ["pyzig_search", "pyzig_get", "pyzig_catalog", "pyzig_check"]

ARM_INSTRUCTIONS = {
    "A": (
        "Entorno A: no tienes acceso a las herramientas MCP de pyzig "
        "(pyzig_search, pyzig_get, pyzig_check, pyzig_catalog) y no debes "
        "invocarlas. Resuelve la tarea solo con tu conocimiento de Zig 0.16."
    ),
    "B": (
        "Entorno B: tienes disponibles las herramientas MCP de pyzig "
        "(pyzig_search, pyzig_get, pyzig_check, pyzig_catalog) y debes usarlas "
        "cuando ayuden: consulta la receta antes de escribir Zig y verifica el "
        "código con pyzig_check. Registra cada llamada en AB_ATTEMPT_META "
        "bajo la clave 'tool_calls'."
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


def _fresh_out(out: pathlib.Path, force: bool) -> None:
    if out.exists() and any(out.rglob("*.zig")) and not force:
        raise ValueError(f"{out} ya contiene soluciones; usa --force u otro --out")
    out.mkdir(parents=True, exist_ok=True)


def run_agent(args: argparse.Namespace, tasks: list[dict[str, Any]],
              out: pathlib.Path, order: list[str], arm_order: dict[str, list[str]]) -> None:
    by_id = {t["task_id"]: t for t in tasks}
    global_log = out / "attempts.jsonl"
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
                meta_path = task_dir / f"meta-attempt-{attempt:02d}.json"
                if meta_path.exists():
                    meta_path.unlink()  # nunca reutilices tokens de un run anterior
                env = dict(os.environ)
                env.update({
                    "AB_TASK_ID": tid,
                    "AB_ARM": arm,
                    "AB_ATTEMPT": str(attempt),
                    "AB_ATTEMPT_META": str(meta_path),
                    "AB_TOOLS": ",".join(TOOLS_B if arm == "B" else []),
                    "AB_PROMPT_SHA256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                })
                started = _now()
                agent_error = ""
                try:
                    proc = subprocess.run(
                        args.agent_cmd, shell=True, input=prompt, text=True,
                        capture_output=True, cwd=out, env=env, timeout=args.timeout,
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
                meta = _read_meta(meta_path)
                tokens = _tokens_from_meta(meta)
                tool_calls = meta.get("tool_calls")
                if not isinstance(tool_calls, list):
                    tool_calls = None
                record = {
                    "ts": started,
                    "task_id": tid,
                    "control": task.get("control", False),
                    "arm": arm,
                    "attempt": attempt,
                    "agent_rc": rc,
                    "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    "prompt_chars": len(prompt),
                    "source_chars": len(source),
                    "tokens": tokens,
                    "reported_tool_calls": tool_calls,
                    "status": scored["status"],
                    "compiled": scored["compiled"],
                    "tests_passed": scored["tests_passed"],
                    "error_records": scored["error_records"],
                    "errors": [e["message"] for e in scored["errors"]],
                    "agent_stderr_tail": agent_error[-2000:],
                }
                line = json.dumps(record, ensure_ascii=False) + "\n"
                with (task_dir / "attempts.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(line)
                with global_log.open("a", encoding="utf-8") as fh:
                    fh.write(line)
                if scored["passed"]:
                    break
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
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.dry_run:
            run_dry_run(args, tasks, out, args.examples_dir)
        else:
            run_agent(args, tasks, out, order, arm_order)
        report = score_solutions(out, args.tasks_dir, cache_dir=args.cache_dir, arms=arms,
                                 tasks=tasks)
        (out / "score.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ab_run: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"out": str(out), "mode": manifest["mode"],
                      "summary": {a: report["arms"][a]["summary"] for a in arms}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

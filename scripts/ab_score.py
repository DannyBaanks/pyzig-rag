#!/usr/bin/env python3
"""Puntúa intentos Zig del ensayo A/B con el sandbox de ``pyzig.check``.

No implementa bwrap ni compila por su cuenta: cada intento se concatena con el
`zig_test` de su tarea y se pasa a ``check_zig(mode="test")``, el mismo verificador
que usa ``pyzig_check``. Las métricas son puramente observacionales: lo que no se
puede medir se declara como ``null`` o ``"NOT_AVAILABLE"``.

Las soluciones se esperan en ``<solutions-dir>/<brazo>/<task_id>/*.zig``.
Cada ``.zig`` es un intento; el orden de intentos es el orden natural de los
números del nombre (`attempt-01.zig`, `attempt-02.zig`, ...). El orquestador
`ab_run.py` escribe además ``attempts.jsonl`` con metadatos (tokens); si no está,
los tokens son ``NOT_AVAILABLE``.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyzig import check as check_mod  # noqa: E402  (import tras fijar sys.path)

SCHEMA = 1
DEFAULT_TASKS_DIR = ROOT / "ab" / "tasks"
DEFAULT_SOLUTIONS_DIR = ROOT / "var" / "ab" / "solutions"
ARMS = ("A", "B")
NOT_AVAILABLE = "NOT_AVAILABLE"

REQUIRED_TASK_FIELDS = ("task_id", "prompt", "py_ref", "zig_test")
_NUM = re.compile(r"(\d+)")


def _natural_key(path: pathlib.Path) -> tuple:
    return tuple((0, int(part)) if part.isdigit() else (1, part)
                 for part in _NUM.split(path.name))


def load_tasks(tasks_dir: pathlib.Path = DEFAULT_TASKS_DIR) -> list[dict[str, Any]]:
    """Carga y valida las tareas ``*.json``; orden estable por ``task_id``."""
    tasks_dir = pathlib.Path(tasks_dir)
    files = sorted(tasks_dir.glob("*.json"))
    if not files:
        raise ValueError(f"sin tareas *.json en {tasks_dir}")
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for field in REQUIRED_TASK_FIELDS:
            if not isinstance(data.get(field), str) or not data[field].strip():
                raise ValueError(f"{path}: campo {field!r} ausente o vacío")
        tid = data["task_id"]
        if tid in seen:
            raise ValueError(f"task_id duplicado: {tid}")
        seen.add(tid)
        data["control"] = bool(data.get("control", False))
        tasks.append(data)
    return sorted(tasks, key=lambda t: t["task_id"])


def combine(source: str, task: dict[str, Any]) -> str:
    """Código del agente + pruebas del arnés, en un único archivo para ``check_zig``."""
    return source.rstrip("\n") + "\n\n" + task["zig_test"].lstrip("\n")


def score_attempt(source: str, task: dict[str, Any],
                  cache_dir: pathlib.Path | None = None,
                  *, suggest: bool = False) -> dict[str, Any]:
    """Compila y ejecuta un intento; devuelve métricas observadas (sin inventar)."""
    result = check_mod.check_zig(combine(source, task), mode="test",
                                 cache_dir=cache_dir, suggest=suggest)
    code = result.get("error")
    if code:
        # SANDBOX_UNAVAILABLE / ZIG_NOT_FOUND / TIMEOUT / INVALID_MODE: no hay
        # observación de compilación ni de tests; no se rellena con 0/false.
        return {
            "status": code,
            "compiled": None,
            "tests_passed": None,
            "passed": False,
            "error_records": 0,
            "stderr_tail": result.get("stderr_tail", ""),
            "errors": [],
        }
    compiled = bool(result.get("compiled"))
    tests_passed = result.get("tests_passed")
    passed = bool(result.get("ok"))
    errors = [
        {"line": e.get("line"), "col": e.get("col"), "message": e.get("message", "")}
        for e in (result.get("errors") or [])
    ]
    if passed:
        status = "PASS"
    elif compiled and tests_passed is False:
        status = "TEST_FAIL"
    elif not compiled:
        status = "COMPILE_FAIL"
    else:
        status = "UNKNOWN"
    return {
        "status": status,
        "compiled": compiled,
        "tests_passed": tests_passed,
        "passed": passed,
        "error_records": len(errors),
        "stderr_tail": result.get("stderr_tail", ""),
        "errors": errors,
    }


def _token_values(task_dir: pathlib.Path) -> dict[int, int]:
    """Tokens por intento desde ``attempts.jsonl`` del orquestador, si existen."""
    meta = task_dir / "attempts.jsonl"
    if not meta.is_file():
        return {}
    out: dict[int, int] = {}
    for line in meta.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        n = rec.get("attempt")
        tok = rec.get("tokens")
        if isinstance(n, int) and isinstance(tok, dict):
            total = tok.get("total", tok.get("total_tokens"))
            if isinstance(total, int) and total >= 0:
                out[n] = total
    return out


def _agent_overrides(task_dir: pathlib.Path) -> dict[int, dict[str, Any]]:
    """Metadatos de ejecución del agente por intento (rc, status forzado)."""
    meta = task_dir / "attempts.jsonl"
    if not meta.is_file():
        return {}
    out: dict[int, dict[str, Any]] = {}
    for line in meta.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        n = rec.get("attempt")
        if not isinstance(n, int):
            continue
        info: dict[str, Any] = {}
        if "agent_rc" in rec:
            info["agent_rc"] = rec.get("agent_rc")
        if rec.get("status") == "AGENT_ERROR":
            info["force_status"] = "AGENT_ERROR"
        elif isinstance(rec.get("agent_rc"), int) and rec["agent_rc"] != 0:
            info["force_status"] = "AGENT_ERROR"
        elif rec.get("agent_rc") in {"TIMEOUT", "SPAWN_ERROR"}:
            info["force_status"] = "AGENT_ERROR"
        if info:
            out[n] = info
    return out


def _attempt_files(task_dir: pathlib.Path) -> list[pathlib.Path]:
    return sorted(task_dir.glob("*.zig"), key=_natural_key)


def _tokens_summary(values: list[int | None]) -> dict[str, Any]:
    measured = [v for v in values if v is not None]
    complete = bool(values) and len(measured) == len(values)
    return {
        "available": complete,
        "measured_attempts": len(measured),
        "total": sum(measured) if complete else NOT_AVAILABLE,
        "by_attempt": [v if v is not None else NOT_AVAILABLE for v in values],
    }


def _summary(per_task: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(per_task)
    passed = [t for t in per_task if t["passed"]]
    until = [t["compiles_until_pass"] for t in passed
             if t["compiles_until_pass"] is not None]
    token_totals = [t["tokens"]["total"] for t in per_task
                    if t["tokens"]["available"]]
    all_tokens = bool(per_task) and len(token_totals) == n
    return {
        "tasks_total": n,
        "tasks_with_solutions": sum(1 for t in per_task if t["attempts"] > 0),
        "passed": len(passed),
        "pass_rate": round(len(passed) / n, 4) if n else None,
        "compiles_total": sum(t["compiles"] for t in per_task),
        "compiles_until_pass": {
            "n": len(until),
            "mean": round(statistics.mean(until), 4) if until else None,
            "median": statistics.median(until) if until else None,
        },
        "compile_errors_total": sum(t["compile_errors"] for t in per_task),
        "error_records_total": sum(t["error_records"] for t in per_task),
        "tests_passed_attempts_total": sum(t["tests_passed_attempts"] for t in per_task),
        "unscored_attempts_total": sum(t["unscored"] for t in per_task),
        "tokens_available": all_tokens,
        "tokens_total": sum(token_totals) if all_tokens else NOT_AVAILABLE,
    }


def score_solutions(solutions_dir: pathlib.Path = DEFAULT_SOLUTIONS_DIR,
                    tasks_dir: pathlib.Path = DEFAULT_TASKS_DIR,
                    *, cache_dir: pathlib.Path | None = None,
                    arms: tuple[str, ...] | None = None,
                    tasks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Puntúa todos los brazos/tareas/intentos disponibles en ``solutions_dir``."""
    solutions_dir = pathlib.Path(solutions_dir)
    tasks_dir = pathlib.Path(tasks_dir)
    tasks = tasks if tasks is not None else load_tasks(tasks_dir)
    arms = tuple(arms) if arms is not None else tuple(
        a for a in ARMS if (solutions_dir / a).is_dir()) or ARMS

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "tasks_dir": str(tasks_dir),
        "solutions_dir": str(solutions_dir),
        "scorer": "pyzig.check.check_zig(mode='test', suggest=False)",
        "arms": {},
    }
    for arm in arms:
        per_task: list[dict[str, Any]] = []
        for task in tasks:
            task_dir = solutions_dir / arm / task["task_id"]
            files = _attempt_files(task_dir) if task_dir.is_dir() else []
            tokens_by_attempt = _token_values(task_dir)
            overrides = _agent_overrides(task_dir)
            details: list[dict[str, Any]] = []
            token_values: list[int | None] = []
            first_pass: int | None = None
            for attempt, path in enumerate(files, start=1):
                # El número del archivo gana si viene explícito (attempt-07.zig).
                m = re.match(r"attempt-(\d+)\.zig$", path.name)
                n = int(m.group(1)) if m else attempt
                scored = score_attempt(path.read_text(encoding="utf-8"), task,
                                       cache_dir=cache_dir)
                ov = overrides.get(n, {})
                if ov.get("force_status") == "AGENT_ERROR":
                    scored = {**scored, "status": "AGENT_ERROR", "passed": False}
                if "agent_rc" in ov:
                    scored = {**scored, "agent_rc": ov["agent_rc"]}
                token_values.append(tokens_by_attempt.get(n))
                if scored["passed"] and first_pass is None:
                    first_pass = attempt  # centro el contador en intentos ejecutados
                details.append({
                    "attempt": attempt,
                    "file": str(path.relative_to(solutions_dir)),
                    **scored,
                })
            per_task.append({
                "task_id": task["task_id"],
                "control": task["control"],
                "attempts": len(files),
                "compiles": sum(1 for d in details if d["compiled"] is not None),
                "compiles_until_pass": first_pass,
                "passed": first_pass is not None,
                "compile_errors": sum(1 for d in details if d["compiled"] is False),
                "error_records": sum(d["error_records"] for d in details),
                "tests_passed_attempts": sum(1 for d in details if d["tests_passed"] is True),
                "runtime_failures": sum(1 for d in details if d["status"] == "TEST_FAIL"),
                "unscored": sum(1 for d in details if d["compiled"] is None),
                "tokens": _tokens_summary(token_values),
                "attempts_detail": details,
            })
        report["arms"][arm] = {
            "tasks": {t["task_id"]: t for t in per_task},
            "summary": _summary(per_task),
        }
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks-dir", type=pathlib.Path, default=DEFAULT_TASKS_DIR)
    ap.add_argument("--solutions-dir", type=pathlib.Path, default=DEFAULT_SOLUTIONS_DIR)
    ap.add_argument("--cache-dir", type=pathlib.Path, default=None,
                    help="directorio de cache de zig (por defecto var/build/check-cache)")
    ap.add_argument("--arms", default="", help="brazos a puntuar, p.ej. A,B (por defecto: los presentes)")
    ap.add_argument("--out", type=pathlib.Path, default=None, help="escribir JSON también aquí")
    args = ap.parse_args(argv)
    arms = tuple(a.strip().upper() for a in args.arms.split(",") if a.strip()) or None
    try:
        report = score_solutions(args.solutions_dir, args.tasks_dir,
                                 cache_dir=args.cache_dir, arms=arms)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ab_score: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

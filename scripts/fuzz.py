#!/usr/bin/env python3
"""pyzig-fuzz: control plane del fuzzer diferencial.

El motor (generacion, ejecucion por chunks, comparacion por campos y
evidencia) esta en Zig (`fuzz/`, el camino caliente). Aqui vive el control
plane: materializar los drivers, lanzar las ejecuciones, triagear las
divergencias y (mas adelante) admitir candidatos en el corpus.

Subcomandos:
    prepare   inyecta la implementacion del corpus en cada driver y compila
    diff      ejecuta el motor para una operacion del corpus
    triage    clasifica las divergencias de una ejecucion (conocidas vs nuevas)
    doctor    estado del entorno (sandbox, zig, drivers)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pyzig import corpus as corpus_mod          # noqa: E402
from pyzig.fuzz import contracts                 # noqa: E402
from pyzig.fuzz import triage as triage_mod      # noqa: E402

VAR = ROOT / "var" / "fuzz"
DRIVERS = VAR / "drivers"
RUNS = VAR / "runs"
WORK = VAR / "work"
FUZZ_BIN = ROOT / "fuzz" / "zig-out" / "bin" / "pyzig-fuzz"
MARKER = "// @IMPL@"


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _zig_version() -> str:
    try:
        out = subprocess.run(["zig", "version"], capture_output=True, text=True, timeout=30)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "desconocida"


# --------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------

def prepare(only: str | None = None, verbose: bool = True) -> int:
    """Materializa los drivers (impl del corpus inyectada) y los compila."""
    entries = corpus_mod.load()
    DRIVERS.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "fuzz" / "drivers" / "driver_lib.zig", DRIVERS / "driver_lib.zig")

    cache = VAR / "zig-cache"
    cache.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, dict] = {}
    failures = 0
    for e in entries:
        contract = e.fuzz
        if not contract.get("fuzzable"):
            continue
        schema = contract["schema"]
        if only and schema != only:
            continue
        template_path = ROOT / "fuzz" / contract["driver"]
        if not template_path.exists():
            print(f"ERROR {schema}: no existe el driver {template_path}", file=sys.stderr)
            failures += 1
            continue
        template = template_path.read_text(encoding="utf-8")
        if MARKER not in template:
            print(f"ERROR {schema}: el driver no tiene el marcador {MARKER}", file=sys.stderr)
            failures += 1
            continue
        source = template.replace(MARKER, e.zig_impl)
        src_path = DRIVERS / f"{schema}.zig"
        src_path.write_text(source, encoding="utf-8")
        bin_path = DRIVERS / schema
        cmd = ["zig", "build-exe", f"{schema}.zig", f"-femit-bin={bin_path}"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=str(DRIVERS))
        if proc.returncode != 0:
            print(f"ERROR {schema}: la compilacion del driver fallo", file=sys.stderr)
            print((proc.stderr or proc.stdout)[-2500:], file=sys.stderr)
            failures += 1
            continue
        manifest[schema] = {
            "operation_id": e.operation_id,
            "driver": contract["driver"],
            "source": str(src_path.relative_to(ROOT)),
            "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "binary": str(bin_path.relative_to(ROOT)),
            "binary_sha256": _sha256(bin_path),
            "compared_fields": contract["compared_fields"],
            "model": contract["model"],
        }
        if verbose:
            print(f"driver {schema}: ok ({contract['driver']})")

    (DRIVERS / "manifest.json").write_text(
        json.dumps({"zig_version": _zig_version(), "drivers": manifest}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    if failures:
        print(f"prepare: {failures} driver(s) con errores", file=sys.stderr)
        return 1
    print(f"prepare: {len(manifest)} driver(s) listos en {DRIVERS}")
    return 0


# --------------------------------------------------------------------------
# diff
# --------------------------------------------------------------------------

def _entry_for_op(op: str):
    for e in corpus_mod.load():
        if e.operation_id == op:
            return e
    raise SystemExit(f"operacion desconocida en el corpus: {op}")


def diff(op: str, seed: int, iterations: int, chunk: int, replay: int,
         timeout_ms: int, python_bin: str, run_dir: str | None,
         allow_unsandboxed: bool, keep: bool) -> int:
    e = _entry_for_op(op)
    contract = e.fuzz
    if not contract.get("fuzzable"):
        raise SystemExit(f"{op} no es fuzzable: {contract.get('skip_reason')}")
    schema = contract["schema"]
    subject = DRIVERS / schema
    if not subject.exists():
        raise SystemExit(f"falta el driver compilado {subject}; ejecuta `prepare` primero")
    if not FUZZ_BIN.exists():
        raise SystemExit(f"falta el motor {FUZZ_BIN}; ejecuta `zig build` en fuzz/")

    run_id = f"{schema}-{seed}-{int(time.time())}"
    run_path = pathlib.Path(run_dir) if run_dir else RUNS / run_id
    run_path.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(FUZZ_BIN), "diff",
        "--op", op,
        "--schema", schema,
        "--fields", ",".join(contract["compared_fields"]),
        "--seed", str(seed),
        "--iterations", str(iterations),
        "--chunk", str(chunk),
        "--replay", str(replay),
        "--timeout-ms", str(timeout_ms),
        "--subject", str(subject),
        "--repo", str(ROOT),
        "--python", python_bin,
        "--workdir", str(WORK),
        "--run-dir", str(run_path),
        "--json",
    ]
    if allow_unsandboxed:
        cmd.append("--allow-unsandboxed")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600,
                          errors="replace")
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    summary_path = run_path / "summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["run_dir"] = str(run_path)
        print(json.dumps(summary, ensure_ascii=False))
    return proc.returncode


# --------------------------------------------------------------------------
# triage
# --------------------------------------------------------------------------

def triage(run: str, op: str | None = None) -> int:
    """Clasifica las divergencias de una ejecucion: conocidas vs nuevas."""
    run_path = pathlib.Path(run)
    if not run_path.exists():
        raise SystemExit(f"no existe la ejecucion: {run_path}")
    results_path = run_path / "results.jsonl"
    if not results_path.exists():
        raise SystemExit(f"no hay results.jsonl en {run_path}")
    meta = {}
    meta_path = run_path / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    op_id = op or meta.get("op")
    if not op_id:
        raise SystemExit("no se pudo determinar la operacion (--op o meta.json)")
    e = _entry_for_op(op_id)
    known = e.fuzz.get("known_divergences", [])

    rows = [json.loads(l) for l in results_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    buckets: dict[str, list[dict]] = {}
    new_rows: list[dict] = []
    for row in rows:
        fields = row.get("fields", [])
        if not fields:
            buckets.setdefault(row.get("class", "?"), []).append(row)
            continue
        match = triage_mod.match_known(fields, known)
        if match:
            buckets.setdefault(f"KNOWN:{match}", []).append(row)
        else:
            new_rows.append(row)

    print(f"op={op_id} divergencias={len(rows)}")
    for key in sorted(buckets):
        print(f"  {key}: {len(buckets[key])}")
    if new_rows:
        print(f"  NUEVAS: {len(new_rows)}")
        for row in new_rows[:5]:
            names = ", ".join(
                f"{d['name']}: subject={d['subject']!r} oracle={d['oracle']!r}"
                for d in row.get("fields", []))
            print(f"    caso={row.get('case_sha256','')[:16]} {names}")
    (run_path / "triage.json").write_text(
        json.dumps({
            "op": op_id,
            "known": known,
            "counts": {k: len(v) for k, v in buckets.items()},
            "new_divergences": new_rows,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if new_rows else 0


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------

def doctor() -> int:
    print(f"repo:    {ROOT}")
    print(f"zig:     {_zig_version()}")
    print(f"motor:   {FUZZ_BIN} {'(ok)' if FUZZ_BIN.exists() else '(FALTA: zig build en fuzz/)'}")
    manifest_path = DRIVERS / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(f"drivers: {len(manifest.get('drivers', {}))} compilados")
        for schema, info in sorted(manifest.get("drivers", {}).items()):
            print(f"  {schema}: {info['binary']} sha={info['binary_sha256'][:12]}")
    else:
        print("drivers: ninguno (ejecuta `prepare`)")
    bwrap = shutil.which("bwrap")
    print(f"bwrap:   {bwrap or 'NO DISPONIBLE (el motor es fail-closed)'}")
    print(f"prlimit: {shutil.which('prlimit') or 'NO DISPONIBLE'}")
    fuzzable = contracts.fuzzable_ids()
    print(f"esquemas fuzzables: {len(fuzzable)}")
    for oid in fuzzable:
        c = contracts.CONTRACTS[oid]
        print(f"  {oid} -> {c['schema']} ({len(c['compared_fields'])} campos)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pyzig-fuzz")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare", help="materializa y compila los drivers")
    p.add_argument("--only", help="solo este esquema")

    p = sub.add_parser("diff", help="diferencial de una operacion")
    p.add_argument("--op", required=True)
    p.add_argument("--seed", type=int, default=1337)
    p.add_argument("--iterations", type=int, default=1000)
    p.add_argument("--chunk", type=int, default=500)
    p.add_argument("--replay", type=int, default=16)
    p.add_argument("--timeout-ms", type=int, default=60000)
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--run-dir")
    p.add_argument("--allow-unsandboxed", action="store_true")

    p = sub.add_parser("triage", help="clasifica las divergencias de una ejecucion")
    p.add_argument("--run", required=True)
    p.add_argument("--op")

    sub.add_parser("doctor", help="estado del entorno")

    args = ap.parse_args(argv)
    if args.cmd == "prepare":
        return prepare(only=args.only)
    if args.cmd == "diff":
        return diff(args.op, args.seed, args.iterations, args.chunk, args.replay,
                    args.timeout_ms, args.python, args.run_dir,
                    args.allow_unsandboxed, keep=False)
    if args.cmd == "triage":
        return triage(args.run, args.op)
    if args.cmd == "doctor":
        return doctor()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

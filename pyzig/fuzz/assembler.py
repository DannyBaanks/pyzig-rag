"""F2 — assembler de ejemplos equivalentes al corpus.

Convierte la cosecha sellada por el motor Zig (`harvest.json` + `equiv.jsonl`)
en entradas de corpus. Todo pase por `pyzig.corpus.append_entry`: el unico
escritor recalcula `content_sha256`, sanea rutas y hace la escritura atomica.

Tipos de artefacto:

    case_fixture    caso + observacion-equivalente de un op existente
    pipeline_entry  mismo caso, pero con el adapter de pipeline del contrato
    operation       receta nueva (NO auto-admisible: requiere warden humano)

Los dos primeros salen con `fuzz.auto_admissible=true`; el tercero con false.
El warden (F3) es quien decide la admission final.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

from .. import corpus as corpus_mod
from ..paths import ROOT

AUTO_ADMISSIBLE = ("case_fixture", "pipeline_entry")
BLOCKING_CLASSES = ("CRASH", "TIMEOUT", "INCONCLUSIVE", "NONDETERMINISTIC", "INVALID_ACCEPTED")


class HarvestError(ValueError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_label(run: pathlib.Path) -> str:
    """Ruta portable del run dentro del repo (nunca absoluta del home)."""
    try:
        return str(run.resolve().relative_to(ROOT))
    except ValueError:
        return run.name


def read_harvest(run: pathlib.Path) -> tuple[dict, list[dict]]:
    """Lee y verifica la cosecha; falla cerrado si algo no cuadra."""
    meta_path = run / "harvest.json"
    if not meta_path.exists():
        raise HarvestError(f"no hay harvest.json en {run}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("kind") != "fuzz-harvest-v1":
        raise HarvestError(f"kind de cosecha desconocido: {meta.get('kind')!r}")

    equiv_path = run / meta.get("equiv_file", "equiv.jsonl")
    raw = equiv_path.read_bytes()
    if _sha256(raw) != meta.get("equiv_sha256"):
        raise HarvestError("equiv.jsonl no coincide con equiv_sha256")

    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if len(rows) != meta.get("equiv_stored"):
        raise HarvestError("equiv_stored no coincide con el numero de registros")
    for r in rows:
        case = bytes.fromhex(r["case"])
        obs = bytes.fromhex(r["obs"])
        if _sha256(case) != r["case_sha256"]:
            raise HarvestError(f"case_sha256 roto en i={r.get('i')}")
        if _sha256(obs) != r["obs_sha256"]:
            raise HarvestError(f"obs_sha256 roto en i={r.get('i')}")
        if r.get("status") != "ok":
            raise HarvestError(f"ejemplo no-ok en la cosecha: i={r.get('i')}")
    return meta, rows


def check_run_health(run: pathlib.Path) -> dict:
    """Un ejemplo solo es admitible si la ejecucion no tuvo hallazgos nuevos."""
    summary_path = run / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    counts = summary.get("counts", {})
    for name in BLOCKING_CLASSES:
        if counts.get(name, 0):
            raise HarvestError(f"la ejecucion tiene {name}={counts[name]}; no se cosecha")
    if counts.get("DIVERGENT", 0):
        triage_path = run / "triage.json"
        if not triage_path.exists():
            raise HarvestError("hay divergencias sin triar; ejecuta `fuzz.py triage` primero")
        triage = json.loads(triage_path.read_text(encoding="utf-8"))
        if triage.get("new_divergences"):
            raise HarvestError("hay divergencias NUEVAS; no se cosecha de esta ejecucion")
    return summary


def build_entry(parent: dict, meta: dict, row: dict, kind: str, run: pathlib.Path) -> dict:
    """Construye una entrada de corpus a partir de un caso equivalente."""
    if kind not in ("case_fixture", "pipeline_entry", "operation"):
        raise HarvestError(f"kind desconocido: {kind}")
    if kind == "pipeline_entry" and not parent.get("fuzz", {}).get("pipeline"):
        raise HarvestError("el op padre no declara fuzz.pipeline")

    short = row["case_sha256"][:12]
    e = dict(parent)
    e["operation_id"] = f"{parent['operation_id']}/{kind}-{short}"
    e["entry_type"] = kind
    e["name"] = f"{parent['name']} — {kind.replace('_', ' ')} {short}"
    e["intent"] = (f"Ejemplo {kind} cosechado por fuzzing diferencial de "
                   f"{parent['operation_id']}; caso y observacion validados EQUIV.")
    e["zig_test"] = None
    e["tests"] = []
    e.pop("content_sha256", None)

    harvest_evidence = {
        "kind": "fuzz-equivalence",
        "run": _run_label(run),
        "seed": meta["seed"],
        "iterations": meta["iterations"],
        "subject_sha256": meta["subject_sha256"],
        "results_sha256": meta["results_sha256"],
        "harvest_sha256": meta["equiv_sha256"],
        "case_sha256": row["case_sha256"],
        "obs_sha256": row["obs_sha256"],
    }
    e["evidence"] = {"status": "FUZZ_EQUIV", "runs": [harvest_evidence]}

    fuzz = dict(parent.get("fuzz", {}))
    fuzz["artifact_kind"] = kind
    fuzz["auto_admissible"] = kind in AUTO_ADMISSIBLE
    fuzz["case_fixture"] = {
        "case_hex": row["case"],
        "case_sha256": row["case_sha256"],
        "obs_hex": row["obs"],
        "obs_sha256": row["obs_sha256"],
        "status": row["status"],
        "compared_fields": meta["fields"].split(","),
        "source_case_index": row.get("i"),
    }
    if kind == "pipeline_entry":
        fuzz["pipeline_fixture"] = dict(parent["fuzz"]["pipeline"])
        fuzz["pipeline_fixture"]["input_bytes_hex"] = row["case"]
        fuzz["pipeline_fixture"]["output_bytes_hex"] = row["obs"]
    e["fuzz"] = fuzz
    e["provenance"] = (f"FUZZ_EQUIV seed={meta['seed']} run={_run_label(run)} "
                       f"case={row['case_sha256'][:12]} (padre: {parent['provenance']})")
    return e


def assemble(run: pathlib.Path, op: str | None, kind: str, limit: int | None,
             dry_run: bool, corpus_path: pathlib.Path | None = None) -> list[str]:
    run = pathlib.Path(run)
    meta, rows = read_harvest(run)
    check_run_health(run)
    op_id = op or meta["op"]

    parent_entry = None
    for e in corpus_mod.load(corpus_path):
        if e.operation_id == op_id:
            parent_entry = e
            break
    if parent_entry is None:
        raise HarvestError(f"no existe el op padre en el corpus: {op_id}")
    parent = parent_entry.raw

    existing = {e.operation_id for e in corpus_mod.load(corpus_path)}
    selected = rows[:limit] if limit is not None else rows
    planned = [build_entry(parent, meta, row, kind, run) for row in selected]

    ids: list[str] = []
    for e in planned:
        oid = e["operation_id"]
        if oid in existing:
            print(f"YA PRESENTE {oid}", file=sys.stderr)
            continue
        if dry_run:
            print(json.dumps(e, ensure_ascii=False, sort_keys=True))
        else:
            corpus_mod.append_entry(e, path=corpus_path)
        ids.append(oid)
    return ids


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pyzig-fuzz-assembler")
    ap.add_argument("--run", required=True)
    ap.add_argument("--op", help="operation_id padre (por defecto, el de harvest.json)")
    ap.add_argument("--kind", default="case_fixture",
                    choices=("case_fixture", "pipeline_entry", "operation"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:
        ids = assemble(pathlib.Path(args.run), args.op, args.kind,
                       args.limit, args.dry_run)
    except (HarvestError, ValueError, KeyError) as exc:
        print(f"assembler: {exc}", file=sys.stderr)
        return 2
    print(f"assembler: {args.kind} {len(ids)} entrada(s)")
    for oid in ids:
        print(f"  {oid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

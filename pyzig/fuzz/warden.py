"""F3 — warden del corpus: 7 invariantes y transiciones admit/regress.

El warden no escribe el JSONL a mano: usa `pyzig.corpus.update_entry`, el unico
escritor, que recalcula `content_sha256` y mantiene la cadena de evidencia.

Invariantes (todas fail-closed):

    I1 HASH_CHAIN          hash del contenido valido e id unico
    I2 ARTIFACT_KIND       solo case_fixture / pipeline_entry son auto-admisibles
    I3 EVIDENCE_PROVENANCE evidencia FUZZ_EQUIV con seed/hashes/ruta portable
    I4 FIXTURE_INTEGRITY   caso y observacion decodifican y sus hashes cuadran
    I5 PARENT_CONTRACT     esquema, campos, modelo y firma coinciden con el padre
    I6 CLEAN_RUN           sandbox fail-closed, sin hallazgos nuevos, driver vigente
    I7 NO_DUPLICATE_CASE   un mismo caso no se admite dos veces
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time

from .. import corpus as corpus_mod
from ..paths import ROOT
from . import drivers

AUTO_ADMISSIBLE = ("case_fixture", "pipeline_entry")
BLOCKING_CLASSES = ("CRASH", "TIMEOUT", "INCONCLUSIVE", "NONDETERMINISTIC", "INVALID_ACCEPTED")
REQUIRED_EVIDENCE = ("seed", "iterations", "subject_sha256", "results_sha256",
                     "harvest_sha256", "case_sha256", "obs_sha256")
INVARIANTS = (
    "HASH_CHAIN", "ARTIFACT_KIND", "EVIDENCE_PROVENANCE", "FIXTURE_INTEGRITY",
    "PARENT_CONTRACT", "CLEAN_RUN", "NO_DUPLICATE_CASE",
)
WARDEN_DIR = ROOT / "var" / "fuzz" / "warden"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _field_count(packed: bytes) -> int:
    """Numero de campos de una observacion length-prefixed (u32 LE)."""
    n = 0
    pos = 0
    while pos + 4 <= len(packed):
        size = int.from_bytes(packed[pos:pos + 4], "little")
        pos += 4 + size
        if pos > len(packed):
            raise ValueError("campo truncado en la observacion")
        n += 1
    if pos != len(packed):
        raise ValueError("colas extra en la observacion")
    return n


def _driver_identity(schema: str) -> dict:
    """Identidad del driver vigente (fuente + zig), no el hash del binario:
    `zig build-exe` no es reproducible y recompilar no cambia el comportamiento."""
    return drivers.identity(drivers.entry(schema))


def check_entry(e: corpus_mod.Entry, by_id: dict[str, corpus_mod.Entry],
                seen_cases: set[tuple[str, str, str]], duplicate_ids: set[str],
                *, regress: bool = False) -> list[str]:
    """Devuelve la lista de invariantes incumplidos (vacia = pasa)."""
    bad: list[str] = []
    fuzz = e.fuzz
    raw = e.raw

    # I1 — hash chain
    if (not e.content_sha256 or e.content_sha256 != corpus_mod.content_hash(raw)
            or e.operation_id in duplicate_ids):
        bad.append("I1 HASH_CHAIN")

    # I2 — artifact kind
    if e.entry_type not in AUTO_ADMISSIBLE or not fuzz.get("auto_admissible"):
        bad.append("I2 ARTIFACT_KIND")

    # I3 — provenance
    runs = e.evidence.get("runs", [])
    run = runs[0] if runs else {}
    missing = [k for k in REQUIRED_EVIDENCE if not run.get(k)]
    allowed = ("ADMITTED", "REGRESSED") if regress else ("FUZZ_EQUIV", "ADMITTED", "REGRESSED")
    if missing or e.evidence.get("status") not in allowed:
        bad.append("I3 EVIDENCE_PROVENANCE")
    label = str(run.get("run", ""))
    if "/home/" in label or label.startswith("/"):
        bad.append("I3 EVIDENCE_PROVENANCE")

    # I4 — fixture integrity
    fixture = fuzz.get("case_fixture", {})
    try:
        case = bytes.fromhex(fixture["case_hex"])
        obs = bytes.fromhex(fixture["obs_hex"])
        if _sha256(case) != fixture["case_sha256"] or _sha256(obs) != fixture["obs_sha256"]:
            raise ValueError("hash de caso/observacion roto")
        if fixture.get("status") != "ok":
            raise ValueError("observacion no-ok en la cosecha")
        if _field_count(obs) != len(fixture.get("compared_fields", [])):
            raise ValueError("numero de campos no coincide con el contrato")
        if not fixture.get("compared_fields"):
            raise ValueError("sin campos comparados")
    except (KeyError, TypeError, ValueError):
        bad.append("I4 FIXTURE_INTEGRITY")

    # I5 — parent contract
    parent_id = e.operation_id.rsplit("/", 1)[0]
    parent = by_id.get(parent_id)
    if parent is None:
        bad.append("I5 PARENT_CONTRACT")
    else:
        for key in ("schema", "compared_fields", "model"):
            if fuzz.get(key) != parent.fuzz.get(key):
                bad.append("I5 PARENT_CONTRACT")
                break
        if e.type_signature != parent.type_signature:
            bad.append("I5 PARENT_CONTRACT")

    # I6 — clean run + driver still current
    snap = run.get("run_snapshot", {})
    counts = snap.get("counts", {})
    if (snap.get("sandbox") != "bwrap" or snap.get("new_divergences") != 0
            or any(counts.get(k, 0) for k in BLOCKING_CLASSES)):
        bad.append("I6 CLEAN_RUN")
    current = _driver_identity(fuzz.get("schema", ""))
    recorded = {"source_sha256": snap.get("driver_source_sha256", ""),
                "zig_version": snap.get("driver_zig_version", "")}
    if not all(recorded.values()) or recorded != current:
        bad.append("I6 CLEAN_RUN")

    # I7 — un mismo caso no se admite dos veces como el MISMO artefacto DEL
    # MISMO op; case_fixture y pipeline_entry del mismo caso son
    # complementarios, y los mismos bytes en otro op son otra prueba.
    key = case_key(e)
    if not key[1] or key in seen_cases:
        bad.append("I7 NO_DUPLICATE_CASE")
    seen_cases.add(key)

    return sorted(set(bad))


def case_key(e: corpus_mod.Entry) -> tuple[str, str, str]:
    """(op padre, sha del caso, tipo de artefacto): identidad para I7."""
    case_sha = e.fuzz.get("case_fixture", {}).get("case_sha256", "")
    return (e.operation_id.rsplit("/", 1)[0], case_sha, e.entry_type)


def _write_report(name: str, report: dict, report_dir: pathlib.Path | None = None) -> pathlib.Path:
    out_dir = pathlib.Path(report_dir or WARDEN_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _run(mode: str, corpus_path: pathlib.Path | None, force: bool,
         report_dir: pathlib.Path | None = None) -> int:
    entries = corpus_mod.load(corpus_path)
    by_id = {e.operation_id: e for e in entries}
    raw_rows = corpus_mod._read_raw(corpus_path or corpus_mod.CORPUS_FILE)
    ids_seen: set[str] = set()
    duplicate_ids: set[str] = set()
    for row in raw_rows:
        oid = row.get("operation_id", "")
        if oid in ids_seen:
            duplicate_ids.add(oid)
        ids_seen.add(oid)
    if mode == "regress":
        candidates = [e for e in entries if e.entry_type in AUTO_ADMISSIBLE
                      and e.evidence.get("status") in ("ADMITTED", "REGRESSED")]
    else:
        candidates = [e for e in entries if e.entry_type in ("case_fixture", "pipeline_entry", "operation")]
    seen_cases: set[tuple[str, str, str]] = set()
    report: dict = {
        "mode": mode,
        "at": int(time.time()),
        "invariants": list(INVARIANTS),
        "results": [],
    }

    for e in candidates:
        if mode == "admit" and e.entry_type == "operation":
            verdict, bad = "MANUAL_REVIEW", ["I2 ARTIFACT_KIND"]
        elif mode == "admit" and not force and e.evidence.get("status") == "ADMITTED":
            verdict, bad = "ADMITTED", []
            # no se reverifica, pero su caso SI cuenta para I7: sin esto un
            # duplicado de algo ya admitido pasaba admit y caia en regress
            seen_cases.add(case_key(e))
        else:
            bad = check_entry(e, by_id, seen_cases, duplicate_ids,
                              regress=(mode == "regress"))
            if mode == "admit":
                verdict = "ADMITTED" if not bad else "REJECTED"
            else:
                verdict = "ADMITTED" if not bad else "REGRESSED"
        report["results"].append({
            "operation_id": e.operation_id,
            "entry_type": e.entry_type,
            "verdict": verdict,
            "failed": bad,
        })
        prev_warden = e.evidence.get("warden", {})
        unchanged = (e.evidence.get("status") == verdict
                     and prev_warden.get("failed_invariants") == bad)
        # Idempotente: si el veredicto no cambia no se reescribe la entrada
        # (antes cada corrida cambiaba `at` y con el content_sha256 del corpus).
        if (e.entry_type in AUTO_ADMISSIBLE or mode == "admit") and not unchanged:
            def mutate(row: dict, status: str = verdict, failures: list[str] = bad, m=mode) -> None:
                ev = dict(row.get("evidence", {}))
                ev["status"] = status
                ev["warden"] = {"mode": m, "at": report["at"],
                                "failed_invariants": failures}
                row["evidence"] = ev
            corpus_mod.update_entry(e.operation_id, mutate, path=corpus_path)

    passed = sum(1 for r in report["results"] if r["verdict"] == "ADMITTED")
    report["summary"] = {"total": len(candidates), "passed": passed,
                         "failed": len(candidates) - passed}
    path = _write_report(mode, report, report_dir)
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(f"warden {mode}: {path}")
    for r in report["results"]:
        if r["verdict"] != "ADMITTED":
            print(f"  {r['verdict']} {r['operation_id']}: {', '.join(r['failed'])}")
    return 0 if report["summary"]["failed"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pyzig-fuzz-warden")
    ap.add_argument("mode", choices=("admit", "regress"))
    ap.add_argument("--force", action="store_true", help="reevalua entradas ya admitidas")
    ap.add_argument("--corpus")
    args = ap.parse_args(argv)
    try:
        return _run(args.mode, pathlib.Path(args.corpus) if args.corpus else None, args.force)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"warden: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

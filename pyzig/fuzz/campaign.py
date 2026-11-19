"""F4 — campana/loop: presupuesto, cola de candidatos y auto-merge.

El trabajo pesado sigue en el motor Zig. Este modulo solo decide QUE ejecutar,
con que semilla y bajo que presupuesto, y si el resultado puede entrar al
corpus: ninguna divergencia nueva (triage), solo artefactos auto-admisibles y
siempre pasando por el warden. Nunca se auto-mergea una receta nueva.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass

from .. import corpus as corpus_mod
from ..paths import ROOT
from . import assembler, contracts, warden

BLOCKING_CLASSES = ("CRASH", "TIMEOUT", "INCONCLUSIVE", "NONDETERMINISTIC", "INVALID_ACCEPTED")
FUZZ_SCRIPT = ROOT / "scripts" / "fuzz.py"
CAMPAIGN_DIR = ROOT / "var" / "fuzz" / "campaigns"


def _sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


@dataclass
class CampaignConfig:
    seed: int = 1337
    iterations: int = 200
    chunk: int = 100
    replay: int = 8
    harvest_limit: int = 20
    timeout_ms: int = 60000
    budget_seconds: float = 600.0
    budget_iterations: int = 5000
    rounds: int = 1                 # 0 = loop hasta agotar presupuesto
    ops: tuple[str, ...] = ()
    auto_merge: bool = True
    dry_run: bool = False

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["ops"] = list(self.ops)
        return d


def build_queue(cfg: CampaignConfig, entries: list[corpus_mod.Entry] | None = None) -> list[dict]:
    """Cola determinista: primero los ops con menos artefactos admitidos."""
    entries = entries if entries is not None else corpus_mod.load()
    admitted: dict[str, int] = {}
    for e in entries:
        if e.entry_type in warden.AUTO_ADMISSIBLE and e.evidence.get("status") == "ADMITTED":
            parent = e.operation_id.rsplit("/", 1)[0]
            admitted[parent] = admitted.get(parent, 0) + 1

    if cfg.ops:
        missing = [op for op in cfg.ops if op not in contracts.CONTRACTS]
        if missing:
            raise ValueError(f"ops desconocidos: {', '.join(missing)}")
        pairs = [(op, contracts.CONTRACTS[op]) for op in cfg.ops]
    else:
        pairs = [(op, contracts.CONTRACTS[op]) for op in contracts.fuzzable_ids()]
    return [{
        "op": op,
        "schema": c["schema"],
        "admitted_artifacts": admitted.get(op, 0),
        "has_pipeline": bool(c.get("pipeline")),
    } for op, c in sorted(pairs, key=lambda pair: (admitted.get(pair[0], 0), pair[0]))]


def merge_decision(summary: dict, triage_ok: bool, kind: str) -> bool:
    """Politica de auto-merge: fail-closed."""
    if kind not in warden.AUTO_ADMISSIBLE:
        return False
    counts = summary.get("counts", {})
    if any(counts.get(k, 0) for k in BLOCKING_CLASSES):
        return False
    divergences = summary.get("divergences", counts.get("DIVERGENT", 0))
    if divergences and not triage_ok:
        return False
    return summary.get("status") in ("CLEAN", "DIVERGENCES_FOUND")


def stage_and_merge(run_dir: pathlib.Path, op: str, kinds: list[str], limit: int,
                    corpus_path: pathlib.Path | None = None) -> tuple[list[str], dict[str, list[str]]]:
    """Ensambla y pasa el warden en una COPIA del corpus; solo lo ADMITTED
    llega al corpus real.

    Antes se anadia al corpus real y despues se corria el warden: lo rechazado
    se quedaba dentro como REJECTED. Devuelve (ids fusionados, rechazados con
    sus invariantes incumplidos).
    """
    real = pathlib.Path(corpus_path or corpus_mod.CORPUS_FILE)
    with tempfile.TemporaryDirectory(prefix="pyzig-stage-") as tmp:
        staging = pathlib.Path(tmp) / real.name
        shutil.copyfile(real, staging)
        ids: list[str] = []
        for kind in kinds:
            ids.extend(assembler.assemble(run_dir, op, kind, limit, False, staging))
        if not ids:
            return [], {}
        warden._run("admit", staging, False, report_dir=run_dir)
        staged = {e.operation_id: e for e in corpus_mod.load(staging)}
        merged: list[str] = []
        rejected: dict[str, list[str]] = {}
        for oid in ids:
            e = staged[oid]
            if e.evidence.get("status") == "ADMITTED":
                corpus_mod.append_entry(e.raw, path=real)
                merged.append(oid)
            else:
                rejected[oid] = e.evidence.get("warden", {}).get("failed_invariants", [])
        return merged, rejected


def _run_cmd(args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(FUZZ_SCRIPT)] + args, cwd=ROOT,
                          capture_output=True, text=True, timeout=timeout)


def run_campaign(cfg: CampaignConfig) -> int:
    queue = build_queue(cfg)
    campaign_id = f"{int(time.time())}-{cfg.seed}"
    out_dir = CAMPAIGN_DIR / campaign_id
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    results: list[dict] = []
    used_iterations = 0
    if cfg.dry_run:
        for i, item in enumerate(queue):
            results.append({"op": item["op"], "round": 0,
                            "seed": cfg.seed + i, "plan": True})
    else:
        rounds = cfg.rounds if cfg.rounds > 0 else 10000
        for round_no in range(rounds):
            if (time.monotonic() - started >= cfg.budget_seconds
                    or used_iterations >= cfg.budget_iterations):
                break
            for i, item in enumerate(queue):
                if (time.monotonic() - started >= cfg.budget_seconds
                        or used_iterations >= cfg.budget_iterations):
                    break
                seed = cfg.seed + round_no * 7919 + i
                run_dir = out_dir / f"{_safe(item['op'])}-r{round_no}-s{seed}"
                rec: dict = {"op": item["op"], "schema": item["schema"],
                             "round": round_no, "seed": seed,
                             "run": assembler._run_label(run_dir)}
                cmd = ["diff", "--op", item["op"], "--seed", str(seed),
                       "--iterations", str(cfg.iterations), "--chunk", str(cfg.chunk),
                       "--replay", str(cfg.replay),
                       "--harvest-limit", str(cfg.harvest_limit),
                       "--timeout-ms", str(cfg.timeout_ms),
                       "--run-dir", str(run_dir)]
                try:
                    proc = _run_cmd(cmd)
                except subprocess.TimeoutExpired:
                    rec.update({"verdict": "TIMEOUT", "detail": "presupuesto agotado"})
                    results.append(rec)
                    break
                used_iterations += cfg.iterations
                # Contrato del motor: exit 0 = CLEAN, exit 1 = hubo divergencias
                # (conocidas o no: eso lo decide triage). Solo es fallo del motor
                # otro codigo o la ausencia de summary.json.
                summary_path = run_dir / "summary.json"
                if proc.returncode not in (0, 1) or not summary_path.exists():
                    rec.update({"verdict": "ENGINE_FAILED",
                                "detail": (proc.stderr or proc.stdout)[-500:]})
                    results.append(rec)
                    continue
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                if (proc.returncode == 1) != (summary.get("status") == "DIVERGENCES_FOUND"):
                    rec.update({"verdict": "ENGINE_FAILED",
                                "detail": f"exit {proc.returncode} incoherente con "
                                          f"status {summary.get('status')!r}"})
                    results.append(rec)
                    continue
                rec["summary_sha256"] = _sha256_file(summary_path)
                triage_ok = True
                if summary.get("divergences", 0):
                    tproc = _run_cmd(["triage", "--run", str(run_dir), "--op", item["op"]])
                    triage_ok = tproc.returncode == 0
                    rec["triage_ok"] = triage_ok
                merged: list[str] = []
                rejected: dict[str, list[str]] = {}
                if cfg.auto_merge and merge_decision(summary, triage_ok, "case_fixture"):
                    kinds = ["case_fixture"] + (["pipeline_entry"] if item["has_pipeline"] else [])
                    try:
                        merged, rejected = stage_and_merge(run_dir, item["op"], kinds,
                                                           cfg.harvest_limit)
                    except (ValueError, KeyError) as exc:
                        # un op que no se puede cosechar no tumba la campana
                        rec.update({"verdict": "MERGE_FAILED", "detail": str(exc)[-500:]})
                        results.append(rec)
                        continue
                verdict = "MERGED" if merged else ("REJECTED" if rejected else "CLEAN")
                rec.update({"verdict": verdict,
                            "divergences": summary.get("divergences", 0),
                            "counts": summary.get("counts", {}),
                            "merged": merged,
                            "rejected": rejected})
                results.append(rec)
            if cfg.rounds == 0 and used_iterations >= cfg.budget_iterations:
                break

    report = {
        "kind": "fuzz-campaign-v1",
        "config": cfg.as_dict(),
        "queue": queue,
        "results": results,
        "summary": {
            "runs": len(results),
            "merged": sum(len(r.get("merged", [])) for r in results),
            "failed": sum(1 for r in results if r.get("verdict") in ("ENGINE_FAILED", "TIMEOUT", "REJECTED", "MERGE_FAILED")),
            "elapsed_s": round(time.monotonic() - started, 3),
            "iterations": used_iterations,
        },
    }
    path = out_dir / "campaign.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "campaign.sha256").write_text(_sha256_file(path) + "  campaign.json\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(f"campana: {path}")
    return 0 if report["summary"]["failed"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pyzig-fuzz-campaign")
    ap.add_argument("mode", choices=("campaign", "loop"))
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--iterations", type=int, default=200)
    ap.add_argument("--chunk", type=int, default=100)
    ap.add_argument("--replay", type=int, default=8)
    ap.add_argument("--harvest-limit", type=int, default=20)
    ap.add_argument("--timeout-ms", type=int, default=60000)
    ap.add_argument("--budget-seconds", type=float, default=600.0)
    ap.add_argument("--budget-iterations", type=int, default=5000)
    ap.add_argument("--rounds", type=int, default=1,
                    help="0 = loop hasta agotar presupuesto")
    ap.add_argument("--ops", help="lista de operation_id separada por comas")
    ap.add_argument("--no-merge", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    cfg = CampaignConfig(
        seed=args.seed, iterations=args.iterations, chunk=args.chunk,
        replay=args.replay, harvest_limit=args.harvest_limit,
        timeout_ms=args.timeout_ms, budget_seconds=args.budget_seconds,
        budget_iterations=args.budget_iterations,
        rounds=args.rounds if args.mode == "campaign" else 0,
        ops=tuple(o.strip() for o in args.ops.split(",") if o.strip()) if args.ops else (),
        auto_merge=not args.no_merge, dry_run=args.dry_run,
    )
    try:
        return run_campaign(cfg)
    except (ValueError, KeyError) as exc:
        print(f"campana: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Gates: compila y ejecuta los zig_test del corpus; promueve evidencia."""
from __future__ import annotations
import hashlib, json, pathlib, subprocess, time, re
from .paths import BUILD, CORPUS_FILE, ROOT
from . import corpus as corpus_mod

def _safe(op_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", op_id)

def _rel(p: pathlib.Path) -> str:
    """Ruta relativa a la raiz del repo: el corpus es portable."""
    try:
        return str(pathlib.Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)

def run_gates(timeout_sec: int = 600) -> list[dict]:
    BUILD.mkdir(parents=True, exist_ok=True)
    entries = corpus_mod.load()
    results = []
    for e in entries:
        if not e.zig_test:
            results.append({"operation_id": e.operation_id, "skipped": True,
                            "reason": "sin zig_test", "status": e.status})
            continue
        f = BUILD / f"{_safe(e.operation_id)}.zig"
        f.write_text(e.zig_test, encoding="utf-8")
        cmd = ["zig", "test", f.name]
        t0 = time.time()
        p = subprocess.run(cmd, cwd=BUILD, capture_output=True, text=True, timeout=timeout_sec)
        dt = round(time.time() - t0, 2)
        out = (p.stdout or "") + (p.stderr or "")
        run = {"cmd": " ".join(cmd), "cwd": _rel(BUILD), "exit": p.returncode,
               "duration_s": dt, "stdout_sha256": hashlib.sha256(out.encode()).hexdigest(),
               "zig_version": _zig_version(), "observed": out.strip()[-4000:]}
        new_status = "DEMONSTRATED" if p.returncode == 0 else "REJECTED"
        ev = dict(e.evidence)
        ev["status"] = new_status
        ev["runs"] = list(ev.get("runs", [])) + [run]
        payload = dict(e.raw)
        payload["evidence"] = ev
        results.append({"operation_id": e.operation_id, "exit": p.returncode,
                        "duration_s": dt, "status": new_status})
        _rewrite(payload)
    return results

def _zig_version() -> str:
    try:
        return subprocess.run(["zig", "version"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"

def _rewrite(payload: dict) -> None:
    """Actualiza la entrada via el unico escritor (recalcula content_sha256)."""
    def mutate(d: dict) -> None:
        d["evidence"] = payload["evidence"]
    corpus_mod.update_entry(payload["operation_id"], mutate)

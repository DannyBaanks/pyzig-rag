"""Gates: compila y ejecuta los zig_test del corpus; promueve evidencia."""
from __future__ import annotations
import hashlib, json, pathlib, subprocess, time, re
from .paths import BUILD, CORPUS_FILE
from . import corpus as corpus_mod

def _safe(op_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", op_id)

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
        run = {"cmd": " ".join(cmd), "cwd": str(BUILD), "exit": p.returncode,
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
    lines = [json.dumps(json.loads(l), ensure_ascii=False) for l in CORPUS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    for i, l in enumerate(lines):
        d = json.loads(l)
        if d["operation_id"] == payload["operation_id"]:
            lines[i] = json.dumps(payload, ensure_ascii=False)
            break
    CORPUS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

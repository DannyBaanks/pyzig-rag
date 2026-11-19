"""Gates: compila y ejecuta los zig_test del corpus; promueve evidencia.

Dos modos por entrada:
- por defecto: `zig test <zig_test>` sobre un archivo suelto (en `var/build`);
- `gate_mode: "build"`: escribe `build_files` (build.zig + src/...) en un
  directorio temporal y ejecuta `zig build test` alli. No necesita red: se rechazan
  URLs y `b.dependency`. NO es un sandbox (igual que el gate de `zig test`): el corpus
  es codigo propio del repo; el codigo no confiable va por `pyzig_check` (bwrap).
"""
from __future__ import annotations
import hashlib, json, pathlib, subprocess, tempfile, time, re
from .paths import BUILD, CORPUS_FILE, ROOT
from . import corpus as corpus_mod

GATE_MODE_BUILD = "build"
#: `--summary all` hace que zig imprima el resumen de tests (sin el, un
#: `zig build test` que pasa no dice cuantos tests ejecuto).
BUILD_CMD = ["zig", "build", "test", "--summary", "all"]
BUILD_CWD_LABEL = "<tmp>"

def _safe(op_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", op_id)

def _rel(p: pathlib.Path) -> str:
    """Ruta relativa a la raiz del repo: el corpus es portable."""
    try:
        return str(pathlib.Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)

def _run_key(run: dict) -> tuple:
    """Identidad de una ejecucion de gate, ignorando tiempo y texto variable."""
    return (run.get("cmd"), run.get("cwd"), run.get("exit"),
            run.get("stdout_sha256"), run.get("zig_version"))


def run_gates(timeout_sec: int = 600) -> list[dict]:
    BUILD.mkdir(parents=True, exist_ok=True)
    entries = corpus_mod.load()
    results = []
    for e in entries:
        mode = e.raw.get("gate_mode")
        if mode == GATE_MODE_BUILD:
            results.append(_gate_build_entry(e, timeout_sec))
            continue
        if mode:
            raise ValueError(f"{e.operation_id}: gate_mode desconocido {mode!r}")
        if not e.zig_test:
            results.append({"operation_id": e.operation_id, "skipped": True,
                            "reason": "sin zig_test", "status": e.status})
            continue
        f = BUILD / f"{_safe(e.operation_id)}.zig"
        f.write_text(e.zig_test, encoding="utf-8")
        # zig_flags opcional por receta (p.ej. ["-lc"] para FFI con libc): sin el, el
        # gate saltaria justo los tests que demuestran la receta.
        flags = [str(x) for x in (e.raw.get("zig_flags") or [])]
        cmd = ["zig", "test", *flags, f.name]
        t0 = time.time()
        p = subprocess.run(cmd, cwd=BUILD, capture_output=True, text=True, timeout=timeout_sec)
        dt = round(time.time() - t0, 2)
        out = (p.stdout or "") + (p.stderr or "")
        run = {"cmd": " ".join(cmd), "cwd": _rel(BUILD), "exit": p.returncode,
               "duration_s": dt, "stdout_sha256": hashlib.sha256(out.encode()).hexdigest(),
               "zig_version": _zig_version(), "observed": out.strip()[-4000:]}
        skipped = _skipped_count(out)
        if p.returncode != 0:
            new_status = "REJECTED"
        elif skipped:
            # pasa, pero con tests saltados: no se promueve a demostrado
            new_status = "MANUAL_REVIEW"
        else:
            new_status = "DEMONSTRATED"
        run["skipped_tests"] = skipped
        ev = dict(e.evidence)
        ev["status"] = new_status
        # Re-ejecutar los gates no debe inflar el corpus: el duration_s varia,
        # pero cmd/cwd/exit/hash de salida/version identifican la misma prueba.
        runs = list(ev.get("runs", []))
        if not any(_run_key(r) == _run_key(run) for r in runs):
            runs.append(run)
        ev["runs"] = runs
        payload = dict(e.raw)
        payload["evidence"] = ev
        results.append({"operation_id": e.operation_id, "exit": p.returncode,
                        "duration_s": dt, "status": new_status})
        _rewrite(payload)
    return results

_SKIPPED_RE = re.compile(r"(\d+) passed; (\d+) skipped; (\d+) failed")

def _skipped_count(out: str) -> int:
    """Tests saltados segun el resumen de `zig test` (0 si dice 'All N tests passed')."""
    m = _SKIPPED_RE.search(out)
    return int(m.group(2)) if m else 0

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

# ---------------------------------------------------------------- gate de build

_URL_RE = re.compile(r"https?://|\.url\s*=")
_DEP_RE = re.compile(r"\bb\.dependency\(")
#: Ruido que cambia entre ejecuciones (tiempos, memoria, cache hit): fuera del hash de salida.
_NOISE_RE = re.compile(r"\d+(?:\.\d+)?(?:ms|s)\b|MaxRSS:\S+|\b(?:cached|success)\b")
_BUILD_TESTS_RE = re.compile(r"(\d+) pass(?:, (\d+) skip)? \((\d+) total\)")

def validate_build_files(files) -> str | None:
    """Motivo de rechazo de `build_files` (None si es admisible): sin red ni dependencias."""
    if not isinstance(files, dict) or "build.zig" not in files:
        return "build_files debe ser un dict que incluya build.zig"
    for path, content in files.items():
        p = pathlib.PurePosixPath(path)
        if (not path or p.is_absolute() or ".." in p.parts or "." in path.split("/")
                or path.endswith("/") or "" in path.split("/") or not isinstance(content, str)):
            return f"ruta o contenido invalido en build_files: {path!r}"
        if _URL_RE.search(content):
            return f"build_files con URL en {path}: el gate no tiene red"
    for path in files:  # un archivo no puede ser a la vez directorio de otro
        parents = {str(q) for q in pathlib.PurePosixPath(path).parents}
        clash = parents & set(files)
        if clash:
            return f"build_files: {sorted(clash)[0]!r} es archivo y directorio de {path!r}"
    if _DEP_RE.search(files["build.zig"]):
        return "build.zig declara dependencias (b.dependency): el gate solo admite proyectos sin dependencias"
    return None

def build_tests(out: str) -> tuple[int, int]:
    """(pasados, saltados) sumados de las lineas `N pass[, M skip] (T total)` de `--summary all`."""
    passed = skipped = 0
    for m in _BUILD_TESTS_RE.finditer(out):
        passed += int(m.group(1))
        skipped += int(m.group(2) or 0)
    return passed, skipped

def _normalize_build_output(out: str, tmp: str) -> str:
    """Salida de zig sin ruta temporal ni ruido de tiempos (para un hash estable)."""
    return _NOISE_RE.sub("", out.replace(tmp, BUILD_CWD_LABEL))

def run_build_project(files: dict, timeout_sec: int = 600) -> dict:
    """Escribe `files` en un directorio temporal y corre `zig build test` alli.

    Devuelve el run (mismo formato que el gate de `zig test`) y `status`.
    """
    reason = validate_build_files(files)
    if reason:
        out = reason
        run = {"cmd": " ".join(BUILD_CMD), "cwd": BUILD_CWD_LABEL, "exit": None,
               "duration_s": 0.0, "stdout_sha256": hashlib.sha256(out.encode()).hexdigest(),
               "zig_version": _zig_version(), "observed": out, "skipped_tests": 0}
        return {**run, "status": "REJECTED"}
    with tempfile.TemporaryDirectory(prefix="pyzig-build-") as tmp:
        root = pathlib.Path(tmp)
        try:
            for rel, content in files.items():
                dst = root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(content, encoding="utf-8")
        except OSError as exc:  # nunca abortar run_gates por una entrada
            out = f"no se pudo escribir build_files: {exc.__class__.__name__}"
            run = {"cmd": " ".join(BUILD_CMD), "cwd": BUILD_CWD_LABEL, "exit": None,
                   "duration_s": 0.0, "stdout_sha256": hashlib.sha256(out.encode()).hexdigest(),
                   "zig_version": _zig_version(), "observed": out, "skipped_tests": 0}
            return {**run, "status": "REJECTED"}
        t0 = time.time()
        try:
            p = subprocess.run(BUILD_CMD, cwd=root, capture_output=True, text=True,
                               timeout=timeout_sec)
            code, raw = p.returncode, (p.stdout or "") + (p.stderr or "")
        except subprocess.TimeoutExpired:
            code = None
            raw = f"TIMEOUT tras {timeout_sec} s"
        dt = round(time.time() - t0, 2)
        real = {str(root), str(root.resolve())}
        out = raw
        for r in real:
            out = out.replace(r, BUILD_CWD_LABEL)
    passed, skipped = build_tests(out)
    if code != 0:
        status = "REJECTED"
    elif passed == 0:
        status = "MANUAL_REVIEW"  # exit 0 sin tests ejecutados: el paso de test no esta conectado
    elif skipped:
        status = "MANUAL_REVIEW"  # pasa, pero con tests saltados
    else:
        status = "DEMONSTRATED"
    norm = _normalize_build_output(out, BUILD_CWD_LABEL)
    run = {"cmd": " ".join(BUILD_CMD), "cwd": BUILD_CWD_LABEL, "exit": code,
           "duration_s": dt, "stdout_sha256": hashlib.sha256(norm.encode()).hexdigest(),
           "zig_version": _zig_version(), "observed": out.strip()[-4000:],
           "skipped_tests": skipped}
    return {**run, "status": status}

def _gate_build_entry(e: corpus_mod.Entry, timeout_sec: int) -> dict:
    res = run_build_project(e.raw.get("build_files") or {}, timeout_sec)
    status = res.pop("status")
    run = res
    ev = dict(e.evidence)
    ev["status"] = status
    # Mismo criterio de deduplicado que el gate de `zig test`.
    runs = list(ev.get("runs", []))
    if not any(_run_key(r) == _run_key(run) for r in runs):
        runs.append(run)
    ev["runs"] = runs
    payload = dict(e.raw)
    payload["evidence"] = ev
    _rewrite(payload)
    return {"operation_id": e.operation_id, "exit": run["exit"],
            "duration_s": run["duration_s"], "status": status}

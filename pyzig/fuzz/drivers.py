"""Identidad de los drivers compilados por `fuzz.py prepare`.

Un binario de `zig build-exe` NO es reproducible (dos compilaciones del mismo
fuente dan hashes distintos), asi que el hash del binario no sirve como
identidad estable: cualquier `prepare` o clon nuevo invalidaria todos los
artefactos admitidos. La identidad de un driver es lo que determina su
comportamiento: el fuente materializado (plantilla + `zig_impl` del corpus) y
la version de zig. El hash del binario se conserva solo para atar una
ejecucion concreta al binario que corrio (`subject_sha256`).

`MANIFEST` se lee en cada llamada (no se copia al importar) para que los tests
puedan redirigirlo a un directorio temporal.
"""
from __future__ import annotations

import json
import pathlib

from ..paths import VAR

MANIFEST = VAR / "fuzz" / "drivers" / "manifest.json"
RUN_DRIVER_FILE = "driver.json"
IDENTITY_KEYS = ("source_sha256", "zig_version")


def load_manifest(path: pathlib.Path | None = None) -> dict:
    p = pathlib.Path(path or MANIFEST)
    if not p.exists():
        return {"zig_version": "", "drivers": {}}
    data = json.loads(p.read_text(encoding="utf-8"))
    data.setdefault("drivers", {})
    return data


def write_manifest(zig_version: str, drivers: dict, *, replace: bool,
                   path: pathlib.Path | None = None) -> dict:
    """Escribe el manifest. Con `replace=False` FUSIONA: `prepare --only X`
    actualiza X y conserva el resto de drivers."""
    p = pathlib.Path(path or MANIFEST)
    merged = {} if replace else dict(load_manifest(p).get("drivers", {}))
    merged.update(drivers)
    data = {"zig_version": zig_version, "drivers": dict(sorted(merged.items()))}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def entry(schema: str, path: pathlib.Path | None = None) -> dict:
    """Entrada del manifest de un esquema ({} si no esta compilado)."""
    manifest = load_manifest(path)
    info = dict(manifest.get("drivers", {}).get(schema, {}))
    if info:
        # manifests antiguos solo tienen zig_version a nivel global
        info.setdefault("zig_version", manifest.get("zig_version", ""))
    return info


def identity(info: dict) -> dict:
    """Identidad estable de un driver: fuente + version de zig."""
    return {k: info.get(k, "") for k in IDENTITY_KEYS}


def for_run(run: pathlib.Path, schema: str, subject_sha256: str) -> dict:
    """Driver que ejecuto un run, verificado contra el binario que corrio.

    - `driver.json` del run (lo escribe `fuzz.py diff` antes de ejecutar);
    - runs anteriores a ese fichero: el manifest actual, SOLO si su binario
      es exactamente el que corrio (`subject_sha256`), lo que prueba que su
      fuente es el de entonces.

    Si nada cuadra devuelve {}: sin procedencia, el warden rechaza (I6).
    """
    candidates = []
    run_file = pathlib.Path(run) / RUN_DRIVER_FILE
    if run_file.exists():
        candidates.append(json.loads(run_file.read_text(encoding="utf-8")))
    else:
        candidates.append(entry(schema))
    for info in candidates:
        if (info and subject_sha256 and info.get("binary_sha256") == subject_sha256
                and all(info.get(k) for k in IDENTITY_KEYS)):
            return info
    return {}

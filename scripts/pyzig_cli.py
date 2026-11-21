#!/usr/bin/env python3
"""CLI mínimo para consultar pyzig desde un agente aislado (ensayo A/B, brazo B).

Comandos:
  search <intent> [--zig-version V] [--platform P] [--limit N] [--mode M]
  get <operation_id>
  check [--mode test|ast] [--timeout-s S]

`check` lee el código Zig desde stdin. Salida JSON en stdout; errores en stderr
con exit code != 0.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyzig import check as check_mod  # noqa: E402
from pyzig import search as search_mod  # noqa: E402


def _dump(obj: object) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_search(args: argparse.Namespace) -> int:
    try:
        results = search_mod.search(
            args.intent,
            zig_version=args.zig_version,
            platform=args.platform,
            limit=args.limit,
            mode=args.mode,
        )
        _dump({"ok": True, "count": len(results), "results": results})
        return 0
    except (search_mod.NoResults, search_mod.VersionMismatch, search_mod.IndexUnavailable) as exc:
        _dump({"ok": False, "error": exc.code, "message": str(exc)})
        return 1


def cmd_get(args: argparse.Namespace) -> int:
    try:
        entry = search_mod.get(args.operation_id)
        _dump({"ok": True, "entry": entry})
        return 0
    except (search_mod.NoResults, search_mod.IndexUnavailable) as exc:
        _dump({"ok": False, "error": exc.code, "message": str(exc)})
        return 1


def cmd_check(args: argparse.Namespace) -> int:
    code = sys.stdin.read()
    try:
        result = check_mod.check_zig(code, mode=args.mode, timeout_s=args.timeout_s)
    except Exception as exc:  # noqa: BLE001
        _dump({"ok": False, "error": "INTERNAL", "message": str(exc)})
        return 1
    _dump(result)
    return 0 if result.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search", help="buscar recetas por intención")
    sp.add_argument("intent")
    sp.add_argument("--zig-version", default="0.16.0")
    sp.add_argument("--platform", default="linux")
    sp.add_argument("--limit", type=int, default=5)
    sp.add_argument("--mode", default="hybrid", choices=["hybrid", "lexical", "vector"])
    sp.set_defaults(func=cmd_search)

    gp = sub.add_parser("get", help="obtener una entrada completa por operation_id")
    gp.add_argument("operation_id")
    gp.set_defaults(func=cmd_get)

    cp = sub.add_parser("check", help="compilar/testear Zig desde stdin con bwrap")
    cp.add_argument("--mode", default="test", choices=["test", "ast"])
    cp.add_argument("--timeout-s", type=int, default=60)
    cp.set_defaults(func=cmd_check)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

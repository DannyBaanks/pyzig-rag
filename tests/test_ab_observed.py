"""Tests del registro observado de herramientas y de rutas portables (ensayo A/B).

- ``pyzig_cli`` añade una línea JSON por invocación a ``$AB_TOOL_LOG``.
- ``ab_run`` guarda esas llamadas como ``observed_tool_calls`` (verdad de terreno),
  además de ``reported_tool_calls`` (lo que declara el agente).
- ``manifest.json``, ``score.json`` y ``attempts.jsonl`` no contienen la raíz del
  repo ni el home: se sustituyen al escribir.

Los tests que compilan se saltan si faltan ``zig`` o ``bwrap``.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from pyzig import check as check_mod
from scripts import ab_run, ab_score, pyzig_cli

REPO = pathlib.Path(__file__).resolve().parents[1]
TASKS_DIR = REPO / "ab" / "tasks"
GOOD = REPO / "ab" / "examples" / "solutions" / "good"
HOME = pathlib.Path.home()

HAS_ZIG = shutil.which("zig") is not None
HAS_BWRAP = check_mod.probe_bwrap() is not None
NEEDS_ZIG = unittest.skipUnless(HAS_ZIG and HAS_BWRAP, "zig o bwrap no disponibles")


class PortablePathsTest(unittest.TestCase):
    def test_repo_and_home_become_relative(self) -> None:
        text = f"{REPO}/ab/tasks x {HOME}/proyecto y {HOME}2/otro"
        out = ab_score._portable_str(text, REPO, HOME)
        self.assertEqual(out, f"ab/tasks x ~/proyecto y {HOME}2/otro")

    def test_portable_is_recursive_and_keeps_other_types(self) -> None:
        obj = {"a": [f"{REPO}", 3, None, {"b": f"{HOME}/x"}], "ok": True}
        self.assertEqual(ab_score.portable(obj, REPO, HOME),
                         {"a": [".", 3, None, {"b": "~/x"}], "ok": True})


class ToolLogCliTest(unittest.TestCase):
    def _call(self, argv: list[str], log_dir: pathlib.Path | None) -> int:
        env = {"AB_TOOL_LOG": str(log_dir)} if log_dir else {}
        with mock.patch.dict(os.environ, env, clear=False):
            if log_dir is None:
                os.environ.pop("AB_TOOL_LOG", None)
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                return pyzig_cli.main(argv)

    def test_one_json_line_per_invocation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyzig-ab-log-") as td:
            log_dir = pathlib.Path(td)
            rc1 = self._call(["get", "op-que-no-existe-xyz"], log_dir)
            rc2 = self._call(["--help"], log_dir)
            log = (log_dir / pyzig_cli.TOOL_LOG_NAME).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(log), 2)
            first, second = (json.loads(x) for x in log)
            self.assertEqual(first["subcommand"], "get")
            self.assertEqual(first["args"], ["get", "op-que-no-existe-xyz"])
            self.assertEqual(first["rc"], rc1)
            self.assertIn("ts", first)
            self.assertEqual(second["rc"], rc2)
            self.assertEqual(second["rc"], 0)

    def test_no_log_without_env(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyzig-ab-nolog-") as td:
            self._call(["--help"], None)
            self.assertEqual(list(pathlib.Path(td).iterdir()), [])


class ObservedToolCallsRunTest(unittest.TestCase):
    @NEEDS_ZIG
    def test_observed_calls_are_recorded_from_the_wrapper(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyzig-ab-observed-") as td:
            root = pathlib.Path(td)
            good = (GOOD / "A" / "t02_gcd_lcm" / "attempt-01.zig").read_text(encoding="utf-8")
            src = root / "good.zig"
            src.write_text(good, encoding="utf-8")
            # El agente B invoca la CLI real dos veces y no declara ninguna llamada.
            agent = root / "agent_b.sh"
            agent.write_text(
                "#!/bin/sh\n"
                "cat >/dev/null\n"
                "\"$PYZIG_CLI\" get op-que-no-existe-xyz >/dev/null 2>&1\n"
                "\"$PYZIG_CLI\" get otra-que-no-existe >/dev/null 2>&1\n"
                f"cat {json.dumps(str(src))}\n",
                encoding="utf-8",
            )
            agent.chmod(0o755)
            out = root / "run"
            with contextlib.redirect_stdout(io.StringIO()):
                rc = ab_run.main([
                    "--tasks", "t02_gcd_lcm", "--arms", "B", "--agent-cmd", str(agent),
                    "--max-attempts", "1", "--out", str(out),
                    "--cache-dir", str(root / "cache"),
                ])
            self.assertEqual(rc, 0)
            rec = json.loads((out / "B" / "t02_gcd_lcm" / "attempts.jsonl")
                             .read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(rec["reported_tool_calls"], None)
            self.assertTrue(rec["tool_log_present"])
            self.assertEqual([c["args"] for c in rec["observed_tool_calls"]],
                             [["get", "op-que-no-existe-xyz"], ["get", "otra-que-no-existe"]])
            self.assertTrue((out / "B" / "t02_gcd_lcm" / "tool-calls-attempt-01.jsonl").is_file())

    @NEEDS_ZIG
    def test_outputs_contain_no_absolute_repo_or_home_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyzig-ab-portable-") as td:
            root = pathlib.Path(td)
            good = (GOOD / "A" / "t02_gcd_lcm" / "attempt-01.zig").read_text(encoding="utf-8")
            src = root / "good.zig"
            src.write_text(good, encoding="utf-8")
            agent = root / "agent.sh"
            # stderr con rutas absolutas del repo y del home: deben quedar sustituidas
            agent.write_text(
                "#!/bin/sh\n"
                "cat >/dev/null\n"
                f"echo 'fallo en {REPO}/ab y {HOME}/x' >&2\n"
                "exit 5\n",
                encoding="utf-8",
            )
            agent.chmod(0o755)
            out = root / "run"
            with contextlib.redirect_stdout(io.StringIO()):
                ab_run.main([
                    "--tasks", "t02_gcd_lcm", "--arms", "A", "--agent-cmd",
                    f"'{agent}'", "--max-attempts", "1", "--out", str(out),
                    "--cache-dir", str(root / "cache"),
                ])
            for name in ("manifest.json", "score.json", "A/t02_gcd_lcm/attempts.jsonl",
                         "attempts.jsonl"):
                text = (out / name).read_text(encoding="utf-8")
                self.assertNotIn(str(REPO), text, name)
                self.assertNotIn(str(HOME) + "/", text, name)
            rec = json.loads((out / "attempts.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertIn("fallo en ab y ~/x", rec["agent_stderr_tail"])


if __name__ == "__main__":
    unittest.main()


class InfraFailureTest(unittest.TestCase):
    def test_quota_and_unrunnable_abort(self) -> None:
        from scripts import ab_run
        self.assertEqual(ab_run._infra_failure(1, "Error: Rate limit exceeded: free-models-per-day"), "quota")
        self.assertIn("no ejecutable", ab_run._infra_failure(126, "/bin/sh: 1: x: Permission denied"))
        self.assertEqual(ab_run._infra_failure(1, "error: use of undeclared identifier"), "")
        self.assertEqual(ab_run._infra_failure(0, "rate limit exceeded"), "")

"""Tests herméticos del arnés A/B (tareas, puntuación y orquestador).

No escriben en el `var/` real: la cache de zig y los runs salen de un
TemporaryDirectory de modulo. Las pruebas que compilan se saltan si faltan
`zig` o `bwrap`; el resto corre siempre.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import pathlib
import re
import shutil
import tempfile
import unittest
from unittest import mock

from pyzig import check as check_mod
from scripts import ab_run, ab_score

REPO = pathlib.Path(__file__).resolve().parents[1]
TASKS_DIR = REPO / "ab" / "tasks"
GOOD = REPO / "ab" / "examples" / "solutions" / "good"
BROKEN = REPO / "ab" / "examples" / "solutions" / "broken"
CORPUS = REPO / "corpus" / "pyzig.corpus.jsonl"

HAS_ZIG = shutil.which("zig") is not None
HAS_BWRAP = check_mod.probe_bwrap() is not None
NEEDS_ZIG = unittest.skipUnless(HAS_ZIG and HAS_BWRAP, "zig o bwrap no disponibles")

_CACHE_TMP = tempfile.TemporaryDirectory(prefix="pyzig-ab-cache-")
CACHE = pathlib.Path(_CACHE_TMP.name) / "zig-cache"


def tearDownModule() -> None:  # noqa: N802  (hook de unittest)
    _CACHE_TMP.cleanup()


def _run_main(argv: list[str]) -> tuple[int, str]:
    """ab_run.main imprime un resumen; lo capturamos para no ensuciar los logs."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = ab_run.main(argv)
    return rc, out.getvalue()


def _write_agent(dirpath: pathlib.Path, broken_src: str, good_src: str) -> pathlib.Path:
    broken = dirpath / "broken.zig"
    good = dirpath / "good.zig"
    broken.write_text(broken_src, encoding="utf-8")
    good.write_text(good_src, encoding="utf-8")
    agent = dirpath / "agent.sh"
    agent.write_text(
        "#!/bin/sh\n"
        'printf \'{"tokens":{"total":17,"prompt":12,"completion":5},'
        '"tool_calls":["pyzig_search"]}\' > "$AB_ATTEMPT_META"\n'
        'if [ "$AB_ATTEMPT" = "1" ]; then cat "' + str(broken) + '"; '
        'else cat "' + str(good) + '"; fi\n',
        encoding="utf-8",
    )
    agent.chmod(0o755)
    return agent


class TasksTest(unittest.TestCase):
    def test_schema_controls_and_non_copy(self) -> None:
        tasks = ab_score.load_tasks(TASKS_DIR)
        self.assertGreaterEqual(len(tasks), 10)
        controls = [t for t in tasks if t["control"]]
        self.assertGreaterEqual(len(controls), 3)
        corpus_text = CORPUS.read_text(encoding="utf-8").lower()
        for t in tasks:
            self.assertIn("Zig", t["prompt"])
            self.assertIn("Devuelve SOLO el código Zig", t["prompt"])
            ast.parse(t["py_ref"])  # reference Python must be valid Python
            self.assertIn("assert ", t["py_ref"])
            self.assertIn('test "', t["zig_test"])
            self.assertNotIn(t["task_id"].lower(), corpus_text)
            for fn in re.findall(r"pub fn (\w+)", t["signature"]):
                self.assertNotIn(fn.lower(), corpus_text, fn)
        for keyword in ("bisect", "gcd", "lcm", "median", "statistics"):
            self.assertNotIn(keyword, corpus_text, keyword)

    def test_prompts_differ_only_in_arm_instructions(self) -> None:
        task = ab_score.load_tasks(TASKS_DIR)[0]
        a = ab_run.build_prompt(task, "A")
        b = ab_run.build_prompt(task, "B")
        self.assertEqual(
            a.replace(ab_run.ARM_INSTRUCTIONS["A"], "<ARM>"),
            b.replace(ab_run.ARM_INSTRUCTIONS["B"], "<ARM>"),
        )
        self.assertIn("AB_ATTEMPT_META", ab_run.ARM_INSTRUCTIONS["B"])
        self.assertNotIn("AB_ATTEMPT_META", ab_run.ARM_INSTRUCTIONS["A"])


class ScoreTest(unittest.TestCase):
    @NEEDS_ZIG
    def test_good_examples_pass_first_attempt(self) -> None:
        report = ab_score.score_solutions(GOOD, TASKS_DIR, cache_dir=CACHE)
        for arm, arm_report in report["arms"].items():
            self.assertEqual(arm_report["summary"]["tasks_total"], 12, arm)
            self.assertEqual(arm_report["summary"]["passed"], 12, arm)
            for t in arm_report["tasks"].values():
                self.assertTrue(t["passed"], t["task_id"])
                self.assertEqual(t["compiles_until_pass"], 1, t["task_id"])
                self.assertEqual(t["compile_errors"], 0, t["task_id"])
                self.assertEqual(t["tests_passed_attempts"], 1, t["task_id"])
                self.assertEqual(t["tokens"]["total"], "NOT_AVAILABLE")

    @NEEDS_ZIG
    def test_broken_examples_distinguish_test_fail_and_compile_error(self) -> None:
        report = ab_score.score_solutions(BROKEN, TASKS_DIR, cache_dir=CACHE)
        tasks = report["arms"]["A"]["tasks"]
        runtime = tasks["t01_bisect_left"]["attempts_detail"][0]
        self.assertEqual(runtime["status"], "TEST_FAIL")
        self.assertTrue(runtime["compiled"])
        self.assertFalse(runtime["tests_passed"])
        self.assertFalse(tasks["t01_bisect_left"]["passed"])
        compile_fail = tasks["t02_gcd_lcm"]["attempts_detail"][0]
        self.assertEqual(compile_fail["status"], "COMPILE_FAIL")
        self.assertFalse(compile_fail["compiled"])
        self.assertIsNone(compile_fail["tests_passed"])
        self.assertGreaterEqual(compile_fail["error_records"], 1)
        self.assertEqual(report["arms"]["A"]["summary"]["compile_errors_total"], 1)
        self.assertEqual(report["arms"]["A"]["summary"]["compiles_until_pass"]["n"], 0)
        self.assertIsNone(report["arms"]["A"]["summary"]["compiles_until_pass"]["median"])

    @NEEDS_ZIG
    def test_compiles_until_pass_counts_attempts_and_tokens(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyzig-ab-seq-") as td:
            root = pathlib.Path(td)
            task_dir = root / "A" / "t02_gcd_lcm"
            task_dir.mkdir(parents=True)
            broken = (BROKEN / "A" / "t02_gcd_lcm" / "attempt-01.zig").read_text(encoding="utf-8")
            good = (GOOD / "A" / "t02_gcd_lcm" / "attempt-01.zig").read_text(encoding="utf-8")
            for i in (1, 2):
                (task_dir / f"attempt-{i:02d}.zig").write_text(broken, encoding="utf-8")
            (task_dir / "attempt-03.zig").write_text(good, encoding="utf-8")
            (task_dir / "attempts.jsonl").write_text(
                "".join(json.dumps({"attempt": i, "tokens": {"total": 5}}) + "\n"
                        for i in (1, 2, 3)), encoding="utf-8")
            tasks = [t for t in ab_score.load_tasks(TASKS_DIR)
                     if t["task_id"] == "t02_gcd_lcm"]
            report = ab_score.score_solutions(root, TASKS_DIR, cache_dir=CACHE, tasks=tasks)
            t = report["arms"]["A"]["tasks"]["t02_gcd_lcm"]
            self.assertEqual(t["attempts"], 3)
            self.assertEqual(t["compiles"], 3)
            self.assertEqual(t["compiles_until_pass"], 3)
            self.assertEqual(t["compile_errors"], 2)
            self.assertGreaterEqual(t["error_records"], 2)
            self.assertTrue(t["passed"])
            self.assertTrue(t["tokens"]["available"])
            self.assertEqual(t["tokens"]["total"], 15)

    def test_unscored_attempts_are_not_invented(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyzig-ab-unscored-") as td:
            root = pathlib.Path(td)
            task_dir = root / "A" / "t01_bisect_left"
            task_dir.mkdir(parents=True)
            (task_dir / "attempt-01.zig").write_text("nada", encoding="utf-8")
            fake = {"error": "SANDBOX_UNAVAILABLE", "compiled": False,
                    "tests_passed": None, "errors": [], "stderr_tail": ""}
            with mock.patch.object(check_mod, "check_zig", return_value=fake) as m:
                report = ab_score.score_solutions(root, TASKS_DIR, cache_dir=CACHE)
            m.assert_called_once()
            t = report["arms"]["A"]["tasks"]["t01_bisect_left"]
            self.assertEqual(t["unscored"], 1)
            self.assertEqual(t["compiles"], 0)
            self.assertEqual(t["compiles_until_pass"], None)
            self.assertEqual(t["compile_errors"], 0)
            self.assertFalse(t["passed"])
            self.assertEqual(t["attempts_detail"][0]["status"], "SANDBOX_UNAVAILABLE")


class RunTest(unittest.TestCase):
    @NEEDS_ZIG
    def test_dry_run_without_agent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyzig-ab-dry-") as td:
            out = pathlib.Path(td) / "run"
            rc, _ = _run_main(["--dry-run", "--out", str(out), "--cache-dir", str(CACHE)])
            self.assertEqual(rc, 0)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["mode"], "dry-run")
            self.assertIsNone(manifest["agent_cmd"])
            self.assertEqual(len(manifest["controls"]), 3)
            self.assertEqual(manifest["tools_by_arm"]["A"], [])
            self.assertEqual(manifest["tools_by_arm"]["B"], ab_run.TOOLS_B)
            score = json.loads((out / "score.json").read_text(encoding="utf-8"))
            self.assertEqual(score["arms"]["A"]["summary"]["passed"], 12)
            self.assertEqual(score["arms"]["B"]["summary"]["passed"], 12)
            self.assertFalse((out / "attempts.jsonl").exists())

    @NEEDS_ZIG
    def test_agent_mode_logs_retry_and_tokens(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyzig-ab-agent-") as td:
            root = pathlib.Path(td)
            broken = (BROKEN / "A" / "t02_gcd_lcm" / "attempt-01.zig").read_text(encoding="utf-8")
            good = (GOOD / "A" / "t02_gcd_lcm" / "attempt-01.zig").read_text(encoding="utf-8")
            agent = _write_agent(root, broken, good)
            out = root / "run"
            rc, _ = _run_main([
                "--tasks", "t02_gcd_lcm", "--arms", "A", "--agent-cmd", str(agent),
                "--max-attempts", "2", "--out", str(out), "--cache-dir", str(CACHE),
            ])
            self.assertEqual(rc, 0)
            log = [json.loads(line) for line in
                   (out / "A" / "t02_gcd_lcm" / "attempts.jsonl").read_text(
                       encoding="utf-8").splitlines()]
            self.assertEqual([r["attempt"] for r in log], [1, 2])
            self.assertEqual(log[0]["status"], "COMPILE_FAIL")
            self.assertEqual(log[1]["status"], "PASS")
            self.assertEqual(log[0]["tokens"]["total"], 17)
            self.assertEqual(log[1]["reported_tool_calls"], ["pyzig_search"])
            self.assertNotEqual(log[0]["prompt_sha256"], log[1]["prompt_sha256"])
            score = json.loads((out / "score.json").read_text(encoding="utf-8"))
            t = score["arms"]["A"]["tasks"]["t02_gcd_lcm"]
            self.assertEqual(t["compiles_until_pass"], 2)
            self.assertEqual(t["compile_errors"], 1)
            self.assertEqual(t["tokens"]["total"], 34)

    @NEEDS_ZIG
    def test_agent_nonzero_rc_is_recorded_as_agent_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyzig-ab-rc-") as td:
            root = pathlib.Path(td)
            good = (GOOD / "A" / "t02_gcd_lcm" / "attempt-01.zig").read_text(encoding="utf-8")
            src = root / "good.zig"
            src.write_text(good, encoding="utf-8")
            agent = root / "agent_fail.sh"
            agent.write_text(
                "#!/bin/sh\n"
                f"cat {json.dumps(str(src))}\n"
                "exit 7\n",
                encoding="utf-8",
            )
            agent.chmod(0o755)
            out = root / "run"
            rc, _ = _run_main([
                "--tasks", "t02_gcd_lcm", "--arms", "A", "--agent-cmd", str(agent),
                "--max-attempts", "1", "--out", str(out), "--cache-dir", str(CACHE),
            ])
            self.assertEqual(rc, 0)
            log = [json.loads(line) for line in
                   (out / "A" / "t02_gcd_lcm" / "attempts.jsonl").read_text(
                       encoding="utf-8").splitlines()]
            self.assertEqual(log[0]["agent_rc"], 7)
            self.assertEqual(log[0]["status"], "AGENT_ERROR")
            score = json.loads((out / "score.json").read_text(encoding="utf-8"))
            t = score["arms"]["A"]["tasks"]["t02_gcd_lcm"]
            self.assertFalse(t["passed"])
            self.assertIsNone(t["compiles_until_pass"])
            self.assertEqual(t["attempts_detail"][0]["status"], "AGENT_ERROR")
            self.assertEqual(t["attempts_detail"][0]["agent_rc"], 7)

    def test_agent_required_outside_dry_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pyzig-ab-noagent-") as td:
            rc, _ = _run_main(["--out", str(pathlib.Path(td) / "unused")])
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()

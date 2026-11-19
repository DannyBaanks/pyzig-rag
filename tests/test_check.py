"""Tests hermeticos para pyzig.check, pyzig_check y registro var/nores.jsonl."""
from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from pyzig import check as check_mod
from pyzig import index as idx
from pyzig import mcp_server
from pyzig import search as search_mod

HAS_ZIG = shutil.which("zig") is not None

FIXTURE_STDERR = """\
check.zig:3:28: error: root source file struct 'fs' has no member named 'cwd'
    const data = try std.fs.cwd().readFileAlloc(std.testing.allocator, "foo.txt", 1024);
                     ~~~~~~^~~~
/opt/zig/lib/std/fs.zig:1:1: note: struct declared here
//! File System.
^~~~~~~~~~~~~~~~
check.zig:7:15: error: expected expression, found ';'
    const x = ;
              ^
"""

FIXTURE_TEST_FAIL_STDERR = """\
1/1 check.test.fails...expected 3, found 2
FAIL (TestExpectedEqual)
/opt/zig/lib/std/testing.zig:118:17: 0x12332d4 in expectEqualInner (std.zig)
                return error.TestExpectedEqual;
                ^
0 passed; 0 skipped; 1 failed.
error: the following test command failed with exit code 1:
local-cache/o/abc/test --seed=0x1
"""


class ParseErrorsTest(unittest.TestCase):
    def test_parse_fixture_errors_and_notes(self) -> None:
        parsed = check_mod.parse_zig_errors(FIXTURE_STDERR)
        self.assertEqual(len(parsed), 2)

        first = parsed[0]
        self.assertEqual(first["line"], 3)
        self.assertEqual(first["col"], 28)
        self.assertEqual(first["message"], "root source file struct 'fs' has no member named 'cwd'")
        self.assertEqual(first["notes"], ["struct declared here"])

        second = parsed[1]
        self.assertEqual(second["line"], 7)
        self.assertEqual(second["col"], 15)
        self.assertEqual(second["message"], "expected expression, found ';'")
        self.assertEqual(second["notes"], [])

    def test_stack_trace_lines_are_not_parsed_as_errors(self) -> None:
        self.assertEqual(check_mod.parse_zig_errors(FIXTURE_TEST_FAIL_STDERR), [])

    def test_extract_api_identifiers_and_build_query(self) -> None:
        line = 'const data = try std.fs.cwd().readFileAlloc(std.testing.allocator, "a", 64);'
        idents = check_mod.extract_api_identifiers(
            "root source file struct 'fs' has no member named 'cwd'",
            notes=["struct declared here"],
            source_line=line,
        )
        self.assertIn("std.fs.cwd", idents)
        self.assertIn("readFileAlloc", idents)
        q = check_mod.build_error_query(
            "root source file struct 'fs' has no member named 'cwd'",
            source_line=line,
        )
        self.assertIn("std.fs.cwd", q)
        self.assertIn("readFileAlloc", q)

    def test_suggest_for_error_returns_none_on_no_results(self) -> None:
        with mock.patch.object(search_mod, "search", side_effect=search_mod.NoResults("none")):
            self.assertIsNone(check_mod.suggest_for_error("expected expression found ;"))

    def test_suggest_for_error_caps_to_two_and_projects_fields(self) -> None:
        fake_hits = [
            {"operation_id": f"zig0.16/op-{i}", "name": f"op {i}", "status": "DEMONSTRATED",
             "apis_used": [f"std.Io.op{i}"], "extra": "ignored"}
            for i in range(3)
        ]
        with mock.patch.object(search_mod, "search", return_value=fake_hits):
            sugg = check_mod.suggest_for_error("std.fs.cwd readFileAlloc")
        self.assertIsNotNone(sugg)
        assert sugg is not None
        self.assertEqual(len(sugg), 2)
        self.assertEqual(set(sugg[0].keys()), {"operation_id", "name", "status", "apis_used"})

    def test_invalid_mode_returns_error(self) -> None:
        res = check_mod.check_zig("const x = 1;", mode="bogus")
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "INVALID_MODE")
        self.assertFalse(res["compiled"])
        self.assertIsNone(res["tests_passed"])


class CheckRealZigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="pyzig-check-test-")
        cls.var = pathlib.Path(cls._tmp.name)
        cls.db = cls.var / "pyzig.db"
        cls.cache = cls.var / "check-cache"
        cls._patchers = [
            mock.patch.object(idx, "DB", cls.db),
            mock.patch.object(idx, "VAR", cls.var),
            mock.patch.object(check_mod, "CACHE_DIR", cls.cache),
        ]
        for p in cls._patchers:
            p.start()
        idx.build(embed=None)

    @classmethod
    def tearDownClass(cls) -> None:
        for p in reversed(cls._patchers):
            p.stop()
        cls._tmp.cleanup()

    @unittest.skipUnless(HAS_ZIG, "zig no instalado en PATH")
    def test_valid_zig_test_compiles_and_passes(self) -> None:
        code = (
            'const std = @import("std");\n'
            'test "suma" {\n'
            '    try std.testing.expectEqual(@as(i32, 2), 1 + 1);\n'
            '}\n'
        )
        res = check_mod.check_zig(code, mode="test")
        self.assertTrue(res["ok"])
        self.assertTrue(res["compiled"])
        self.assertTrue(res["tests_passed"])
        self.assertEqual(res["errors"], [])

    @unittest.skipUnless(HAS_ZIG, "zig no instalado en PATH")
    def test_valid_zig_ast_check(self) -> None:
        code = 'pub fn add(a: i32, b: i32) i32 { return a + b; }\n'
        res = check_mod.check_zig(code, mode="ast")
        self.assertTrue(res["ok"])
        self.assertTrue(res["compiled"])
        self.assertIsNone(res["tests_passed"])
        self.assertEqual(res["errors"], [])

    @unittest.skipUnless(HAS_ZIG, "zig no instalado en PATH")
    def test_old_api_fails_compile_and_suggests_recipe(self) -> None:
        code = (
            'const std = @import("std");\n'
            'test "old api" {\n'
            '    const data = try std.fs.cwd().readFileAlloc(std.testing.allocator, "x.txt", 1024);\n'
            '    defer std.testing.allocator.free(data);\n'
            '}\n'
        )
        res = check_mod.check_zig(code, mode="test")
        self.assertFalse(res["ok"])
        self.assertFalse(res["compiled"])
        self.assertIsNone(res["tests_passed"])
        self.assertGreaterEqual(len(res["errors"]), 1)
        err0 = res["errors"][0]
        self.assertEqual(err0["line"], 3)
        self.assertIn("cwd", err0["message"])
        self.assertIsNotNone(err0["suggestions"])
        self.assertLessEqual(len(err0["suggestions"]), 2)
        for s_item in err0["suggestions"]:
            self.assertEqual(set(s_item.keys()), {"operation_id", "name", "status", "apis_used"})

    @unittest.skipUnless(HAS_ZIG, "zig no instalado en PATH")
    def test_runtime_test_failure_marks_compiled_true_and_tests_passed_false(self) -> None:
        code = (
            'const std = @import("std");\n'
            'test "fail" {\n'
            '    try std.testing.expectEqual(@as(i32, 3), 1 + 1);\n'
            '}\n'
        )
        res = check_mod.check_zig(code, mode="test")
        self.assertFalse(res["ok"])
        self.assertTrue(res["compiled"])
        self.assertFalse(res["tests_passed"])
        self.assertEqual(res["errors"], [])


class NoresAndMcpTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="pyzig-nores-test-")
        self.var = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.db = self.var / "pyzig.db"
        self.nores = self.var / "nores.jsonl"
        for target, attr, value in (
            (idx, "DB", self.db),
            (idx, "VAR", self.var),
            (mcp_server, "NORES_FILE", self.nores),
        ):
            p = mock.patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        idx.build(embed=None)

    def test_nores_logged_and_counted_in_catalog(self) -> None:
        cat0 = mcp_server.pyzig_catalog()
        self.assertTrue(cat0["ok"])
        self.assertEqual(cat0["catalog"]["nores_count"], 0)

        long_intent = "zqxjkvbnm_inexistente " * 25  # > 300 chars
        res = mcp_server.pyzig_search(intent=long_intent, zig_version="0.16.0", mode="lexical")
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "NO_RESULTS")
        self.assertTrue(self.nores.exists())

        lines = [ln for ln in self.nores.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(set(rec.keys()), {"ts", "intent", "zig_version"})
        self.assertEqual(len(rec["intent"]), 300)
        self.assertEqual(rec["zig_version"], "0.16.0")

        cat1 = mcp_server.pyzig_catalog()
        self.assertTrue(cat1["ok"])
        self.assertEqual(cat1["catalog"]["nores_count"], 1)

    def test_nores_write_failure_is_silent(self) -> None:
        # Apunta a un directorio existente como si fuera archivo -> OSError al abrir en modo 'a'.
        bad_path = self.var / "dir_not_file"
        bad_path.mkdir()
        with mock.patch.object(mcp_server, "NORES_FILE", bad_path):
            res = mcp_server.pyzig_search(
                intent="zqxjkvbnm_inexistente_silencioso",
                zig_version="0.16.0",
                mode="lexical",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"], "NO_RESULTS")
            cat = mcp_server.pyzig_catalog()
            self.assertTrue(cat["ok"])
            self.assertEqual(cat["catalog"]["nores_count"], 0)

    def test_instructions_mention_pyzig_check(self) -> None:
        self.assertIn("pyzig_check", mcp_server.INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()

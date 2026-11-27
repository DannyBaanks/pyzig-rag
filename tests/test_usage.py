"""Uso de pyzig medido con transcripts SINTETICOS (hermetico: ni home ni red).

Los fixtures viven en `tests/fixtures/usage/`; todo lleva nombres y rutas
inventados. La prueba central es que el informe agregado no filtre nada de eso.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "usage_sessions", _HERE.parent / "scripts" / "usage_sessions.py")
usage = importlib.util.module_from_spec(_SPEC)
sys.modules["usage_sessions"] = usage
_SPEC.loader.exec_module(usage)

FIX = _HERE / "fixtures" / "usage"
CLAUDE = FIX / "claude"
CORPUS = FIX / "corpus.jsonl"
FORBIDDEN = (
    "PROJECT-PRIVATE", "CONSULTA-PRIVADA", "/work/proyecto", "miVariablePrivada",
    "s1_pedida_hub", "s2_espontanea", "s3_error_sin_pyzig", "s4_check_falla",
    "s5_sin_zig", "/" + "home/",
)


def run_usage(tmp: Path, **roots) -> tuple[int, dict, str]:
    out = tmp / "usage.json"
    args = ["--out", str(out), "--jobs", "1", "--corpus", str(roots.get("corpus", CORPUS)),
            "--labels", str(FIX / "labels.tsv")]
    for flag in ("claude", "codex", "opencode", "gemini", "qwen"):
        args += [f"--{flag}", str(roots.get(flag, tmp / f"vacio-{flag}"))]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = usage.main(args)
    return rc, json.loads(out.read_text(encoding="utf-8")), out.read_text(encoding="utf-8")


def write_jsonl(path: Path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


class DetectionTest(unittest.TestCase):
    def test_pyzig_call_direct_hub_and_prefixed_names(self):
        self.assertEqual(usage.pyzig_call("pyzig_search", {}), ("pyzig_search", "direct"))
        self.assertEqual(
            usage.pyzig_call("mcp__pyzig-rag__pyzig_get", {}), ("pyzig_get", "direct"))
        self.assertEqual(
            usage.pyzig_call("pyzig-rag_pyzig_check", {}), ("pyzig_check", "direct"))
        self.assertEqual(
            usage.pyzig_call("mcp__isymcp-hub__hub_execute",
                             {"server": "pyzig-rag", "tool": "pyzig_catalog"}),
            ("pyzig_catalog", "hub"))
        self.assertEqual(
            usage.pyzig_call("call_mcp_tool",
                             {"ServerName": "pyzig-rag", "ToolName": "pyzig_search"}),
            ("pyzig_search", "hub"))
        # argumentos serializados como string (ASI llegan en varias TUIs)
        self.assertEqual(
            usage.pyzig_call("hub_execute",
                             '{"server": "pyzig-rag", "tool": "pyzig_search"}'),
            ("pyzig_search", "hub"))
        # otro servidor o herramienta ajena no cuenta
        self.assertIsNone(usage.pyzig_call("hub_execute",
                                           {"server": "rea", "tool": "pyzig_search"}))
        self.assertIsNone(usage.pyzig_call("hub_execute",
                                           {"server": "pyzig-rag", "tool": "read_file"}))

    def test_pyzig_call_from_codex_exec_text(self):
        body = ('text(await tools.isymcp_hub.hub_execute('
                '{server:"pyzig-rag", tool:"pyzig_search", arguments:{}}))')
        self.assertEqual(usage.pyzig_call_from_text(body), ("pyzig_search", "hub"))
        self.assertIsNone(usage.pyzig_call_from_text("zig build test"))

    def test_classify_result(self):
        self.assertEqual(usage.classify_result("pyzig_search", '{"count": 0, "error": "NO_RESULTS"}'),
                         "no_results")
        self.assertEqual(usage.classify_result("pyzig_search", '{"count": 2}'), "results")
        self.assertEqual(usage.classify_result("pyzig_check", '{"compiled": false}'), "compile_fail")
        self.assertEqual(usage.classify_result("pyzig_check", '{"compiled": true}'), "results")
        self.assertEqual(usage.classify_result("pyzig_search", "Traceback (most recent call last):"),
                         "error")
        self.assertEqual(usage.classify_result("pyzig_catalog", '{"error": "INDEX_UNAVAILABLE"}'),
                         "error")
        self.assertEqual(usage.classify_result("pyzig_search", '{"error": "VERSION_MISMATCH"}'),
                         "version_mismatch")
        self.assertEqual(usage.classify_result("pyzig_search", ""), "unknown")

    def test_mentions_pyzig(self):
        self.assertTrue(usage.mentions_pyzig("usa PYzig-rag"))
        self.assertFalse(usage.mentions_pyzig("arregla el build"))

    def test_load_labels_ignores_none_and_takes_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "labels.tsv"
            p.write_text("firma uno\tzig0.16/a,zig0.16/b\nfirma dos\tNONE\nmal formada\n",
                         encoding="utf-8")
            labels = usage.load_labels(p)
            self.assertEqual(labels, {"firma uno": "zig0.16/a"})
            self.assertEqual(usage.load_labels(Path(tmp) / "no-existe.tsv"), {})

    def test_recipe_falls_back_to_human_label(self):
        old_cov, old_labels = usage.COVERAGE, usage.LABELS
        try:
            usage.COVERAGE = usage.mine.CorpusCoverage()
            usage.LABELS = {"firma x": "zig0.16/etiquetada"}
            self.assertEqual(
                usage._recipe_for({"sig": "firma x", "apis_msg": []}), "zig0.16/etiquetada")
        finally:
            usage.COVERAGE, usage.LABELS = old_cov, old_labels


class ClaudeEndToEndTest(unittest.TestCase):
    def test_aggregates_and_privacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, rep, blob = run_usage(Path(tmp), claude=CLAUDE)
            self.assertEqual(rc, 0)
            self.assertEqual(rep["sessions_total"], 5)
            self.assertEqual(rep["sessions_with_zig"], 4)        # s5 no compila ni edita
            self.assertEqual(rep["sessions_with_pyzig"], 3)
            self.assertEqual(rep["pyzig_calls_total"], 4)
            self.assertEqual(rep["pyzig_calls_requested"], 2)     # s1 (hub, mencion previa)
            self.assertEqual(rep["pyzig_calls_spontaneous"], 2)   # s2 directa y s4 check
            self.assertEqual(rep["pyzig_calls_by_tool"],
                             {"pyzig_check": 1, "pyzig_get": 1, "pyzig_search": 2})
            self.assertEqual(rep["pyzig_calls_by_origin"]["pyzig_search"],
                             {"requested": 1, "spontaneous": 1})
            self.assertEqual(rep["pyzig_status_by_tool"]["pyzig_search"]["no_results"], 2)
            self.assertEqual(rep["pyzig_status_by_tool"]["pyzig_get"]["results"], 1)
            self.assertEqual(rep["pyzig_status_by_tool"]["pyzig_check"]["compile_fail"], 1)
            self.assertEqual(rep["no_results_rate_by_tool"]["pyzig_search"], 1.0)
            self.assertEqual(rep["zig_runs"], 6)
            self.assertEqual(rep["zig_runs_with_errors"], 3)
            opps = rep["compile_error_opportunities"]
            self.assertEqual(opps["with_recipe"], 2)              # s1 y s3 (firma fs.cwd)
            self.assertEqual(opps["consulted_pyzig"], 1)          # s1 consulto pyzig
            self.assertEqual(opps["not_consulted_with_recipe"], 1)  # s3 no consulto
            self.assertEqual(opps["not_consulted_with_recipe_and_next_run_passed"], 1)
            top = {t["signature"]: t for t in rep["top_error_signatures"]}
            cwd = "root source file struct 'fs' has no member named 'cwd'"
            self.assertIn(cwd, top)
            self.assertEqual(top[cwd]["recipe"], "zig0.16/migrate-cwd")
            self.assertEqual(top[cwd]["consulted"], 1)
            for forbidden in FORBIDDEN:
                self.assertNotIn(forbidden, blob)
            self.assertIn("solo agregados y firmas de error normalizadas", blob)

    def test_no_server_leaks_session_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            _rc, rep, blob = run_usage(Path(tmp), claude=CLAUDE)
            self.assertEqual(rep["sources"]["claude"], "5 transcripts")
            for sid in ("s1", "s2", "s3", "s4", "s5"):
                self.assertNotIn(sid + ".jsonl", blob)


class OtherSourcesTest(unittest.TestCase):
    def test_codex_function_call_and_exec_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            codex = tmp / "codex"
            write_jsonl(codex / "s.jsonl", [
                {"type": "response_item", "payload": {"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": "usa pyzig para esto"}]}},
                {"type": "response_item", "payload": {
                    "type": "function_call", "name": "hub_execute", "call_id": "c1",
                    "arguments": '{"server":"pyzig-rag","tool":"pyzig_get","arguments":{}}'}},
                {"type": "response_item", "payload": {
                    "type": "function_call_output", "call_id": "c1",
                    "output": '{"operation_id": "zig0.16/migrate-cwd"}'}},
                {"type": "response_item", "payload": {
                    "type": "custom_tool_call", "name": "exec", "call_id": "e1",
                    "input": "text(await tools.exec_command({cmd:\"zig build test\"}))"}},
                {"type": "response_item", "payload": {
                    "type": "custom_tool_call_output", "call_id": "e1",
                    "output": "All 1 tests passed."}},
                {"type": "response_item", "payload": {
                    "type": "custom_tool_call", "name": "exec", "call_id": "e2",
                    "input": ('text(await tools.isymcp_hub.hub_execute('
                              '{server:"pyzig-rag",tool:"pyzig_search"}))')}},
                {"type": "response_item", "payload": {
                    "type": "custom_tool_call_output", "call_id": "e2",
                    "output": '{"count": 0, "error": "NO_RESULTS"}'}},
            ])
            rc, rep, _blob = run_usage(tmp, codex=codex)
            self.assertEqual(rc, 0)
            self.assertEqual(rep["sessions_with_zig"], 1)
            self.assertEqual(rep["sessions_with_pyzig"], 1)
            self.assertEqual(rep["pyzig_calls_total"], 2)
            self.assertEqual(rep["pyzig_calls_requested"], 2)      # el usuario menciono pyzig
            self.assertEqual(rep["pyzig_calls_by_tool"], {"pyzig_get": 1, "pyzig_search": 1})
            self.assertEqual(rep["pyzig_status_by_tool"]["pyzig_search"]["no_results"], 1)

    def test_opencode_sqlite_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "opencode"
            root.mkdir()
            db = root / "opencode.db"
            con = sqlite3.connect(str(db))
            con.execute("create table message (id text, data text)")
            con.execute("create table part (id text, message_id text, session_id text, "
                        "time_created integer, data text)")
            con.execute("insert into message values (?,?)",
                        ("m1", json.dumps({"role": "user"})))
            rows = [
                ("p1", "m1", "ses-x", 1, {"type": "text", "message_id": "m1",
                                          "text": "consulta pyzig por favor"}),
                ("p2", "m1", "ses-x", 2, {
                    "type": "tool", "tool": "bash", "callID": "b1",
                    "state": {"input": {"command": "zig build test"},
                              "output": ("/tmp/x.zig:1:1: error: root source file struct 'fs' "
                                         "has no member named 'cwd'")}}),
                ("p3", "m1", "ses-x", 3, {
                    "type": "tool", "tool": "hub_execute", "callID": "h1",
                    "state": {"input": {"server": "pyzig-rag", "tool": "pyzig_search"},
                              "output": '{"count": 0, "error": "NO_RESULTS"}'}}),
            ]
            con.executemany(
                "insert into part values (?,?,?,?,?)",
                [(a, b, c, d, json.dumps(e)) for a, b, c, d, e in rows])
            con.commit()
            con.close()
            rc, rep, blob = run_usage(tmp, opencode=root)
            self.assertEqual(rc, 0)
            self.assertEqual(rep["sessions_total"], 1)
            self.assertEqual(rep["sessions_with_zig"], 1)
            self.assertEqual(rep["pyzig_calls_total"], 1)
            self.assertEqual(rep["pyzig_calls_requested"], 1)
            self.assertEqual(rep["pyzig_status_by_tool"]["pyzig_search"]["no_results"], 1)
            self.assertNotIn("ses-x", blob)
            self.assertNotIn("/tmp/x.zig", blob)

    def test_gemini_function_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            chats = tmp / "gemini" / "tmp" / "proj" / "chats"
            chats.mkdir(parents=True)
            write_jsonl(chats / "s.jsonl", [
                {"type": "user", "content": [{"text": "pregunta a pyzig"}]},
                {"type": "assistant", "content": [
                    {"functionCall": {"id": "g1", "name": "run_shell_command",
                                      "args": {"command": "zig test x.zig"}}}]},
                {"type": "tool", "content": [
                    {"functionResponse": {"id": "g1", "response": {"output": "All 1 tests passed."}}}]},
                {"type": "assistant", "content": [
                    {"functionCall": {"id": "g2", "name": "hub_execute",
                                      "args": {"server": "pyzig-rag", "tool": "pyzig_catalog"}}}]},
                {"type": "tool", "content": [
                    {"functionResponse": {"id": "g2", "response": {"output": '{"entries": 115}'}}}]},
            ])
            rc, rep, _blob = run_usage(tmp, gemini=tmp / "gemini")
            self.assertEqual(rc, 0)
            self.assertEqual(rep["sessions_with_zig"], 1)
            self.assertEqual(rep["pyzig_calls_by_tool"], {"pyzig_catalog": 1})
            self.assertEqual(rep["pyzig_calls_requested"], 1)
            self.assertEqual(rep["pyzig_status_by_tool"]["pyzig_catalog"]["results"], 1)


if __name__ == "__main__":
    unittest.main()

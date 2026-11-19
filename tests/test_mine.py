"""Mineria de transcripts con transcripts SINTETICOS en un tmpdir (hermetico, sin red ni home)."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "mine_sessions", Path(__file__).resolve().parent.parent / "scripts" / "mine_sessions.py")
mine = importlib.util.module_from_spec(_SPEC)
sys.modules["mine_sessions"] = mine
_SPEC.loader.exec_module(mine)

SECRET_TOKEN = "sk-" + "A1b2C3d4E5f6G7h8I9j0"
USER_TEXT = "PROMPT-PRIVADO-DEL-USUARIO"

ERR = (
    "/work/alguien/proyecto/src/main.zig:12:20: error: root source file struct 'fs' has no member named 'cwd'\n"
    "    const d = std.fs.cwd();\n"
    "                 ~~^~~~\n"
    "/work/alguien/proyecto/src/main.zig:30:5: error: use of undeclared identifier 'miVariableSecreta'\n"
    "    miVariableSecreta += 1;\n"
)


def claude_lines(session_ok: bool = True):
    def tu(i, name, inp):
        return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": i, "name": name, "input": inp}]}}

    def tr(i, text):
        return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": i, "content": text}]}}
    return [
        {"type": "user", "message": {"content": USER_TEXT + " zig build"}},
        tu("t1", "Bash", {"command": "cd /work/alguien/proyecto && zig build test"}),
        tr("t1", ERR),
        tu("t2", "Edit", {"file_path": "/work/alguien/proyecto/src/main.zig",
                          "old_string": "const d = std.fs.cwd();", "new_string": "const d = std.Io.Dir.cwd();"}),
        tu("t3", "Bash", {"command": "zig build test"}),
        tr("t3", "All 3 tests passed."),
        tu("t4", "Bash", {"command": "ls"}),
        tr("t4", "x.zig:1:1: error: esto no es zig; " + SECRET_TOKEN),
    ]


class MineTest(unittest.TestCase):
    def test_normalize_drops_paths_numbers_and_private_names(self):
        sig, apis = mine.normalize_msg("root source file struct 'fs' has no member named 'cwd'")
        self.assertEqual(sig, "root source file struct 'fs' has no member named 'cwd'")
        self.assertEqual(apis, ["std.fs.cwd"])
        sig, apis = mine.normalize_msg("use of undeclared identifier 'miVariableSecreta'")
        self.assertNotIn("miVariableSecreta", sig)
        self.assertEqual(apis, [])
        sig, _ = mine.normalize_msg("evaluation exceeded 1000 backwards branches")
        self.assertEqual(sig, "evaluation exceeded N backwards branches")
        sig, _ = mine.normalize_msg("root source file struct 'std' has no member named 'io'")
        self.assertIn("'io'", sig)

    def test_parse_zig_output(self):
        errs = mine.parse_zig_output(ERR)
        self.assertEqual(len(errs), 2)
        self.assertIn("std.fs.cwd", errs[0]["apis"])
        self.assertEqual(errs[0]["base"], "main.zig")
        self.assertNotIn("/work", json.dumps(errs))

    def test_end_to_end_privacy_and_fix_pairing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cdir = tmp / "claude" / "-proj"
            cdir.mkdir(parents=True)
            (cdir / "s1.jsonl").write_text("\n".join(json.dumps(x) for x in claude_lines()) + "\n")
            # una linea corrupta no debe romper nada
            with open(cdir / "s1.jsonl", "a") as fh:
                fh.write("{no es json zig\n")
            out = tmp / "out"
            corpus = tmp / "corpus.jsonl"
            corpus.write_text(json.dumps({"operation_id": "x", "apis_used": ["std.Io.Dir.cwd"], "aliases": []}) + "\n")
            rc = mine.main(["--claude", str(tmp / "claude"), "--codex", str(tmp / "no-existe"),
                            "--out", str(out), "--corpus", str(corpus)])
            self.assertEqual(rc, 0)
            sigs = [json.loads(l) for l in (out / "signatures.jsonl").read_text().splitlines()]
            by = {s["signature"]: s for s in sigs}
            fs = by["root source file struct 'fs' has no member named 'cwd'"]
            self.assertEqual(fs["count"], 1)
            self.assertEqual(fs["sessions"], 1)
            self.assertEqual(fs["fix_edits"], 1)
            self.assertEqual(fs["fix_then_compiled"], 1)
            self.assertIn("std.Io.Dir.cwd", fs["fix_added_apis"])
            self.assertIn("std.fs.cwd", fs["fix_removed_apis"])
            # el resultado del `ls` no es una ejecucion zig: no se cuela
            self.assertFalse([s for s in sigs if "esto no es zig" in s["signature"]])
            blob = (out / "signatures.jsonl").read_text() + (out / "report.md").read_text()
            for forbidden in (USER_TEXT, SECRET_TOKEN, "/work/", "miVariableSecreta", "alguien", "proyecto"):
                self.assertNotIn(forbidden, blob)
            self.assertIn("## 15 recetas candidatas", blob)

    def test_secret_filter(self):
        self.assertNotIn(SECRET_TOKEN, mine.redact("x " + SECRET_TOKEN))
        errs = mine.parse_zig_output("a.zig:1:1: error: algo " + SECRET_TOKEN)
        self.assertEqual(errs, [])

    def test_covered(self):
        self.assertTrue(mine.covered("std.Io.Dir.cwd", {"std.Io.Dir.cwd"}))
        self.assertTrue(mine.covered("std.Io.File", {"std.Io.File.Writer"}))
        self.assertFalse(mine.covered("std.Thread.sleep", {"std.Io.Dir.cwd"}))

    def test_unquoted_project_names_are_masked(self):
        sig, apis = mine.normalize_msg("COM object MiProyecto.MiTipo must keep vtbl at offset 8")
        self.assertNotIn("MiProyecto", sig)
        self.assertNotIn("MiTipo", sig)
        sig, _ = mine.normalize_msg("missing struct field: secreto_interno")
        self.assertNotIn("secreto_interno", sig)
        sig, _ = mine.normalize_msg("expected type std.mem.Allocator, found Foo.Bar")
        self.assertIn("std.mem.Allocator", sig)
        self.assertNotIn("Foo", sig)


if __name__ == "__main__":
    unittest.main()

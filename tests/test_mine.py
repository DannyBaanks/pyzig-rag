"""Mineria de transcripts con transcripts SINTETICOS en un tmpdir (hermetico, sin red ni home)."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sqlite3
import subprocess
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
PRIVATE_PATH = "/data/victima/proyecto/src/main.zig"
PRIVATE_EMAIL = "ana.secretaria@ejemplo.com"
PRIVATE_NAME = "Ana Secretaria"

ERR = (
    "/work/alguien/proyecto/src/main.zig:12:20: error: root source file struct 'fs' has no member named 'cwd'\n"
    "    const d = std.fs.cwd();\n"
    "                 ~~^~~~\n"
    "/work/alguien/proyecto/src/main.zig:30:5: error: use of undeclared identifier 'miVariableSecreta'\n"
    "    miVariableSecreta += 1;\n"
)

ERR_PRIV = (
    f"{PRIVATE_PATH}:12:20: error: root source file struct 'fs' has no member named 'cwd'\n"
    "    const d = std.fs.cwd();\n"
    "                 ~~^~~~\n"
    f"{PRIVATE_PATH}:31:1: error: unexpected token '{PRIVATE_EMAIL}'\n"
    f"    // {PRIVATE_NAME} " + SECRET_TOKEN + "\n"
)

FORBIDDEN = (USER_TEXT, SECRET_TOKEN, "/data/victima", "/work/", "miVariableSecreta",
             "alguien", "proyecto", PRIVATE_EMAIL, PRIVATE_NAME)
FS_SIG = "root source file struct 'fs' has no member named 'cwd'"

CORPUS_MIGRATE = [
    {"operation_id": "zig0.16/migrate-readfilealloc",
     "apis_used": ["std.Io.Dir.cwd", "std.Io.Dir.readFileAlloc"],
     "aliases": ["std.fs.cwd", "readFileAlloc", "fs.cwd removed"],
     "error_signatures": ["error: root source file struct 'fs' has no member named 'cwd'"]},
    {"operation_id": "zig0.16/migrate-time-sleep",
     "apis_used": ["std.Io.sleep"],
     "aliases": ["std.time.sleep", "std.Thread.sleep", "Io.sleep"],
     "error_signatures": ["error: root source file struct 'Thread' has no member named 'sleep'"]},
    {"operation_id": "zig0.16/migrate-child-run",
     "apis_used": ["std.process.run"],
     "aliases": ["std.process.Child.run", "Child.run"],
     "error_signatures": ["error: root source file struct 'process.Child' has no member named 'run'"]},
    {"operation_id": "zig0.16/migrate-thread-mutex",
     "apis_used": ["std.Io.Mutex"],
     "aliases": ["std.Thread.Mutex", "Io.Mutex"],
     "error_signatures": ["error: root source file struct 'Thread' has no member named 'Mutex'"]},
    {"operation_id": "zig0.16/migrate-stdout-writer",
     "apis_used": ["std.Io.File.stdout"],
     "aliases": ["std.io.getStdOut", "getStdOut().writer()"],
     "error_signatures": ["error: root source file struct 'std' has no member named 'io'"]},
]


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


def write_jsonl(path: Path, lines):
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


def run_mine(tmp: Path, **roots):
    """Todas las raices son temporales: nunca se toca el home real."""
    out = tmp / "out"
    args = ["--out", str(out)]
    for flag in ("claude", "codex", "opencode", "gemini", "qwen"):
        args += [f"--{flag}", str(roots.get(flag, tmp / f"vacio-{flag}"))]
    if "corpus" in roots:
        args += ["--corpus", str(roots["corpus"])]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mine.main(args)
    blob = ""
    if (out / "signatures.jsonl").exists():
        blob += (out / "signatures.jsonl").read_text(encoding="utf-8")
    if (out / "report.md").exists():
        blob += (out / "report.md").read_text(encoding="utf-8")
    return rc, out, blob, json.loads(buf.getvalue())


def codex_lines():
    return [
        {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "c1",
         "input": "text(await tools.exec_command({cmd:\"zig test x.zig\"}))"}},
        {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1",
         "output": ERR_PRIV}},
    ]


def gemini_lines():
    return [
        {"type": "session", "sessionId": "sintetico", "kind": "main"},
        {"type": "assistant", "content": [
            {"functionCall": {"id": "g1", "name": "run_shell_command",
                              "args": {"command": "zig test x.zig"}}}]},
        {"type": "tool", "content": [
            {"functionResponse": {"id": "g1", "response": {"output": ERR_PRIV}}}]},
    ]


def qwen_lines():
    return [
        {"type": "assistant", "message": {"role": "model", "parts": [
            {"functionCall": {"id": "q1", "name": "shell", "args": {"command": "zig test x.zig"}}}]}},
        {"type": "tool_result", "toolCallResult": {"callId": "q1"},
         "message": {"role": "user", "parts": [
             {"functionResponse": {"id": "q1", "response": {"output": ERR_PRIV}}}]}},
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
            corpus = tmp / "corpus.jsonl"
            corpus.write_text(json.dumps({"operation_id": "x", "apis_used": ["std.Io.Dir.cwd"], "aliases": []}) + "\n")
            rc, out, blob, meta = run_mine(tmp, claude=cdir, corpus=corpus)
            self.assertEqual(rc, 0)
            self.assertEqual(meta["fuentes"].count("vacio-"), 0)  # solo conteos, no rutas
            sigs = [json.loads(l) for l in (out / "signatures.jsonl").read_text().splitlines()]
            by = {s["signature"]: s for s in sigs}
            fs = by[FS_SIG]
            self.assertEqual(fs["count"], 1)
            self.assertEqual(fs["sessions"], 1)
            self.assertEqual(fs["fix_edits"], 1)
            self.assertEqual(fs["fix_then_compiled"], 1)
            self.assertIn("std.Io.Dir.cwd", fs["fix_added_apis"])
            self.assertIn("std.fs.cwd", fs["fix_removed_apis"])
            # el resultado del `ls` no es una ejecucion zig: no se cuela
            self.assertFalse([s for s in sigs if "esto no es zig" in s["signature"]])
            for forbidden in FORBIDDEN:
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

    def test_coverage_from_aliases_signatures_and_mined_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "corpus.jsonl"
            write_jsonl(corpus, CORPUS_MIGRATE)
            cov = mine.load_corpus_apis(corpus)
            for api, oid in (
                ("std.fs.cwd", "zig0.16/migrate-readfilealloc"),
                ("std.Thread.sleep", "zig0.16/migrate-time-sleep"),
                ("std.time.sleep", "zig0.16/migrate-time-sleep"),
                ("std.process.Child.run", "zig0.16/migrate-child-run"),
                ("std.Thread.Mutex", "zig0.16/migrate-thread-mutex"),
                ("std.io", "zig0.16/migrate-stdout-writer"),  # solo en error_signatures
            ):
                self.assertEqual(cov.locate(api), oid, api)
                self.assertTrue(mine.covered(api, cov), api)
            mined = mine.parse_zig_output(
                "x.zig:1:1: error: root source file struct 'Thread' has no member named 'Mutex'")[0]["sig"]
            self.assertEqual(cov.locate("", [mined]), "zig0.16/migrate-thread-mutex")
            self.assertIsNone(cov.locate("std.API.nunca_vista"))

    def test_operation_id_in_signatures_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            claude = tmp / "claude"
            claude.mkdir()
            write_jsonl(claude / "s1.jsonl", claude_lines())
            corpus = tmp / "corpus.jsonl"
            write_jsonl(corpus, CORPUS_MIGRATE)
            rc, out, blob, _meta = run_mine(tmp, claude=claude, corpus=corpus)
            self.assertEqual(rc, 0)
            sigs = {s["signature"]: s for s in
                    (json.loads(l) for l in (out / "signatures.jsonl").read_text().splitlines())}
            self.assertIn("zig0.16/migrate-readfilealloc", sigs[FS_SIG]["covered_by"])
            self.assertIn("zig0.16/migrate-readfilealloc", blob)
            cands = [l for l in (out / "report.md").read_text().splitlines() if "`std.fs.cwd`" in l]
            self.assertTrue(cands)
            self.assertIn("migrate-readfilealloc", cands[0])

    def test_context_api_does_not_cover_signature(self):
        """Una API solo de la linea de codigo no arregla el error: context_ops, no covered_by."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            claude = tmp / "claude"
            claude.mkdir()
            err = (
                "/work/x.zig:9:1: error: use of undeclared identifier 'cosaPrivada'\n"
                "    try std.mem.eql(u8, a, b);\n"
                "/work/x.zig:10:1: error: expected type 'std.mem.Allocator', found Foo.Bar\n"
                "    const y = 1;\n"
            )
            write_jsonl(claude / "s1.jsonl", [
                {"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": "t1", "name": "Bash",
                     "input": {"command": "zig test x.zig"}}]}},
                {"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": err}]}},
            ])
            corpus = tmp / "corpus.jsonl"
            write_jsonl(corpus, [
                {"operation_id": "zig0.16/solo-contexto", "apis_used": ["std.mem.eql"],
                 "aliases": [], "error_signatures": ["error: otro error distinto"]},
                {"operation_id": "zig0.16/api-fuerte", "apis_used": ["std.mem.Allocator"],
                 "aliases": [], "error_signatures": ["error: otro error distinto"]},
            ])
            rc, out, _blob, meta = run_mine(tmp, claude=claude, corpus=corpus)
            self.assertEqual(rc, 0)
            sigs = {s["signature"]: s for s in
                    (json.loads(l) for l in (out / "signatures.jsonl").read_text().splitlines())}
            debil = sigs["use of undeclared identifier '_'"]
            self.assertEqual(debil["apis"], ["std.mem.eql"])
            self.assertEqual(debil["apis_msg"], [])
            self.assertEqual(debil["covered_by"], [])
            self.assertEqual(debil["context_ops"], ["zig0.16/solo-contexto"])
            fuerte = sigs["expected type 'std.mem.Allocator', found _._"]
            self.assertEqual(fuerte["covered_by"], ["zig0.16/api-fuerte"])
            self.assertEqual(meta["firmas con operation_id"], 1)
            for forbidden in FORBIDDEN:
                self.assertNotIn(forbidden, (out / "signatures.jsonl").read_text(encoding="utf-8"))

    @unittest.skipUnless(Path("/usr/bin/zstd").exists(), "zstd requerido para leer .zst")
    def test_codex_zst_streaming_and_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            codex = tmp / "codex"
            codex.mkdir()
            raw = tmp / "raw.jsonl"
            write_jsonl(raw, codex_lines())
            subprocess.run(["/usr/bin/zstd", "-q", "-f", "-o", str(codex / "s.jsonl.zst"), str(raw)],
                           check=True, capture_output=True)
            rc, out, blob, meta = run_mine(tmp, codex=codex)
            self.assertEqual(rc, 0)
            self.assertIn("codex: 1 transcripts", meta["fuentes"])
            sigs = [json.loads(l) for l in (out / "signatures.jsonl").read_text().splitlines()]
            self.assertIn(FS_SIG, [s["signature"] for s in sigs])
            for forbidden in FORBIDDEN:
                self.assertNotIn(forbidden, blob)
            # un .zst corrupto se declara, no crashea
            (codex / "roto.zst").write_bytes(b"esto no es zstd")
            rc, _out, blob, meta = run_mine(tmp, codex=codex)
            self.assertEqual(rc, 0)
            self.assertIn("codex:", meta["no parseadas"])
            self.assertIn("ilegible", meta["no parseadas"])

    def test_opencode_sqlite_readonly_streaming(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "opencode"
            root.mkdir()
            db = root / "opencode.db"
            con = sqlite3.connect(str(db))
            con.execute("create table part (id text, message_id text, session_id text, "
                        "time_created integer, data text)")
            con.executemany("insert into part values (?,?,?,?,?)", [
                ("p1", "m1", "ses-sintetica", 1, json.dumps({
                    "type": "tool", "tool": "bash", "callID": "oc1",
                    "state": {"input": {"command": "cd /data/victima/proyecto && zig test x.zig"},
                              "output": ERR_PRIV}})),
                ("p2", "m1", "ses-sintetica", 2, json.dumps({
                    "type": "tool", "tool": "edit",
                    "state": {"input": {"file_path": PRIVATE_PATH,
                                        "old_string": "std.fs.cwd()",
                                        "new_string": "std.Io.Dir.cwd()"}}})),
            ])
            con.commit()
            con.close()
            rc, out, blob, meta = run_mine(tmp, opencode=root)
            self.assertEqual(rc, 0)
            self.assertIn("opencode: 1 transcripts", meta["fuentes"])
            sigs = {s["signature"]: s for s in
                    (json.loads(l) for l in (out / "signatures.jsonl").read_text().splitlines())}
            self.assertIn(FS_SIG, sigs)
            self.assertIn("std.Io.Dir.cwd", sigs[FS_SIG]["fix_added_apis"])
            for forbidden in FORBIDDEN:
                self.assertNotIn(forbidden, blob)

    def test_gemini_and_qwen_synthetic_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            gem = tmp / "gemini" / "tmp" / "proj" / "chats"
            gem.mkdir(parents=True)
            write_jsonl(gem / "s.jsonl", gemini_lines())
            qwen = tmp / "qwen"
            qwen.mkdir()
            write_jsonl(qwen / "s.jsonl", qwen_lines())
            rc, out, blob, meta = run_mine(tmp, gemini=tmp / "gemini", qwen=qwen)
            self.assertEqual(rc, 0)
            self.assertIn("gemini: 1 transcripts", meta["fuentes"])
            self.assertIn("qwen: 1 transcripts", meta["fuentes"])
            sigs = [json.loads(l) for l in (out / "signatures.jsonl").read_text().splitlines()]
            by = {s["signature"]: s for s in sigs}
            self.assertIn(FS_SIG, by)
            self.assertEqual(by[FS_SIG]["count"], 2)
            self.assertEqual(by[FS_SIG]["sources"], {"gemini": 1, "qwen": 1})
            for forbidden in FORBIDDEN:
                self.assertNotIn(forbidden, blob)

    def test_unknown_roots_are_declared_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, _out, blob, meta = run_mine(Path(tmp))
            self.assertEqual(rc, 0)
            self.assertIn("no encontrado", meta["fuentes"])
            self.assertIn("raiz no encontrada", meta["no parseadas"])
            self.assertNotIn("Traceback", blob)

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

"""Recetas promovidas a fuzzables en la ola 6 (fuzz-mas2):
str-find-replace-affix (straffix), parse-float-format-decimals (parsefloat),
sorted-key-stable (sortkey), int-from-bytes-to-bytes-endian (intbytes),
round-floor-ceil-bankers (roundfloat) y utf8-codepoints-validate (utf8cp).

Comprueba contratos, modelos Python, predicados de triage (positivos y
negativos para asegurar fallo cerrado) y el camino generador -> oracle.
Hermetico: no escribe en `var/`.
"""
from __future__ import annotations

import importlib.util
import math
import pathlib
import struct
import subprocess
import tempfile
import unittest

from pyzig.fuzz import contracts, models, triage
from pyzig.fuzz.oracle import decode_fields, observe, pack_fields

ROOT = pathlib.Path(__file__).resolve().parents[1]
FUZZ_BIN = ROOT / "fuzz" / "zig-out" / "bin" / "pyzig-fuzz"
MARKER = "// @IMPL@"

PROMOTED = {
    "zig0.16/str-find-replace-affix": ("straffix", "drivers/straffix.zig", "texto_num.py"),
    "zig0.16/parse-float-format-decimals": ("parsefloat", "drivers/parsefloat.zig", "texto_num.py"),
    "zig0.16/sorted-key-stable": ("sortkey", "drivers/sortkey.zig", "colecciones.py"),
    "zig0.16/int-from-bytes-to-bytes-endian": ("intbytes", "drivers/intbytes.zig", "mate_bytes.py"),
    "zig0.16/round-floor-ceil-bankers": ("roundfloat", "drivers/roundfloat.zig", "mate_bytes.py"),
    "zig0.16/utf8-codepoints-validate": ("utf8cp", "drivers/utf8cp.zig", "texto_num.py"),
}


def _dec(*fields: bytes) -> bytes:
    return pack_fields(list(fields))


def _f64hex(x: float) -> bytes:
    return struct.pack(">d", x).hex().encode("ascii")


class PromotedWave6ContractsTest(unittest.TestCase):
    def test_contrato_fuzzable_con_driver_modelo_y_marcador(self):
        for oid, (schema, driver, _) in PROMOTED.items():
            c = contracts.CONTRACTS[oid]
            with self.subTest(oid=oid):
                self.assertTrue(c["fuzzable"])
                self.assertIsNone(c["skip_reason"])
                self.assertEqual(c["schema"], schema)
                self.assertEqual(c["driver"], driver)
                self.assertIn(c["model"], models.MODELS)
                self.assertEqual(len(contracts.by_schema(schema)), 1)
                template = (ROOT / "fuzz" / driver).read_text(encoding="utf-8")
                self.assertIn(MARKER, template)
                for decl in c["known_divergences"]:
                    self.assertIn("input", decl, f"{oid}/{decl.get('id')} sin predicado")
                    self.assertTrue(decl.get("why"), f"{oid}/{decl.get('id')} sin why")

    def test_recetas_apuntan_al_mismo_contrato_que_contracts_py(self):
        by_file: dict[str, list[str]] = {}
        for oid, (_, _, fname) in PROMOTED.items():
            by_file.setdefault(fname, []).append(oid)
        for fname, oids in by_file.items():
            spec = importlib.util.spec_from_file_location(
                f"pyzig_recipes_{fname[:-3]}", ROOT / "scripts" / "recipes" / fname)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for oid in oids:
                with self.subTest(oid=oid):
                    self.assertIs(mod.CONTRACTS[oid], contracts.CONTRACTS[oid])

    def test_modelo_devuelve_tantos_campos_como_el_contrato(self):
        samples = {
            "straffix": [_dec(b"find", b"foo.bar", b"bar", b""), _dec(b"bad", b"a", b"b", b"c")],
            "parsefloat": [_dec(b"parse", b"3.14"), _dec(b"fmt2", _f64hex(3.14)), _dec(b"x", b"1")],
            "sortkey": [_dec(b"byage", b"0", b"a", b"2", b"b", b"1"), _dec(b"strings", b"0", b"b", b"a")],
            "intbytes": [_dec(b"to", b"4", b"0", b"big", b"16909060", b""),
                         _dec(b"from", b"4", b"1", b"big", b"0", b"\xff\xff\xff\xfe")],
            "roundfloat": [_dec(b"round_even", _f64hex(2.5)), _dec(b"floor", _f64hex(-2.5))],
            "utf8cp": [_dec("aé€".encode("utf-8")), _dec(b"\xff")],
        }
        for oid, (schema, _, _) in PROMOTED.items():
            n = len(contracts.CONTRACTS[oid]["compared_fields"])
            for payload in samples[schema]:
                with self.subTest(schema=schema):
                    _, obs = observe(schema, payload)
                    self.assertEqual(len(decode_fields(obs)), n)


class Wave6ModelsTest(unittest.TestCase):
    def test_straffix(self):
        self.assertEqual(models.model_straffix([b"starts", b"foo.txt", b"foo", b""]),
                         ("ok", ["ok", "", "1"]))
        self.assertEqual(models.model_straffix([b"ends", b"foo.txt", b".txt", b""]),
                         ("ok", ["ok", "", "1"]))
        self.assertEqual(models.model_straffix([b"find", "é-e".encode(), b"e", b""]),
                         ("ok", ["ok", "", "2"]))
        self.assertEqual(models.model_straffix([b"replace", b"aaa", b"aa", b"b"]),
                         ("ok", ["ok", "", "ba"]))
        self.assertEqual(models.model_straffix([b"find", b"\xff", b"a", b""])[0], "invalid")

    def test_parsefloat(self):
        self.assertEqual(models.model_parsefloat([b"parse", b"3.14"]),
                         ("ok", ["ok", "", _f64hex(3.14).decode()]))
        self.assertEqual(models.model_parsefloat([b"parse", b"nan"]),
                         ("ok", ["ok", "", "nan"]))
        self.assertEqual(models.model_parsefloat([b"parse", b"1,5"]),
                         ("err", ["err", "InvalidLiteral", ""]))
        self.assertEqual(models.model_parsefloat([b"fmt2", _f64hex(2.675)]),
                         ("ok", ["ok", "", "2.67"]))
        self.assertEqual(models.model_parsefloat([b"fmt2", b"zzzz"])[0], "invalid")

    def test_sortkey_estable(self):
        # reverse=True conserva orden original entre claves iguales
        fields = [b"byage", b"1", b"a", b"2", b"b", b"1", b"c", b"2", b"d", b"1"]
        self.assertEqual(models.model_sortkey(fields),
                         ("ok", ["ok", "", "a:2,c:2,b:1,d:1"]))
        self.assertEqual(models.model_sortkey([b"byage", b"2"])[0], "invalid")

    def test_intbytes(self):
        self.assertEqual(models.model_intbytes([b"to", b"4", b"0", b"big", b"16909060", b""]),
                         ("ok", ["ok", "", "", "01020304"]))
        self.assertEqual(models.model_intbytes([b"to", b"1", b"0", b"big", b"300", b""]),
                         ("err", ["err", "OutOfRange", "", ""]))
        self.assertEqual(models.model_intbytes([b"from", b"4", b"1", b"big", b"0", b"\xff\xff\xff\xfe"]),
                         ("ok", ["ok", "", "-2", ""]))
        self.assertEqual(models.model_intbytes([b"from", b"4", b"0", b"big", b"0", b"\x01\x02"])[0],
                         "invalid")

    def test_roundfloat(self):
        self.assertEqual(models.model_roundfloat([b"round_even", _f64hex(2.5)]),
                         ("ok", ["ok", "", "2"]))
        self.assertEqual(models.model_roundfloat([b"floor", _f64hex(-2.5)]),
                         ("ok", ["ok", "", "-3"]))
        self.assertEqual(models.model_roundfloat([b"ceil", _f64hex(-2.5)]),
                         ("ok", ["ok", "", "-2"]))
        self.assertEqual(models.model_roundfloat([b"round_even", _f64hex(math.inf)]),
                         ("err", ["err", "Overflow", ""]))
        self.assertEqual(models.model_roundfloat([b"round_even", _f64hex(math.nan)]),
                         ("err", ["err", "InvalidArgument", ""]))

    def test_utf8cp(self):
        self.assertEqual(models.model_utf8cp(["aé€".encode("utf-8")]),
                         ("ok", ["ok", "", "1", "3", str(ord("a") + 0xE9 + 0x20AC)]))
        self.assertEqual(models.model_utf8cp([b"\xed\xa0\x80"]),
                         ("err", ["err", "BadEncoding", "0", "", ""]))


class Wave6TriagePredicatesTest(unittest.TestCase):
    def _diffs(self, pairs):
        return [{"name": n, "subject": s, "oracle": o} for n, s, o in pairs]

    def _ctx(self, subject=None, oracle=None, **inp):
        return {"input": dict(inp), "subject": subject or {}, "oracle": oracle or {}}

    def test_straffix_predicados_y_fallo_cerrado(self):
        known = contracts.CONTRACTS["zig0.16/str-find-replace-affix"]["known_divergences"]
        # Positivo: find en UTF-8 con indice byte != codepoint
        d = self._diffs([("out", "3", "2")])
        ctx = self._ctx(op="find", s="é-e", a="e", b="",
                        subject={"status": "ok", "out": "3"}, oracle={"status": "ok", "out": "2"})
        self.assertEqual(triage.match_known(d, known, ctx), "straffix-find-bytes-vs-codepoints")
        # Negativo: indice byte equivocado NO se absorbe
        d_bad = self._diffs([("out", "4", "2")])
        ctx_bad = self._ctx(op="find", s="é-e", a="e", b="",
                            subject={"status": "ok", "out": "4"}, oracle={"status": "ok", "out": "2"})
        self.assertIsNone(triage.match_known(d_bad, known, ctx_bad))
        # Positivo: replace con old vacio
        d_rep = self._diffs([("status", "err", "ok"), ("error", "EmptyNeedle", ""), ("out", "", "-a-")])
        ctx_rep = self._ctx(op="replace", s="a", a="", b="-",
                            subject={"status": "err", "error": "EmptyNeedle", "out": ""},
                            oracle={"status": "ok", "error": "", "out": "-a-"})
        self.assertEqual(triage.match_known(d_rep, known, ctx_rep), "straffix-replace-empty-needle")
        # Negativo: EmptyNeedle con old NO vacio es NUEVA
        ctx_rep_bad = self._ctx(op="replace", s="a", a="a", b="-",
                                subject={"status": "err", "error": "EmptyNeedle", "out": ""},
                                oracle={"status": "ok", "error": "", "out": "-"})
        self.assertIsNone(triage.match_known(d_rep, known, ctx_rep_bad))

    def test_parsefloat_predicados_y_fallo_cerrado(self):
        known = contracts.CONTRACTS["zig0.16/parse-float-format-decimals"]["known_divergences"]
        # Espacios ASCII
        hex15 = _f64hex(1.5).decode()
        d_ws = self._diffs([("status", "err", "ok"), ("error", "InvalidLiteral", ""), ("value", "", hex15)])
        ctx_ws = self._ctx(op="parse", text=" 1.5 ",
                           subject={"status": "err", "error": "InvalidLiteral", "value": ""},
                           oracle={"status": "ok", "error": "", "value": hex15})
        self.assertEqual(triage.match_known(d_ws, known, ctx_ws), "parsefloat-recorta-espacios-ascii")
        # Hexfloat Zig
        hex8 = _f64hex(8.0).decode()
        d_hx = self._diffs([("status", "ok", "err"), ("error", "", "InvalidLiteral"), ("value", hex8, "")])
        ctx_hx = self._ctx(op="parse", text="0x1p3",
                           subject={"status": "ok", "error": "", "value": hex8},
                           oracle={"status": "err", "error": "InvalidLiteral", "value": ""})
        self.assertEqual(triage.match_known(d_hx, known, ctx_hx), "parsefloat-hexfloat-zig")
        # fmt2 shortest decimal
        d_fmt = self._diffs([("value", "2.68", "2.67")])
        ctx_fmt = self._ctx(op="fmt2", text=_f64hex(2.675).decode(),
                            subject={"status": "ok", "value": "2.68"},
                            oracle={"status": "ok", "value": "2.67"})
        self.assertEqual(triage.match_known(d_fmt, known, ctx_fmt), "parsefloat-fmt2-shortest-decimal")
        # Negativo: valor Zig erroneo en fmt2 NO se absorbe
        d_fmt_bad = self._diffs([("value", "9.99", "2.67")])
        ctx_fmt_bad = self._ctx(op="fmt2", text=_f64hex(2.675).decode(),
                                subject={"status": "ok", "value": "9.99"},
                                oracle={"status": "ok", "value": "2.67"})
        self.assertIsNone(triage.match_known(d_fmt_bad, known, ctx_fmt_bad))

    def test_roundfloat_predicados_y_fallo_cerrado(self):
        known = contracts.CONTRACTS["zig0.16/round-floor-ceil-bankers"]["known_divergences"]
        # zig_round empate .5 -> conocido
        d_tie = self._diffs([("value", "3", "2")])
        ctx_zig = self._ctx(op="zig_round", hex_bits=_f64hex(2.5).decode(),
                            subject={"status": "ok", "value": "3"}, oracle={"status": "ok", "value": "2"})
        self.assertEqual(triage.match_known(d_tie, known, ctx_zig), "roundfloat-zig-round-empate")
        # round_even empate .5 que diera 3 seria BUG NUEVO (NO se absorbe!)
        ctx_even = self._ctx(op="round_even", hex_bits=_f64hex(2.5).decode(),
                             subject={"status": "ok", "value": "3"}, oracle={"status": "ok", "value": "2"})
        self.assertIsNone(triage.match_known(d_tie, known, ctx_even))
        # -0.0 -> conocido
        d_mz = self._diffs([("value", "-0", "0")])
        ctx_mz = self._ctx(op="round_even", hex_bits=_f64hex(-0.0).decode(),
                           subject={"status": "ok", "value": "-0"}, oracle={"status": "ok", "value": "0"})
        self.assertEqual(triage.match_known(d_mz, known, ctx_mz), "roundfloat-menos-cero")


@unittest.skipUnless(FUZZ_BIN.exists(), "motor Zig no compilado (zig build en fuzz/)")
class EngineWave6RoundTripTest(unittest.TestCase):
    def test_generacion_y_oracle(self):
        for schema in ("straffix", "parsefloat", "sortkey", "intbytes", "roundfloat", "utf8cp"):
            with self.subTest(schema=schema), tempfile.TemporaryDirectory() as tmp:
                out = pathlib.Path(tmp) / "cases.hexl"
                proc = subprocess.run(
                    [str(FUZZ_BIN), "gen", "--schema", schema, "--seed", "11",
                     "--iterations", "50", "--out", str(out)],
                    capture_output=True, text=True, timeout=120)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                lines = [l for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
                self.assertEqual(len(lines), 50)
                statuses = set()
                for line in lines:
                    status, _ = observe(schema, bytes.fromhex(line))
                    statuses.add(status)
                self.assertTrue(statuses <= {"ok", "err", "invalid"}, statuses)


if __name__ == "__main__":
    unittest.main()

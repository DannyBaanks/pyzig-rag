"""Recetas de mate_bytes promovidas a fuzzables: // y % con negativos (divmod),
bit_count/bit_length (bits) y struct.pack/readInt con endian (packint).

Comprueba el contrato (driver, modelo, esquema registrado), los vectores del
modelo Python (incluidos los bordes), el orden de las divergencias conocidas y,
si el motor Zig esta compilado, el camino generador -> oracle. Nada escribe en
`var/`.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import tempfile
import unittest

from pyzig.fuzz import contracts, models, triage
from pyzig.fuzz.oracle import observe, pack_fields, decode_fields

ROOT = pathlib.Path(__file__).resolve().parents[1]
FUZZ_BIN = ROOT / "fuzz" / "zig-out" / "bin" / "pyzig-fuzz"
MARKER = "// @IMPL@"

PROMOTED = {
    "zig0.16/div-floor-mod-negative": ("divmod", "drivers/divmod.zig"),
    "zig0.16/int-bit-count-bit-length": ("bits", "drivers/bits.zig"),
    "zig0.16/struct-pack-endian-readint": ("packint", "drivers/packint.zig"),
}

I32_MIN, I32_MAX = -(2 ** 31), 2 ** 31 - 1


def _dec(*fields: bytes) -> bytes:
    return pack_fields(list(fields))


class PromotedContractsTest(unittest.TestCase):
    def test_contrato_fuzzable_con_driver_modelo_y_marcador(self):
        for oid, (schema, driver) in PROMOTED.items():
            c = contracts.CONTRACTS[oid]
            with self.subTest(oid=oid):
                self.assertTrue(c["fuzzable"])
                self.assertIsNone(c["skip_reason"])
                self.assertEqual(c["schema"], schema)
                self.assertEqual(c["driver"], driver)
                self.assertIn(c["model"], models.MODELS)
                template = (ROOT / "fuzz" / driver).read_text(encoding="utf-8")
                self.assertIn(MARKER, template)

    def test_esquema_unico_entre_fuzzables(self):
        # observe() resuelve el contrato por esquema: no puede haber dos
        for schema in ("divmod", "bits", "packint"):
            with self.subTest(schema=schema):
                self.assertEqual(len(contracts.by_schema(schema)), 1)

    def test_modelo_devuelve_tantos_campos_como_el_contrato(self):
        samples = {
            "divmod": [_dec(b"-7", b"2"), _dec(b"7", b"0"), _dec(b"x", b"1")],
            "bits": [_dec(b"count", b"-3"), _dec(b"length", b"0"), _dec(b"zip", b"1")],
            "packint": [_dec(b"pack", b"big", b"1", b"0", b""),
                        _dec(b"read", b"little", b"0", b"0", b"\x01\x02\x03\x04"),
                        _dec(b"write", b"big", b"1", b"0", b"\x00\x00\x00\x00")],
        }
        for oid, (schema, _) in PROMOTED.items():
            n = len(contracts.CONTRACTS[oid]["compared_fields"])
            for payload in samples[schema]:
                with self.subTest(schema=schema):
                    _, obs = observe(schema, payload)
                    self.assertEqual(len(decode_fields(obs)), n)

    def test_recetas_apuntan_al_mismo_contrato_que_contracts_py(self):
        spec = importlib.util.spec_from_file_location(
            "pyzig_recipes_mate_bytes", ROOT / "scripts" / "recipes" / "mate_bytes.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for oid in PROMOTED:
            with self.subTest(oid=oid):
                self.assertIs(mod.CONTRACTS[oid], contracts.CONTRACTS[oid])
        for oid, c in mod.CONTRACTS.items():
            if oid not in PROMOTED:
                self.assertFalse(c["fuzzable"], oid)


class DivModModelTest(unittest.TestCase):
    def test_floor_y_resto_con_negativos(self):
        cases = [
            ((b"-7", b"2"), ("ok", ["ok", "", "-4", "1"])),
            ((b"7", b"-2"), ("ok", ["ok", "", "-4", "-1"])),
            ((b"-7", b"-2"), ("ok", ["ok", "", "3", "-1"])),
            ((b"7", b"2"), ("ok", ["ok", "", "3", "1"])),
            ((b"0", b"-5"), ("ok", ["ok", "", "0", "0"])),
        ]
        for args, want in cases:
            with self.subTest(args=args):
                self.assertEqual(models.model_divmod(list(args)), want)

    def test_bordes(self):
        self.assertEqual(models.model_divmod([b"5", b"0"]),
                         ("err", ["err", "DivisionByZero", "", ""]))
        # minInt // -1 == 2**31: no cabe en i32
        self.assertEqual(models.model_divmod([str(I32_MIN).encode(), b"-1"]),
                         ("err", ["err", "Overflow", "", ""]))
        self.assertEqual(models.model_divmod([str(I32_MIN).encode(), b"1"]),
                         ("ok", ["ok", "", str(I32_MIN), "0"]))
        self.assertEqual(models.model_divmod([str(I32_MAX).encode(), b"-1"]),
                         ("ok", ["ok", "", str(-I32_MAX), "0"]))

    def test_formato_estricto_es_invalid(self):
        for bad in (b"", b"+5", b"1.5", b" 7", b"7 ", b"0x10", b"1_0", b"-", b"2147483648"):
            with self.subTest(bad=bad):
                self.assertEqual(models.model_divmod([bad, b"3"])[0], "invalid")


class BitsModelTest(unittest.TestCase):
    def test_vectores_del_recipe(self):
        self.assertEqual(models.model_bits([b"count", b"11"]), ("ok", ["ok", "", "3"]))
        self.assertEqual(models.model_bits([b"count", b"0"]), ("ok", ["ok", "", "0"]))
        self.assertEqual(models.model_bits([b"count", b"255"]), ("ok", ["ok", "", "8"]))
        self.assertEqual(models.model_bits([b"count", b"-3"]), ("ok", ["ok", "", "2"]))
        self.assertEqual(models.model_bits([b"length", b"255"]), ("ok", ["ok", "", "8"]))
        self.assertEqual(models.model_bits([b"length", b"0"]), ("ok", ["ok", "", "0"]))
        self.assertEqual(models.model_bits([b"length", b"-1"]), ("ok", ["ok", "", "1"]))

    def test_minint_en_python(self):
        # divergencia conocida: Python da 1, el driver responde Overflow
        self.assertEqual(models.model_bits([b"count", str(-(2 ** 63)).encode()]),
                         ("ok", ["ok", "", "1"]))
        self.assertEqual(models.model_bits([b"length", str(-(2 ** 63)).encode()]),
                         ("ok", ["ok", "", "64"]))

    def test_operacion_y_rango_invalidos(self):
        self.assertEqual(models.model_bits([b"popcount", b"1"])[0], "invalid")
        self.assertEqual(models.model_bits([b"count", b"9223372036854775808"])[0], "invalid")


class PackIntModelTest(unittest.TestCase):
    def test_pack_y_endian(self):
        self.assertEqual(models.model_packint([b"pack", b"little", b"16909060", b"0", b""]),
                         ("ok", ["ok", "", "", "04030201"]))
        self.assertEqual(models.model_packint([b"pack", b"big", b"16909060", b"0", b""]),
                         ("ok", ["ok", "", "", "01020304"]))

    def test_read_con_signo_y_sin_signo(self):
        data = b"\xff\xff\xff\xfe"
        self.assertEqual(models.model_packint([b"read", b"big", b"0", b"0", data]),
                         ("ok", ["ok", "", str(2 ** 32 - 2), ""]))
        self.assertEqual(models.model_packint([b"readi", b"big", b"0", b"0", data]),
                         ("ok", ["ok", "", "-2", ""]))

    def test_buffer_corto_y_offset(self):
        buf = b"\xaa\x01\x02\x03\x04\xbb"
        self.assertEqual(models.model_packint([b"read", b"big", b"0", b"1", buf]),
                         ("ok", ["ok", "", str(0x01020304), ""]))
        self.assertEqual(models.model_packint([b"read", b"big", b"0", b"3", buf]),
                         ("err", ["err", "ShortBuffer", "", ""]))

    def test_write_limites_antes_que_rango(self):
        # CPython: pack_into mira el buffer antes que el valor
        self.assertEqual(models.model_packint([b"write", b"big", b"1", b"0", b"\x00"]),
                         ("err", ["err", "ShortBuffer", "", ""]))
        self.assertEqual(models.model_packint([b"write", b"big", b"1", b"0", b"\x00" * 4]),
                         ("ok", ["ok", "", "", "00000001"]))
        self.assertEqual(models.model_packint([b"write", b"big", b"4294967296", b"0", b"\x00" * 4])[1][1],
                         "OutOfRange")

    def test_rango_del_valor(self):
        self.assertEqual(models.model_packint([b"pack", b"big", b"-1", b"0", b""])[1][1], "OutOfRange")
        self.assertEqual(models.model_packint([b"pack", b"big", b"4294967295", b"0", b""])[0], "ok")

    def test_formato_invalido(self):
        for fields in ([b"unpack", b"big", b"1", b"0", b""],
                       [b"pack", b"middle", b"1", b"0", b""],
                       [b"pack", b"big", b"1", b"-1", b""],
                       [b"pack", b"big", b"x", b"0", b""]):
            with self.subTest(fields=fields):
                self.assertEqual(models.model_packint(fields)[0], "invalid")


class KnownDivergenceTest(unittest.TestCase):
    def test_minint_declarado_y_clasificado(self):
        known = contracts.CONTRACTS["zig0.16/int-bit-count-bit-length"]["known_divergences"]
        d = [{"name": "status", "subject": "err", "oracle": "ok"},
             {"name": "error", "subject": "Overflow", "oracle": ""},
             {"name": "value", "subject": "", "oracle": "1"}]
        self.assertEqual(triage.match_known(d, known), "bit-count-minint-desborda")

    def test_packint_y_divmod_sin_divergencias_declaradas(self):
        for oid in ("zig0.16/div-floor-mod-negative", "zig0.16/struct-pack-endian-readint"):
            with self.subTest(oid=oid):
                self.assertEqual(contracts.CONTRACTS[oid]["known_divergences"], [])


@unittest.skipUnless(FUZZ_BIN.exists(), "motor Zig no compilado (zig build en fuzz/)")
class EngineRoundTripTest(unittest.TestCase):
    """Generador Zig -> oracle Python: todo caso se responde con un estado valido."""

    def test_generacion_y_oracle(self):
        for schema in ("divmod", "bits", "packint"):
            with self.subTest(schema=schema), tempfile.TemporaryDirectory() as tmp:
                out = pathlib.Path(tmp) / "cases.hexl"
                proc = subprocess.run(
                    [str(FUZZ_BIN), "gen", "--schema", schema, "--seed", "7",
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

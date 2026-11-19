"""Recetas de area promovidas a fuzzables: base64, hex y parse-int (texto_num).

Comprueba el contrato (driver, modelo, esquema registrado), los vectores del
modelo Python, el orden de las divergencias conocidas y, si el motor Zig esta
compilado, el camino generador -> oracle sobre casos reales. Nada escribe en
`var/`: el driver y el manifest se redirigen (ver `_hermetic`).
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
    "zig0.16/base64-encode-decode": ("base64", "drivers/base64.zig"),
    "zig0.16/hex-encode-decode": ("hex", "drivers/hex.zig"),
    "zig0.16/parse-int-base-overflow": ("parseint", "drivers/parseint.zig"),
}


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

    def test_modelo_devuelve_tantos_campos_como_el_contrato(self):
        samples = {
            "base64": [_dec(b"enc", b"hello"), _dec(b"dec", b"aGVsbG8="), _dec(b"dec", b"a")],
            "hex": [_dec(b"enc", b"\x00\xff"), _dec(b"dec", b"00ff"), _dec(b"dec", b"0")],
            "parseint": [_dec(b"42", b"10"), _dec(b"x", b"2"), _dec(b"1", b"37")],
        }
        for oid, (schema, _) in PROMOTED.items():
            n = len(contracts.CONTRACTS[oid]["compared_fields"])
            for payload in samples[schema]:
                with self.subTest(schema=schema):
                    _, obs = observe(schema, payload)
                    self.assertEqual(len(decode_fields(obs)), n)

    def test_recetas_apuntan_al_mismo_contrato_que_contracts_py(self):
        spec = importlib.util.spec_from_file_location(
            "pyzig_recipes_texto_num", ROOT / "scripts" / "recipes" / "texto_num.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for oid in PROMOTED:
            with self.subTest(oid=oid):
                self.assertIs(mod.CONTRACTS[oid], contracts.CONTRACTS[oid])
        for oid, c in mod.CONTRACTS.items():
            if oid not in PROMOTED:
                self.assertFalse(c["fuzzable"], oid)


class Base64ModelTest(unittest.TestCase):
    def test_vectores(self):
        self.assertEqual(models.model_base64([b"enc", b"hello world"]),
                         ("ok", ["ok", "", b"aGVsbG8gd29ybGQ="]))
        self.assertEqual(models.model_base64([b"dec", b"aGVsbG8="]),
                         ("ok", ["ok", "", b"hello"]))

    def test_decodificacion_estricta_como_zig(self):
        for bad in (b"aGVsbG8", b"aGVs!G8=", b"aGV\nbG8=", b"YQ==YQ=="):
            with self.subTest(bad=bad):
                self.assertEqual(models.model_base64([b"dec", bad]),
                                 ("err", ["err", "BadEncoding", ""]))

    def test_operacion_desconocida_es_invalid(self):
        self.assertEqual(models.model_base64([b"zip", b"x"])[0], "invalid")


class HexModelTest(unittest.TestCase):
    def test_vectores(self):
        self.assertEqual(models.model_hex([b"enc", b"\xde\xad\xbe\xef"]),
                         ("ok", ["ok", "", "deadbeef"]))
        self.assertEqual(models.model_hex([b"dec", b"DeAdBeEf"]),
                         ("ok", ["ok", "", b"\xde\xad\xbe\xef"]))

    def test_longitud_impar_y_no_hex_son_error(self):
        for bad in (b"abc", b"zz", b"\xc3\xb1\xc3\xb1"):
            with self.subTest(bad=bad):
                self.assertEqual(models.model_hex([b"dec", bad]),
                                 ("err", ["err", "BadEncoding", ""]))

    def test_python_acepta_espacios_entre_pares(self):
        # divergencia conocida: el modelo es Python de verdad (fromhex ignora
        # espacios); el lado Zig rechaza. Ver known_divergences del contrato.
        self.assertEqual(models.model_hex([b"dec", b"de ad"]),
                         ("ok", ["ok", "", b"\xde\xad"]))


class ParseIntModelTest(unittest.TestCase):
    def test_vectores(self):
        cases = [
            ((b"42", b"10"), ("ok", ["ok", "", "42"])),
            ((b"-42", b"10"), ("ok", ["ok", "", "-42"])),
            ((b"ff", b"16"), ("ok", ["ok", "", "255"])),
            ((b"0xff", b"0"), ("ok", ["ok", "", "255"])),
            ((b"-2147483648", b"10"), ("ok", ["ok", "", "-2147483648"])),
        ]
        for args, want in cases:
            with self.subTest(args=args):
                self.assertEqual(models.model_parseint(list(args)), want)

    def test_errores_canonicos(self):
        self.assertEqual(models.model_parseint([b"12a", b"10"]),
                         ("err", ["err", "InvalidLiteral", ""]))
        self.assertEqual(models.model_parseint([b"", b"10"]),
                         ("err", ["err", "InvalidLiteral", ""]))
        self.assertEqual(models.model_parseint([b"2147483648", b"10"]),
                         ("err", ["err", "Overflow", ""]))
        self.assertEqual(models.model_parseint([b"-2147483649", b"10"]),
                         ("err", ["err", "Overflow", ""]))

    def test_base_fuera_de_rango_es_invalid(self):
        for base in (b"1", b"37", b"x", b""):
            with self.subTest(base=base):
                self.assertEqual(models.model_parseint([b"7", base])[0], "invalid")


class KnownDivergenceTest(unittest.TestCase):
    """El orden de las declaraciones decide la clase: cada caso debe caer en la suya."""

    def _diffs(self, pairs):
        return [{"name": n, "subject": s, "oracle": o} for n, s, o in pairs]

    def _known(self, oid):
        return contracts.CONTRACTS[oid]["known_divergences"]

    def test_espacios_y_prefijo_de_base(self):
        d = self._diffs([("status", "err", "ok"), ("error", "InvalidLiteral", ""),
                         ("value", "", "7")])
        self.assertEqual(triage.match_known(d, self._known("zig0.16/parse-int-base-overflow")),
                         "int-recorta-espacios-y-prefijo-de-base")

    def test_overflow_antes_que_caracter_invalido(self):
        d = self._diffs([("error", "Overflow", "InvalidLiteral")])
        self.assertEqual(triage.match_known(d, self._known("zig0.16/parse-int-base-overflow")),
                         "precedencia-overflow-sobre-caracter-invalido")

    def test_zig_acepta_guion_bajo_doble(self):
        d = self._diffs([("status", "ok", "err"), ("error", "", "InvalidLiteral"),
                         ("value", "10", "")])
        self.assertEqual(triage.match_known(d, self._known("zig0.16/parse-int-base-overflow")),
                         "zig-acepta-lo-que-int-rechaza")

    def test_hex_espacios(self):
        d = self._diffs([("status", "err", "ok"), ("error", "BadEncoding", ""),
                         ("out", "", "\xde\xad")])
        self.assertEqual(triage.match_known(d, self._known("zig0.16/hex-encode-decode")),
                         "hex-espacios-entre-pares")

    def test_divergencia_sin_declarar_es_nueva(self):
        d = self._diffs([("status", "ok", "ok"), ("value", "1", "2")])
        self.assertIsNone(triage.match_known(d, self._known("zig0.16/parse-int-base-overflow")))


@unittest.skipUnless(FUZZ_BIN.exists(), "motor Zig no compilado (zig build en fuzz/)")
class EngineRoundTripTest(unittest.TestCase):
    """Generador Zig -> oracle Python: todo caso se responde con un estado valido."""

    def test_generacion_y_oracle(self):
        for schema in ("base64", "hex", "parseint"):
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

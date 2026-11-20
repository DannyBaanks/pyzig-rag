"""Predicados de entrada en el triage de fuzz (`known_divergences` con `input`).

Cada caso se construye con el empaquetado real (`oracle.pack_fields`) y se
clasifica con `triage.classify`, el mismo camino que usa `fuzz.py triage`.
Sin dependencia del motor Zig ni de `var/`.
"""
from __future__ import annotations

import pathlib
import re
import unittest

from pyzig.fuzz import contracts, triage
from pyzig.fuzz.oracle import pack_fields

ROOT = pathlib.Path(__file__).resolve().parents[1]
PI = "zig0.16/parse-int-base-overflow"
HX = "zig0.16/hex-encode-decode"
PI_FIELDS = ["status", "error", "value"]
HX_FIELDS = ["status", "error", "out"]

INT_RECORTA = "int-recorta-espacios-y-prefijo-de-base"
PRECEDENCIA = "precedencia-overflow-sobre-caracter-invalido"
ZIG_ACEPTA = "zig-acepta-lo-que-int-rechaza"
HEX_ESP = "hex-espacios-entre-pares"


def _row(case_fields, subject, oracle, names):
    """Fila de results.jsonl sintetica: `case_fields` bytes, observaciones como listas."""
    diffs = [{"name": n, "subject": s, "oracle": o}
             for n, s, o in zip(names, subject, oracle) if s != o]
    return {
        "class": "DIVERGENT",
        "case": pack_fields(case_fields).hex(),
        "fields": diffs,
        "subject": {"payload": pack_fields([x.encode("utf-8") for x in subject]).hex()},
        "oracle": {"payload": pack_fields([x.encode("utf-8") for x in oracle]).hex()},
    }


def _pi(text: str, base: str, subject, oracle):
    """Caso parseint: subject/oracle = [status, error, value]."""
    return _row([text.encode("utf-8"), base.encode("ascii")], subject, oracle, PI_FIELDS)


def _classify_pi(row):
    e = contracts.CONTRACTS[PI]
    return triage.classify(row, e["known_divergences"], e["schema"], e["compared_fields"])


def _classify_hx(row):
    e = contracts.CONTRACTS[HX]
    return triage.classify(row, e["known_divergences"], e["schema"], e["compared_fields"])


ERR_LIT = ["err", "InvalidLiteral", ""]
OK = lambda v: ["ok", "", v]  # noqa: E731


class ParseIntRecortaTest(unittest.TestCase):
    def test_espacios_ascii_en_bordes_es_conocida(self):
        row = _pi(" 7 ", "10", ERR_LIT, OK("7"))
        self.assertEqual(_classify_pi(row), INT_RECORTA)

    def test_salto_de_linea_en_borde_es_conocida(self):
        row = _pi("7\n", "8", ERR_LIT, OK("7"))
        self.assertEqual(_classify_pi(row), INT_RECORTA)

    def test_prefijo_que_coincide_con_la_base_es_conocida(self):
        self.assertEqual(_classify_pi(_pi("0o17", "8", ERR_LIT, OK("15"))), INT_RECORTA)
        self.assertEqual(_classify_pi(_pi("0x10", "16", ERR_LIT, OK("16"))), INT_RECORTA)

    def test_prefijo_que_no_coincide_con_la_base_es_nueva(self):
        # 0b101 con base 16 es 0xb101 = 45313 para Python: 0b no es prefijo de base 16
        row = _pi("0b101", "16", ERR_LIT, OK("45313"))
        self.assertIsNone(_classify_pi(row))

    def test_digito_unicode_es_nueva(self):
        # Python: int('٣') == 3. El patron de campos es el mismo que el de
        # espacios ASCII, pero la entrada no es ASCII: no es la clase conocida.
        row = _pi("٣", "10", ERR_LIT, OK("3"))
        self.assertIsNone(_classify_pi(row))

    def test_espacio_unicode_en_borde_es_nueva(self):
        # 　 (ideografico) lo recorta Python; no es espacio ASCII
        row = _pi("　7", "10", ERR_LIT, OK("7"))
        self.assertIsNone(_classify_pi(row))

    def test_valor_python_que_no_es_el_recortado_es_nueva(self):
        row = _pi(" 7 ", "10", ERR_LIT, OK("8"))
        self.assertIsNone(_classify_pi(row))


class ParseIntGuionBajoTest(unittest.TestCase):
    def test_doble_guion_bajo_con_valor_sin_guiones_es_conocida(self):
        row = _pi("1__0", "10", OK("10"), ["err", "InvalidLiteral", ""])
        self.assertEqual(_classify_pi(row), ZIG_ACEPTA)

    def test_valor_erroneo_es_nueva(self):
        # Zig devuelve 99 para '1__0': no es el valor de quitar los '_'
        row = _pi("1__0", "10", OK("99"), ["err", "InvalidLiteral", ""])
        self.assertIsNone(_classify_pi(row))

    def test_base_0_cero_a_la_izquierda_sin_guiones(self):
        # '010' base 0: Zig 10 (decimal), Python rechaza
        row = _pi("010", "0", OK("10"), ["err", "InvalidLiteral", ""])
        self.assertEqual(_classify_pi(row), ZIG_ACEPTA)

    def test_base_0_cero_a_la_izquierda_con_valor_octal_es_nueva(self):
        row = _pi("010", "0", OK("8"), ["err", "InvalidLiteral", ""])
        self.assertIsNone(_classify_pi(row))

    def test_guion_bajo_simple_no_es_la_clase(self):
        # '1_0' base 10 es valido para Python: no hay '__' ni cero a la izquierda
        row = _pi("1_0", "10", OK("10"), ["err", "InvalidLiteral", ""])
        self.assertIsNone(_classify_pi(row))

    def test_signo_y_valor_con_signo(self):
        row = _pi("-1__0", "10", OK("-10"), ["err", "InvalidLiteral", ""])
        self.assertEqual(_classify_pi(row), ZIG_ACEPTA)

    def test_digito_unicode_con_guiones_es_nueva(self):
        row = _pi("٣__1", "10", OK("31"), ["err", "InvalidLiteral", ""])
        self.assertIsNone(_classify_pi(row))


class ParseIntPrecedenciaTest(unittest.TestCase):
    def test_desbordamiento_antes_del_caracter_invalido_es_conocida(self):
        row = _pi("4d3ce2YZyYc0+6-31y Z8d", "36", ["err", "Overflow", ""], ERR_LIT)
        self.assertEqual(_classify_pi(row), PRECEDENCIA)

    def test_prefijo_sin_desbordamiento_es_nueva(self):
        # '12+' base 10: el prefijo '12' no desborda; Zig deberia dar InvalidLiteral
        row = _pi("12+", "10", ["err", "Overflow", ""], ERR_LIT)
        self.assertIsNone(_classify_pi(row))

    def test_desbordamiento_con_unicode_es_nueva(self):
        row = _pi("٣٣٣٣٣٣٣٣٣٣٣٣+", "10", ["err", "Overflow", ""], ERR_LIT)
        self.assertIsNone(_classify_pi(row))


class HexEspaciosTest(unittest.TestCase):
    def _hx(self, op, data, subject, oracle):
        return _row([op.encode(), data.encode("utf-8")], subject, oracle, HX_FIELDS)

    def test_espacios_entre_pares_es_conocida(self):
        row = self._hx("dec", "de ad", ["err", "BadEncoding", ""], ["ok", "", "\xde\xad"])
        # el out de Python son los bytes; se empaqueta como bytes en el oracle
        row["oracle"]["payload"] = pack_fields([b"ok", b"", b"\xde\xad"]).hex()
        self.assertEqual(_classify_hx(row), HEX_ESP)

    def test_espacios_al_borde_y_tabulador_es_conocida(self):
        row = self._hx("dec", " de\tad ", ["err", "BadEncoding", ""], ["ok", "", "\xde\xad"])
        row["oracle"]["payload"] = pack_fields([b"ok", b"", b"\xde\xad"]).hex()
        self.assertEqual(_classify_hx(row), HEX_ESP)

    def test_caracter_no_hex_es_nueva(self):
        row = self._hx("dec", "dé ad", ["err", "BadEncoding", ""], ["ok", "", ""])
        self.assertIsNone(_classify_hx(row))

    def test_espacio_unicode_es_nueva(self):
        # \x1c no es espacio ASCII para bytes.fromhex
        row = self._hx("dec", "de\x1cad", ["err", "BadEncoding", ""], ["ok", "", ""])
        self.assertIsNone(_classify_hx(row))

    def test_operacion_enc_es_nueva(self):
        row = self._hx("enc", "de ad", ["err", "BadEncoding", ""], ["ok", "", ""])
        self.assertIsNone(_classify_hx(row))


class PredicateMechanicsTest(unittest.TestCase):
    def test_sin_contexto_declaracion_con_input_no_encaja(self):
        known = contracts.CONTRACTS[PI]["known_divergences"]
        diffs = [{"name": "error", "subject": "Overflow", "oracle": "InvalidLiteral"}]
        self.assertIsNone(triage.match_known(diffs, known))

    def test_declaracion_sin_input_sigue_igual(self):
        known = [{"id": "solo-campos", "fields": ["status"],
                  "expect": {"status": "err"}, "oracle": {"status": "ok"}}]
        diffs = [{"name": "status", "subject": "err", "oracle": "ok"}]
        self.assertEqual(triage.match_known(diffs, known), "solo-campos")
        self.assertEqual(triage.match_known(diffs, known, {"input": {}}), "solo-campos")

    def test_regex_sobre_campo_de_entrada(self):
        known = [{"id": "solo-digitos", "fields": ["status"],
                  "expect": {"status": "err"}, "oracle": {"status": "ok"},
                  "input": {"text": {"regex": r"[0-9]+"}}}]
        diffs = [{"name": "status", "subject": "err", "oracle": "ok"}]
        ctx = {"input": {"text": "123"}, "subject": {}, "oracle": {}}
        self.assertEqual(triage.match_known(diffs, known, ctx), "solo-digitos")
        ctx["input"]["text"] = "12a"
        self.assertIsNone(triage.match_known(diffs, known, ctx))

    def test_predicado_no_registrado_falla_fuerte(self):
        known = [{"id": "x", "fields": ["status"], "input": "no-existe"}]
        diffs = [{"name": "status", "subject": "err", "oracle": "ok"}]
        with self.assertRaises(ValueError):
            triage.match_known(diffs, known, {"input": {}, "subject": {}, "oracle": {}})

    def test_caso_sin_case_no_se_decodifica(self):
        row = {"fields": [{"name": "status", "subject": "err", "oracle": "ok"}]}
        ctx = triage.case_context(row, "parseint", PI_FIELDS)
        self.assertEqual(ctx["input"], {})
        self.assertIsNone(triage.classify(row, contracts.CONTRACTS[PI]["known_divergences"],
                                          "parseint", PI_FIELDS))

    def test_todos_los_predicados_de_contratos_resuelven(self):
        for oid, c in contracts.CONTRACTS.items():
            for decl in c.get("known_divergences", []):
                spec = decl.get("input")
                if spec is None:
                    continue
                with self.subTest(oid=oid, id=decl["id"]):
                    if isinstance(spec, str):
                        self.assertIn(spec, triage.PREDICATES)
                    else:
                        for name, rule in spec.items():
                            self.assertIn(name, triage.INPUT_FIELDS[c["schema"]])
                            if "regex" in rule:
                                re.compile(rule["regex"])


if __name__ == "__main__":
    unittest.main()

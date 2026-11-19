"""Emparejamiento de firmas de error (pyzig.check.match_signature / suggest_for_message).

Usa el corpus real (solo lectura) y aisla la busqueda con un mock: estos tests
fijan la regla de plantilla + huecos, no el ranking del indice."""
from __future__ import annotations

import unittest
from unittest import mock

from pyzig import check as check_mod


def _ids(hits):
    return [h["operation_id"] for h in (hits or [])]


class SignatureMatchTests(unittest.TestCase):
    def test_unique_template_ignores_user_identifiers(self) -> None:
        # 'limite' en el corpus, 'total' en el mensaje: el nombre es del usuario
        hits = check_mod.match_signature("local constant shadows declaration of 'total'")
        self.assertEqual(_ids(hits), ["zig0.16/diag-shadow-local"])

    def test_numbers_and_int_types_normalize(self) -> None:
        hits = check_mod.match_signature("expected type 'u16', found 'u64'")
        self.assertEqual(_ids(hits), ["zig0.16/diag-narrowing-intcast"])
        hits = check_mod.match_signature("evaluation exceeded 5000 backwards branches")
        self.assertEqual(_ids(hits)[0], "zig0.16/diag-eval-branch-quota")

    def test_shared_template_requires_matching_slots(self) -> None:
        self.assertEqual(
            _ids(check_mod.match_signature(
                "root source file struct 'time' has no member named 'sleep'")),
            ["zig0.16/migrate-time-sleep"])
        # misma plantilla, huecos que no estan en el corpus: no hay firma
        self.assertEqual(check_mod.match_signature(
            "root source file struct 'testing' has no member named 'expectCrash'"), [])

    def test_pure_wildcard_slots_are_generic(self) -> None:
        self.assertEqual(check_mod.match_signature("expected type '_', found '_'"), [])

    def test_identity_slot_must_match(self) -> None:
        self.assertEqual(
            _ids(check_mod.match_signature("use of undeclared identifier 'builtin'")),
            ["zig0.16/diag-builtin-undeclared"])
        self.assertEqual(check_mod.match_signature("use of undeclared identifier 'foo'"), [])

    def test_unknown_template_is_none(self) -> None:
        self.assertIsNone(check_mod.match_signature("expected ';' after statement"))

    def test_partial_wildcard_slot(self) -> None:
        hits = check_mod.match_signature(
            "no field or member function named '_' in 'Build._._'")
        self.assertEqual(_ids(hits), ["zig0.16/build-c-source-files"])


class SuggestForMessageTests(unittest.TestCase):
    def test_signature_hit_skips_search(self) -> None:
        with mock.patch.object(check_mod, "suggest_for_error") as s:
            hits = check_mod.suggest_for_message("local variable is never mutated")
        s.assert_not_called()
        self.assertEqual(_ids(hits), ["zig0.16/diag-never-mutated"])

    def test_generic_error_abstains_without_search(self) -> None:
        with mock.patch.object(check_mod, "suggest_for_error") as s:
            self.assertIsNone(check_mod.suggest_for_message("expected type 'Foo', found 'Bar'"))
        s.assert_not_called()

    def test_missing_member_searches_by_api(self) -> None:
        with mock.patch.object(check_mod, "suggest_for_error", return_value=None) as s:
            check_mod.suggest_for_message(
                "root source file struct 'os' has no member named 'argv'")
        query = s.call_args.args[0]
        self.assertTrue(query.startswith("std.os.argv"), query)

    def test_std_api_in_source_line_allows_search(self) -> None:
        with mock.patch.object(check_mod, "suggest_for_error", return_value=None) as s:
            check_mod.suggest_for_message("expected type 'Foo', found 'Bar'",
                                          source_line="const x = std.mem.span(p);")
        s.assert_called_once()


if __name__ == "__main__":
    unittest.main()

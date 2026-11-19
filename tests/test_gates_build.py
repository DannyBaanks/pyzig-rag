"""Gate de build (`gate_mode: "build"`): herméticos.

No leen ni escriben `var/` ni el corpus: el gate corre sobre proyectos temporales.
Los tests que necesitan `zig` se saltan limpiamente si no esta en PATH.
"""
from __future__ import annotations

import json
import shutil
import unittest

from pyzig import corpus as corpus_mod
from pyzig import gates

HAS_ZIG = shutil.which("zig") is not None

BUILD_OK = '''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const root = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    const tests = b.addTest(.{ .root_module = root });
    const run_tests = b.addRunArtifact(tests);
    b.step("test", "Run unit tests").dependOn(&run_tests.step);
}
'''

MAIN_OK = '''const std = @import("std");
test "suma" { try std.testing.expectEqual(@as(i32, 5), 2 + 3); }
'''

MAIN_FAIL = '''const std = @import("std");
test "falla" { try std.testing.expectEqual(@as(i32, 6), 2 + 3); }
'''

MAIN_SKIP = '''const std = @import("std");
test "uno" { try std.testing.expect(true); }
test "saltado" { return error.SkipZigTest; }
'''

# Paso `test` sin ningun test conectado: zig build test pasa sin ejecutar nada.
BUILD_NO_TESTS = '''const std = @import("std");
pub fn build(b: *std.Build) void {
    _ = b.standardTargetOptions(.{});
    _ = b.standardOptimizeOption(.{});
    _ = b.step("test", "vacio");
}
'''


def _project(main: str, build: str = BUILD_OK) -> dict:
    return {"build.zig": build, "src/main.zig": main}


class ValidateBuildFilesTest(unittest.TestCase):
    def test_proyecto_minimo_es_admisible(self) -> None:
        self.assertIsNone(gates.validate_build_files(_project(MAIN_OK)))

    def test_exige_build_zig(self) -> None:
        self.assertIsNotNone(gates.validate_build_files({"src/main.zig": MAIN_OK}))
        self.assertIsNotNone(gates.validate_build_files(None))

    def test_rechaza_rutas_absolutas_y_subida(self) -> None:
        self.assertIsNotNone(gates.validate_build_files({**_project(MAIN_OK), "/etc/x.zig": "x"}))
        self.assertIsNotNone(gates.validate_build_files({**_project(MAIN_OK), "../x.zig": "x"}))

    def test_rechaza_rutas_raras_y_archivo_que_es_directorio(self) -> None:
        for bad in (".", "src/./a.zig", "src//a.zig", "src/"):
            self.assertIsNotNone(gates.validate_build_files({**_project(MAIN_OK), bad: "x"}), bad)
        self.assertIsNotNone(gates.validate_build_files({**_project(MAIN_OK), "build.zig/x": "x"}))
        res = gates.run_build_project({**_project(MAIN_OK), "build.zig/x": "x"})
        self.assertEqual(res["status"], "REJECTED")

    def test_rechaza_urls_y_dependencias(self) -> None:
        zon = '.{ .dependencies = .{ .x = .{ .url = "https://example.invalid/x.tar.gz" } } }'
        self.assertIsNotNone(gates.validate_build_files({**_project(MAIN_OK), "build.zig.zon": zon}))
        dep = BUILD_OK.replace("const tests", "const d = b.dependency(\"x\", .{});\n    const tests")
        self.assertIsNotNone(gates.validate_build_files(_project(MAIN_OK, dep)))


class BuildTestsParseTest(unittest.TestCase):
    def test_cuenta_pasados_y_saltados(self) -> None:
        out = "run test 1 pass, 1 skip (2 total) 5ms\nBuild Summary: 1/1 tests passed"
        self.assertEqual(gates.build_tests(out), (1, 1))

    def test_sin_resumen_no_hay_tests(self) -> None:
        self.assertEqual(gates.build_tests(""), (0, 0))

    def test_normaliza_tiempos_y_cache(self) -> None:
        a = "compile test Debug native cached 14ms MaxRSS:37M"
        b = "compile test Debug native success 412ms MaxRSS:141M"
        self.assertEqual(gates._normalize_build_output(a, "<tmp>"),
                         gates._normalize_build_output(b, "<tmp>"))


class CorpusHashTest(unittest.TestCase):
    """Los campos nuevos solo entran en el hash si estan presentes y no vacios."""

    def _base(self) -> dict:
        return {"operation_id": "x/y", "name": "n", "zig_test": "t", "zig_impl": "i",
                "evidence": {"status": "UNVERIFIED", "runs": []}}

    def test_sin_campos_nuevos_el_hash_no_cambia(self) -> None:
        base = self._base()
        same = {**base, "gate_mode": None, "build_files": {}, "error_signatures": []}
        self.assertEqual(corpus_mod.content_hash(base), corpus_mod.content_hash(same))

    def test_con_campos_nuevos_el_hash_cambia(self) -> None:
        base = self._base()
        with_build = {**base, "gate_mode": "build", "build_files": {"build.zig": "x"}}
        self.assertNotEqual(corpus_mod.content_hash(base), corpus_mod.content_hash(with_build))

    def test_canonico_es_json_valido(self) -> None:
        json.loads(corpus_mod.canonical(self._base()))


@unittest.skipUnless(HAS_ZIG, "zig no esta en PATH")
class BuildGateRunTest(unittest.TestCase):
    def test_proyecto_correcto_es_demostrado(self) -> None:
        res = gates.run_build_project(_project(MAIN_OK), timeout_sec=300)
        self.assertEqual(res["status"], "DEMONSTRATED", res["observed"])
        self.assertEqual(res["exit"], 0)
        self.assertEqual(res["cmd"], "zig build test --summary all")
        self.assertEqual(res["cwd"], gates.BUILD_CWD_LABEL)
        self.assertEqual(res["skipped_tests"], 0)

    def test_test_fallido_es_rechazado(self) -> None:
        res = gates.run_build_project(_project(MAIN_FAIL), timeout_sec=300)
        self.assertEqual(res["status"], "REJECTED")
        self.assertNotEqual(res["exit"], 0)

    def test_sin_tests_ejecutados_no_es_demostrado(self) -> None:
        res = gates.run_build_project(_project(MAIN_OK, BUILD_NO_TESTS), timeout_sec=300)
        self.assertEqual(res["status"], "MANUAL_REVIEW")

    def test_test_saltado_no_es_demostrado(self) -> None:
        res = gates.run_build_project(_project(MAIN_SKIP), timeout_sec=300)
        self.assertEqual(res["status"], "MANUAL_REVIEW")
        self.assertEqual(res["skipped_tests"], 1)

    def test_salida_no_contiene_ruta_temporal(self) -> None:
        res = gates.run_build_project(_project(MAIN_FAIL), timeout_sec=300)
        self.assertNotIn("pyzig-build-", res["observed"])


class BuildGateRejectTest(unittest.TestCase):
    """Sin zig tambien se comprueba que un proyecto inadmisible no llega a ejecutarse."""

    def test_url_se_rechaza_sin_ejecutar_zig(self) -> None:
        zon = '.{ .url = "https://example.invalid/x" }'
        res = gates.run_build_project({**_project(MAIN_OK), "build.zig.zon": zon})
        self.assertEqual(res["status"], "REJECTED")
        self.assertIsNone(res["exit"])


if __name__ == "__main__":
    unittest.main()

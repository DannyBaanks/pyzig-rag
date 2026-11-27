"""Regresiones del piloto A/B real (2026-11-27): 24/24 COMPILE_FAIL falsos."""
import os
import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ab_score  # noqa: E402
from pyzig import check  # noqa: E402

TASK = {"zig_test": 'test "t" {\n    try std.testing.expectEqual(@as(u32, 3), add(1, 2));\n}\n'}
SOL_SIN_STD = "pub fn add(a: u32, b: u32) u32 {\n    return a + b;\n}\n"
SOL_CON_STD = 'const std = @import("std");\n' + SOL_SIN_STD


def test_combine_anade_std_si_la_solucion_no_lo_declara():
    out = ab_score.combine(SOL_SIN_STD, TASK)
    assert out.count('const std = @import("std");') == 1


def test_combine_no_duplica_std():
    out = ab_score.combine(SOL_CON_STD, TASK)
    assert out.count("const std") == 1


needs_sandbox = pytest.mark.skipif(check.probe_bwrap() is None or shutil.which("zig") is None,
                                   reason="sin bwrap/zig")


@needs_sandbox
def test_solucion_correcta_sin_std_pasa_con_cache_relativa(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = ab_score.score_attempt(SOL_SIN_STD, TASK, cache_dir=pathlib.Path("rel-cache"))
    assert r["status"] == "PASS", r["stderr_tail"]


@needs_sandbox
def test_fallo_de_bwrap_no_es_compile_fail(monkeypatch):
    real_run = check.subprocess.run

    def fake_run(cmd, *a, **kw):
        if cmd and os.path.basename(str(cmd[0])) == "bwrap" and "test" in cmd:
            return check.subprocess.CompletedProcess(cmd, 1, "", "bwrap: Can't find source path x: No such file or directory\n")
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(check.subprocess, "run", fake_run)
    r = check.check_zig(SOL_CON_STD + TASK["zig_test"], mode="test")
    assert r.get("error") == "SANDBOX_ERROR"
    assert r["compiled"] is None


def test_force_aparta_la_corrida_previa_sin_mezclar(tmp_path):
    import ab_run
    out = tmp_path / "run"
    (out / "A" / "t").mkdir(parents=True)
    (out / "A" / "t" / "attempt-03.zig").write_text("viejo")
    (out / "attempts.jsonl").write_text("{}\n")
    with pytest.raises(ValueError):
        ab_run._fresh_out(out, force=False)
    moved = ab_run._fresh_out(out, force=True)
    assert out.is_dir() and not any(out.iterdir())
    assert (moved / "A" / "t" / "attempt-03.zig").read_text() == "viejo"

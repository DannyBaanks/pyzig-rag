"""Base de tests herméticos: nada lee ni escribe el `var/` real del repo.

Antes los tests del warden dependian de `var/fuzz/drivers/manifest.json`
(ignorado por git: 2/11 fallaban en un clon limpio) y pisaban
`var/fuzz/warden/*.json` y `var/fuzz/campaigns/` con datos de prueba.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from pyzig.fuzz import campaign, drivers, warden

#: Identidad del driver falso que usan los fixtures (`subject_sha256`).
FAKE_BINARY = "a" * 64
FAKE_SOURCE = "c" * 64
FAKE_ZIG = "0.16.0"


def fake_driver(schema: str = "sha256") -> dict:
    return {"schema": schema, "binary_sha256": FAKE_BINARY,
            "source_sha256": FAKE_SOURCE, "zig_version": FAKE_ZIG}


class HermeticCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="pyzig-test-var-")
        self.var = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.manifest = self.var / "drivers" / "manifest.json"
        self.manifest.parent.mkdir(parents=True)
        self.manifest.write_text(json.dumps({
            "zig_version": FAKE_ZIG,
            "drivers": {"sha256": fake_driver()},
        }), encoding="utf-8")
        for target, attr, value in (
            (drivers, "MANIFEST", self.manifest),
            (warden, "WARDEN_DIR", self.var / "warden"),
            (campaign, "CAMPAIGN_DIR", self.var / "campaigns"),
        ):
            patcher = mock.patch.object(target, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)

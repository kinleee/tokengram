"""license_gate açarsız davranışı (R3 fix — 2026-06-11).

Run: `python tests/test_license_gate_keyless.py`

Yoxlayır: açar faylı yoxdursa hooks license modulunu HEÇ import etmir
(deməli trial şəbəkə sorğusu da yoxdur) və dərhal False qaytarır.
Açar yarananda isə cache yazılmadığı üçün növbəti çağırış dərhal
normal yoxlama yoluna düşür.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))

import license_gate as lg


class KeylessGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._env = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME", "MLA_LICENSE_KEY")}
        os.environ["USERPROFILE"] = self.tmp.name
        os.environ["HOME"] = self.tmp.name
        os.environ.pop("MLA_LICENSE_KEY", None)
        self._orig_import = lg._import_license_module

    def tearDown(self):
        lg._import_license_module = self._orig_import
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_no_key_returns_false_without_network(self):
        def boom():
            raise AssertionError("açarsız halda license modulu import olunmamalı idi (şəbəkə riski)")

        lg._import_license_module = boom
        self.assertFalse(lg.license_valid())

    def test_env_key_proceeds_to_validation(self):
        os.environ["MLA_LICENSE_KEY"] = "mla_live_x"
        self.assertTrue(lg._key_present())

    def test_key_file_detected_immediately_after_creation(self):
        """Cache yazılmır → açar faylı yaranan kimi gate onu görür."""
        self.assertFalse(lg._key_present())
        key_dir = Path(self.tmp.name) / ".tokengram"
        key_dir.mkdir(parents=True, exist_ok=True)
        (key_dir / "license_key.txt").write_text("mla_trial_abc", encoding="utf-8")
        self.assertTrue(lg._key_present())

    def test_legacy_mla_dir_also_checked(self):
        key_dir = Path(self.tmp.name) / ".mla"
        key_dir.mkdir(parents=True, exist_ok=True)
        (key_dir / "license_key.txt").write_text("mla_live_x", encoding="utf-8")
        self.assertTrue(lg._key_present())


if __name__ == "__main__":
    unittest.main(verbosity=2)

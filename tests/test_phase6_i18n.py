"""Phase 6 — i18n test suite.

NOTE (2026-07-06): AZ locale faylı QƏSDƏN silinib (commit fdc3ef5,
"az.json removal") — launch English-only-dir. `i18n._SUPPORTED` hələ
"az"-ı tanıyır, amma az.json yoxdur → `tr()` EN-ə fallback etməlidir.
AZ geri gələrsə: az.json bərpa et + buradakı fallback testlərini yenidən
key/placeholder-parity testlərinə çevir (git tarixçəsində hazır formaları var).

Verifies:
  * `en.json` sağlamdır (boş tərcümə yoxdur, placeholder-lər düzgün formatdır).
  * az.json yoxdur və `MLA_LANG=az` EN-ə səssiz fallback edir (crash yox).
  * `tr()` `MLA_LANG` əsasında düzgün seçir.
  * Missing key returns the key literal (loud fail-mode).
"""
import json
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MESSAGES_DIR = ROOT / "messages"
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def _placeholders(s: str):
    return frozenset(_PLACEHOLDER_RE.findall(s))


class TestMessageFiles(unittest.TestCase):
    def setUp(self):
        self.en = json.loads((MESSAGES_DIR / "en.json").read_text(encoding="utf-8"))

    def test_az_json_intentionally_absent(self):
        """az.json qəsdən yoxdur (fdc3ef5). Geri qayıdıbsa, bu test qəsdən
        sınır: parity testlərini git tarixçəsindən bərpa etmək lazımdır."""
        self.assertFalse(
            (MESSAGES_DIR / "az.json").exists(),
            "az.json geri gəlib — phase6-nı key/placeholder-parity rejiminə qaytar",
        )

    def test_en_placeholders_are_valid_identifiers(self):
        """`template.format(**kwargs)` yalnız identifier placeholder-lərlə
        işləyir — `{0}` / `{a.b}` kimi formalar tr()-in kwargs müqaviləsini pozur."""
        for key, val in self.en.items():
            for ph in _placeholders(val):
                self.assertTrue(
                    ph.isidentifier(),
                    msg=f"bad placeholder {{{ph}}} in en.json key={key!r}",
                )

    def test_no_empty_translations(self):
        for key, val in self.en.items():
            self.assertTrue(
                val.strip(),
                msg=f"empty translation in en.json key={key!r}",
            )


class TestTrFunction(unittest.TestCase):
    def setUp(self):
        # Hər test üçün təmiz state
        import i18n
        i18n._cache.clear()
        self._saved_env = os.environ.get("MLA_LANG")

    def tearDown(self):
        if self._saved_env is None:
            os.environ.pop("MLA_LANG", None)
        else:
            os.environ["MLA_LANG"] = self._saved_env
        import i18n
        i18n._cache.clear()

    def _tr(self, *args, **kwargs):
        import i18n
        i18n._cache.clear()
        return i18n.tr(*args, **kwargs)

    def test_default_is_english(self):
        os.environ.pop("MLA_LANG", None)
        os.environ.pop("LANG", None)
        os.environ.pop("LC_ALL", None)
        msg = self._tr("arch_missing")
        self.assertIn("hasn't been generated", msg)

    def test_az_locale_via_mla_lang_falls_back_to_en(self):
        # az.json silinib (fdc3ef5) → az seçimi EN template qaytarır
        os.environ["MLA_LANG"] = "az"
        msg = self._tr("arch_missing")
        self.assertIn("hasn't been generated", msg)

    def test_az_locale_via_lang_env_falls_back_to_en(self):
        os.environ.pop("MLA_LANG", None)
        os.environ["LANG"] = "az_AZ.UTF-8"
        msg = self._tr("arch_missing")
        self.assertIn("hasn't been generated", msg)

    def test_unknown_locale_falls_back_to_en(self):
        os.environ["MLA_LANG"] = "kr"  # not supported
        os.environ.pop("LANG", None)
        msg = self._tr("arch_missing")
        self.assertIn("hasn't been generated", msg)

    def test_format_placeholders(self):
        os.environ["MLA_LANG"] = "en"
        msg = self._tr("read_block", name="foo.ts", lines=104)
        self.assertIn("foo.ts", msg)
        self.assertIn("104", msg)

    def test_missing_key_returns_key(self):
        os.environ["MLA_LANG"] = "en"
        self.assertEqual(self._tr("__never_a_real_key__"), "__never_a_real_key__")

    def test_format_error_returns_template_not_crash(self):
        # `{lines}` lazımdır, vermirik → template raw qaytarılır
        os.environ["MLA_LANG"] = "en"
        msg = self._tr("read_warn", name="x.py")
        self.assertIsInstance(msg, str)
        self.assertIn("{lines}", msg)  # raw template


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Phase 6 — i18n test suite.

Verifies:
  * `i18n.py` has the same keys in `en.json` and `az.json` (no missing or
    extra translations).
  * Format placeholders (`{name}`, `{lines}`, …) match across locales —
    otherwise `template.format(**kwargs)` raises KeyError silently
    (the fallback returns the raw template, losing data).
  * `tr()` correctly switches based on `MLA_LANG`.
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
        self.az = json.loads((MESSAGES_DIR / "az.json").read_text(encoding="utf-8"))

    def test_key_parity(self):
        en_keys = set(self.en.keys())
        az_keys = set(self.az.keys())
        missing_in_az = en_keys - az_keys
        extra_in_az = az_keys - en_keys
        self.assertFalse(missing_in_az, f"keys missing in az: {missing_in_az}")
        self.assertFalse(extra_in_az, f"unknown keys in az: {extra_in_az}")

    def test_placeholder_parity(self):
        for key in self.en:
            self.assertEqual(
                _placeholders(self.en[key]),
                _placeholders(self.az[key]),
                msg=f"placeholder mismatch in key={key!r}: "
                f"en={self.en[key]!r} az={self.az[key]!r}",
            )

    def test_no_empty_translations(self):
        for locale_name, table in (("en", self.en), ("az", self.az)):
            for key, val in table.items():
                self.assertTrue(
                    val.strip(),
                    msg=f"empty translation in {locale_name}.json key={key!r}",
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

    def test_az_locale_via_mla_lang(self):
        os.environ["MLA_LANG"] = "az"
        msg = self._tr("arch_missing")
        self.assertIn("yaradılmayıb", msg)

    def test_az_locale_via_lang_env(self):
        os.environ.pop("MLA_LANG", None)
        os.environ["LANG"] = "az_AZ.UTF-8"
        msg = self._tr("arch_missing")
        self.assertIn("yaradılmayıb", msg)

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

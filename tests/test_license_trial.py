"""Trial axını unit testləri (A1 — launch plan).

Run: `python tests/test_license_trial.py`
Vanilla unittest, şəbəkəyə çıxmır — HTTP qatı stub-lanır.

Nəyi yoxlayır:
  1. Açar yoxdursa → /trial çağırılır, açar lokala yazılır, guard qayıdır
  2. Server trial_expired deyirsə → istifadəçiyə aydın mesaj (buy link + "heç nə sınmır")
  3. Dev mode compiled build-də QADAĞANDIR (env var ilə açıla bilməz)
  4. Dev mode source layout-da işləyir
  5. Bitmiş trial açarı (keyed axın) → aydın mesaj
  6. license_status() trialing-i period_end-ə görə hesablayır
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import license as lic

FP = "f" * 64
NOW = int(time.time())


def _trial_claims(period_end=None):
    return lic.Claims(
        user_id="usr_test",
        license_key="mla_trial_abc",
        fingerprint=FP,
        exp=NOW + 7 * 86400,
        subscription_status="trialing",
        period_end=period_end if period_end is not None else NOW + 30 * 86400,
    )


class TrialTestBase(unittest.TestCase):
    """HOME-u tmp-ə yönəldir, license modulunun stub-lanan attributlarını qoruyur."""

    _PATCHED = (
        "_http_post", "_http_get_text", "verify_token",
        "machine_fingerprint", "_IS_COMPILED", "_start_trial",
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_home = Path(self.tmp.name)
        self._env = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME", "TOKENGRAM_DEV_MODE")}
        os.environ["USERPROFILE"] = self.tmp.name  # Windows Path.home()
        os.environ["HOME"] = self.tmp.name          # POSIX Path.home()
        os.environ.pop("TOKENGRAM_DEV_MODE", None)
        self._orig = {n: getattr(lic, n) for n in self._PATCHED}
        lic.reset_cache()

    def tearDown(self):
        for n, v in self._orig.items():
            setattr(lic, n, v)
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        lic.reset_cache()
        self.tmp.cleanup()

    def _config(self, key=None, pem=b"-----BEGIN PUBLIC KEY-----\nfake\n-----END PUBLIC KEY-----"):
        return lic.LicenseConfig(
            license_key=key,
            server_url="https://srv.test",
            public_key_pem=pem,
            cache_path=self.tmp_home / ".tokengram" / "token.jwt",
        )


class TestTrialStart(TrialTestBase):
    def test_no_key_starts_trial_and_persists_state(self):
        calls = []

        def fake_post(url, *, json_body=None, bearer=None):
            calls.append(url)
            self.assertTrue(url.endswith("/trial"), f"gözlənilməz URL: {url}")
            self.assertEqual(json_body, {"machine_fingerprint": FP})
            return {
                "token": "TOKEN",
                "expires_at": NOW + 7 * 86400,
                "license_key": "mla_trial_abc",
                "trial_ends_at": NOW + 30 * 86400,
            }

        lic.machine_fingerprint = lambda: FP
        lic._http_post = fake_post
        lic.verify_token = lambda token, pem: _trial_claims()

        guard = lic.ensure_license(self._config())

        self.assertIsNotNone(guard, "trial guard qayıtmalı idi")
        self.assertEqual(guard.claims.subscription_status, "trialing")
        self.assertEqual(len(calls), 1)
        key_file = self.tmp_home / ".tokengram" / "license_key.txt"
        self.assertEqual(key_file.read_text(encoding="utf-8"), "mla_trial_abc")
        url_file = self.tmp_home / ".tokengram" / "server_url.txt"
        self.assertEqual(url_file.read_text(encoding="utf-8"), "https://srv.test")
        self.assertTrue((self.tmp_home / ".tokengram" / "token.jwt").exists())

    def test_no_pubkey_fetches_from_server(self):
        pem_text = "-----BEGIN PUBLIC KEY-----\nserverpem\n-----END PUBLIC KEY-----"
        lic.machine_fingerprint = lambda: FP
        lic._http_get_text = lambda url: pem_text
        lic._http_post = lambda url, *, json_body=None, bearer=None: {
            "token": "TOKEN",
            "expires_at": NOW + 7 * 86400,
            "license_key": "mla_trial_abc",
        }
        lic.verify_token = lambda token, pem: _trial_claims()

        guard = lic.ensure_license(self._config(pem=None))

        self.assertIsNotNone(guard)
        saved = (self.tmp_home / ".tokengram" / "pubkey.pem").read_text(encoding="utf-8")
        self.assertIn("serverpem", saved)

    def test_trial_expired_friendly_message(self):
        def fake_post(url, *, json_body=None, bearer=None):
            raise lic.LicenseServerError(f'{url} → HTTP 403: {{"error":"trial_expired"}}')

        lic.machine_fingerprint = lambda: FP
        lic._http_post = fake_post

        with self.assertRaises(lic.LicenseError) as ctx:
            lic.ensure_license(self._config())
        msg = str(ctx.exception)
        self.assertIn("tokengram.click/buy", msg)
        self.assertIn("sınmır", msg)
        self.assertNotIn("HTTP 403", msg, "xam HTTP mətni istifadəçiyə getməməlidir")

    def test_network_error_friendly_message(self):
        def fake_post(url, *, json_body=None, bearer=None):
            raise lic.LicenseError("network error (https://srv.test/trial): timeout")

        lic.machine_fingerprint = lambda: FP
        lic._http_post = fake_post

        with self.assertRaises(lic.LicenseError) as ctx:
            lic.ensure_license(self._config())
        self.assertIn("çatmaq olmur", str(ctx.exception))


class TestDevModeGate(TrialTestBase):
    def test_compiled_build_ignores_dev_env(self):
        """R1: release build-də TOKENGRAM_DEV_MODE=1 dev mode AÇMIR."""
        os.environ["TOKENGRAM_DEV_MODE"] = "1"
        lic._IS_COMPILED = True
        sentinel = lic.LicenseGuard(_trial_claims())
        lic._start_trial = lambda config: sentinel

        result = lic.ensure_license(self._config())

        self.assertIs(result, sentinel, "compiled build trial axınına getməli idi, dev mode-a yox")

    def test_compiled_build_ignores_dev_flag_file(self):
        flag = self.tmp_home / ".tokengram" / "dev_mode.flag"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("on", encoding="utf-8")
        lic._IS_COMPILED = True
        sentinel = lic.LicenseGuard(_trial_claims())
        lic._start_trial = lambda config: sentinel

        self.assertIs(lic.ensure_license(self._config()), sentinel)

    def test_source_layout_dev_env_allows(self):
        os.environ["TOKENGRAM_DEV_MODE"] = "1"
        lic._IS_COMPILED = False

        self.assertIsNone(lic.ensure_license(self._config()), "source layout-da dev mode işləməli idi")

    def test_source_layout_without_flag_starts_trial(self):
        lic._IS_COMPILED = False
        sentinel = lic.LicenseGuard(_trial_claims())
        lic._start_trial = lambda config: sentinel

        self.assertIs(lic.ensure_license(self._config()), sentinel)


class TestExpiredTrialKeyedFlow(TrialTestBase):
    def test_expired_trial_key_friendly_message(self):
        """Trial açarı yazılıb, sonra server abunəni rədd edir → aydın mesaj."""

        def fake_post(url, *, json_body=None, bearer=None):
            raise lic.LicenseServerError(f'{url} → HTTP 402: {{"error":"no_active_subscription"}}')

        lic.machine_fingerprint = lambda: FP
        lic._http_post = fake_post

        with self.assertRaises(lic.LicenseError) as ctx:
            lic.ensure_license(self._config(key="mla_trial_abc"))
        msg = str(ctx.exception)
        self.assertIn("tokengram.click/buy", msg)
        self.assertIn("sınmır", msg)

    def test_expired_live_key_keeps_raw_error(self):
        """Pullu açarda eyni server cavabı trial mesajına çevrilmir."""

        def fake_post(url, *, json_body=None, bearer=None):
            raise lic.LicenseServerError(f'{url} → HTTP 402: {{"error":"no_active_subscription"}}')

        lic.machine_fingerprint = lambda: FP
        lic._http_post = fake_post

        with self.assertRaises(lic.LicenseServerError):
            lic.ensure_license(self._config(key="mla_live_abc"))


class TestLicenseStatus(TrialTestBase):
    # days_left = (horizon - now) // 86400 (floor, "qalan TAM gün").
    # Sərhəd üstünə düz N*86400 qoymaq flaky idi: modul-load `NOW`-u ilə testin
    # işlədiyi an arasındakı saniyələr floor-u N-1-ə salırdı (tam suite-də
    # collection ~30s çəkir). Yarım-gün buffer testi sərhəddən çəkir.
    def test_status_trialing_uses_period_end(self):
        period_end = NOW + 5 * 86400 + 43200
        guard = lic.LicenseGuard(_trial_claims(period_end=period_end))
        orig = lic.ensure_license_cached
        lic.ensure_license_cached = lambda: guard
        try:
            status = lic.license_status()
        finally:
            lic.ensure_license_cached = orig

        self.assertEqual(status["status"], "trialing")
        self.assertEqual(status["days_left"], 5)
        self.assertEqual(status["expires_at"], period_end)

    def test_status_active_without_period_end_falls_back_to_exp(self):
        claims = lic.Claims(
            user_id="u", license_key="mla_live_x", fingerprint=FP,
            exp=NOW + 3 * 86400 + 43200,  # +yarım gün: floor sərhəd flakiness-i
            subscription_status="active", period_end=None,
        )
        orig = lic.ensure_license_cached
        lic.ensure_license_cached = lambda: lic.LicenseGuard(claims)
        try:
            status = lic.license_status()
        finally:
            lic.ensure_license_cached = orig

        self.assertEqual(status["status"], "active")
        self.assertEqual(status["days_left"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)

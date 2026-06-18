"""
test_license.py — license.py modulu üçün unit testlər.

İcra:
    pytest test_license.py -v
    və ya
    python -m unittest test_license.py -v

Bütün testlər real server LAZIM DEYİL — RSA keypair test daxilində yaradılır,
HTTP çağırışları mock-lanır.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import license as lic


# ============================================================
# Test helper: yalnız MLA_* env-ləri sil (USERPROFILE/HOME-a toxunma)
# ============================================================
class _scrub_mla_env:
    """patch.dict(clear=True) Windows-da Path.home()-ni qırır.
    Bu helper yalnız MLA_LICENSE_* env-ləri silir, qalanı saxlayır."""

    def __init__(self, **overrides):
        self.overrides = overrides
        self.saved = {}

    def __enter__(self):
        for k in list(os.environ.keys()):
            if k.startswith("MLA_LICENSE_"):
                self.saved[k] = os.environ.pop(k)
        for k, v in self.overrides.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, exc_type, exc, tb):
        for k in list(os.environ.keys()):
            if k.startswith("MLA_LICENSE_") and k not in self.saved:
                del os.environ[k]
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ============================================================
# Yardımçı: test üçün RSA keypair və token generate
# ============================================================
def _generate_keypair():
    """Test üçün ephemeral RSA keypair yarad. Real keypair-ə təsir etmir."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _sign_token(
    private_pem: bytes,
    *,
    user_id: str = "user_test",
    license_key: str = "mla_live_test",
    fingerprint: str = "test_fp",
    subscription_status: str = "active",
    exp_offset_seconds: int = 7 * 24 * 60 * 60,
    iat_offset_seconds: int = 0,
    issuer: str = lic.JWT_ISSUER,
) -> str:
    import jwt as pyjwt

    now = int(time.time())
    claims = {
        "user_id": user_id,
        "license_key": license_key,
        "fingerprint": fingerprint,
        "subscription_status": subscription_status,
        "iat": now + iat_offset_seconds,
        "exp": now + exp_offset_seconds,
        "iss": issuer,
    }
    return pyjwt.encode(claims, private_pem, algorithm="RS256")


# ============================================================
# Fingerprint testləri
# ============================================================
class TestFingerprint(unittest.TestCase):
    def test_fingerprint_is_stable(self):
        a = lic.machine_fingerprint()
        b = lic.machine_fingerprint()
        self.assertEqual(a, b)

    def test_fingerprint_is_sha256_hex(self):
        fp = lic.machine_fingerprint()
        self.assertEqual(len(fp), 64)
        # Yalnız hex hərflər (0-9, a-f)
        int(fp, 16)


# ============================================================
# Dev mode testləri
# ============================================================
class TestDevMode(unittest.TestCase):
    def setUp(self):
        lic.reset_cache()

    def test_dev_mode_when_no_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = lic.LicenseConfig(
                license_key=None,
                server_url=None,
                public_key_pem=None,
                cache_path=Path(tmp) / "token.jwt",
            )
            self.assertIsNone(lic.ensure_license(config))

    def test_dev_mode_when_empty_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = lic.LicenseConfig(
                license_key="",
                server_url=None,
                public_key_pem=None,
                cache_path=Path(tmp) / "token.jwt",
            )
            self.assertIsNone(lic.ensure_license(config))

    def test_from_env_dev_mode(self):
        with _scrub_mla_env():
            config = lic.LicenseConfig.from_env()
            self.assertIsNone(config.license_key)
            self.assertIsNone(lic.ensure_license(config))


# ============================================================
# Config validation testləri
# ============================================================
class TestConfigValidation(unittest.TestCase):
    def setUp(self):
        lic.reset_cache()

    def test_missing_server_url_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = lic.LicenseConfig(
                license_key="mla_live_xxx",
                server_url=None,
                public_key_pem=b"dummy",
                cache_path=Path(tmp) / "token.jwt",
            )
            with self.assertRaises(lic.LicenseError) as ctx:
                lic.ensure_license(config)
            self.assertIn("MLA_LICENSE_SERVER_URL", str(ctx.exception))

    def test_missing_pubkey_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = lic.LicenseConfig(
                license_key="mla_live_xxx",
                server_url="https://license.example.com",
                public_key_pem=None,
                cache_path=Path(tmp) / "token.jwt",
            )
            with self.assertRaises(lic.LicenseError) as ctx:
                lic.ensure_license(config)
            self.assertIn("MLA_LICENSE_PUBKEY", str(ctx.exception))


# ============================================================
# JWT verify testləri (real RSA keypair ilə)
# ============================================================
class TestVerifyToken(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_pem, cls.public_pem = _generate_keypair()

    def test_valid_token_returns_claims(self):
        token = _sign_token(self.private_pem, fingerprint="abc123")
        claims = lic.verify_token(token, self.public_pem)
        self.assertEqual(claims.user_id, "user_test")
        self.assertEqual(claims.fingerprint, "abc123")
        self.assertEqual(claims.subscription_status, "active")
        self.assertGreater(claims.exp, int(time.time()))

    def test_tampered_token_raises(self):
        token = _sign_token(self.private_pem)
        # Token-in payload hissəsini dəyişdir (signature kasılacaq)
        parts = token.split(".")
        parts[1] = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
        tampered = ".".join(parts)
        with self.assertRaises(lic.LicenseError):
            lic.verify_token(tampered, self.public_pem)

    def test_expired_token_raises(self):
        token = _sign_token(self.private_pem, exp_offset_seconds=-100)
        with self.assertRaises(lic.LicenseError) as ctx:
            lic.verify_token(token, self.public_pem)
        self.assertIn("expired", str(ctx.exception).lower())

    def test_wrong_issuer_raises(self):
        token = _sign_token(self.private_pem, issuer="evil-issuer")
        with self.assertRaises(lic.LicenseError):
            lic.verify_token(token, self.public_pem)

    def test_wrong_pubkey_raises(self):
        token = _sign_token(self.private_pem)
        _, other_pubkey = _generate_keypair()
        with self.assertRaises(lic.LicenseError):
            lic.verify_token(token, other_pubkey)

    def test_future_iat_within_leeway_ok(self):
        # 2026-06-12 insidenti: lokal saat serverdən bir neçə saniyə geri
        # qalanda təzə tokenin iat-ı gələcəkdə görünürdü və 0-leeway verify
        # tokeni rədd edirdi. Leeway daxilindəki fərq artıq keçməlidir.
        token = _sign_token(
            self.private_pem,
            iat_offset_seconds=lic.JWT_LEEWAY_SECONDS - 10,
        )
        claims = lic.verify_token(token, self.public_pem)
        self.assertEqual(claims.user_id, "user_test")

    def test_future_iat_beyond_leeway_raises(self):
        token = _sign_token(
            self.private_pem,
            iat_offset_seconds=lic.JWT_LEEWAY_SECONDS + 60,
        )
        with self.assertRaises(lic.LicenseError) as ctx:
            lic.verify_token(token, self.public_pem)
        self.assertIn("iat", str(ctx.exception).lower())

    def test_missing_required_claim_raises(self):
        import jwt as pyjwt
        claims = {
            "user_id": "u",
            # license_key missing
            "fingerprint": "fp",
            "exp": int(time.time()) + 3600,
            "iss": lic.JWT_ISSUER,
        }
        token = pyjwt.encode(claims, self.private_pem, algorithm="RS256")
        with self.assertRaises(lic.LicenseError):
            lic.verify_token(token, self.public_pem)


# ============================================================
# ensure_license — server mock ilə end-to-end axın
# ============================================================
class TestEnsureLicenseFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_pem, cls.public_pem = _generate_keypair()

    def setUp(self):
        lic.reset_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_path = Path(self._tmp.name) / "token.jwt"

    def tearDown(self):
        self._tmp.cleanup()

    def _config(self) -> lic.LicenseConfig:
        return lic.LicenseConfig(
            license_key="mla_live_test",
            server_url="https://license.example.com",
            public_key_pem=self.public_pem,
            cache_path=self.cache_path,
        )

    def test_first_activation_calls_activate_and_caches(self):
        real_fp = lic.machine_fingerprint()
        token = _sign_token(self.private_pem, fingerprint=real_fp)
        exp = int(time.time()) + 7 * 24 * 60 * 60

        with patch("license._activate", return_value={"token": token, "expires_at": exp}) as m_act, \
             patch("license._refresh") as m_ref:
            guard = lic.ensure_license(self._config())

        self.assertIsNotNone(guard)
        self.assertEqual(guard.claims.fingerprint, real_fp)
        m_act.assert_called_once()
        m_ref.assert_not_called()
        self.assertTrue(self.cache_path.exists())

        cached = json.loads(self.cache_path.read_text())
        self.assertEqual(cached["fingerprint"], real_fp)

    def test_cache_used_when_valid(self):
        real_fp = lic.machine_fingerprint()
        token = _sign_token(self.private_pem, fingerprint=real_fp)
        exp = int(time.time()) + 7 * 24 * 60 * 60
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        # last_refreshed_at olmasa periodik recheck dərhal serverə gedir və
        # cache-only ssenari pozulur (sahə PERIODIC_RECHECK ilə əlavə olunub).
        self.cache_path.write_text(json.dumps({
            "token": token, "expires_at": exp, "fingerprint": real_fp,
            "last_refreshed_at": int(time.time()),
        }))

        with patch("license._activate") as m_act, patch("license._refresh") as m_ref:
            guard = lic.ensure_license(self._config())

        self.assertIsNotNone(guard)
        m_act.assert_not_called()
        m_ref.assert_not_called()

    def test_cache_with_stale_fingerprint_triggers_activate(self):
        real_fp = lic.machine_fingerprint()
        old_fp = "0" * 64
        old_token = _sign_token(self.private_pem, fingerprint=old_fp)
        exp = int(time.time()) + 7 * 24 * 60 * 60
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps({
            "token": old_token, "expires_at": exp, "fingerprint": old_fp,
        }))

        new_token = _sign_token(self.private_pem, fingerprint=real_fp)
        # cache fingerprint != current → 1-ci yoxlama ötür, 2-də /validate cəhdi olur (cached token ilə),
        # uğursuz olsa /activate. Bizim mock /validate uğurlu olsun, amma fingerprint yenisi gəlsin.
        with patch("license._refresh", return_value={"token": new_token, "expires_at": exp}) as m_ref, \
             patch("license._activate") as m_act:
            guard = lic.ensure_license(self._config())

        self.assertIsNotNone(guard)
        self.assertEqual(guard.claims.fingerprint, real_fp)
        # Refresh ilk növbədə cəhd edilir (cache-də token var)
        m_ref.assert_called_once()

    def test_cache_expired_triggers_refresh(self):
        real_fp = lic.machine_fingerprint()
        # Expiry 12 saat sonra — REFRESH_THRESHOLD (24 saat) içindədir, refresh tələb olunur
        expired_token = _sign_token(self.private_pem, fingerprint=real_fp, exp_offset_seconds=12 * 3600)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps({
            "token": expired_token,
            "expires_at": int(time.time()) + 12 * 3600,
            "fingerprint": real_fp,
        }))

        new_exp = int(time.time()) + 7 * 24 * 60 * 60
        fresh_token = _sign_token(self.private_pem, fingerprint=real_fp, exp_offset_seconds=7 * 24 * 60 * 60)

        with patch("license._refresh", return_value={"token": fresh_token, "expires_at": new_exp}) as m_ref, \
             patch("license._activate") as m_act:
            guard = lic.ensure_license(self._config())

        self.assertIsNotNone(guard)
        m_ref.assert_called_once()
        m_act.assert_not_called()

    def test_refresh_failure_falls_back_to_activate(self):
        real_fp = lic.machine_fingerprint()
        old_token = _sign_token(self.private_pem, fingerprint=real_fp, exp_offset_seconds=12 * 3600)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps({
            "token": old_token,
            "expires_at": int(time.time()) + 12 * 3600,
            "fingerprint": real_fp,
        }))

        new_token = _sign_token(self.private_pem, fingerprint=real_fp)
        new_exp = int(time.time()) + 7 * 24 * 60 * 60

        with patch("license._refresh", side_effect=lic.LicenseError("subscription cancelled")) as m_ref, \
             patch("license._activate", return_value={"token": new_token, "expires_at": new_exp}) as m_act:
            guard = lic.ensure_license(self._config())

        self.assertIsNotNone(guard)
        m_ref.assert_called_once()
        m_act.assert_called_once()

    def test_fingerprint_mismatch_from_server_raises(self):
        # Server bizim fingerprint ilə istənilən səbəbdən fərqli token qaytarsa → reject
        token = _sign_token(self.private_pem, fingerprint="WRONG_FINGERPRINT_FROM_SERVER")
        exp = int(time.time()) + 7 * 24 * 60 * 60
        with patch("license._activate", return_value={"token": token, "expires_at": exp}):
            with self.assertRaises(lic.LicenseError) as ctx:
                lic.ensure_license(self._config())
            self.assertIn("fingerprint", str(ctx.exception).lower())

    def test_malformed_server_response_raises(self):
        with patch("license._activate", return_value={"token": "x"}):  # expires_at missing
            with self.assertRaises(lic.LicenseError):
                lic.ensure_license(self._config())

    def test_offline_grace_period_uses_cache_when_server_down(self):
        """Refresh + activate ikisi də network xətası verirsə, cache valid token-i istifadə et."""
        real_fp = lic.machine_fingerprint()
        # Cache: token hələ etibarlıdır (exp > now) amma refresh window-dadır (exp - 24h < now)
        cached_token = _sign_token(self.private_pem, fingerprint=real_fp, exp_offset_seconds=12 * 3600)
        cached_exp = int(time.time()) + 12 * 3600
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        # last_refreshed_at offline grace pəncərəsinin açarıdır — yoxdursa 0
        # sayılır və grace heç vaxt işləmir (sahə PERIODIC_RECHECK ilə gəlib).
        self.cache_path.write_text(json.dumps({
            "token": cached_token, "expires_at": cached_exp, "fingerprint": real_fp,
            "last_refreshed_at": int(time.time()),
        }))

        with patch("license._refresh", side_effect=lic.LicenseError("network error: timeout")) as m_ref, \
             patch("license._activate", side_effect=lic.LicenseError("network error: timeout")) as m_act:
            guard = lic.ensure_license(self._config())

        # Server unreachable amma cached token hələ etibarlıdır → graceful degradation
        self.assertIsNotNone(guard)
        self.assertEqual(guard.claims.fingerprint, real_fp)
        m_ref.assert_called_once()
        m_act.assert_called_once()

    def test_offline_grace_period_fails_when_cache_expired(self):
        """Cache exp < now-dısa graceful degradation işləməməlidir."""
        real_fp = lic.machine_fingerprint()
        expired_token = _sign_token(self.private_pem, fingerprint=real_fp, exp_offset_seconds=-100)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps({
            "token": expired_token,
            "expires_at": int(time.time()) - 100,
            "fingerprint": real_fp,
        }))

        with patch("license._refresh", side_effect=lic.LicenseError("network error")), \
             patch("license._activate", side_effect=lic.LicenseError("network error")):
            with self.assertRaises(lic.LicenseError):
                lic.ensure_license(self._config())

    def test_offline_grace_period_fails_when_no_cache(self):
        """Cache yoxdursa network down → LicenseError."""
        with patch("license._activate", side_effect=lic.LicenseError("network error")):
            with self.assertRaises(lic.LicenseError):
                lic.ensure_license(self._config())


# ============================================================
# In-memory cache (ensure_license_cached) testləri
# ============================================================
class TestCachedGuard(unittest.TestCase):
    def setUp(self):
        lic.reset_cache()

    def test_dev_mode_cached(self):
        with _scrub_mla_env():
            g1 = lic.ensure_license_cached()
            g2 = lic.ensure_license_cached()
            self.assertIsNone(g1)
            self.assertIsNone(g2)

    def test_reset_cache_clears(self):
        with _scrub_mla_env():
            lic.ensure_license_cached()
            self.assertTrue(lic._cached_dev_mode)
            lic.reset_cache()
            self.assertFalse(lic._cached_dev_mode)
            self.assertIsNone(lic._cached_guard)


# ============================================================
# license_status — UI üçün cavab formatı
# ============================================================
class TestLicenseStatus(unittest.TestCase):
    def setUp(self):
        lic.reset_cache()

    def test_dev_mode_status(self):
        with _scrub_mla_env():
            status = lic.license_status()
            self.assertEqual(status["status"], "dev_mode")

    def test_error_status_when_config_invalid(self):
        with _scrub_mla_env(MLA_LICENSE_KEY="x"):
            status = lic.license_status()
            self.assertEqual(status["status"], "error")
            self.assertIn("MLA_LICENSE_SERVER_URL", status["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

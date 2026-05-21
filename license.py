"""
license.py — MLA Agent lisenziya yoxlaması.

Rust prototipindəki `license.rs` modulunun Python portu.

Mühit dəyişənləri:
- MLA_LICENSE_KEY:        License key (mla_live_xxx). Boşdursa dev mode.
- MLA_LICENSE_SERVER_URL: Cloudflare Worker URL (məs. https://license.mla-agent.com)
- MLA_LICENSE_PUBKEY:     RSA public key PEM faylının yolu (JWT verify üçün)

Cache: ~/.mla/token.jwt — JSON {token, expires_at, fingerprint}

Threat model:
- Token başqa PC-yə kopyalansa fingerprint mismatch → reject
- Token expire olsa /validate ilə refresh (subscription cancel olunsa server 401)
- Internet yoxdursa cache-də etibarlı token varsa offline işləyir
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mla.license")

REFRESH_THRESHOLD_SECONDS = 24 * 60 * 60  # exp-dən 1 gün əvvəl refresh
PERIODIC_RECHECK_SECONDS = 60 * 60  # 1 saatdan bir məcburi server check (admin cancel-i tez tutmaq üçün)
OFFLINE_GRACE_SECONDS = 7 * 24 * 60 * 60  # server-ə 7 gün çatmadıqda cache-i hələ də işlət
HTTP_TIMEOUT_SECONDS = 10
JWT_ISSUER = "mla-license-server"
_GUARD_CACHE_TTL = 60  # in-memory guard cache (saniyə) — hər tool çağırışında file I/O olmasın


@dataclass(frozen=True)
class Claims:
    user_id: str
    license_key: str
    fingerprint: str
    exp: int
    subscription_status: Optional[str] = None
    iat: Optional[int] = None
    iss: Optional[str] = None


@dataclass
class LicenseConfig:
    license_key: Optional[str]
    server_url: Optional[str]
    public_key_pem: Optional[bytes]
    cache_path: Path

    @classmethod
    def from_env(cls) -> "LicenseConfig":
        """Env var-lar prioritetdir; boşdursa ~/.mla/ qovluğundakı fallback fayllara bax.

        Bu, VSCode extension üçün vacibdir: extension license key-i fayla yazır,
        MCP server (Claude Code tərəfindən spawn olunur) faylı oxuyur.
        """
        mla_dir = Path.home() / ".mla"
        cache_path = mla_dir / "token.jwt"

        # Public key: env (path) → ~/.mla/pubkey.pem (default)
        pubkey_path = os.environ.get("MLA_LICENSE_PUBKEY") or None
        public_key_pem: Optional[bytes] = None
        if pubkey_path:
            try:
                public_key_pem = Path(pubkey_path).read_bytes()
            except OSError as e:
                logger.warning("public key oxunmadı (%s): %s", pubkey_path, e)
        else:
            default_pubkey = mla_dir / "pubkey.pem"
            if default_pubkey.exists():
                try:
                    public_key_pem = default_pubkey.read_bytes()
                except OSError as e:
                    logger.warning("default public key oxunmadı (%s): %s", default_pubkey, e)

        # License key: env → ~/.mla/license_key.txt (extension yazır)
        license_key = os.environ.get("MLA_LICENSE_KEY") or None
        if not license_key:
            key_file = mla_dir / "license_key.txt"
            if key_file.exists():
                try:
                    license_key = key_file.read_text(encoding="utf-8").strip() or None
                except OSError as e:
                    logger.warning("license_key.txt oxunmadı: %s", e)

        # Server URL: env → ~/.mla/server_url.txt → default production
        server_url = os.environ.get("MLA_LICENSE_SERVER_URL") or None
        if not server_url:
            url_file = mla_dir / "server_url.txt"
            if url_file.exists():
                try:
                    server_url = url_file.read_text(encoding="utf-8").strip() or None
                except OSError:
                    pass

        return cls(
            license_key=license_key,
            server_url=server_url,
            public_key_pem=public_key_pem,
            cache_path=cache_path,
        )


class LicenseServerError(RuntimeError):
    """Server cavab verdi və açarı/abunəni rədd etdi (məs. 401 cancelled, 402 inactive).

    Bu xəta üçün offline grace-ə düşmək olmaz — server intentional olaraq icazə vermir.
    """


class LicenseError(RuntimeError):
    """License yoxlaması uğursuz olduqda atılan exception."""


class LicenseGuard:
    """Lisenziya etibarlı olduqda qaytarılan sentinel obyekt."""
    __slots__ = ("claims",)

    def __init__(self, claims: Claims):
        self.claims = claims


def machine_fingerprint() -> str:
    """Sabit machine fingerprint: machine_uid + hostname → SHA256 hex (64 char).

    Rust prototipi ilə eyni alqoritm — başqa PC-də fərqli dəyər çıxır.
    """
    uid = _machine_id()
    host = socket.gethostname() or ""
    combined = f"{uid}|{host}".encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def _machine_id() -> str:
    """Cross-platform machine UID. py-machineid varsa istifadə et, yoxsa fallback."""
    try:
        import machineid  # type: ignore[import-not-found]
        # machineid.id() bəzən şəbəkə adapter MAC-ı qaytarır — stabilliyi üçün hashed_id istifadə edək
        # Lakin tutarlılıq üçün id() istifadə edirik (Rust machine-uid crate ilə eyni davranır)
        return machineid.id()
    except ImportError:
        pass
    except Exception as e:
        logger.warning("py-machineid xətası, fallback istifadə edilir: %s", e)

    if os.name == "nt":
        return _windows_machine_guid()
    return _unix_machine_id()


def _windows_machine_guid() -> str:
    """HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid (Windows-da sabit)."""
    try:
        import winreg  # type: ignore[import-not-found]
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value)
    except Exception as e:
        logger.warning("Windows MachineGuid oxunmadı: %s", e)
        return socket.gethostname() or "unknown"


def _unix_machine_id() -> str:
    """Linux: /etc/machine-id. macOS: ioreg IOPlatformUUID."""
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            continue

    # macOS
    try:
        import platform
        import subprocess
        if platform.system() == "Darwin":
            out = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                timeout=5,
            ).decode("utf-8", errors="ignore")
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    parts = line.split('"')
                    if len(parts) >= 4:
                        return parts[3]
    except Exception as e:
        logger.warning("macOS IOPlatformUUID oxunmadı: %s", e)

    return socket.gethostname() or "unknown"


def verify_token(token: str, public_key_pem: bytes) -> Claims:
    """RS256 JWT-ni public key ilə verify et və Claims qaytar.

    Raises:
        LicenseError — token etibarsız (signature, expiry, issuer, claims).
    """
    try:
        import jwt as pyjwt
    except ImportError as e:
        raise LicenseError("pyjwt kitabxanası tapılmadı (pip install pyjwt[crypto])") from e

    try:
        payload = pyjwt.decode(
            token,
            public_key_pem,
            algorithms=["RS256"],
            issuer=JWT_ISSUER,
            options={"require": ["exp", "user_id", "license_key", "fingerprint"]},
        )
    except pyjwt.PyJWTError as e:
        raise LicenseError(f"JWT verify uğursuz: {e}") from e

    return Claims(
        user_id=str(payload["user_id"]),
        license_key=str(payload["license_key"]),
        fingerprint=str(payload["fingerprint"]),
        exp=int(payload["exp"]),
        subscription_status=payload.get("subscription_status"),
        iat=payload.get("iat"),
        iss=payload.get("iss"),
    )


def _now_unix() -> int:
    return int(time.time())


def _http_post(url: str, *, json_body: Optional[dict] = None, bearer: Optional[str] = None) -> dict:
    try:
        import requests  # type: ignore[import-not-found]
    except ImportError as e:
        raise LicenseError("requests kitabxanası tapılmadı (pip install requests)") from e

    headers = {}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    try:
        res = requests.post(url, json=json_body, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        # Network-level failure — server-ə çatmadıq, offline grace-ə eligible.
        raise LicenseError(f"network error ({url}): {e}") from e

    if not res.ok:
        # Server cavab verdi və rədd etdi — offline grace-ə eligible DEYİL.
        raise LicenseServerError(f"{url} → HTTP {res.status_code}: {res.text[:200]}")

    try:
        return res.json()
    except ValueError as e:
        raise LicenseError(f"server cavabı JSON deyil ({url}): {e}") from e


def _activate(server_url: str, license_key: str, fingerprint: str) -> dict:
    return _http_post(
        f"{server_url.rstrip('/')}/activate",
        json_body={"license_key": license_key, "machine_fingerprint": fingerprint},
    )


def _refresh(server_url: str, old_token: str) -> dict:
    return _http_post(
        f"{server_url.rstrip('/')}/validate",
        bearer=old_token,
    )


def _load_cache(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def ensure_license(config: Optional[LicenseConfig] = None) -> Optional[LicenseGuard]:
    """Lisenziya yoxlamasının tam axını.

    Axın:
    1. Dev mode (no key) → None qaytar, çağıran skip edə bilər
    2. Cache-də etibarlı token varsa (fingerprint match + expiry > now + 24h) → onu işlət
    3. Cache köhnəlibsə /validate (cached token ilə), uğursuz olsa /activate
    4. Yeni token verify + fingerprint match yoxlanışı → cache-yə yaz, guard qaytar

    Returns:
        None — dev mode
        LicenseGuard — etibarlı lisenziya

    Raises:
        LicenseError — config natamam, server xətası, token uğursuz, fingerprint mismatch
    """
    config = config or LicenseConfig.from_env()

    if not config.license_key:
        # Dev mode yalnız explicit flag ilə açıqdır — yoxsa key tələb olunur.
        # Inkişaf vərdişi: TOKENGRAM_DEV_MODE=1 və ya ~/.tokengram/dev_mode.flag faylı.
        dev_flag = (
            os.environ.get("TOKENGRAM_DEV_MODE") == "1"
            or (Path.home() / ".tokengram" / "dev_mode.flag").exists()
        )
        if dev_flag:
            logger.info("DEV MODE: TOKENGRAM_DEV_MODE active, enforcement disabled.")
            return None
        raise LicenseError(
            "License key tapılmadı. Setup wizard-ı işə sal (Tokengram: Run setup wizard) "
            "və ya MLA_LICENSE_KEY env var-ı qoy. Açar yoxdursa: https://tokengram.click/buy"
        )

    if not config.server_url:
        raise LicenseError("MLA_LICENSE_SERVER_URL is required when MLA_LICENSE_KEY is set")
    if not config.public_key_pem:
        raise LicenseError("MLA_LICENSE_PUBKEY (PEM file path) is required when MLA_LICENSE_KEY is set")

    fingerprint = machine_fingerprint()
    now = _now_unix()

    # 1) Cache-də etibarlı token varmı? + Periodik server recheck.
    # Cache JWT-yə görə hələ "fresh" olsa belə, son server check-dən
    # PERIODIC_RECHECK_SECONDS keçibsə server-ə getməyə məcbur edirik —
    # admin DB-də subscription cancel etsə cache-də 7 günlük JWT olsa belə
    # 1 saat ərzində user-ə çatır.
    cached = _load_cache(config.cache_path)
    if cached and cached.get("fingerprint") == fingerprint:
        expires_at = int(cached.get("expires_at", 0))
        last_refreshed = int(cached.get("last_refreshed_at", 0))
        cache_fresh = expires_at > now + REFRESH_THRESHOLD_SECONDS
        recheck_due = (now - last_refreshed) > PERIODIC_RECHECK_SECONDS
        if cache_fresh and not recheck_due:
            try:
                claims = verify_token(cached["token"], config.public_key_pem)
                return LicenseGuard(claims)
            except LicenseError as e:
                logger.warning("cache-də token verify uğursuz, server-dən yenilə: %s", e)

    # 2) Cache köhnəlib və ya periodik recheck vaxtıdır → /validate (cached token ilə),
    #    uğursuz olsa /activate.
    response: Optional[dict] = None
    refresh_error: Optional[Exception] = None
    activate_error: Optional[Exception] = None
    # Server explicit "no" dedimi? (cancelled, revoked, machine_mismatch, və s.)
    # Bu vəziyyətdə offline grace-ə düşmək DÜZGÜN deyil.
    server_rejected = False

    if cached and isinstance(cached.get("token"), str):
        try:
            response = _refresh(config.server_url, cached["token"])
        except LicenseServerError as e:
            refresh_error = e
            server_rejected = True
            logger.info("refresh rədd edildi (server cavabı): %s", e)
        except LicenseError as e:
            refresh_error = e
            logger.info("refresh uğursuz (network), activate cəhdi: %s", e)

    if response is None:
        try:
            response = _activate(config.server_url, config.license_key, fingerprint)
        except LicenseServerError as e:
            activate_error = e
            server_rejected = True
        except LicenseError as e:
            activate_error = e

    # 2a) Server-ə çatmaq mümkün olmadı (network error) — cache hələ
    #     cryptographically etibarlıdırsa VƏ son uğurlu refresh
    #     OFFLINE_GRACE_SECONDS-dan yaxındadırsa, davam et.
    #     ƏGƏR server explicit rədd edibsə (cancelled, revoked) — grace YOXDUR.
    if response is None:
        if not server_rejected and cached and cached.get("fingerprint") == fingerprint:
            cached_exp = int(cached.get("expires_at", 0))
            cached_refreshed = int(cached.get("last_refreshed_at", 0))
            in_grace = (
                cached_exp > now
                and (now - cached_refreshed) < OFFLINE_GRACE_SECONDS
            )
            if in_grace:
                try:
                    claims = verify_token(cached["token"], config.public_key_pem)
                    logger.warning(
                        "license server unreachable (refresh: %s; activate: %s) — "
                        "cached token istifadə olunur, exp: %s, last refresh: %s",
                        refresh_error, activate_error,
                        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(claims.exp)),
                        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(cached_refreshed)),
                    )
                    return LicenseGuard(claims)
                except LicenseError:
                    pass  # cache token özü qırıqdırsa fall through to error
        raise activate_error or refresh_error or LicenseError("license check uğursuz")

    if "token" not in response or "expires_at" not in response:
        raise LicenseError(f"server cavabı natamam: {list(response.keys())}")

    # 3) Yeni token verify + fingerprint match
    claims = verify_token(response["token"], config.public_key_pem)
    if claims.fingerprint != fingerprint:
        raise LicenseError("token fingerprint bu machine ilə uyğun gəlmir")

    # 4) Cache-yə yaz
    _save_cache(config.cache_path, {
        "token": response["token"],
        "expires_at": int(response["expires_at"]),
        "fingerprint": fingerprint,
        "last_refreshed_at": now,
    })

    return LicenseGuard(claims)


# ============================================================
# In-memory cached wrapper — hər MCP tool çağırışında file I/O etmir.
# Yalnız _GUARD_CACHE_TTL sn-dən sonra və ya guard expire olunduqda yenidən yoxlanır.
# ============================================================
_cached_guard: Optional[LicenseGuard] = None
_cached_at: int = 0
_cached_dev_mode: bool = False


def ensure_license_cached() -> Optional[LicenseGuard]:
    """ensure_license()-in TTL-cached versiyası — MCP tool entry-də işlədilir."""
    global _cached_guard, _cached_at, _cached_dev_mode
    now = _now_unix()

    if _cached_dev_mode and (now - _cached_at) < _GUARD_CACHE_TTL:
        return None

    if _cached_guard is not None and (now - _cached_at) < _GUARD_CACHE_TTL:
        if _cached_guard.claims.exp > now:
            return _cached_guard

    guard = ensure_license()
    _cached_guard = guard
    _cached_dev_mode = guard is None
    _cached_at = now
    return guard


def reset_cache() -> None:
    """In-memory cache-i sıfırla (test üçün və ya config dəyişəndə)."""
    global _cached_guard, _cached_at, _cached_dev_mode
    _cached_guard = None
    _cached_at = 0
    _cached_dev_mode = False


def license_status() -> dict:
    """Status bar / UI üçün license vəziyyəti.

    Heç vaxt exception atmır — status field-ə baxılmalıdır.
    """
    try:
        guard = ensure_license_cached()
    except LicenseError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": f"unexpected: {e}"}

    if guard is None:
        return {"status": "dev_mode", "message": "Dev mode (no license key)"}

    now = _now_unix()
    days_left = max(0, (guard.claims.exp - now) // 86400)
    return {
        "status": "active",
        "user_id": guard.claims.user_id,
        "subscription": guard.claims.subscription_status or "unknown",
        "days_left": int(days_left),
        "expires_at": guard.claims.exp,
        "fingerprint": guard.claims.fingerprint[:12] + "…",
    }

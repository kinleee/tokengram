"""License-gated enforcement check.

`enforcement_active(project_root)` returns True only when BOTH:
  1. .mla_enforcement.flag in project_root reads "on"
  2. A valid license is present (per license.py.ensure_license_cached)

Without a valid license the hooks treat enforcement as OFF — silent allow —
regardless of the flag file's contents.

PERF: license_valid() used to import cryptography + license module on
every hook invocation (~150-300 ms). Now a file-based cache stores the
last result with a TTL; we only re-import + re-validate when the cache
is stale or missing. The cache lives in ~/.tokengram/.license_gate_cache
so it's shared across hooks of all projects.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_INSTALL_ROOT = Path(__file__).resolve().parent.parent

# 5 minutes — long enough to shave per-hook cost, short enough that an
# admin-side subscription cancel propagates quickly.
_CACHE_TTL_SEC = 300
_CACHE_PATH = Path.home() / ".tokengram" / ".license_gate_cache"


def _flag_on(project_root: Path) -> bool:
    # Retry once on transient OSError — toggle_mla.py atomic-write
    # races with concurrent hook reads are now rare, but a Windows
    # sharing-violation can still flip enforcement OFF for one hook
    # invocation otherwise.
    for attempt in range(2):
        try:
            return (
                (project_root / ".mla_enforcement.flag")
                .read_text(encoding="utf-8")
                .strip()
                .lower()
                == "on"
            )
        except OSError:
            if attempt == 0:
                time.sleep(0.01)
    return False


def _read_cache() -> tuple[float, bool] | None:
    try:
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        return float(data["ts"]), bool(data["valid"])
    except (OSError, ValueError, KeyError):
        return None


def _write_cache(valid: bool) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_PATH.with_suffix(f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps({"ts": time.time(), "valid": valid}), encoding="utf-8")
        os.replace(tmp, _CACHE_PATH)
    except OSError:
        pass


def _import_license_module():
    # Wheel install path: tokengram.license (compiled .pyd)
    try:
        from tokengram import license as lic  # type: ignore

        return lic
    except ImportError:
        pass
    # Source / dev layout: license.py next to the hooks/ folder
    if str(_INSTALL_ROOT) not in sys.path:
        sys.path.insert(0, str(_INSTALL_ROOT))
    try:
        import license as lic  # type: ignore

        return lic
    except ImportError:
        # Leave a breadcrumb so silent-disabled enforcement is debuggable
        # without rewiring every hook to log on its own.
        try:
            (Path.home() / ".tokengram" / ".license_gate_import_error").write_text(
                f"{time.time()}\n", encoding="utf-8"
            )
        except OSError:
            pass
        return None


def _key_present() -> bool:
    """Açar faylının mövcudluğu — ucuz, şəbəkəsiz yoxlama.

    0.1.26-dan license.ensure_license_cached() açarsız halda serverə trial
    sorğusu göndərir (10-20s ola bilər). Hook yolunda buna yer yoxdur:
    açar yoxdursa enforcement onsuz da OFF-dur, ona görə şəbəkəyə çıxmadan
    dərhal False qaytarırıq. Trial-ı MCP server (ilk tool çağırışında) və ya
    extension başladır; açar faylı yaranan kimi hooks növbəti çağırışda
    (cache yazmırıq) normal yoxlama yoluna qayıdır.
    """
    if os.environ.get("MLA_LICENSE_KEY"):
        return True
    for d in (Path.home() / ".tokengram", Path.home() / ".mla"):
        try:
            if (d / "license_key.txt").exists():
                return True
        except OSError:
            pass
    return False


def license_valid() -> bool:
    """True only if a license key is present and currently active.

    Cached for _CACHE_TTL_SEC seconds — most hook invocations are O(1)
    file read; full validation runs at most every 5 minutes per machine.
    """
    if not _key_present():
        return False

    cache = _read_cache()
    if cache is not None:
        ts, valid = cache
        if time.time() - ts < _CACHE_TTL_SEC:
            return valid

    lic = _import_license_module()
    if lic is None:
        _write_cache(False)
        return False
    try:
        guard = lic.ensure_license_cached()
    except Exception:
        _write_cache(False)
        return False
    # guard is None means dev_mode (no key file). Treat as unlicensed.
    result = guard is not None
    _write_cache(result)
    return result


def project_root_from_env() -> Path:
    # Bütün digər hook-lar (və status bar) `project_root.find_project_root()`
    # walk-up işlədir. Eyni mənbə olsun deyə biz də ona delegate edirik —
    # əks halda monorepo subfolder-də enforcement flag fərqli qovluqdan oxunub
    # səssiz söndürülə bilərdi. Import alınmasa təhlükəsiz cwd fallback.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from project_root import find_project_root

        return find_project_root()
    except Exception:
        return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


def enforcement_active(project_root: Path | None = None) -> bool:
    root = project_root or project_root_from_env()
    return _flag_on(root) and license_valid()

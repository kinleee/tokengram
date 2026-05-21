"""License-gated enforcement check.

`enforcement_active(project_root)` returns True only when BOTH:
  1. .mla_enforcement.flag in project_root reads "on"
  2. A valid license is present (per license.py.ensure_license_cached)

Without a valid license the hooks treat enforcement as OFF — silent allow —
regardless of the flag file's contents.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_INSTALL_ROOT = Path(__file__).resolve().parent.parent


def _flag_on(project_root: Path) -> bool:
    try:
        return (
            (project_root / ".mla_enforcement.flag")
            .read_text(encoding="utf-8")
            .strip()
            .lower()
            == "on"
        )
    except OSError:
        return False


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
        return None


def license_valid() -> bool:
    """True only if a license key is present and currently active."""
    lic = _import_license_module()
    if lic is None:
        return False
    try:
        guard = lic.ensure_license_cached()
    except Exception:
        return False
    # guard is None means dev_mode (no key file). Treat as unlicensed.
    return guard is not None


def project_root_from_env() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


def enforcement_active(project_root: Path | None = None) -> bool:
    root = project_root or project_root_from_env()
    return _flag_on(root) and license_valid()

"""Localized user-facing strings for MLA Agent Python side.

Locale resolution order:
  1. `MLA_LANG` env var ("en", "az")
  2. `LANG` / `LC_ALL` / `LC_MESSAGES` (starts with "az" → az)
  3. Default: "en"

Usage:
    from i18n import tr
    print(tr("read_block", name="foo.ts", lines=104))

Missing keys fall back to the default locale (en); missing in both
returns the key itself, which is loud and easy to spot in dev.

No third-party deps so hooks can import this cheaply (~3ms cold).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict

_MESSAGES_DIR = Path(__file__).resolve().parent / "messages"
_DEFAULT = "en"
_SUPPORTED = ("en", "az")
_cache: Dict[str, Dict[str, str]] = {}


def _detect_locale() -> str:
    explicit = os.environ.get("MLA_LANG", "").strip().lower()
    if explicit in _SUPPORTED:
        return explicit
    for var in ("LANG", "LC_ALL", "LC_MESSAGES"):
        v = os.environ.get(var, "").lower()
        if v.startswith("az"):
            return "az"
    return _DEFAULT


def _load(locale: str) -> Dict[str, str]:
    if locale in _cache:
        return _cache[locale]
    path = _MESSAGES_DIR / f"{locale}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    _cache[locale] = data
    return data


def tr(key: str, **kwargs) -> str:
    """Return the localized string for `key`, formatted with `kwargs`.

    Falls back to the English string, then to `key` literal if missing
    everywhere. Format errors return the raw template (no crash).
    """
    locale = _detect_locale()
    template = _load(locale).get(key)
    if template is None and locale != _DEFAULT:
        template = _load(_DEFAULT).get(key)
    if template is None:
        return key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return template

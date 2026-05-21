#!/usr/bin/env python3
"""Auto-generated arch doc-u stdout-a yaz (slash command üçün)."""
import sys
from pathlib import Path

# Windows-un default stdout encoding-i cp1252-dir, Azərbaycan hərfləri
# print-də UnicodeEncodeError verir və skript exit 1 ilə yıxılır. UTF-8-ə force.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from i18n import tr

ARCH_DOC = Path(__file__).resolve().parent.parent / ".mla_arch.md"


def main() -> int:
    if not ARCH_DOC.exists():
        print(tr("arch_missing"))
        return 0
    print(ARCH_DOC.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Write the auto-generated arch doc to stdout (for the slash command)."""
import sys
from pathlib import Path

# Windows' default stdout encoding is cp1252; non-ASCII letters raise a
# UnicodeEncodeError in print and the script crashes with exit 1. Force UTF-8.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from i18n import tr
from project_root import find_project_root

# ARCH_DOC is created in the project root (arch_doc.py writes it there).
# Path(__file__).parent.parent pointed at the package folder — never matched.
ARCH_DOC = find_project_root() / ".mla_arch.md"


def main() -> int:
    if not ARCH_DOC.exists():
        print(tr("arch_missing"))
        return 0
    print(ARCH_DOC.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

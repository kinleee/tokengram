#!/usr/bin/env python3
"""Auto-generated arch doc-u stdout-a yaz (slash command üçün)."""
from pathlib import Path

ARCH_DOC = Path(__file__).resolve().parent.parent / ".mla_arch.md"


def main() -> int:
    if not ARCH_DOC.exists():
        print(
            "Arch doc hələ yaradılmayıb. "
            "Bir-iki search_code çağırışından sonra Stop hook bu faylı doldurar."
        )
        return 0
    print(ARCH_DOC.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

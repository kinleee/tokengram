#!/usr/bin/env python3
"""MLA Read-enforcement state-i .mla_enforcement.flag fayl ilə dəyişir."""
import os
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 2 or sys.argv[1].lower() not in ("on", "off"):
        print("Usage: toggle_mla.py [on|off]", file=sys.stderr)
        sys.exit(1)

    state = sys.argv[1].lower()
    project_root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    flag = project_root / ".mla_enforcement.flag"
    flag.write_text(state, encoding="utf-8")
    print(f"MLA enforcement: {state.upper()}")


if __name__ == "__main__":
    main()

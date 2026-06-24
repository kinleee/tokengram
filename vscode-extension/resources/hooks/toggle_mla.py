#!/usr/bin/env python3
"""Toggle the MLA Read-enforcement state via the .mla_enforcement.flag file."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_root import find_project_root
from atomic_write import write_atomic


def main():
    if len(sys.argv) != 2 or sys.argv[1].lower() not in ("on", "off"):
        print("Usage: toggle_mla.py [on|off]", file=sys.stderr)
        sys.exit(1)

    state = sys.argv[1].lower()
    flag = find_project_root() / ".mla_enforcement.flag"
    # Atomic write: so license_gate can't read a partial value in a read-during-write race.
    write_atomic(flag, state)
    print(f"MLA enforcement: {state.upper()}")


if __name__ == "__main__":
    main()

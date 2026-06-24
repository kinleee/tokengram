#!/usr/bin/env python3
"""Reset the savings history. The old one is moved to a backup."""
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_root import find_project_root


def main():
    history = find_project_root() / ".mla_savings_history.jsonl"

    if not history.exists() or history.stat().st_size == 0:
        history.touch()
        print("Savings history already empty.")
        return

    # Nanosecond-precision suffix: two resets in the same second don't overwrite.
    ts = time.strftime("%Y%m%d_%H%M%S") + f"_{time.time_ns() % 1_000_000_000:09d}"
    backup = history.parent / f".mla_savings_history.jsonl.bak.{ts}"

    shutil.copy(history, backup)
    history.write_text("", encoding="utf-8")
    print(f"Savings history reset. Backup: {backup.name}")

    # Clean up old backups — keep only the 2 most recent. Previously each reset
    # created a new .bak and never deleted one -> dozens of .bak files piled up in
    # the folder (messy, scares the user). Since the backup is only a safety net for
    # "I reset by accident", 2 copies are enough.
    backups = sorted(
        history.parent.glob(".mla_savings_history.jsonl.bak.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in backups[2:]:
        try:
            old.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()

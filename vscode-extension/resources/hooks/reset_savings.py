#!/usr/bin/env python3
"""Savings history-i sıfırla. Köhnəsi backup-a köçürülür."""
import os
import shutil
from datetime import datetime
from pathlib import Path


def main():
    project_root = Path(
        os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    ).resolve()
    history = project_root / ".mla_savings_history.jsonl"

    if not history.exists() or history.stat().st_size == 0:
        history.touch()
        print("Savings history already empty.")
        return

    backup = history.with_suffix(".jsonl.bak")
    if backup.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = history.parent / f".mla_savings_history.jsonl.bak.{ts}"

    shutil.copy(history, backup)
    history.write_text("", encoding="utf-8")
    print(f"Savings history reset. Backup: {backup.name}")


if __name__ == "__main__":
    main()

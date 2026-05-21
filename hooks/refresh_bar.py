#!/usr/bin/env python3
"""Status bar widget-i indi yenilə — history faylının mtime-ını yenilə.

Extension `.mla_savings_history.jsonl` faylını FileSystemWatcher ilə izləyir.
Bu skript mtime-ı yeniləyir, ekstension dərhal refresh çağırır.
"""
import os
from pathlib import Path


def main():
    project_root = Path(
        os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    ).resolve()
    history = project_root / ".mla_savings_history.jsonl"
    history.touch(exist_ok=True)
    print("Status bar refresh triggered")


if __name__ == "__main__":
    main()

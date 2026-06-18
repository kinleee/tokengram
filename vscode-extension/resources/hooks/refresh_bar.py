#!/usr/bin/env python3
"""Status bar widget-i indi yenilə — history faylının mtime-ını yenilə.

Extension `.mla_savings_history.jsonl` faylını FileSystemWatcher ilə izləyir.
Bu skript mtime-ı yeniləyir, ekstension dərhal refresh çağırır.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_root import find_project_root


def main():
    history = find_project_root() / ".mla_savings_history.jsonl"
    history.touch(exist_ok=True)
    # macOS FSEvents identical-mtime touch-ları debounce edir; forced utime.
    try:
        now = os.path.getmtime(history) + 0.001
        os.utime(history, (now, now))
    except OSError:
        pass
    print("Status bar refresh triggered", file=sys.stderr)


if __name__ == "__main__":
    main()

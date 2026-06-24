#!/usr/bin/env python3
"""Refresh the status bar widget now — update the history file's mtime.

The extension watches the `.mla_savings_history.jsonl` file with a FileSystemWatcher.
This script updates the mtime, and the extension triggers a refresh immediately.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_root import find_project_root


def main():
    history = find_project_root() / ".mla_savings_history.jsonl"
    history.touch(exist_ok=True)
    # macOS FSEvents debounces identical-mtime touches; forced utime.
    try:
        now = os.path.getmtime(history) + 0.001
        os.utime(history, (now, now))
    except OSError:
        pass
    print("Status bar refresh triggered", file=sys.stderr)


if __name__ == "__main__":
    main()

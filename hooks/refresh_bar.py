#!/usr/bin/env python3
"""Status bar widget-i indi yenilə — history faylının mtime-ını yenilə.

Extension `.mla_savings_history.jsonl` faylını FileSystemWatcher ilə izləyir.
Bu skript mtime-ı yeniləyir, ekstension dərhal refresh çağırır.
"""
from pathlib import Path


def main():
    history = Path(__file__).resolve().parent.parent / ".mla_savings_history.jsonl"
    history.touch(exist_ok=True)
    print("Status bar refresh triggered")


if __name__ == "__main__":
    main()

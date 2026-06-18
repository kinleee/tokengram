#!/usr/bin/env python3
"""Savings history-i sıfırla. Köhnəsi backup-a köçürülür."""
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

    # Nanosecond-precision suffix: eyni saniyədə 2 reset üzərinə yazmasın.
    ts = time.strftime("%Y%m%d_%H%M%S") + f"_{time.time_ns() % 1_000_000_000:09d}"
    backup = history.parent / f".mla_savings_history.jsonl.bak.{ts}"

    shutil.copy(history, backup)
    history.write_text("", encoding="utf-8")
    print(f"Savings history reset. Backup: {backup.name}")

    # Köhnə backup-ları təmizlə — yalnız ən təzə 2-ni saxla. Əvvəl hər reset yeni
    # .bak yaradırdı, heç vaxt silmirdi → qovluqda onlarla .bak yığılırdı
    # (səliqəsiz, useri qorxudur). Backup sırf "səhvən sıfırladım" üçün təhlükəsizlik
    # toru olduğundan 2 nüsxə kifayətdir.
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

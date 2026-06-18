"""Yazıçı kilidini tutub saxlayan köməkçi proses (canlı kilid testi üçün).

İstifadə: python tests/live_lock_holder.py <db_path> <saniye>
Kilidi alan kimi stdout-a "LOCKED" yazır, sonra verilən müddət saxlayır.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import db_guard

db = sys.argv[1]
hold = float(sys.argv[2])
lock = db_guard.acquire_writer_lock(db, wait_sec=5.0)
if lock is None:
    print("BUSY", flush=True)
    sys.exit(2)
print("LOCKED", flush=True)
time.sleep(hold)
lock.release()
print("RELEASED", flush=True)

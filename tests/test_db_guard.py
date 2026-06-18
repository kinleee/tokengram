"""db_guard testləri — 2026-06-11 korrupsiya insidentinin qoruma qatları.

Ssenarilər real insidentdən götürülüb:
- index_metadata.pickle ortasına zibil bayt düşüb (yarımçıq yazı)
- chroma.sqlite3 zədələnib
- rename mümkün olmayanda pending marker → növbəti start sağaldır
- iki proses eyni bazaya yazmağa çalışır (yazıçı kilidi)
- köhnə sidecar state təzə bazaya aid sayılır (generation)
"""
import json
import os
import pickle
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# DİQQƏT: repo kökündə tərtib olunmuş `db_guard.cp312-win_amd64.pyd` mövcuddur
# və adi `import db_guard` onu .py mənbəyindən ÜSTÜN yükləyir (CPython extension
# modulunu source-dan əvvəl seçir). O .pyd KÖHNƏ tərtibdir — split-brain orfan-lock
# fix-i (`_LEGACY_LOCK_DIR`/`_candidate_lock_dirs`) yoxdur. Wheel yenidən tərtib
# olunana qədər test mənbəyi DOĞRUDAN faylı (db_guard.py) yükləməlidir ki, dəyişiklik
# yoxlana bilsin. Buna görə .py-i fayl yolu ilə açıq import edirik (.pyd-i ötürürük).
import importlib.util as _ilu

_src = Path(__file__).parent.parent / "db_guard.py"
_spec = _ilu.spec_from_file_location("db_guard", _src)
db_guard = _ilu.module_from_spec(_spec)
sys.modules["db_guard"] = db_guard
_spec.loader.exec_module(db_guard)


# ============================================
# Köməkçilər — sintetik chroma_db qovluğu
# ============================================

def _make_valid_sqlite(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    con.execute("INSERT INTO t (v) VALUES ('x')")
    con.commit()
    con.close()


def _make_chroma_dir(root: Path, *, corrupt_pickle=False, corrupt_sqlite=False) -> Path:
    db = root / "chroma_db"
    seg = db / "3b4dcea5-c56f-4253-b9e4-3959529ffc75"
    seg.mkdir(parents=True)
    _make_valid_sqlite(db / "chroma.sqlite3")
    if corrupt_sqlite:
        # sqlite header-i poz — "file is not a database"
        data = bytearray((db / "chroma.sqlite3").read_bytes())
        data[0:16] = b"GARBAGEGARBAGE!!"
        (db / "chroma.sqlite3").write_bytes(bytes(data))

    payload = pickle.dumps({"ids": list(range(1000)), "labels": ["x"] * 1000})
    if corrupt_pickle:
        # Real insident: faylın ORTASINA zibil bayt (offset 637122 analoqu)
        mid = len(payload) // 2
        payload = payload[:mid] + b"\x6b\x00\xff\xfe" + payload[mid + 4:]
    (seg / "index_metadata.pickle").write_bytes(payload)
    return db


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Hər test öz preflight keşi və sidecar yolları ilə işləsin."""
    db_guard.reset_preflight_cache()
    monkeypatch.setattr(db_guard, "HEALTH_PATH", None)
    monkeypatch.setattr(db_guard, "_sidecar_paths", lambda: [
        tmp_path / ".bm25_index.pkl", tmp_path / ".file_hashes.json",
    ])
    yield
    db_guard.reset_preflight_cache()


# ============================================
# Bütövlük yoxlamaları
# ============================================

class TestIntegrityChecks:
    def test_valid_db_is_not_corrupt(self, tmp_path):
        db = _make_chroma_dir(tmp_path)
        assert db_guard.db_is_corrupt(db) is False

    def test_corrupt_pickle_detected(self, tmp_path):
        db = _make_chroma_dir(tmp_path, corrupt_pickle=True)
        assert db_guard.db_is_corrupt(db) is True

    def test_corrupt_sqlite_detected(self, tmp_path):
        db = _make_chroma_dir(tmp_path, corrupt_sqlite=True)
        assert db_guard.db_is_corrupt(db) is True

    def test_truncated_pickle_detected(self, tmp_path):
        db = _make_chroma_dir(tmp_path)
        p = next(db.glob("*/index_metadata.pickle"))
        p.write_bytes(p.read_bytes()[: len(p.read_bytes()) // 2])
        assert db_guard.db_is_corrupt(db) is True

    def test_missing_db_is_not_corrupt(self, tmp_path):
        assert db_guard.db_is_corrupt(tmp_path / "yoxdur") is False


# ============================================
# Pre-flight + karantin
# ============================================

class TestPreflight:
    def test_healthy_db_passes(self, tmp_path):
        db = _make_chroma_dir(tmp_path)
        assert db_guard.preflight_check_and_heal(db) == "ok"
        assert db.exists()

    def test_corrupt_db_quarantined(self, tmp_path):
        db = _make_chroma_dir(tmp_path, corrupt_pickle=True)
        assert db_guard.preflight_check_and_heal(db) == "healed"
        assert not db.exists()
        backups = list(tmp_path.glob("chroma_db.corrupt-*"))
        assert len(backups) == 1
        # Zədəli data silinmir — backup-da qalır
        assert (backups[0] / "chroma.sqlite3").exists()

    def test_sidecars_move_with_quarantine(self, tmp_path):
        db = _make_chroma_dir(tmp_path, corrupt_pickle=True)
        (tmp_path / ".bm25_index.pkl").write_bytes(b"old-bm25")
        (tmp_path / ".file_hashes.json").write_text("{}", encoding="utf-8")
        assert db_guard.preflight_check_and_heal(db) == "healed"
        backup = next(tmp_path.glob("chroma_db.corrupt-*"))
        assert (backup / ".bm25_index.pkl").exists()
        assert (backup / ".file_hashes.json").exists()
        assert not (tmp_path / ".bm25_index.pkl").exists()

    def test_pending_marker_completes_on_next_start(self, tmp_path):
        db = _make_chroma_dir(tmp_path)  # sağlam görünür...
        db_guard.mark_quarantine_pending(db)  # ...amma marker var
        assert db_guard.preflight_check_and_heal(db) == "healed"
        assert not db.exists()
        assert not (tmp_path / "chroma_db.quarantine_pending").exists()

    def test_result_is_cached_per_process(self, tmp_path):
        db = _make_chroma_dir(tmp_path)
        assert db_guard.preflight_check_and_heal(db) == "ok"
        # Keşlənib: zədə salsaq belə təkrar skan olmur (tool cağırışı sürəti)
        next(db.glob("*/index_metadata.pickle")).write_bytes(b"qarbage")
        assert db_guard.preflight_check_and_heal(db) == "ok"
        # Keş sıfırlanınca yenidən yoxlanır və sağaldır
        db_guard.reset_preflight_cache(db)
        assert db_guard.preflight_check_and_heal(db) == "healed"

    def test_health_event_written(self, tmp_path):
        db = _make_chroma_dir(tmp_path, corrupt_pickle=True)
        db_guard.preflight_check_and_heal(db)
        health = db_guard.read_health_event(db)
        assert health is not None
        assert health["event"] == "quarantined"


# ============================================
# Yazıçı kilidi
# ============================================

class TestWriterLock:
    def test_exclusive(self, tmp_path):
        db = tmp_path / "chroma_db"
        first = db_guard.acquire_writer_lock(db, wait_sec=0.0)
        assert first is not None
        assert db_guard.acquire_writer_lock(db, wait_sec=0.0) is None
        first.release()
        second = db_guard.acquire_writer_lock(db, wait_sec=0.0)
        assert second is not None
        second.release()

    def test_wait_succeeds_after_release(self, tmp_path):
        import threading
        db = tmp_path / "chroma_db"
        first = db_guard.acquire_writer_lock(db, wait_sec=0.0)
        threading.Timer(0.6, first.release).start()
        second = db_guard.acquire_writer_lock(db, wait_sec=5.0, poll=0.2)
        assert second is not None
        second.release()

    def test_context_manager_releases(self, tmp_path):
        db = tmp_path / "chroma_db"
        with db_guard.acquire_writer_lock(db, wait_sec=0.0):
            assert not db_guard.writer_lock_is_free(db)
        assert db_guard.writer_lock_is_free(db)

    def test_lock_file_outside_db_dir(self, tmp_path):
        """Kilid faylı bazanın İÇİNDƏ olsa, karantin rename-i ona ilişərdi."""
        db = tmp_path / "chroma_db"
        lock = db_guard.acquire_writer_lock(db, wait_sec=0.0)
        try:
            assert not str(db_guard._lock_path(db)).startswith(str(db) + os.sep)
        finally:
            lock.release()


# ============================================
# clear_stale_locks — ölü-pid kilid + orfan .tmp təmizliyi (2026-06-16)
# ============================================

class TestClearStaleLocks:
    @staticmethod
    def _dead_pid() -> int:
        """Dərhal bitən proses → onun pid-i artıq ölüdür (recycle riski cüzi)."""
        if os.name == "nt":
            p = subprocess.Popen(["cmd", "/c", "exit"])
        else:
            p = subprocess.Popen(["true"])
        p.wait()
        return p.pid

    def test_dead_lock_and_orphan_tmp_removed(self, tmp_path):
        db = tmp_path / "chroma_db"
        dead = self._dead_pid()
        dpath = db_guard._drainer_lock_path(db)
        wpath = db_guard._lock_path(db)
        dpath.write_text(json.dumps({"pid": dead, "ts": time.time()}), encoding="utf-8")
        wpath.write_text(json.dumps({"pid": dead, "ts": time.time()}), encoding="utf-8")
        # Kəsilmiş `os.replace`-dən qalan orfan atomik-yazı temp faylı:
        orphan = dpath.parent / (dpath.name + f".tmp.{dead}")
        orphan.write_text("partial", encoding="utf-8")

        cleared = db_guard.clear_stale_locks(db)

        assert not dpath.exists(), "ölü-pid drainer lock silinməli idi"
        assert not wpath.exists(), "ölü-pid writer lock silinməli idi"
        assert not orphan.exists(), "orfan .tmp.<deadpid> silinməli idi"
        assert orphan.name in cleared

    def test_live_lock_and_own_orphan_preserved(self, tmp_path):
        db = tmp_path / "chroma_db"
        dpath = db_guard._drainer_lock_path(db)
        # CANLI sahib (bu proses) — kilidə TOXUNMA:
        dpath.write_text(json.dumps({"pid": os.getpid(), "ts": time.time()}), encoding="utf-8")
        own_orphan = dpath.parent / (dpath.name + f".tmp.{os.getpid()}")
        own_orphan.write_text("partial", encoding="utf-8")

        db_guard.clear_stale_locks(db)

        assert dpath.exists(), "canlı sahibin kilidi qalmalı idi"
        assert own_orphan.exists(), "öz prosesimizin .tmp-i qalmalı idi"

    def test_dead_lock_in_legacy_dir_is_cleared(self, tmp_path, monkeypatch):
        """Split-brain (2026-06-17): köhnə paket qovluğunda qalan ölü-pid lock
        + orfan .tmp kanonik db verilsə də süpürülməlidir."""
        db = tmp_path / "chroma_db"          # kanonik (config) yolu
        legacy = tmp_path / "legacy_pkg"     # köhnə paket qovluğu
        legacy.mkdir()
        monkeypatch.setattr(db_guard, "_LEGACY_LOCK_DIR", legacy)

        dead = self._dead_pid()
        wlock = legacy / db_guard._LOCK_FILENAME
        wlock.write_text(json.dumps({"pid": dead, "ts": time.time()}), encoding="utf-8")
        orphan = legacy / (db_guard._DRAINER_LOCK_FILENAME + f".tmp.{dead}")
        orphan.write_text("partial", encoding="utf-8")

        cleared = db_guard.clear_stale_locks(db)

        assert not wlock.exists(), "köhnə qovluqdakı ölü-pid lock silinməli idi"
        assert not orphan.exists(), "köhnə qovluqdakı orfan .tmp silinməli idi"
        assert wlock.name in cleared

    def test_live_lock_in_legacy_dir_is_preserved(self, tmp_path, monkeypatch):
        """Köhnə qovluqda CANLI sahibin (bu proses) kilidinə TOXUNMA."""
        db = tmp_path / "chroma_db"
        legacy = tmp_path / "legacy_pkg"
        legacy.mkdir()
        monkeypatch.setattr(db_guard, "_LEGACY_LOCK_DIR", legacy)

        wlock = legacy / db_guard._LOCK_FILENAME
        wlock.write_text(json.dumps({"pid": os.getpid(), "ts": time.time()}), encoding="utf-8")

        db_guard.clear_stale_locks(db)

        assert wlock.exists(), "köhnə qovluqda canlı kilid qalmalı idi"

    def test_candidate_dirs_deduped_when_legacy_equals_canonical(self, tmp_path, monkeypatch):
        """Kanonik parent köhnə qovluqla eyni olanda dublikat qovluq olmamalı."""
        db = tmp_path / "chroma_db"
        canonical_parent = db_guard._lock_path(db).parent
        monkeypatch.setattr(db_guard, "_LEGACY_LOCK_DIR", canonical_parent)
        dirs = db_guard._candidate_lock_dirs(db)
        assert len(dirs) == 1


# ============================================
# Generation — sidecar ↔ baza bağlılığı
# ============================================

class TestGeneration:
    def test_stable_within_same_db(self, tmp_path):
        db = tmp_path / "chroma_db"
        g1 = db_guard.current_generation(db)
        g2 = db_guard.current_generation(db)
        assert g1 == g2 and g1 != "unknown"

    def test_changes_after_recreate(self, tmp_path):
        import shutil
        db = tmp_path / "chroma_db"
        g1 = db_guard.current_generation(db)
        shutil.rmtree(db)
        g2 = db_guard.current_generation(db)
        assert g1 != g2

    def test_generation_moves_with_quarantine(self, tmp_path):
        db = _make_chroma_dir(tmp_path, corrupt_pickle=True)
        g1 = db_guard.current_generation(db)
        db_guard.preflight_check_and_heal(db)
        g2 = db_guard.current_generation(db)
        assert g1 != g2


# ============================================
# Timeout-lu probe
# ============================================

class TestBoundedProbe:
    def test_fast_fn_returns_value(self):
        assert db_guard.run_with_timeout(lambda: 42, 5.0) == 42

    def test_slow_fn_times_out(self):
        t0 = time.monotonic()
        r = db_guard.run_with_timeout(lambda: time.sleep(30), 0.5)
        assert r is db_guard.PROBE_TIMEOUT
        assert time.monotonic() - t0 < 2.0

    def test_exception_propagates(self):
        with pytest.raises(ValueError):
            db_guard.run_with_timeout(lambda: (_ for _ in ()).throw(ValueError("x")), 5.0)

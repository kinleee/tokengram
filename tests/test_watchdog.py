"""No-progress self-heal watchdog + leader-election (single-instance) testləri.

2026-06-17: server-tərəf avtomatik bərpa — donmuş server özünü restart edir,
spawn-storm-da yalnız lider model yükləyir. Bax [[reindex_livelock_dual_server]].

KRİTİK: repo kökündə `db_guard.cp312-win_amd64.pyd` MƏNBƏ `.py`-nı shadow edir
(`import db_guard` .pyd yükləyir). Yeni `should_self_heal`/`acquire_leader_lock`
yalnız mənbədədir → testlər MƏNBƏNİ force-load etməlidir (rebuild-dən əvvəl).
"""
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_py(name):
    """<root>/<name>.py-nı yüklə, yanındakı .pyd-ni İGNORE edərək."""
    path = ROOT / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # intra-module 'import db_guard' da .py-a düşsün
    spec.loader.exec_module(mod)
    return mod


db_guard = _load_py("db_guard")
S = db_guard._DRAINER_STALE_SEC


# ============================================
# should_self_heal — saf predikat (yan-təsirsiz)
# ============================================

class TestShouldSelfHeal:
    @pytest.mark.parametrize("lock_held,age,cli,stale,expect", [
        (True,  S + 1,    False, S,    True),   # 1 donmuş sahib → restart
        (True,  60.0,     False, 150,  False),  # 2 soyuq-yük grace (60s < 150)
        (True,  S,        False, S,    False),  # 3 sərhəd: strict > only
        (True,  S + 0.01, False, S,    True),   # 4 sərhəddən bir az yuxarı
        (False, 99999,    False, S,    False),  # 5 kilid bizdə deyil/idle → heç vaxt
        (True,  S + 999,  True,  S,    False),  # 6 reindex CLI istisna
        (True,  2.0,      False, S,    False),  # 7 yenicə irəlilədi
        (True,  10.0,     False, 5.0,  True),   # 8 custom stale_sec
    ])
    def test_predicate(self, lock_held, age, cli, stale, expect):
        assert db_guard.should_self_heal(
            lock_held=lock_held, last_progress_age=age,
            in_cli_mode=cli, stale_sec=stale,
        ) is expect


# ============================================
# acquire_leader_lock — tək-lider seçimi
# ============================================

class TestLeaderLock:
    def test_first_caller_becomes_leader(self, tmp_path):
        db = tmp_path / "chroma_db"
        lock = db_guard.acquire_leader_lock(db, wait_sec=0.0)
        assert lock is not None
        lock.release()

    def test_second_distinct_process_is_follower(self, tmp_path, monkeypatch):
        db = tmp_path / "chroma_db"
        held = db_guard.acquire_leader_lock(db, wait_sec=0.0)  # bu proses lider
        assert held is not None
        # "başqa canlı proses" gözü: getpid-i dəyiş → re-entrant qısa-yol işləməsin
        monkeypatch.setattr(db_guard.os, "getpid", lambda: db_guard.os.getppid())
        follower = db_guard.acquire_leader_lock(db, wait_sec=0.0)
        assert follower is None  # canlı + fresh lider var → follower olur
        held.release()

    def test_stale_leader_is_taken_over(self, tmp_path, monkeypatch):
        db = tmp_path / "chroma_db"
        monkeypatch.setattr(db_guard, "_DRAINER_STALE_SEC", 0.5)
        # canlı amma KÖHNƏ heartbeat-li lider əkv et (ppid canlıdır, ts 100s köhnə)
        lf = db_guard._leader_lock_path(db)
        lf.parent.mkdir(parents=True, exist_ok=True)
        lf.write_text(json.dumps({"pid": db_guard.os.getppid(), "ts": time.time() - 100}),
                      encoding="utf-8")
        seized = db_guard.acquire_leader_lock(db, wait_sec=1.0)
        assert seized is not None  # stale lider preempt olundu (HEÇ KİM öldürülmədi)
        seized.release()


# ============================================
# _read_lock_owner — REAL tutulan writer.lock-u offset-1-dən oxuyur
# ============================================

class TestReadHeldWriterLock:
    def test_owner_readable_while_lock_held(self, tmp_path):
        """Canlı writer.lock 0-cı baytı kilidləyir; sahib JSON offset 1-dədir.
        Watchdog "kilid bizdədirmi" üçün bunu oxuya bilməlidir."""
        db = tmp_path / "chroma_db"
        # Ayrı proses writer kilidini tutur (.pyd db_guard — format eynidir).
        code = (
            "import sys, time, os; "
            f"sys.path.insert(0, r'{ROOT}'); import db_guard; "
            f"l = db_guard.acquire_writer_lock(r'{db}', wait_sec=0.0); "
            "print(os.getpid(), flush=True); time.sleep(6); l.release()"
        )
        holder = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            holder_pid = int(holder.stdout.readline().strip())
            time.sleep(1.0)  # kilidin alındığına əmin ol
            lock_file = db_guard._lock_path(db)
            # Bütün faylı oxumaq 0-cı bayta görə fail olmalı (kilid sübutu):
            whole_ok = True
            try:
                json.loads(lock_file.read_text(encoding="utf-8"))
            except Exception:
                whole_ok = False
            assert whole_ok is False, "0-cı bayt kilidli olmalıydı"
            # _read_lock_owner offset-1 fallback ilə sahibi oxuyur:
            owner = db_guard._read_lock_owner(lock_file)
            assert owner is not None and owner.get("pid") == holder_pid
        finally:
            holder.terminate()
            holder.wait(timeout=5)

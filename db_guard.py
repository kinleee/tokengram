"""
============================================
db_guard.py — ChromaDB bütövlük qoruması
============================================
2026-06-11 korrupsiya insidentinin dərsi: index_metadata.pickle yarımçıq
yazılanda Chroma açılışda 3 dəqiqəlik daxili retry-a girir, fresh=true belə
kömək etmir (sıfırlamadan əvvəl köhnə kolleksiyanı açmağa məcburdur) və
rename başqa prosesin handle-ları üzündən mümkün olmur.

Bu modul üç müstəqil qoruma verir:

1. PRE-FLIGHT (preflight_check_and_heal): baza AÇILMAZDAN ƏVVƏL pickle
   opcode-ları (pickletools.genops — class import etmədən) və sqlite
   quick_check yoxlanır. Zədə taparsa qovluq dərhal karantinə köçürülür —
   hələ heç bir handle açıq deyil, rename həmişə mümkündür.

2. KARANTİN + PENDING MARKER (quarantine_db / mark_quarantine_pending):
   işləmə zamanı aşkarlanan zədədə rename mümkün olmasa (başqa proses
   faylı tutub) `.quarantine_pending` marker yazılır — NÖVBƏTİ start
   pre-flight-da əvvəlcə karantini bitirir. "Əl ilə cərrahiyyə" bitir:
   restart özü sağaldır.

3. YAZIÇI KİLİDİ (acquire_writer_lock): eyni bazaya proses-arası tək
   yazıçı. OS kilidi proses öləndə özü buraxır — köhnəlmiş kilid problemi
   yoxdur. Korrupsiyanın əsas mənbəyi (paralel proses yazısı) bağlanır.

Əlavə: GENERATION faylı (current_generation) — chroma_db hər yenidən
yaradılanda yeni UUID alır; hash-store və BM25 pickle bu UUID-ə bağlanır,
beləcə köhnə sidecar state təzə/boş bazaya "hər şey indekslidir" deyə bilmir.
"""
from __future__ import annotations

import json
import logging
import os
import pickletools
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# mcp_server import zamanı PROJECT_ROOT-a yönləndirir; default baza yanında.
HEALTH_PATH: Optional[Path] = None

_GENERATION_FILENAME = ".tg_generation"
_PENDING_MARKER_SUFFIX = ".quarantine_pending"
_LOCK_FILENAME = ".tokengram.writer.lock"
# Tək-drainer koordinasiya kilidi — writer lock-dan AYRI fayl. writer_lock
# aşağı-səviyyəli per-write qorumadır; bu isə "kim bulk indeksləyir" qərarını
# verir ki, çox server instansı (çox pəncərə) + reindex CLI eyni anda yazıb
# livelock yaratmasın (2026-06-14 insidenti).
_DRAINER_LOCK_FILENAME = ".tokengram.drainer.lock"
# Drainer kilidini tutan proses bu qədər saniyə heartbeat yeniləməsə "ilişib"
# sayılır və kilid avtomatik götürülür (2026-06-16 insidenti: sahib proses
# canlı idi amma irəliləmirdi — 8GB RAM-da paging/hung — OS byte-lock əbədi
# tutulurdu, Re-index 120s timeout → exit 4, "bir dəqiqə gözlə" heç işləmirdi).
# Soyuq model yükü ~60s çəkir, ona görə eşik onun xeyli üstündədir: canlı-yavaş
# drainer-i yanlışlıqla ilişmiş saymamaq üçün.
_DRAINER_STALE_SEC = 150.0

# Lider kilidi — "kim model warmup edir + bulk drain edir" qərarını verir.
# drainer/writer lock-dan AYRI: məqsəd çox server instansı (spawn-storm) RAM
# təzyiqini azaltmaq — yalnız LİDER embedding modelini eager yükləyir (~700MB),
# followerlər yüngül qalır (lazy model, fast-mode search). AdvisoryLock heartbeat
# semantikası (sahib ölü/stale → növbəti follower lider olur, HEÇ KİM öldürülmür).
_LEADER_LOCK_FILENAME = ".tokengram.leader.lock"

# Pre-flight prosesdə bir dəfə kifayətdir (eyni qovluq üçün) — tool
# çağırışlarını təkrar skanla yavaşlatmamaq üçün nəticə yadda saxlanır.
_preflight_done: dict = {}
_preflight_lock = threading.Lock()


# ============================================
# SAĞLAMLIQ HADİSƏLƏRİ (status bar / get_stats üçün)
# ============================================

def _health_file(db_path: Path) -> Path:
    return HEALTH_PATH if HEALTH_PATH is not None else db_path.parent / ".mla_db_health.json"


def write_health_event(db_path, event: str, detail: str = "") -> None:
    """Son özünü-sağaltma hadisəsini atomik qeyd et (get_stats oxuyur)."""
    try:
        target = _health_file(Path(db_path))
        payload = json.dumps(
            {"ts": time.time(), "event": event, "detail": detail, "pid": os.getpid()},
            ensure_ascii=False,
        )
        tmp = target.with_suffix(target.suffix + f".tmp.{os.getpid()}")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        pass


def read_health_event(db_path) -> Optional[dict]:
    try:
        target = _health_file(Path(db_path))
        if not target.exists():
            return None
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ============================================
# GENERATION — sidecar state-i baza nəslinə bağla
# ============================================

def current_generation(db_path) -> str:
    """Bazanın nəsil UUID-i. Qovluq yenidən yarananda dəyişir.

    Hash-store/BM25 pickle öz daxilində bu dəyəri saxlayır; uyğunsuzluq =
    sidecar köhnə bazaya aiddir → atılır (səssiz boş-indeks bug-ı qarşısı).
    """
    db_path = Path(db_path)
    gen_file = db_path / _GENERATION_FILENAME
    try:
        if gen_file.exists():
            gen = gen_file.read_text(encoding="utf-8").strip()
            if gen:
                return gen
        db_path.mkdir(parents=True, exist_ok=True)
        gen = uuid.uuid4().hex
        tmp = gen_file.with_suffix(f".tmp.{os.getpid()}")
        tmp.write_text(gen, encoding="utf-8")
        os.replace(tmp, gen_file)
        return gen
    except OSError:
        return "unknown"


# ============================================
# BÜTÖVLÜK YOXLAMALARI
# ============================================

def _pickle_is_valid(path: Path) -> bool:
    """Pickle faylını CLASS İMPORT ETMƏDƏN opcode səviyyəsində yoxla.

    pickletools.genops zədəni (unsupported opcode, yarımçıq fayl) tapır,
    amma chromadb daxili siniflərini import etməyə çalışmır — yalnış
    pozitiv vermir. 1MB fayl üçün ~1s.
    """
    try:
        with open(path, "rb") as f:
            for _ in pickletools.genops(f):
                pass
        return True
    except Exception as e:
        logger.error(f"Zədəli pickle aşkarlandı: {path} — {type(e).__name__}: {e}")
        return False


def _sqlite_is_valid(path: Path) -> bool:
    """sqlite quick_check — read-only, qısa timeout.

    Başqa sağlam proses bazanı kilidləyibsə yoxlaya bilmərik → OK sayırıq
    (canlı istifadə zədə demək deyil); yalnız aşkar "malformed" zədə sayılır.
    """
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=3)
        try:
            row = con.execute("PRAGMA quick_check(1)").fetchone()
            return bool(row) and str(row[0]).lower() == "ok"
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        m = str(e).lower()
        if "locked" in m or "unable to open" in m:
            return True
        logger.error(f"Zədəli sqlite aşkarlandı: {path} — {e}")
        return False
    except OSError:
        return True


def db_is_corrupt(db_path) -> bool:
    """Diski yoxla: pickle seqmentləri + sqlite. Heç nə AÇMIR (handle yox)."""
    db_path = Path(db_path)
    if not db_path.exists():
        return False
    sqlite_file = db_path / "chroma.sqlite3"
    if sqlite_file.exists() and not _sqlite_is_valid(sqlite_file):
        return True
    for seg_pickle in db_path.glob("*/index_metadata.pickle"):
        if not _pickle_is_valid(seg_pickle):
            return True
    return False


# ============================================
# KARANTİN
# ============================================

def _sidecar_paths() -> list:
    """Baza ilə birgə köçürülməli sidecar state faylları."""
    try:
        import config
        return [Path(config.BM25_INDEX_PATH), Path(config.HASH_STORE_PATH)]
    except Exception:
        return []


def quarantine_db(db_path) -> Optional[Path]:
    """Zədəli qovluğu `<ad>.corrupt-<vaxt>`-a köçür, sidecar-ları içinə at.

    Uğurda yeni karantin yolunu, rename mümkün olmazsa (başqa proses handle
    saxlayır) None qaytarır — o halda pending marker yazılır və NÖVBƏTİ
    start pre-flight-da karantini bitirir.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        _clear_pending_marker(db_path)
        return db_path  # köçürüləcək bir şey yoxdur — sağlam vəziyyət
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = db_path.with_name(f"{db_path.name}.corrupt-{stamp}")
    n = 1
    while target.exists():
        n += 1
        target = db_path.with_name(f"{db_path.name}.corrupt-{stamp}-{n}")

    moved = False
    for attempt in range(5):
        try:
            os.rename(str(db_path), str(target))
            moved = True
            break
        except OSError:
            time.sleep(0.5 * (attempt + 1))
    if not moved:
        mark_quarantine_pending(db_path)
        write_health_event(
            db_path, "quarantine_pending",
            "rename mümkün olmadı (başqa proses handle saxlayır); "
            "növbəti açılışda avtomatik karantin ediləcək",
        )
        logger.error(
            "❌ Zədəli baza köçürülə bilmədi — başqa proses açıq saxlayır. "
            "Marker yazıldı: növbəti açılış özü sağaldacaq."
        )
        return None

    # Sidecar-lar (hash store, BM25 pickle) köhnə bazaya aiddir — birgə köçür.
    for sc in _sidecar_paths():
        try:
            if sc.exists():
                os.replace(str(sc), str(target / sc.name))
        except OSError:
            try:
                sc.unlink()
            except OSError:
                pass
    _clear_pending_marker(db_path)
    write_health_event(
        db_path, "quarantined",
        f"zədəli baza karantinə alındı: {target.name}; təmiz baza qurulacaq",
    )
    logger.warning(f"🛡️ Zədəli baza karantinə alındı: {target}")
    return target


def _pending_marker(db_path: Path) -> Path:
    return db_path.with_name(db_path.name + _PENDING_MARKER_SUFFIX)


def mark_quarantine_pending(db_path) -> None:
    try:
        _pending_marker(Path(db_path)).write_text(
            json.dumps({"ts": time.time(), "pid": os.getpid()}), encoding="utf-8"
        )
    except OSError:
        pass


def _clear_pending_marker(db_path: Path) -> None:
    try:
        _pending_marker(db_path).unlink(missing_ok=True)
    except OSError:
        pass


# ============================================
# PRE-FLIGHT — açılışdan əvvəl yoxla + sağalt
# ============================================

def preflight_check_and_heal(db_path) -> str:
    """ChromaDB AÇILMAZDAN ƏVVƏL çağır. Qaytarır:
      "ok"          — baza sağlamdır (və ya yoxdur, təzə yaranacaq)
      "healed"      — zədə tapıldı, karantinə alındı, təmiz başlana bilər
      "heal_failed" — zədə var amma köçürülə bilmədi (marker yazıldı)

    Proses daxilində eyni qovluq üçün nəticə keşlənir (tool çağırışlarını
    yavaşlatmamaq üçün); karantin/yenidənqurma halında keş təmizlənir.
    """
    db_path = Path(db_path)
    key = str(db_path)
    with _preflight_lock:
        if key in _preflight_done:
            return _preflight_done[key]

        result = "ok"
        # Əvvəlki sessiyadan yarımçıq qalan karantin?
        if _pending_marker(db_path).exists():
            logger.warning("⏳ Yarımçıq karantin markeri tapıldı — tamamlanır...")
            result = "healed" if quarantine_db(db_path) is not None else "heal_failed"
        elif db_is_corrupt(db_path):
            logger.warning("🛡️ Pre-flight: baza zədəlidir — karantinə alınır...")
            result = "healed" if quarantine_db(db_path) is not None else "heal_failed"

        # "heal_failed" KEŞLƏNMİR: maneə törədən proses hər an ölə bilər —
        # növbəti cəhd karantini tamamlaya bilsin. "ok"/"healed" keşlənir.
        if result != "heal_failed":
            _preflight_done[key] = result
        return result


def reset_preflight_cache(db_path=None) -> None:
    """Karantin/yenidənqurmadan sonra keşi sıfırla (yeni qovluq yenidən yoxlansın)."""
    with _preflight_lock:
        if db_path is None:
            _preflight_done.clear()
        else:
            _preflight_done.pop(str(Path(db_path)), None)


# ============================================
# PROSES-ARASI YAZIÇI KİLİDİ
# ============================================

class WriterLock:
    """OS-səviyyəli eksklüziv kilid. Proses öləndə OS özü buraxır."""

    def __init__(self, fd: int, path: Path):
        self._fd = fd
        self._path = path
        self.acquired_at = time.time()

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def _lock_path(db_path) -> Path:
    # Kilid faylı bazanın YANINDA (içində yox) — karantin rename-i
    # açıq kilid faylına ilişməsin.
    return Path(db_path).parent / _LOCK_FILENAME


def _drainer_lock_path(db_path) -> Path:
    return Path(db_path).parent / _DRAINER_LOCK_FILENAME


def _leader_lock_path(db_path) -> Path:
    return Path(db_path).parent / _LEADER_LOCK_FILENAME


# Köhnə wheel-lər kilid fayllarını paket qovluğuna (`tokengram/`) qoyurdu
# (os.path.dirname(__file__)). Yeni kod config-dən gələn kanonik yolu işlədir.
# Split-brain: ölü prosesin qalıq lock-u köhnə paket qovluğunda qala bilər və
# tək-qovluq scan onu HEÇ vaxt görmür (2026-06-17: pid 9444 ölü, writer.lock
# `tokengram/`-də qalıb, canlı lider 3 gün stall). Buna görə təmizləməni HƏM
# kanonik, HƏM köhnə paket qovluğunda aparırıq.
_LEGACY_LOCK_DIR = Path(__file__).resolve().parent


def _candidate_lock_dirs(db_path) -> list:
    """Kilid fayllarının ola biləcəyi qovluqlar: kanonik (config) parent +
    köhnə paket qovluğu. Dedup edilir; köhnə qovluq yalnız mövcuddursa və
    kanonikdən fərqlidirsə əlavə olunur. Discovery/walk YOXDUR — tam iki yol."""
    dirs = [_lock_path(db_path).parent]
    try:
        legacy = _LEGACY_LOCK_DIR
        if legacy.exists() and legacy.resolve() != dirs[0].resolve():
            dirs.append(legacy)
    except OSError:
        pass
    return dirs


def should_self_heal(
    *,
    lock_held: bool,
    last_progress_age: float,
    in_cli_mode: bool,
    stale_sec: float = _DRAINER_STALE_SEC,
) -> bool:
    """Saf qərar: bu server donmuş yazıçıdır → özünü restart etməlidir?

    Yan-təsirsiz (os._exit ETMİR) ki, izolə unit-test oluna bilsin. Watchdog
    thread-i bunu çağırır, True olarsa health_event + os._exit edir.

    True YALNIZ: bizim proses writer kilidini tutur (`lock_held`) VƏ
    `stale_sec`-dən çox müddətdir indeks irəliləmir (`last_progress_age`) VƏ
    bu one-shot reindex CLI deyil (`in_cli_mode`). Boş/kilidsiz server heç
    vaxt tetiklənmir; soyuq model yükü (~60s) `stale_sec`-dən (150s) aşağıdır.
    """
    if in_cli_mode:
        return False
    if not lock_held:
        return False
    return last_progress_age > stale_sec


def _acquire_lock(lock_file: Path, wait_sec: float, poll: float) -> Optional[WriterLock]:
    """OS-səviyyəli eksklüziv kilidi `lock_file` üzərində al (writer + drainer
    üçün ortaq nüvə). wait_sec=0 → bir cəhd; >0 → bu qədər gözlə, alınmasa None."""
    deadline = time.monotonic() + wait_sec
    while True:
        fd = None
        try:
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o644)
            if sys.platform == "win32":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Kilid alındı — diaqnostika üçün sahibini yaz (best-effort).
            try:
                info = json.dumps({"pid": os.getpid(), "ts": time.time()}).encode()
                os.lseek(fd, 1, os.SEEK_SET)
                os.write(fd, info + b" " * 8)
            except OSError:
                pass
            return WriterLock(fd, lock_file)
        except OSError:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if time.monotonic() >= deadline:
                return None
            time.sleep(poll)


def acquire_writer_lock(db_path, wait_sec: float = 0.0, poll: float = 0.5) -> Optional[WriterLock]:
    """Bazaya proses-arası tək-yazıçı kilidi al (per-write aşağı-səviyyə qoruma).

    wait_sec=0 → bir cəhd (fon işçisi üçün: məşğuldursa bu dövrü ötür).
    wait_sec>0 → bu qədər gözlə, alınmasa None (tool aydın mesaj qaytarır).
    """
    return _acquire_lock(_lock_path(db_path), wait_sec, poll)


def _pid_alive(pid: int) -> bool:
    """PID hələ canlıdırmı? (öz spawn etdiyimiz python prosesləri üçün).

    DİQQƏT: Windows-da `os.kill(pid, 0)` prosesi TerminateProcess ilə ÖLDÜRÜR
    (sig=0 "any other value" sayılır) — liveness üçün istifadə ETMƏ. Bunun
    əvəzinə OpenProcess + GetExitCodeProcess (STILL_ACTIVE=259) yoxlayırıq.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = ctypes.c_void_p
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        PROCESS_QUERY_INFORMATION = 0x0400
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            h = k32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
        if not h:
            return False  # proses yoxdur (öz user-imizin prosesi üçün access var)
        try:
            STILL_ACTIVE = 259
            code = ctypes.c_ulong()
            if k32.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True  # sorğu alınmadı — ehtiyatlı: canlı say
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True


def _read_lock_owner(path: Path) -> Optional[dict]:
    """Kilid faylından {pid, ts} oxu. Köhnə OS-lock formatında json offset 1-də
    (öncə padding/null) yazılırdı — `{`...`}` aralığını tapıb parse edirik ki,
    həm köhnə, həm yeni format oxunsun."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if 0 <= start < end:
            return json.loads(raw[start:end + 1])
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    # CANLI writer kilidi yalnız 0-cı baytı kilidləyir (_acquire_lock: locking(1)),
    # owner JSON isə offset 1-dədir. Bütün faylı oxumaq kilidli 0-cı bayta görə
    # fail olur (öz prosesimizin başqa handle-ı üçün də) — ona görə offset 1-dən
    # oxuyuruq ki, TUTULAN writer kilidinin sahibini (məs. self-heal watchdog
    # "bu kilid bizdədirmi?" yoxlaması üçün) ala bilək.
    try:
        with open(path, "rb") as f:
            f.seek(1)
            raw = f.read(256).decode("utf-8", errors="replace")
        start = raw.find("{")
        end = raw.rfind("}")
        if 0 <= start < end:
            return json.loads(raw[start:end + 1])
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return None


class AdvisoryLock:
    """Heartbeat əsaslı məsləhət (advisory) kilidi — OS byte-lock DEYİL.

    Sahibi faylına {pid, ts} yazır və işlədikcə `touch()` ilə ts-i təzələyir.
    Başqa proses faylı oxuyur: sahib ölübsə VƏ YA heartbeat _DRAINER_STALE_SEC-
    dən köhnədirsə (sahib ilişib) kilidi özünə götürür.

    KORRUPSİYA RİSKİ YOXDUR — heç bir proses öldürülmür: real ChromaDB yazısı
    hələ də ayrıca OS `writer_lock` altında serialize olunur. İki drainer eyni
    anda işləsə belə, atomik `pending→processing` rename + per-file writer_lock
    onları təhlükəsiz ayırır. Bu kilid yalnız churn/livelock-un qarşısını alan
    optimizasiyadır — korrupsiya qoruması yox.
    """

    def __init__(self, path: Path):
        self._path = path
        self.acquired_at = time.time()

    def touch(self) -> None:
        """Heartbeat ts-ini təzələ (atomik tmp + replace — torn read olmaz)."""
        try:
            payload = json.dumps({"pid": os.getpid(), "ts": time.time()})
            tmp = self._path.with_suffix(self._path.suffix + f".tmp.{os.getpid()}")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError:
            pass

    def release(self) -> None:
        """Yalnız hələ BİZ sahibiksə faylı sil (başqası götürübsə toxunma)."""
        try:
            info = _read_lock_owner(self._path)
            if info and info.get("pid") == os.getpid():
                self._path.unlink(missing_ok=True)
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def acquire_drainer_lock(db_path, wait_sec: float = 0.0, poll: float = 0.5) -> Optional[AdvisoryLock]:
    """Tək-drainer koordinasiya kilidi — HEARTBEAT əsaslı advisory kilid.

    Məqsəd: çox server instansı (çox IDE pəncərəsi) + manual reindex CLI
    arasında eyni anda yalnız bir bulk yazıcı olsun (churn/livelock qarşısı).

    Niyə OS byte-lock DEYİL (2026-06-16 insidenti): köhnə drainer kilidi OS
    byte-lock idi. Sahib proses ölsə OS onu buraxırdı, AMMA sahib canlı-amma-
    ilişmiş olanda (8GB RAM-da paging, model-yükü hangı, livelock) kilid əbədi
    tutulurdu — heç kim əvəz edə bilmirdi, Re-index 120s gözləyib exit 4 verirdi
    ("Another process is still indexing"), "bir dəqiqə sonra cəhd et" HEÇ VAXT
    işləmirdi. İndi: sahib ölübsə və ya heartbeat köhnədirsə kilid avtomatik
    götürülür. Heç bir proses öldürülmür (bax AdvisoryLock).
    """
    path = _drainer_lock_path(db_path)
    deadline = time.monotonic() + wait_sec
    while True:
        info = _read_lock_owner(path)
        free = info is None
        reason = ""
        if info is not None:
            holder = info.get("pid")
            ts = info.get("ts", 0)
            if holder == os.getpid():
                free = True  # re-entrant — özümüz tuturuq
            elif not _pid_alive(holder):
                free = True  # sahib çıxıb — NORMAL təmizlik, log yox (reason="")
            else:
                try:
                    age = time.time() - float(ts)
                except (TypeError, ValueError):
                    age = _DRAINER_STALE_SEC + 1  # parse olmadı — köhnə say
                if age > _DRAINER_STALE_SEC:
                    # Sahib CANLI amma irəliləmir = əsl anomaliya → qeyd et.
                    free, reason = True, (
                        f"sahib (PID {holder}) {int(age)}s heartbeat yeniləmir "
                        f"— ilişib sayılır"
                    )
        if free:
            lock = AdvisoryLock(path)
            lock.touch()  # {bizim pid, indi} yaz
            # Race təsdiqi: iki proses eyni anda boş görüb yazsa, sonuncu udur.
            # Biz udmadıqsa busy davam edirik. (İki drainer benign olsa da,
            # gərəksiz iş yaratmamaq üçün.)
            confirm = _read_lock_owner(path)
            if confirm and confirm.get("pid") == os.getpid():
                if reason:
                    write_health_event(
                        db_path, "stale_lock_recovered",
                        f"drainer kilidi avtomatik bərpa olundu: {reason}",
                    )
                    logger.warning("🩹 Drainer kilidi bərpa olundu: %s", reason)
                return lock
            # race uddurduq — busy kimi davam
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll)


def acquire_leader_lock(db_path, wait_sec: float = 0.0, poll: float = 0.5) -> Optional[AdvisoryLock]:
    """Lider kilidi — heartbeat advisory (acquire_drainer_lock-un qəsdən klonu).

    Ayrı saxlanır ki, döyüş-sınaqlı drainer koduna toxunmayaq. Yalnız LİDER
    embedding modelini eager yükləyir + bulk drain-ə "sahib"dir; sahib ölü/stale
    olarsa növbəti follower lideri götürür. HEÇ KİM öldürülmür (bax AdvisoryLock).
    Real DB yazısı hələ də ayrıca writer_lock + drainer_lock altında serialize
    olunur — bu kilid yalnız RAM optimizasiyasıdır (spawn-storm 3×700MB → 1×700MB).
    """
    path = _leader_lock_path(db_path)
    deadline = time.monotonic() + wait_sec
    while True:
        info = _read_lock_owner(path)
        free = info is None
        reason = ""
        if info is not None:
            holder = info.get("pid")
            ts = info.get("ts", 0)
            if holder == os.getpid():
                free = True  # re-entrant — özümüz tuturuq
            elif not _pid_alive(holder):
                free = True  # sahib çıxıb — NORMAL təmizlik
            else:
                try:
                    age = time.time() - float(ts)
                except (TypeError, ValueError):
                    age = _DRAINER_STALE_SEC + 1
                if age > _DRAINER_STALE_SEC:
                    free, reason = True, (
                        f"lider (PID {holder}) {int(age)}s heartbeat yeniləmir "
                        f"— ilişib sayılır"
                    )
        if free:
            lock = AdvisoryLock(path)
            lock.touch()
            confirm = _read_lock_owner(path)
            if confirm and confirm.get("pid") == os.getpid():
                if reason:
                    write_health_event(
                        db_path, "leader_recovered",
                        f"lider kilidi avtomatik bərpa olundu: {reason}",
                    )
                    logger.warning("🩹 Lider kilidi bərpa olundu: %s", reason)
                return lock
            # race uddurduq — busy davam
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll)


def clear_stale_locks(db_path) -> list:
    """Ölü prosesin qoyub getdiyi kilid FAYLLARINI sil (writer + drainer).

    YALNIZ sahib PID ölübsə silir — canlı sahibin faylına TOXUNMUR. Ölü
    prosesin OS byte-lock-u onsuz da buraxılıb; bu funksiya qalıq faylı
    təmizləyir ki, diaqnostika və kod yolları köhnə sahibi səhvən canlı
    sanmasın (2026-06-16: pid 21480 ölü idi, amma hər iki lock faylı onun
    adı ilə qalmışdı və user təkrar-təkrar "başqa proses indeksləyir"
    görürdü). Server start-da və reindex CLI başında çağırılır.

    Qaytarır: təmizlənən faylların adları.
    """
    cleared = []
    lock_names = (_LOCK_FILENAME, _DRAINER_LOCK_FILENAME, _LEADER_LOCK_FILENAME)
    # Həm kanonik, həm köhnə paket qovluğunu süpür (split-brain qalıq lock-ları).
    for parent in _candidate_lock_dirs(db_path):
        for name in lock_names:
            lf = parent / name
            try:
                if not lf.exists():
                    continue
                info = _read_lock_owner(lf)
                if info is None:
                    continue
                holder = info.get("pid")
                if holder == os.getpid():
                    continue  # özümüz — toxunma
                if not _pid_alive(holder):
                    lf.unlink(missing_ok=True)
                    cleared.append(lf.name)
            except OSError:
                pass
        # Orfan atomik-yazı temp faylları: <kilid>.tmp.<pid> (AdvisoryLock.touch /
        # write_health_event-də kəsilmiş `os.replace`). Sahib PID ölübsə sil — canlıya
        # TOXUNMA. 2026-06-16: `.tokengram.drainer.lock.tmp.19788` (ölü pid) belə qalıq
        # idi; əsl lock faylı oxunmasa da litter qalır və diaqnostikanı çaşdırır.
        for base in lock_names:
            try:
                orphans = list(parent.glob(base + ".tmp.*"))
            except OSError:
                orphans = []
            for tmp in orphans:
                try:
                    pid = int(tmp.name.rsplit(".", 1)[-1])
                except (ValueError, IndexError):
                    continue
                if pid == os.getpid():
                    continue
                if not _pid_alive(pid):
                    try:
                        tmp.unlink(missing_ok=True)
                        cleared.append(tmp.name)
                    except OSError:
                        pass
    if cleared:
        logger.info("🧹 Ölü proses kilid faylları təmizləndi: %s", cleared)
    return cleared


def writer_lock_is_free(db_path) -> bool:
    """Kilidin boş olub-olmadığını yoxla (almadan). get_stats üçün."""
    probe = acquire_writer_lock(db_path, wait_sec=0.0)
    if probe is None:
        return False
    probe.release()
    return True


# ============================================
# TIMEOUT-LU PROBE
# ============================================

PROBE_TIMEOUT = object()  # sentinel


def run_with_timeout(fn, timeout_sec: float):
    """fn()-i daemon thread-də işlət; vaxt bitsə PROBE_TIMEOUT qaytar.

    Chroma-nın daxili Rust retry dövrü probe sorğusunu dəqiqələrlə saxlaya
    bilir (2026-06-11: 150+ saniyə). Bu sarğı aşkarlamanı məhdudlaşdırır:
    asılı qalan probe = zədəli baza kimi qəbul olunur.
    """
    box = {}
    def _runner():
        try:
            box["result"] = fn()
        except BaseException as e:  # probe xətası nəticədir, udulmur
            box["error"] = e
    t = threading.Thread(target=_runner, name="tg-bounded-probe", daemon=True)
    t.start()
    t.join(timeout_sec)
    if t.is_alive():
        return PROBE_TIMEOUT
    if "error" in box:
        raise box["error"]
    return box.get("result")

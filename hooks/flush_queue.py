"""
============================================
hooks/flush_queue.py — Stop hook (task-sonu drain trigger)
============================================
DİZAYN (2026-06-19 yenidən-qurma): tək oxuyucu, task-sonu trigger.

Claude task gedişində dəyişən fayllar `queue_change.py` (PostToolUse) tərəfindən
`.mla_pending.txt`-ə YIĞILIR — modeli yükləmir, ucuzdur. Task BİTƏNDƏ bu Stop
hook işə düşür və növbəni BİR DƏFƏ drenləyir.

İKİ YOL (toqquşma drainer kilidi ilə fiziki olaraq qarşısı alınır):
  1. İSTİ (norma): `.mla_drain.now` marker-ini buraxırıq. İşləyən MCP server
     onu görüb növbəni öz isti modeli ilə drenləyir (soyuq-start yox, RAM-da
     ikinci model yox). Server marker-i siləndə biz onu görüb TEZ qayıdırıq —
     Claude donmur. İndeksləmə hook qayıtdıqdan SONRA fonda davam edir.
  2. SOYUQ (fallback): server işləmirsə (marker silinmir), drainer kilidini
     alıb növbəni ELƏ BURADA soyuq drenləyirik. Bu, köhnə watchdog/self-heal
     qülləsini əvəz edən YEGANƏ self-heal mexanizmidir.

Köhnə dizayn: bu hook HƏMİŞƏ soyuq indeksləyirdi (hər task ~3s + ikinci model)
VƏ eyni anda MCP server davamlı poll-drain edirdi → iki yazıçı yarışı.
"""

import sys
import time
from pathlib import Path

# Import path-larını həm install root, həm hook-un yanına əlavə et.
_INSTALL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_INSTALL_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_root import find_project_root

PROJECT_ROOT = find_project_root()
QUEUE_FILE = PROJECT_ROOT / ".mla_pending.txt"
PROCESSING_FILE = PROJECT_ROOT / ".mla_pending.processing"
DRAIN_MARKER = PROJECT_ROOT / ".mla_drain.now"

# İsti server-ə marker-i istehlak etməyə nə qədər vaxt veririk. Server hər ~1s
# poll edir; 2.4s = ~2 dövr. Bu müddətdə marker silinsə → server işi götürdü,
# tez qayıdırıq. Silinməsə → server yoxdur → soyuq fallback.
_GRACE_SEC = 2.4
_GRACE_POLL = 0.3


def _queue_is_empty() -> bool:
    for qf in (QUEUE_FILE, PROCESSING_FILE):
        try:
            if any(line.strip() for line in qf.read_text(encoding="utf-8").splitlines()):
                return False
        except OSError:
            pass
    return True


def _read_queue_paths() -> list:
    """Pending + processing-i oxu, dedup et, sıranı qoru."""
    seen = set()
    paths = []
    for qf in (PROCESSING_FILE, QUEUE_FILE):  # processing əvvəl (köhnə qalıq)
        try:
            raw = qf.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in raw.splitlines():
            line = line.strip()
            key = line.lower()
            if line and key not in seen:
                seen.add(key)
                paths.append(line)
    return paths


def _clear_queue() -> None:
    for qf in (QUEUE_FILE, PROCESSING_FILE):
        try:
            qf.unlink(missing_ok=True)
        except OSError:
            pass


def _cold_drain() -> int:
    """Server işləmir — növbəni ELƏ BURADA soyuq drenlə (drainer kilidi altında)."""
    paths = _read_queue_paths()
    if not paths:
        _clear_queue()
        DRAIN_MARKER.unlink(missing_ok=True)
        return 0

    # Ağır importlar — yalnız soyuq fallback lazım olanda.
    # Installed (wheel) layout bu modulları YALNIZ `tokengram` paketi altında
    # quraşdırır — top-level `config`/`vector_store` tapılmır. `import tokengram`
    # paket qovluğunu sys.path-a qoyur (tokengram/__init__._ensure_pkg_dir...),
    # ondan sonra top-level adlar işləyir. Dev (top-level mənbə) layout-unda
    # `import tokengram` zərərsiz fail olur, adlar repo kökündən gəlir.
    try:
        try:
            import tokengram  # noqa: F401  (yan təsir: pkg dir-i sys.path-a salır)
        except ImportError:
            pass
        from vector_store import ChromaVectorStore
        from document_loader import _CHUNKER_MAP, _fallback_chunk
        import config
        import db_guard
    except ImportError as e:
        sys.stderr.write(f"[tokengram flush] import xətası: {e}\n")
        return 0

    # Drainer kilidi: işləyən server və ya manual reindex eyni anda chroma-ya
    # yazmasın. Sahib ölü/stale-dirsə db_guard avtomatik götürür (self-heal).
    dlock = db_guard.acquire_drainer_lock(config.CHROMA_DB_PATH, wait_sec=3.0)
    if dlock is None:
        # Canlı bir yazıçı (server/reindex) kilidi tutur — o, işi görəcək.
        # Növbəyə TOXUNMURUQ (itki olmasın); marker-i də saxlayırıq ki, server
        # hələ görməyibsə növbəti poll-da götürsün.
        return 0

    indexed = deleted = skipped = errors = 0
    try:
        store = ChromaVectorStore()
        for i, path_str in enumerate(paths):
            p = Path(path_str)
            try:
                if not p.exists():
                    store.delete_file(str(p))
                    deleted += 1
                    continue
                if p.suffix not in config.SUPPORTED_EXTENSIONS:
                    skipped += 1
                    continue
                if any(part in config.EXCLUDED_DIRS for part in p.parts):
                    skipped += 1
                    continue
                if any(p.name.startswith(pat) for pat in config.EXCLUDED_FILE_PATTERNS):
                    skipped += 1
                    continue
                source = p.read_text(encoding="utf-8", errors="replace")
                if not source.strip():
                    skipped += 1
                    continue
                chunker = _CHUNKER_MAP.get(p.suffix, _fallback_chunk)
                chunks = chunker(source, str(p))
                if chunks and store.index_file(str(p), chunks):
                    indexed += 1
                else:
                    skipped += 1
            except Exception as e:
                sys.stderr.write(f"[tokengram flush] {p.name}: {e}\n")
                errors += 1
            if i % 5 == 0:
                dlock.touch()  # uzun drain-də kilid stale sayılmasın
    except Exception as e:
        sys.stderr.write(f"[tokengram flush] ChromaDB xətası: {e}\n")
        return 0
    finally:
        dlock.release()

    _clear_queue()
    DRAIN_MARKER.unlink(missing_ok=True)
    sys.stderr.write(
        f"[tokengram] re-index (soyuq): {indexed} yenilik, {deleted} silinmə, "
        f"{skipped} keçildi, {errors} xəta\n"
    )
    return 0


def main() -> int:
    # Stdin oxuyub atırıq — Stop hook-da maraqlı bir şey yoxdur.
    try:
        sys.stdin.read()
    except Exception:
        pass

    # Görüləsi iş yoxdursa dərhal çıx (marker da buraxma).
    if _queue_is_empty():
        return 0

    # İSTİ YOL: marker burax, işləyən server-ə bir neçə poll-luq fürsət ver.
    try:
        DRAIN_MARKER.write_text("", encoding="utf-8")
    except OSError:
        # Marker yazıla bilmir — birbaşa soyuq drenlə.
        return _cold_drain()

    deadline = time.time() + _GRACE_SEC
    while time.time() < deadline:
        time.sleep(_GRACE_POLL)
        if not DRAIN_MARKER.exists():
            # Server marker-i istehlak etdi → o, isti modeli ilə drenləyir.
            # Tez qayıdırıq; indeksləmə fonda davam edir (Claude donmur).
            return 0

    # Marker hələ də qalır → marker-i istehlak edən işləyən server yoxdur.
    # SOYUQ fallback: özümüz drenləyirik (server ölübsə yeganə self-heal yolu).
    return _cold_drain()


if __name__ == "__main__":
    sys.exit(main())

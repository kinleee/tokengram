"""
============================================
mcp_server.py — Claude Code üçün MCP Server
============================================
MƏRHƏLƏ 8a: FastMCP ilə RAG sistemini Claude Code-a
alət (tool) kimi açır.

Açılan alətlər (yalnız retrieval — heç bir LLM çağırışı yoxdur):
- search_code(query, top_k)        — Hybrid axtarış (semantic + BM25 + reranker)
- index_directory(path, fresh)     — Layihəni indeksləşdir
- index_file(path)                 — Tək faylı re-index
- get_stats()                      — Baza statistikası
- route_project(path)              — Smart router məsləhəti

Bütün düşünmə işi Claude Code-un öz Claude-u tərəfindən edilir.
Bu server yalnız axtarış nəticələri qaytarır — API açarı LAZIM DEYİL.

İşlədilməsi:
    Claude Code başlayanda .mcp.json oxuyur və bu prosesi stdio
    ilə fork edir. Heç nəyi əl ilə işə salmaq lazım deyil.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Dict, Literal, Optional

from mcp.server.fastmcp import FastMCP

import config

# DİQQƏT: Ağır import-lar module-level-də olmalıdır.
# FastMCP sync tool-ları worker thread-də çağırır — orada lazy
# `from vector_store import ...` Python import lock-u ilə deadlock yaradır.
# Module-level import bu problemi tam həll edir.
from vector_store import ChromaVectorStore
from search_engine import HybridSearchEngine
from document_loader import _CHUNKER_MAP, _fallback_chunk, load_directory
from smart_router import SmartRouter, count_tokens

# Sessiya analytics — hər search_code çağırışı bura yazılır,
# Stop hook bunu oxuyur və qənaət hesabatı göstərir.
SESSION_LOG = Path(__file__).parent / ".mla_session_log.jsonl"

# PostToolUse hook-u (queue_change.py) bu fayla redaktə olunmuş yolları yazır.
# Fon işçisi (aşağıda) periodik olaraq dren edir və yenidən indeksləşdirir.
PENDING_QUEUE = Path(__file__).parent / ".mla_pending.txt"
PROCESSING_QUEUE = Path(__file__).parent / ".mla_pending.processing"

# Logging — stderr-ə (stdout MCP üçün rezerv olunub)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=__import__("sys").stderr,
)
logger = logging.getLogger("mcp-mla-agent")

mcp = FastMCP("mla-agent")


# ============================================
# LAZY-LOAD STATE
# ============================================
# MCP serverin ömrü boyu bu obyektlər bir dəfə qurulur.
# Beləcə hər alət çağırışında ChromaDB və embedding modeli
# yenidən yüklənmir.

_store = None
_engine = None

# Re-index əməliyyatları — həm tool çağırışları, həm də fon işçisi
# eyni ChromaDB-yə yazır. RLock paralel yazmanı sıralayır.
_index_lock = threading.RLock()


def _get_store():
    global _store
    if _store is None:
        logger.info("ChromaDB açılır...")
        _store = ChromaVectorStore()
    return _store


def _get_engine():
    global _engine
    if _engine is None:
        logger.info("HybridSearchEngine qurulur...")
        _engine = HybridSearchEngine(_get_store())
    return _engine


# ============================================
# FON YENİDƏN-İNDEKSLƏMƏ İŞÇİSİ
# ============================================
# Əvvəllər Stop hook (flush_queue.py) hər cavabdan sonra
# soyuq Python prosesi başladır, ChromaDB və embedding modelini
# təkrar yükləyirdi (~30-60s ilk fayl üçün, çoxlu fayl varsa
# 2-3 dəqiqə). Claude Code bu hook-u gözlədiyi üçün istifadəçi
# "Cogitating" donur deyə görürdü.
#
# İndi: MCP server canlıdır, modellər artıq RAM-dadır. Fon işçisi
# növbəni periodik dren edir — Stop hook isə dərhal çıxır.

# Bir drain dövründə işlənəcək maksimum fayl sayı. Daha böyük partiyaları
# növbəti dövrə yayır — `_index_lock`-un uzun müddət saxlanmasının qarşısını
# alır və `get_stats` kimi tool çağırışları bloklanmır.
MAX_FILES_PER_DRAIN = 20


def _filter_indexable(path_str: str) -> Optional[Path]:
    """Path-i layihəyə uyğunluğuna görə yoxla. None qaytarsa atılır."""
    try:
        p = Path(path_str)
    except (TypeError, ValueError):
        return None
    if p.suffix not in config.SUPPORTED_EXTENSIONS:
        return None
    if any(part in config.EXCLUDED_DIRS for part in p.parts):
        return None
    if any(p.name.startswith(pat) for pat in config.EXCLUDED_FILE_PATTERNS):
        return None
    return p


def _drain_pending_queue() -> int:
    """`.mla_pending.txt`-i atomik dren et və hər faylı yenidən indekslə.

    Eyni anda işləyən başqa drain-i nəzərə alaraq əvvəlcə fayl
    `.processing`-ə adlandırılır. Boş qayıdırsa heç nə etmir.

    Maksimum `MAX_FILES_PER_DRAIN` fayl bir dövrdə işlənir; qalanı
    `.processing`-də qalır və növbəti dövrdə davam edir.
    """
    if not PENDING_QUEUE.exists() and not PROCESSING_QUEUE.exists():
        return 0

    # Atomik təhvil: pending → processing. Başqa drain qabaqlayıbsa
    # rename uğursuz olur, bu drain tələsmir.
    try:
        if PENDING_QUEUE.exists():
            if PROCESSING_QUEUE.exists():
                # Əvvəlki drain çatmamışdır — pending-i ona əlavə edib silirik
                with open(PROCESSING_QUEUE, "a", encoding="utf-8") as out:
                    out.write(PENDING_QUEUE.read_text(encoding="utf-8"))
                PENDING_QUEUE.unlink(missing_ok=True)
            else:
                PENDING_QUEUE.rename(PROCESSING_QUEUE)
    except OSError:
        return 0

    try:
        raw = PROCESSING_QUEUE.read_text(encoding="utf-8").strip()
    except IOError:
        PROCESSING_QUEUE.unlink(missing_ok=True)
        return 0

    if not raw:
        PROCESSING_QUEUE.unlink(missing_ok=True)
        return 0

    seen = set()
    all_paths = []
    for line in raw.splitlines():
        line = line.strip()
        if line and line not in seen:
            seen.add(line)
            all_paths.append(line)

    # Bu dövrdə yalnız ilk MAX_FILES_PER_DRAIN-i götür, qalanını qoy
    batch = all_paths[:MAX_FILES_PER_DRAIN]
    leftover = all_paths[MAX_FILES_PER_DRAIN:]

    indexed = 0
    deleted = 0
    skipped = 0
    with _index_lock:
        store = _get_store()
        for path_str in batch:
            try:
                p_raw = Path(path_str)
                if not p_raw.exists():
                    # Silinib — supported olmasa belə bazadan təmizlə
                    store.delete_file(str(p_raw))
                    deleted += 1
                    continue
                p = _filter_indexable(path_str)
                if p is None:
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
                    logger.info(f"  ↻ {p.name} ({len(chunks)} chunk)")
                else:
                    skipped += 1
            except Exception as e:
                logger.error(f"Fon yenidən-indeksləmə xətası ({path_str}): {e}")

        if (indexed > 0 or deleted > 0) and _engine is not None:
            try:
                _engine.rebuild_bm25()
            except Exception as e:
                logger.warning(f"BM25 yenidən qurma xətası: {e}")

    # Qalanı varsa, processing-ə geri yaz; yoxsa sil
    if leftover:
        try:
            PROCESSING_QUEUE.write_text(
                "\n".join(leftover) + "\n", encoding="utf-8"
            )
        except IOError as e:
            logger.warning(f"Leftover yazılma xətası: {e}")
            PROCESSING_QUEUE.unlink(missing_ok=True)
    else:
        PROCESSING_QUEUE.unlink(missing_ok=True)

    if indexed or deleted or skipped:
        logger.info(
            f"📥 Fon dren batch: {indexed} indeks, {deleted} silinmə, "
            f"{skipped} atlanmış"
            + (f", {len(leftover)} qalıb" if leftover else "")
        )
    return indexed + deleted


_worker_stop_event = threading.Event()
_worker_thread: Optional[threading.Thread] = None


def _worker_loop(poll_interval: float = 2.0) -> None:
    """Növbəni periodik yoxlayan fon işçisi."""
    while not _worker_stop_event.is_set():
        try:
            _drain_pending_queue()
        except Exception as e:
            logger.error(f"Fon işçisi dövrü xətası: {e}")
        # `wait` iki funksiya görür: yatma + sürətli stop reaksiyası
        _worker_stop_event.wait(poll_interval)


def _recover_stale_processing_queue() -> None:
    """MCP server start-da əvvəlki seans yarıda qalmış `.processing`
    saxlaya bilər. Onu pending-ə geri qaytarırıq ki, yeni drainer dövrü
    onu normal qaydada işləsin."""
    if not PROCESSING_QUEUE.exists():
        return
    try:
        leftover = PROCESSING_QUEUE.read_text(encoding="utf-8")
    except IOError as e:
        logger.warning(f"Köhnə processing oxunmadı: {e}")
        return

    if not leftover.strip():
        PROCESSING_QUEUE.unlink(missing_ok=True)
        return

    try:
        with open(PENDING_QUEUE, "a", encoding="utf-8") as out:
            out.write(leftover)
        PROCESSING_QUEUE.unlink(missing_ok=True)
        n = sum(1 for line in leftover.splitlines() if line.strip())
        logger.info(f"🔄 Köhnə processing-dən {n} fayl pending-ə qaytarıldı")
    except IOError as e:
        logger.warning(f"Pending-ə qaytarılma xətası: {e}")


def _start_background_worker() -> None:
    """Fon yenidən-indeksləmə işçisini başlat (idempotent)."""
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    _recover_stale_processing_queue()
    _worker_thread = threading.Thread(
        target=_worker_loop,
        name="mla-reindex-worker",
        daemon=True,
    )
    _worker_thread.start()
    logger.info("🧵 Fon yenidən-indeksləmə işçisi başladı")


# ============================================
# DAXİLİ (BUİLTİN) FAYL İZLƏYİCİSİ
# ============================================
# Hooks-dan asılı olmadan işləyir — istənilən IDE-də (VS Code,
# Antigravity, Cursor) avtomatik re-index təmin edir. Mexanizm:
# watchdog FS hadisələrini izləyir, debounce edir, sonra yalnız
# `.mla_pending.txt` növbəsinə yazır. Yuxarıdakı `_drain_pending_queue`
# qalan işi görür — yəni bu watcher və hookları eyni pipeline-ı bölüşür
# (ikiqat re-index olmur, hash check + dedup mövcuddur).

_observer: Optional[object] = None  # watchdog.observers.Observer
_watcher_handler_lock = threading.Lock()


def _resolve_watch_directory() -> Optional[str]:
    """Hansı qovluq izlənəcək? Override > cwd > None."""
    override = config.WATCH_DIRECTORY_OVERRIDE
    if override:
        path = Path(override).expanduser().resolve()
        if path.exists() and path.is_dir():
            return str(path)
        logger.warning(f"MLA_WATCH_DIR mövcud deyil: {override}")
        return None

    cwd = Path(os.getcwd()).resolve()
    # Layihə kökü əvəzinə təsadüfən mla-agent-in özünü izləməyək
    if cwd == Path(__file__).resolve().parent:
        logger.info(
            "Watcher cwd mla-agent-in özüdür — bu adətən proyekt kökü deyil. "
            "MLA_WATCH_DIR ilə hədəf qovluğu göstərin."
        )
    return str(cwd)


def _append_to_pending_queue(paths: list) -> None:
    """Yolları `.mla_pending.txt`-ə əlavə et (drainer onu dren edəcək)."""
    if not paths:
        return
    try:
        with open(PENDING_QUEUE, "a", encoding="utf-8") as f:
            for p in paths:
                f.write(p + "\n")
    except IOError as e:
        logger.warning(f"Pending queue-ya yazıla bilmədi: {e}")


def _build_queueing_handler():
    """Watchdog handler — yalnız növbəyə yazır, indeksləmir."""
    from watchdog.events import FileSystemEventHandler

    class _Handler(FileSystemEventHandler):
        def __init__(self) -> None:
            super().__init__()
            self._pending: Dict[str, str] = {}
            self._lock = threading.Lock()
            self._timer: Optional[threading.Timer] = None

        @staticmethod
        def _is_supported(path: str) -> bool:
            p = Path(path)
            if any(part in config.EXCLUDED_DIRS for part in p.parts):
                return False
            if any(p.name.startswith(pat) for pat in config.EXCLUDED_FILE_PATTERNS):
                return False
            return p.suffix in config.SUPPORTED_EXTENSIONS

        def _schedule(self, path: str, event_type: str) -> None:
            with self._lock:
                self._pending[path] = event_type
                if self._timer is not None:
                    self._timer.cancel()
                self._timer = threading.Timer(
                    config.WATCHER_DEBOUNCE_SEC, self._flush
                )
                self._timer.daemon = True
                self._timer.start()

        def _flush(self) -> None:
            with self._lock:
                pending = list(self._pending.keys())
                self._pending.clear()
            if pending:
                _append_to_pending_queue(pending)
                logger.info(
                    f"👁️  {len(pending)} dəyişiklik növbəyə yazıldı"
                )

        def on_created(self, event) -> None:
            if event.is_directory or not self._is_supported(event.src_path):
                return
            self._schedule(event.src_path, "modified")

        def on_modified(self, event) -> None:
            if event.is_directory or not self._is_supported(event.src_path):
                return
            self._schedule(event.src_path, "modified")

        def on_deleted(self, event) -> None:
            if event.is_directory or not self._is_supported(event.src_path):
                return
            self._schedule(event.src_path, "deleted")

        def on_moved(self, event) -> None:
            if event.is_directory:
                return
            if self._is_supported(event.src_path):
                self._schedule(event.src_path, "deleted")
            if self._is_supported(getattr(event, "dest_path", "")):
                self._schedule(event.dest_path, "modified")

    return _Handler()


def _start_builtin_watcher() -> None:
    """Daxili watchdog izləyicisini başlat (idempotent, opsional)."""
    global _observer
    with _watcher_handler_lock:
        if _observer is not None:
            return

        if not config.ENABLE_BUILTIN_WATCHER:
            logger.info("Daxili watcher söndürülüb (MLA_DISABLE_WATCHER)")
            return

        watch_dir = _resolve_watch_directory()
        if not watch_dir:
            logger.warning("Watcher üçün izlənəcək qovluq tapılmadı")
            return

        try:
            from watchdog.observers import Observer
        except ImportError:
            logger.warning("watchdog paketi yoxdur — daxili watcher başlamır")
            return

        handler = _build_queueing_handler()
        observer = Observer()
        observer.schedule(handler, watch_dir, recursive=True)
        observer.start()
        _observer = observer
        logger.info(f"👁️  Daxili watcher başladı: {watch_dir}")


def _stop_builtin_watcher() -> None:
    """Daxili watcher-i təmiz dayandır."""
    global _observer
    with _watcher_handler_lock:
        if _observer is None:
            return
        try:
            _observer.stop()
            _observer.join(timeout=3)
        except Exception as e:
            logger.warning(f"Watcher dayandırma xətası: {e}")
        _observer = None


# ============================================
# ALƏTLƏR (TOOLS)
# ============================================

@mcp.tool()
def search_code(
    query: str,
    top_k: int = 4,
    mode: Literal["fast", "semantic", "rerank"] = "fast",
    file_type: Optional[str] = None,
) -> str:
    """Kod bazasında axtarış edir — 3 səviyyəli güc/RAM trade-off ilə.

    Args:
        query: Axtarış sualı (Azərbaycanca və ya İngiliscə)
        top_k: Qaytarılacaq nəticə sayı (default 4)
        mode: Axtarış səviyyəsi (default "fast"):
          - "fast":     yalnız BM25 keyword. ML yüklənmir. ~50ms.
                        Funksiya/sinif adı, fayl adı tipli sintaktik sorğulara idealdır.
          - "semantic": BM25 + embedding semantic. İlk çağırış 30-60s
                        (embedding modeli RAM-a yüklənir, +400-700 MB).
                        "Auth necə işləyir" tipli konseptual sorğulara.
          - "rerank":   semantic + cross-encoder reranker. İlk çağırış +30s
                        (reranker modeli RAM-a yüklənir, +200 MB).
                        Maksimum sıralanma keyfiyyəti.
        file_type: Filtr: ".py", ".sol", ".sql", ".md" və ya None
    """
    engine = _get_engine()

    if mode == "fast":
        # BM25-only — heç bir ML yüklənmir. Bu Tier 1.
        bm25_results = engine.bm25_index.search(query, top_k=top_k * 2)
        if file_type:
            bm25_results = [
                r for r in bm25_results
                if r.metadata.get("file_extension") == file_type
            ]
        results = bm25_results[:top_k]
        confidence = "BM25_ONLY"
    elif mode == "semantic":
        # Tier 2: BM25 + embedding (ML model yüklənir)
        results, confidence = engine.search(
            query, top_k=top_k, file_type=file_type, use_reranker=False
        )
    else:  # rerank
        # Tier 3: + cross-encoder reranker
        results, confidence = engine.search(
            query, top_k=top_k, file_type=file_type, use_reranker=True
        )

    if not results:
        _log_search(query, results, "")
        return "Heç bir uyğun kod tapılmadı."

    blocks = [f"Etibar: {confidence} (mode={mode})\n"]
    for i, r in enumerate(results, 1):
        blocks.append(
            f"--- Mənbə #{i}: {r.file_info} (skor: {r.score:.3f}) ---\n"
            f"{r.content}"
        )
    response = "\n\n".join(blocks)
    _log_search(query, results, response)
    return response


def _log_search(query: str, results, response_text: str) -> None:
    """Hər search_code çağırışını analytics üçün qeyd edir.

    Stop hook (savings_report.py) bunu oxuyaraq qənaət hesablayır.
    """
    try:
        # Bu çağırışın nəticəsində hansı unikal fayllar gəldi
        unique_files = {}
        for r in results:
            fp = r.metadata.get("file_path")
            if fp and fp not in unique_files:
                try:
                    content = Path(fp).read_text(encoding="utf-8", errors="replace")
                    unique_files[fp] = count_tokens(content)
                except Exception:
                    unique_files[fp] = 0

        entry = {
            "ts": time.time(),
            "query": query[:200],
            "files": unique_files,
            "actual_tokens": count_tokens(response_text),
        }
        with open(SESSION_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Session log yazıla bilmədi: {e}")


@mcp.tool()
def index_directory(path: str, fresh: bool = False) -> str:
    """Verilmiş qovluğu indeksləşdirir.

    Args:
        path: İndekslənəcək qovluğun mütləq yolu
        fresh: True olarsa, mövcud baza əvvəl sıfırlanır
    """
    directory = Path(path).resolve()
    if not directory.exists():
        return f"Xəta: Qovluq tapılmadı: {directory}"

    chunks = load_directory(str(directory))
    if not chunks:
        return "Xəbərdarlıq: Heç bir chunk yaradılmadı."

    with _index_lock:
        store = _get_store()
        if fresh:
            store.clear_collection()

        stats = store.index_documents(chunks)

        # Yeni fayllar gəldi → BM25-i yenidən qur
        if _engine is not None:
            _engine.rebuild_bm25()

    return (
        f"İndeksləmə tamamlandı.\n"
        f"  Qovluq: {directory}\n"
        f"  Chunk: {stats['indexed']} indekslənmiş, "
        f"{stats['errors']} xəta\n"
    )


@mcp.tool()
def index_file(path: str) -> str:
    """Tək faylı incremental indeksləşdirir (hash yoxlaması ilə).

    Args:
        path: Faylın mütləq yolu
    """
    p = Path(path)
    if not p.exists():
        return f"Xəta: Fayl tapılmadı: {p}"

    if p.suffix not in config.SUPPORTED_EXTENSIONS:
        return f"Atlandı: dəstəklənməyən uzantı ({p.suffix})"

    if any(part in config.EXCLUDED_DIRS for part in p.parts):
        return f"Atlandı: istisna edilən qovluqdadır"

    try:
        source = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Xəta: oxuma uğursuz: {e}"

    if not source.strip():
        return "Atlandı: boş fayl"

    chunker = _CHUNKER_MAP.get(p.suffix, _fallback_chunk)
    chunks = chunker(source, str(p))
    if not chunks:
        return "Atlandı: chunk yaradılmadı"

    with _index_lock:
        store = _get_store()
        changed = store.index_file(str(p), chunks)

        if changed and _engine is not None:
            _engine.rebuild_bm25()

    return (
        f"{'İndekslənildi' if changed else 'Dəyişiklik yox'}: {p.name} "
        f"({len(chunks)} chunk)"
    )


@mcp.tool()
def get_stats() -> str:
    """Vektor bazası statistikasını qaytarır."""
    store = _get_store()
    stats = store.get_stats()
    lines = ["Baza statistikası:"]
    for key, value in stats.items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


@mcp.tool()
def route_project(path: str) -> str:
    """Layihə ölçüsünə əsaslanan rejim tövsiyəsi.

    Args:
        path: Qiymətləndiriləcək qovluğun mütləq yolu
    """
    router = SmartRouter(path)
    return (
        f"{router.summary()}\n"
        f"  Tövsiyə olunan parametrlər: {router.search_params()}\n"
        f"  RAG istifadə: {router.should_use_rag()}"
    )


# ============================================
# ƏSAS GİRİŞ
# ============================================

if __name__ == "__main__":
    logger.info("MLA Agent MCP server başladı (stdio)")
    _start_background_worker()
    _start_builtin_watcher()
    try:
        mcp.run()
    finally:
        _stop_builtin_watcher()

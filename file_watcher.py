"""
============================================
file_watcher.py — Avtomatik Yenidən-İndeksləmə
============================================
MƏRHƏLƏ 6: watchdog ilə qovluğu izləyir; fayl
yaradılması/dəyişməsi/silinməsi olduqda yalnız
həmin faylı yenidən indeksləyir (incremental).

Xüsusiyyətlər:
- Debounce: 2 saniyə ərzində eyni faylın çoxsaylı save-ləri bir hadisə
- Yalnız dəstəklənən uzantılar (.py, .sol, .sql, .md)
- İstisna edilən qovluqlar avtomatik atlanır (chroma_db, .git, ...)
"""

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional

from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

import config
from document_loader import _CHUNKER_MAP, _fallback_chunk

logger = logging.getLogger(__name__)


def _is_supported(path: str) -> bool:
    """Bu fayl indekslənməyə uyğundurmu?"""
    p = Path(path)
    if any(part in config.EXCLUDED_DIRS for part in p.parts):
        return False
    return p.suffix in config.SUPPORTED_EXTENSIONS


def _chunk_file(path: str):
    """Faylı oxu və chunk-lara böl."""
    p = Path(path)
    try:
        source = p.read_text(encoding="utf-8", errors="replace")
        if not source.strip():
            return []
        chunker = _CHUNKER_MAP.get(p.suffix, _fallback_chunk)
        return chunker(source, str(p))
    except Exception as e:
        logger.error(f"Chunk xətası ({path}): {e}")
        return []


class _DebouncedHandler(FileSystemEventHandler):
    """Hadisələri toplayıb debounce ilə tətbiq edir."""

    def __init__(self, vector_store, on_change: Optional[Callable] = None):
        super().__init__()
        self.vector_store = vector_store
        self.on_change = on_change

        # path → (event_type, scheduled_time)
        self._pending: Dict[str, str] = {}
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None

    # ----- Watchdog hadisələri -----

    def on_created(self, event: FileSystemEvent):
        if event.is_directory or not _is_supported(event.src_path):
            return
        self._schedule(event.src_path, "modified")

    def on_modified(self, event: FileSystemEvent):
        if event.is_directory or not _is_supported(event.src_path):
            return
        self._schedule(event.src_path, "modified")

    def on_deleted(self, event: FileSystemEvent):
        if event.is_directory or not _is_supported(event.src_path):
            return
        self._schedule(event.src_path, "deleted")

    def on_moved(self, event: FileSystemEvent):
        # Köhnə faylı sil, yenisini əlavə et
        if not event.is_directory:
            if _is_supported(event.src_path):
                self._schedule(event.src_path, "deleted")
            if _is_supported(event.dest_path):
                self._schedule(event.dest_path, "modified")

    # ----- Debounce -----

    def _schedule(self, path: str, event_type: str):
        with self._lock:
            self._pending[path] = event_type
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(
                config.WATCHER_DEBOUNCE_SEC, self._flush
            )
            self._timer.daemon = True
            self._timer.start()

    def _flush(self):
        with self._lock:
            pending = dict(self._pending)
            self._pending.clear()

        if not pending:
            return

        for path, event_type in pending.items():
            try:
                if event_type == "deleted":
                    logger.info(f"🗑️  Silinmə aşkarlandı: {path}")
                    self.vector_store.delete_file(path)
                else:
                    logger.info(f"♻️  Dəyişmə aşkarlandı: {path}")
                    chunks = _chunk_file(path)
                    if chunks:
                        self.vector_store.index_file(path, chunks)
            except Exception as e:
                logger.error(f"Watcher tətbiq xətası ({path}): {e}")

        if self.on_change:
            try:
                self.on_change(list(pending.keys()))
            except Exception as e:
                logger.error(f"on_change callback xətası: {e}")


class FileWatcher:
    """Qovluq izləyicisi.

    İstifadə:
        watcher = FileWatcher("./my_project", vector_store)
        watcher.start()
        # ... bir müddət işlə ...
        watcher.stop()
    """

    def __init__(self, directory: str, vector_store, on_change=None):
        self.directory = str(Path(directory).resolve())
        self.vector_store = vector_store
        self.on_change = on_change
        self.observer: Optional[Observer] = None

    def start(self):
        """İzləməyə başla (qeyri-blok edici)."""
        if self.observer is not None:
            logger.warning("Watcher artıq işləyir")
            return

        handler = _DebouncedHandler(self.vector_store, self.on_change)
        self.observer = Observer()
        self.observer.schedule(handler, self.directory, recursive=True)
        self.observer.start()
        logger.info(f"👁️  Watcher başladı: {self.directory}")

    def stop(self):
        """İzləməyi dayandır."""
        if self.observer is None:
            return
        self.observer.stop()
        self.observer.join(timeout=5)
        self.observer = None
        logger.info("🛑 Watcher dayandı")

    def run_forever(self):
        """Bloklayan rejimdə işlə (Ctrl+C ilə dayandırın)."""
        self.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("⏸️  Ctrl+C aşkarlandı")
        finally:
            self.stop()

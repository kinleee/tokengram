"""
============================================
hooks/flush_queue.py — Stop hook (end-of-task drain trigger)
============================================
DESIGN (2026-06-19 rebuild): single reader, end-of-task trigger.

Files changed during a Claude task are COLLECTED into `.mla_pending.txt` by
`queue_change.py` (PostToolUse) — it doesn't load the model, it's cheap. When the
task ENDS this Stop hook fires and drains the queue ONCE.

TWO PATHS (collision is physically prevented by the drainer lock):
  1. WARM (normal): we drop the `.mla_drain.now` marker. A running MCP server
     sees it and drains the queue with its own warm model (no cold-start, no
     second model in RAM). When the server deletes the marker we see that and
     return QUICKLY — Claude doesn't freeze. Indexing continues in the
     background AFTER the hook returns.
  2. COLD (fallback): if the server isn't running (marker not deleted), we
     acquire the drainer lock and drain the queue COLD RIGHT HERE. This is the
     ONLY self-heal mechanism, replacing the old watchdog/self-heal tower.

Old design: this hook ALWAYS indexed cold (every task ~3s + a second model)
AND at the same time the MCP server continuously poll-drained → two-writer race.
"""

import sys
import time
from pathlib import Path

# Add import paths for both the install root and next to the hook.
_INSTALL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_INSTALL_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_root import find_project_root

PROJECT_ROOT = find_project_root()
QUEUE_FILE = PROJECT_ROOT / ".mla_pending.txt"
PROCESSING_FILE = PROJECT_ROOT / ".mla_pending.processing"
DRAIN_MARKER = PROJECT_ROOT / ".mla_drain.now"

# How long we give the warm server to consume the marker. The server now polls
# every ~0.25s (previously 1.0s), so the marker is usually deleted in ~0.25-0.5s.
# We dropped the poll to 0.1s so we return IMMEDIATELY once the marker is deleted —
# the Stop hook runs at the end of EVERY edit turn, and completing the turn waits
# on this hook, so this busy-wait is directly the end-of-turn latency the user
# sees. 1.5s ceiling = a window even if the server is briefly busy (then cold fallback).
_GRACE_SEC = 1.5
_GRACE_POLL = 0.1


def _queue_is_empty() -> bool:
    for qf in (QUEUE_FILE, PROCESSING_FILE):
        try:
            if any(line.strip() for line in qf.read_text(encoding="utf-8").splitlines()):
                return False
        except OSError:
            pass
    return True


def _read_queue_paths() -> list:
    """Read pending + processing, dedup, preserve order."""
    seen = set()
    paths = []
    for qf in (PROCESSING_FILE, QUEUE_FILE):  # processing first (old leftover)
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
    """Server isn't running — drain the queue COLD RIGHT HERE (under the drainer lock)."""
    paths = _read_queue_paths()
    if not paths:
        _clear_queue()
        DRAIN_MARKER.unlink(missing_ok=True)
        return 0

    # Heavy imports — only when the cold fallback is actually needed.
    # The installed (wheel) layout installs these modules ONLY under the
    # `tokengram` package — top-level `config`/`vector_store` aren't found.
    # `import tokengram` puts the package directory on sys.path
    # (tokengram/__init__._ensure_pkg_dir...), after which the top-level names
    # work. In the dev (top-level source) layout `import tokengram` fails
    # harmlessly and the names come from the repo root.
    try:
        try:
            import tokengram  # noqa: F401  (side effect: puts pkg dir on sys.path)
        except ImportError:
            pass
        from vector_store import ChromaVectorStore
        from document_loader import _CHUNKER_MAP, _fallback_chunk
        import config
        import db_guard
    except ImportError as e:
        sys.stderr.write(f"[tokengram flush] import error: {e}\n")
        return 0

    # Drainer lock: prevent a running server and a manual reindex from writing
    # to chroma at the same time. If the owner is dead/stale, db_guard takes it
    # over automatically (self-heal).
    dlock = db_guard.acquire_drainer_lock(config.CHROMA_DB_PATH, wait_sec=3.0)
    if dlock is None:
        # A live writer (server/reindex) holds the lock — it will do the work.
        # We DON'T TOUCH the queue (no loss); we also keep the marker so that if
        # the server hasn't seen it yet it picks it up on the next poll.
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
                dlock.touch()  # on a long drain, keep the lock from being considered stale
    except Exception as e:
        sys.stderr.write(f"[tokengram flush] ChromaDB error: {e}\n")
        return 0
    finally:
        dlock.release()

    _clear_queue()
    DRAIN_MARKER.unlink(missing_ok=True)
    sys.stderr.write(
        f"[tokengram] re-index (cold): {indexed} updated, {deleted} deleted, "
        f"{skipped} skipped, {errors} errors\n"
    )
    return 0


def main() -> int:
    # Read stdin and discard it — there's nothing interesting in the Stop hook.
    try:
        sys.stdin.read()
    except Exception:
        pass

    # If there's no work to do, exit immediately (don't even drop the marker).
    if _queue_is_empty():
        return 0

    # WARM PATH: drop the marker, give a running server a few polls' worth of opportunity.
    try:
        DRAIN_MARKER.write_text("", encoding="utf-8")
    except OSError:
        # The marker can't be written — drain cold directly.
        return _cold_drain()

    deadline = time.time() + _GRACE_SEC
    while time.time() < deadline:
        time.sleep(_GRACE_POLL)
        if not DRAIN_MARKER.exists():
            # The server consumed the marker → it's draining with its warm model.
            # We return quickly; indexing continues in the background (Claude doesn't freeze).
            return 0

    # The marker still remains → there's no running server consuming the marker.
    # COLD fallback: we drain it ourselves (the only self-heal path if the server is dead).
    return _cold_drain()


if __name__ == "__main__":
    sys.exit(main())

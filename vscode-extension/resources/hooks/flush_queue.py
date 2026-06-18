"""
============================================
hooks/flush_queue.py — Manual növbə dren skripti
============================================
TARİXÇƏ: Bu fayl əvvəllər Stop hook idi və hər Claude cavabından
sonra işə düşürdü. Lakin soyuq Python başlanğıcı + embedding
modelinin təkrar yüklənməsi 2-3 dəqiqəlik gözləməyə səbəb olurdu.

İNDİ: Yenidən-indeksləmə MCP server daxilində fon işçisi tərəfindən
edilir (mcp_server.py → _start_background_worker). Modellər artıq
RAM-dadır, gözləmə yoxdur.

Bu skript yalnız MCP server söndürülmüş olduqda və növbəni dren
etmək lazım gəldikdə manual işlədilir:

    python hooks/flush_queue.py
"""

import json
import os
import sys
from pathlib import Path

# Import path-larını həm install root, həm hook-un yanına əlavə et.
_INSTALL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_INSTALL_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_root import find_project_root

PROJECT_ROOT = find_project_root()
QUEUE_FILE = PROJECT_ROOT / ".mla_pending.txt"


def main() -> int:
    # Stdin oxuyub atırıq — Stop hook-da maraqlı bir şey yoxdur
    try:
        sys.stdin.read()
    except Exception:
        pass

    if not QUEUE_FILE.exists():
        return 0

    # Növbəni oxu və silmək üçün hazırla
    try:
        raw = QUEUE_FILE.read_text(encoding="utf-8").strip()
    except IOError:
        return 0

    if not raw:
        QUEUE_FILE.unlink(missing_ok=True)
        return 0

    # Duplikatları sil, sıranı qoru
    seen = set()
    paths = []
    for line in raw.splitlines():
        line = line.strip()
        if line and line not in seen:
            seen.add(line)
            paths.append(line)

    if not paths:
        QUEUE_FILE.unlink(missing_ok=True)
        return 0

    # Ağır importlar — yalnız iş varsa
    try:
        from vector_store import ChromaVectorStore
        from document_loader import _CHUNKER_MAP, _fallback_chunk
        import config
    except ImportError as e:
        # Layihə qurulmayıb və ya asılılıqlar yoxdur — sakit çıx
        sys.stderr.write(f"[mla-agent flush] import xətası: {e}\n")
        return 0

    try:
        store = ChromaVectorStore()
    except Exception as e:
        sys.stderr.write(f"[mla-agent flush] ChromaDB açıla bilmədi: {e}\n")
        return 0

    indexed = 0
    deleted = 0
    skipped = 0
    errors = 0

    for path_str in paths:
        p = Path(path_str)
        try:
            if not p.exists():
                # Silinib — bazadan da sil
                store.delete_file(str(p))
                deleted += 1
                continue

            if p.suffix not in config.SUPPORTED_EXTENSIONS:
                skipped += 1
                continue

            # AI agent / IDE qovluqlarındakı faylları bazaya qatma
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
            sys.stderr.write(f"[mla-agent flush] {p.name}: {e}\n")
            errors += 1

    # Növbəni təmizlə
    try:
        QUEUE_FILE.unlink(missing_ok=True)
    except IOError:
        pass

    # Stop hook üçün strukturlu çıxış (Claude Code görəcək)
    sys.stderr.write(
        f"[mla-agent] re-index: {indexed} yenilik, "
        f"{deleted} silinmə, {skipped} keçildi, {errors} xəta\n"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())

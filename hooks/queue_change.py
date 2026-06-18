"""
============================================
hooks/queue_change.py — PostToolUse Hook (Sürətli)
============================================
MƏRHƏLƏ 8b: Claude Code Edit/Write/MultiEdit-dən sonra
çağırır. Bu skript yalnız fayl yolunu pending növbəsinə
yazır — ChromaDB və ya embedding modelini yükləmir.

Niyə belə? Hər redaktədə 3-5 saniyəlik Python+Chroma
yüklənməsi Claude Code-u yavaşladar. Növbə strategiyası:
- Bu skript: ~50ms (yalnız fayl yazır)
- Stop hook (flush_queue.py): bir dəfə işləyir, hamısını birləşdirir

Stdin-dən gələn JSON formatı:
{
  "tool_name": "Edit" | "Write" | "MultiEdit",
  "tool_input": {"file_path": "..."},
  "cwd": "...",
  ...
}
"""

import json
import os
import sys
from pathlib import Path

# Mərkəzi siyahılar — install layout-unda mla_constants hook-un yanındadır.
_INSTALL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_INSTALL_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from mla_constants import (
        SUPPORTED_EXTENSIONS,
        EXCLUDED_DIRS,
        EXCLUDED_FILE_PATTERNS,
        EXCLUDED_FILE_SUFFIXES,
    )
    from license_gate import enforcement_active
    from project_root import find_project_root
    from atomic_write import append_atomic
except Exception:
    # Dependency import alınmadı — queue hook-u səssiz keç, heç nə block etmə.
    sys.exit(0)

PROJECT_ROOT = find_project_root()
QUEUE_FILE = PROJECT_ROOT / ".mla_pending.txt"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Pis JSON — sakit çıx, Claude Code-u bloklamayaq
        return 0

    # Off-mode-da queue böyüməsin (flush_queue sonsuz işləməsin).
    if not enforcement_active(PROJECT_ROOT):
        return 0

    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not file_path:
        return 0

    p = Path(file_path)

    # Müvəqqəti qovluqlardakı faylları növbəyə salma. ChromaDB/test skriptləri
    # AppData\Local\Temp altında .py faylı yaradıb redaktə edəndə hook onları
    # növbəyə yazırdı; fayl sonra silinir, amma sətir növbədə "ghost" qalırdı.
    try:
        import tempfile
        _tmp = Path(tempfile.gettempdir()).resolve()
        _rp = p.resolve()
        if _rp == _tmp or _tmp in _rp.parents:
            return 0
    except Exception:
        pass

    # Filtrlər (Windows-da `.PY` ≠ `.py` problemi üçün lowercase suffix)
    if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return 0
    if any(part in EXCLUDED_DIRS for part in p.parts):
        return 0
    if any(p.name.startswith(pat) for pat in EXCLUDED_FILE_PATTERNS):
        return 0
    if any(p.name.endswith(sfx) for sfx in EXCLUDED_FILE_SUFFIXES):
        return 0

    # Növbədə (.txt) və ya drain-də (.processing) artıq varsa təkrar yazma —
    # eyni faylı dəfələrlə redaktə etmək növbəni şişirdirdi. Drainer onsuz da
    # dedup edir, lakin sayğac/təkrar-embed işi böyüyürdü. Hərf-həssas (Windows).
    resolved = str(p.resolve())
    want = resolved.lower()
    processing = PROJECT_ROOT / ".mla_pending.processing"
    for qf in (QUEUE_FILE, processing):
        try:
            with open(qf, "r", encoding="utf-8") as fh:
                if any(line.strip().lower() == want for line in fh):
                    return 0
        except OSError:
            pass
    append_atomic(QUEUE_FILE, resolved)
    return 0


if __name__ == "__main__":
    sys.exit(main())

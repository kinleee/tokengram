#!/usr/bin/env python3
"""PostToolUse hook — Grep indeksli fayl üzərində call olduqda
'grep_search' entry-ni session_log-a yaz.

Grep = "Read-ə alternativ" hesab olunur:
  baseline = (lines * 10) — tam Read olsa nə qədər token gedərdi
  actual   ≈ 15% baseline  — Grep matched lines + context (heuristik)
"""
import json
import os
import sys
import time
from pathlib import Path

_INSTALL_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(_INSTALL_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from mla_constants import SUPPORTED_EXTENSIONS as INDEXED_EXTS, estimate_tokens
    from license_gate import enforcement_active
    from project_root import find_project_root
    from atomic_write import append_atomic
except Exception:
    # Dependency import alınmadı — heç vaxt tool-u block etmə, səssiz çıx.
    sys.exit(0)

# Nudge köməkçisi ayrıca try-da: yoxdursa hook normal işləməyə davam etsin.
try:
    from nudge import should_nudge, emit
except Exception:
    def should_nudge(*_a, **_k):
        return False

    def emit(*_a, **_k):
        return None

PROJECT_ROOT = find_project_root()
SESSION_LOG = PROJECT_ROOT / ".mla_session_log.jsonl"

THRESHOLD_LINES = 30
# Grep çox vaxt DOĞRU alətdir (dəqiq mətn) — ona görə yönləndirmə çox yumşaqdır:
# yalnız böyük faylda və tək açarla (~30 dəq-də bir dəfə), nudge.py global cap-i ilə.
NUDGE_LINES = 200
ESTIMATED_ACTUAL_RATIO = 0.15
AVG_CHARS_PER_LINE = 80  # böyük faylda stat→sətir təxmini üçün


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0

    if not enforcement_active(PROJECT_ROOT):
        return 0

    if payload.get("tool_name") != "Grep":
        return 0

    tool_input = payload.get("tool_input", {})
    path_str = tool_input.get("path", "")
    if not path_str:
        return 0

    try:
        file_path = Path(path_str).resolve()
    except (OSError, ValueError):
        return 0

    try:
        file_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return 0

    if not file_path.is_file():
        return 0

    if file_path.suffix.lower() not in INDEXED_EXTS:
        return 0

    # Böyük faylda tam read_bytes() ETMƏ — sadəcə baseline/line təxmini üçün
    # bütün faylı oxumaq (size cap-siz) hər Grep-də əlavə disk IO idi. Stat ilə
    # təxmin et; yalnız kiçik fayllarda real oxu (line-threshold qərarı dəqiq olsun).
    try:
        file_size = file_path.stat().st_size
    except OSError:
        return 0

    if file_size > 200_000:
        line_count = max(THRESHOLD_LINES, file_size // AVG_CHARS_PER_LINE)
        estimated_baseline = estimate_tokens(b"x" * file_size)
    else:
        try:
            content = file_path.read_bytes()
        except OSError:
            return 0
        line_count = content.count(b"\n") + (1 if content and not content.endswith(b"\n") else 0)
        if line_count < THRESHOLD_LINES:
            return 0
        estimated_baseline = estimate_tokens(content)

    estimated_actual = int(estimated_baseline * ESTIMATED_ACTUAL_RATIO)

    record = {
        "ts": time.time(),
        "type": "grep_search",
        "file": str(file_path),
        "lines": line_count,
        "pattern": tool_input.get("pattern", ""),
        "estimated_baseline_tokens": estimated_baseline,
        "estimated_actual_tokens": estimated_actual,
    }
    append_atomic(SESSION_LOG, json.dumps(record, ensure_ascii=False))

    # Çox yumşaq xatırlatma (BLOKLAMIR): konseptual/davranış axtarışında
    # search_code Grep-in qaçırdığı əlaqəli kodu da tapır. Tək açar → ~30 dəq-də
    # bir dəfə; dəqiq mətn axtarışı üçün Grep onsuz da doğrudur.
    if line_count >= NUDGE_LINES and should_nudge(PROJECT_ROOT, "grep:any"):
        emit(
            "Tokengram tip: Grep is ideal for exact strings. For conceptual or "
            "\"where/how is X handled\" searches, the `search_code` MCP tool does "
            "semantic search and often surfaces related code a text Grep misses.",
            event="PostToolUse",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

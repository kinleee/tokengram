#!/usr/bin/env python3
"""PostToolUse hook — Grep indeksli fayl üzərində call olduqda
'grep_search' entry-ni session_log-a yaz.

Grep = "Read-ə alternativ" hesab olunur:
  baseline = (lines * 10) — tam Read olsa nə qədər token gedərdi
  actual   ≈ 15% baseline  — Grep matched lines + context (heuristik)
"""
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSION_LOG = PROJECT_ROOT / ".mla_session_log.jsonl"
ENFORCEMENT_FLAG = PROJECT_ROOT / ".mla_enforcement.flag"

THRESHOLD_LINES = 30
INDEXED_EXTS = {".py", ".md", ".sol", ".sql"}
ESTIMATED_ACTUAL_RATIO = 0.15


def _is_enforcement_on() -> bool:
    if not ENFORCEMENT_FLAG.exists():
        return False
    try:
        return ENFORCEMENT_FLAG.read_text(encoding="utf-8").strip().lower() == "on"
    except OSError:
        return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0

    if not _is_enforcement_on():
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

    try:
        line_count = sum(1 for _ in file_path.open("rb"))
    except OSError:
        return 0

    if line_count < THRESHOLD_LINES:
        return 0

    estimated_baseline = line_count * 10
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
    try:
        with open(SESSION_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())

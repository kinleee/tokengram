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
from mla_constants import SUPPORTED_EXTENSIONS as INDEXED_EXTS, estimate_tokens
from license_gate import enforcement_active
from project_root import find_project_root

PROJECT_ROOT = find_project_root()
SESSION_LOG = PROJECT_ROOT / ".mla_session_log.jsonl"

THRESHOLD_LINES = 30
ESTIMATED_ACTUAL_RATIO = 0.15


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
    try:
        with open(SESSION_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())

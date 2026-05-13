#!/usr/bin/env python3
"""PreToolUse hook — Read tool-u indekslənmiş fayllar üçün tənzimləyir.

İki səviyyə:
  >= THRESHOLD_BLOCK  → exit 2 (block) + search_code istifadəsi tələb olunur
  >= THRESHOLD_WARN   → exit 0 (allow) + yumşaq məsləhət (stderr)
  < THRESHOLD_WARN    → exit 0 (silent allow)
"""
import json
import sys
import time
from pathlib import Path

# Windows-da AZ locale-ında stderr-ə Azərbaycan hərfləri yazsa cp1252 escape
# olmasın deyə (savings_report-da göründüyü kimi).
if sys.platform == "win32":
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
from mla_constants import SUPPORTED_EXTENSIONS as INDEXED_EXTS, estimate_tokens
from i18n import tr

THRESHOLD_BLOCK = 50
THRESHOLD_WARN = 30


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        sys.exit(0)

    project_root = Path(__file__).resolve().parent.parent
    flag = project_root / ".mla_enforcement.flag"
    if not flag.exists() or flag.read_text(encoding="utf-8").strip().lower() != "on":
        sys.exit(0)

    if payload.get("tool_name") != "Read":
        sys.exit(0)

    file_path_str = payload.get("tool_input", {}).get("file_path", "")
    if not file_path_str:
        sys.exit(0)

    try:
        file_path = Path(file_path_str).resolve()
    except (OSError, ValueError):
        sys.exit(0)

    try:
        file_path.relative_to(project_root)
    except ValueError:
        sys.exit(0)

    if file_path.suffix.lower() not in INDEXED_EXTS:
        sys.exit(0)

    if not file_path.exists() or not file_path.is_file():
        sys.exit(0)

    try:
        content = file_path.read_bytes()
    except OSError:
        sys.exit(0)

    line_count = content.count(b"\n") + (1 if content and not content.endswith(b"\n") else 0)
    estimated_baseline = estimate_tokens(content)
    session_log = project_root / ".mla_session_log.jsonl"

    if line_count >= THRESHOLD_BLOCK:
        # Block hadisəsini session_log-a yaz — savings_report təxmini qənaəti
        # baseline-ə əlavə edəcək (biz 0 token istifadə etdik).
        try:
            record = {
                "ts": time.time(),
                "type": "read_block",
                "file": str(file_path),
                "lines": line_count,
                "estimated_baseline_tokens": estimated_baseline,
            }
            with open(session_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

        print(tr("read_block", name=file_path.name, lines=line_count), file=sys.stderr)
        sys.exit(2)

    if line_count >= THRESHOLD_WARN:
        # Soft warning — user (və ya AI) hələ də Read edə bilər, amma biz
        # event-i log-a salırıq ki, savings_report "soft" kateqoriyasında
        # tracking aparsın. Bu BASELINE-a əlavə olunmur (Read faktiki baş
        # verə bilər), yalnız MLA-nın guidance işini sayır.
        try:
            record = {
                "ts": time.time(),
                "type": "read_warn",
                "file": str(file_path),
                "lines": line_count,
                "estimated_baseline_tokens": estimated_baseline,
            }
            with open(session_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

        print(
            tr(
                "read_warn",
                name=file_path.name,
                lines=line_count,
                est_tokens=estimated_baseline,
            ),
            file=sys.stderr,
        )
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()

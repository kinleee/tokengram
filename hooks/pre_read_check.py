#!/usr/bin/env python3
"""PreToolUse hook — Read tool-u indekslənmiş fayllar üçün tənzimləyir.

İki səviyyə:
  >= THRESHOLD_BLOCK  → exit 2 (block) + search_code istifadəsi tələb olunur
  >= THRESHOLD_WARN   → exit 0 (allow) + yumşaq məsləhət (stderr)
  < THRESHOLD_WARN    → exit 0 (silent allow)
"""
import json
import os
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mla_constants import SUPPORTED_EXTENSIONS as INDEXED_EXTS, estimate_tokens
from i18n import tr
from license_gate import enforcement_active
from project_root import find_project_root

THRESHOLD_BLOCK = 50
THRESHOLD_WARN = 30

# Average chars per line for estimating "limit-bounded Read" cost when only
# `limit` is specified but actual content isn't measured yet. ~80 chars/line.
AVG_CHARS_PER_LINE = 80


def _log_read_pass(session_log, file_path, estimated_tokens, reason):
    """Bypassed / silent-allowed Read-i real-spend bucket-inə salır."""
    try:
        record = {
            "ts": time.time(),
            "type": "read_pass",
            "file": str(file_path),
            "reason": reason,
            "estimated_tokens": int(estimated_tokens),
        }
        with open(session_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _log_read_chunked(session_log, file_path, lines, limit, baseline, spent):
    """Limit-bounded Read — agent qənaət etdi, faylın bir hissəsini oxudu.

    Həm baseline (tam-oxuma alternativi), həm spent (faktiki oxuduğu hissə)
    qeydə alınır. savings_report.py bunları həm "saved", həm "real_spent"
    bucket-lərinə düzgün böləcək.
    """
    try:
        record = {
            "ts": time.time(),
            "type": "read_chunked",
            "file": str(file_path),
            "lines": int(lines),
            "limit": int(limit),
            "estimated_baseline_tokens": int(baseline),
            "estimated_spent_tokens": int(spent),
        }
        with open(session_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        sys.exit(0)

    project_root = find_project_root()
    if not enforcement_active(project_root):
        sys.exit(0)

    if payload.get("tool_name") != "Read":
        sys.exit(0)

    tool_input = payload.get("tool_input", {})

    file_path_str = tool_input.get("file_path", "")
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

    session_log = project_root / ".mla_session_log.jsonl"
    limit_val = tool_input.get("limit")

    try:
        content = file_path.read_bytes()
    except OSError:
        sys.exit(0)

    line_count = content.count(b"\n") + (1 if content and not content.endswith(b"\n") else 0)
    estimated_baseline = estimate_tokens(content)

    # Bounded Read — agent qənaət etdi. Hər ölçüdə qeydə al:
    #  - Agent yalnız `limit` sətir oxudu (`offset`-dən başlayaraq), bütöv fayl yox.
    #  - "spent" = faktiki oxunan hissənin token sayı (file content slice-i ilə hesablanır).
    #  - "saved" = baseline - spent (faylın oxunmayan hissəsinin token dəyəri).
    # Limit faylın bütün sətirlərini ötürsə qənaət yoxdur — spent ≈ baseline.
    if isinstance(limit_val, int) and limit_val > 0:
        offset_val = tool_input.get("offset") or 0
        try:
            offset_int = int(offset_val)
        except (TypeError, ValueError):
            offset_int = 0
        # offset agent-dən 1-tabanlıdır (Read tool tərifinə görə)
        start = max(0, offset_int - 1) if offset_int else 0
        end = start + limit_val
        lines = content.split(b"\n")
        sliced = b"\n".join(lines[start:end])
        spent = max(1, estimate_tokens(sliced))
        _log_read_chunked(
            session_log, file_path, line_count, limit_val,
            estimated_baseline, spent,
        )
        sys.exit(0)

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

        # Warn-da fayl yenə də oxunur → real_spent-ə daxil et
        _log_read_pass(session_log, file_path, estimated_baseline, "warn_allow")
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

    # Silent allow (< 30 sətir indexed) — fayl yenə də oxunur, kiçik real spend
    _log_read_pass(session_log, file_path, estimated_baseline, "silent_allow")
    sys.exit(0)


if __name__ == "__main__":
    main()

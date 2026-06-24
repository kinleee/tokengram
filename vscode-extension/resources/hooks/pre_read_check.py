#!/usr/bin/env python3
"""PreToolUse hook — adjusts the Read tool for indexed files.

WARN-ONLY (never blocks — blocking broke editing):
  >= THRESHOLD_WARN   → exit 0 (allow) + a soft hint: search_code is cheaper (stderr)
  < THRESHOLD_WARN    → exit 0 (silent allow)
chunked Read (limit) and files of any size are always allowed.
"""
import json
import os
import sys
import time
from pathlib import Path

# So that writing Azerbaijani letters to stderr under the AZ locale on Windows
# doesn't get cp1252-escaped (as seen in savings_report).
if sys.platform == "win32":
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from mla_constants import SUPPORTED_EXTENSIONS as INDEXED_EXTS, estimate_tokens
    from i18n import tr
    from license_gate import enforcement_active
    from project_root import find_project_root
    from atomic_write import append_atomic
except Exception:
    # One of the dependency modules wasn't found (incomplete install, etc.) — NEVER
    # block Read. Fail open: silently allow (exit 0 = allow).
    sys.exit(0)

# The nudge helper goes in a separate try: if it's missing, the hook keeps working normally.
try:
    from nudge import should_nudge, emit
except Exception:
    def should_nudge(*_a, **_k):
        return False

    def emit(*_a, **_k):
        return None


def _nudge_large_read(project_root, file_path, lines, tokens):
    """On a large full Read, deliver a search_code/chunked hint to the model WITHOUT BLOCKING.

    The Read happens anyway (exit 0, no permissionDecision) — only text is
    added. Rate-limited (once per file, with a per-window cap)."""
    if should_nudge(project_root, f"read:{file_path}"):
        emit(
            f"Tokengram tip: '{file_path.name}' is large (~{int(lines)} lines, "
            f"~{int(tokens)} tokens). Next time consider the `search_code` MCP "
            f"tool to jump straight to the relevant section, or Read with a "
            f"`limit=`/`offset=` to page through it. (Reading it now is fine.)",
            event="PreToolUse",
        )

# NOTE: there is NO MORE HARD-BLOCK. Previously a full Read of a 50+ line file
# was blocked (exit 2) → because Edit requires a Read first, editing broke
# entirely and the user was forced into /MlaOff. That was wrong: the purpose of
# enforcement is to steer large EXPLORATION reads toward search_code to save
# tokens — NOT to break editing.
#
# Now the hook ONLY WARNS (never blocks): on a large file it says "search_code
# is cheaper", but it always allows the read. The savings come when the agent
# follows the suggestion and uses search_code/chunked Read.
THRESHOLD_WARN = 250

# Average chars per line for estimating "limit-bounded Read" cost when only
# `limit` is specified but actual content isn't measured yet. ~80 chars/line.
AVG_CHARS_PER_LINE = 80


def _log_read_pass(session_log, file_path, estimated_tokens, reason):
    """Puts a bypassed / silently-allowed Read into the real-spend bucket."""
    record = {
        "ts": time.time(),
        "type": "read_pass",
        "file": str(file_path),
        "reason": reason,
        "estimated_tokens": int(estimated_tokens),
    }
    append_atomic(session_log, json.dumps(record, ensure_ascii=False))


def _log_read_chunked(session_log, file_path, lines, limit, baseline, spent):
    """Limit-bounded Read — the agent saved, reading only part of the file.

    Both the baseline (the full-read alternative) and the spent (the part it
    actually read) are recorded. savings_report.py will split these correctly
    into the "saved" and "real_spent" buckets.
    """
    record = {
        "ts": time.time(),
        "type": "read_chunked",
        "file": str(file_path),
        "lines": int(lines),
        "limit": int(limit),
        "estimated_baseline_tokens": int(baseline),
        "estimated_spent_tokens": int(spent),
    }
    append_atomic(session_log, json.dumps(record, ensure_ascii=False))


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

    # Stat-based early-out: if the file is larger than 1MB, even read_bytes
    # adds 30-100ms of IO (5 parallel Reads = 500ms of visible Claude lag).
    # If there's no limit and the file is very large, it's already known it
    # would be blocked — instead of a full read, estimate the baseline from
    # stat.st_size.
    try:
        file_size = file_path.stat().st_size
    except OSError:
        sys.exit(0)

    # ~80 chars/line average → byte-based heuristic line count.
    # Only do a real read on large files or limit-bounded Reads.
    if limit_val is None and file_size > 200_000:
        # Very large file — WE DON'T HARD-BLOCK (blocking breaks editing).
        # Just a warning + allow. For perf we don't read_bytes; we estimate the
        # baseline from stat. The Read actually happens → count it as real spend.
        estimated_line_count = max(THRESHOLD_WARN + 1, file_size // 80)
        estimated_baseline = estimate_tokens(b"x" * file_size)
        record = {
            "ts": time.time(),
            "type": "read_warn",
            "file": str(file_path),
            "lines": int(estimated_line_count),
            "estimated_baseline_tokens": estimated_baseline,
        }
        append_atomic(session_log, json.dumps(record, ensure_ascii=False))
        _log_read_pass(session_log, file_path, estimated_baseline, "large_allow")
        print(
            tr("read_warn", name=file_path.name,
               lines=int(estimated_line_count), est_tokens=estimated_baseline),
            file=sys.stderr,
        )
        _nudge_large_read(project_root, file_path, estimated_line_count, estimated_baseline)
        sys.exit(0)

    # Chunked (limit-bounded) Read on a LARGE file: DON'T do a full read_bytes(). This is
    # MLA's recommended primary path (Read + a small `limit`) and works all the time; the
    # agent only wants `limit` lines of the file anyway. Previously the whole file was read
    # from disk and split (5 parallel Reads = 5 full-file reads → visible lag + RAM spike).
    # We estimate the baseline from stat and the spent from limit*AVG —
    # the same stat-based pattern as in the no-limit branch.
    if isinstance(limit_val, int) and limit_val > 0 and file_size > 200_000:
        estimated_line_count = max(THRESHOLD_WARN + 1, file_size // AVG_CHARS_PER_LINE)
        estimated_baseline = estimate_tokens(b"x" * file_size)
        spent_bytes = min(file_size, max(1, limit_val) * AVG_CHARS_PER_LINE)
        spent = max(1, estimate_tokens(b"x" * spent_bytes))
        _log_read_chunked(
            session_log, file_path, estimated_line_count, limit_val,
            estimated_baseline, spent,
        )
        sys.exit(0)

    try:
        content = file_path.read_bytes()
    except OSError:
        sys.exit(0)

    line_count = content.count(b"\n") + (1 if content and not content.endswith(b"\n") else 0)
    estimated_baseline = estimate_tokens(content)

    # Bounded Read — the agent saved. Record it at any size:
    #  - The agent read only `limit` lines (starting from `offset`), not the whole file.
    #  - "spent" = the token count of the part actually read (computed from the file content slice).
    #  - "saved" = baseline - spent (the token value of the unread part of the file).
    # If the limit covers all the file's lines there's no saving — spent ≈ baseline.
    if isinstance(limit_val, int) and limit_val > 0:
        offset_val = tool_input.get("offset") or 0
        try:
            offset_int = int(offset_val)
        except (TypeError, ValueError):
            offset_int = 0
        # offset is 1-based from the agent (per the Read tool definition)
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

    if line_count >= THRESHOLD_WARN:
        # Soft warning — the user (or the AI) can still Read, but we log the
        # event so savings_report can track it in the "soft" category. This is
        # NOT added to the BASELINE (the Read may actually happen), it only
        # counts MLA's guidance work.
        record = {
            "ts": time.time(),
            "type": "read_warn",
            "file": str(file_path),
            "lines": line_count,
            "estimated_baseline_tokens": estimated_baseline,
        }
        append_atomic(session_log, json.dumps(record, ensure_ascii=False))

        # On a warn the file is still read → include it in real_spent
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
        _nudge_large_read(project_root, file_path, line_count, estimated_baseline)
        sys.exit(0)

    # Silent allow (< 30 lines indexed) — the file is still read, a small real spend
    _log_read_pass(session_log, file_path, estimated_baseline, "silent_allow")
    sys.exit(0)


if __name__ == "__main__":
    main()

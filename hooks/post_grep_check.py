#!/usr/bin/env python3
"""PostToolUse hook — when Grep is called on an indexed file,
write a 'grep_search' entry to session_log.

Grep is treated as "an alternative to Read":
  baseline = (lines * 10) — how many tokens a full Read would have cost
  actual   ≈ 15% baseline  — Grep matched lines + context (heuristic)
"""
import json
import os
import re
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
    # A dependency import failed — never block the tool, exit silently.
    sys.exit(0)

# The nudge helper is in a separate try: if it's missing, the hook keeps working normally.
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
ESTIMATED_ACTUAL_RATIO = 0.15
AVG_CHARS_PER_LINE = 80  # for the stat→line estimate on a large file

# Grep is often the RIGHT tool (an exact symbol/line you already know). Redirection
# happens only for a BROAD / exploratory grep — where search_code shines:
# a repo/folder-wide search AND (a 3+ alternative pattern, or a conceptual multi-word
# query). On a single file or for a single exact symbol, grep is "narrow" → we don't touch it.
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _grep_breadth(tool_input):
    """(is_broad, reason): is this grep broad enough to redirect to search_code?

    Narrow (NO nudge): single-file scope, or a single short exact token.
    Broad (nudge): repo/folder-wide AND (multi-alternative pattern / conceptual query).
    Conservative — when in doubt, DON'T nudge (return False)."""
    pattern = (tool_input.get("pattern") or "").strip()
    if not pattern:
        return (False, "")
    # A grep aimed at a single existing file → narrow (searching a file it knows).
    path = tool_input.get("path") or ""
    if path:
        try:
            if Path(path).resolve().is_file():
                return (False, "")
        except (OSError, ValueError):
            pass
    # Repo / folder-wide: look at the pattern's form.
    alts = [a for a in pattern.split("|") if a.strip()]
    if len(alts) >= 3:
        return (True, f"{len(alts)}-alternative codebase-wide pattern")
    segments = [s for s in re.split(r"\s+|\.\*", pattern) if s]
    words = _WORD_RE.findall(pattern)
    if len(segments) >= 3 and len(words) >= 3:
        return (True, "multi-word codebase-wide query")
    # A single exact token repo-wide → most likely a symbol it knows; Grep is right.
    return (False, "")


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

    # BROAD / exploratory grep redirection (DOES NOT BLOCK) — comes BEFORE the
    # single-file accounting, because that requires a `path`, whereas a broad
    # repo-wide grep usually has NO `path` (the old code ignored such greps
    # entirely). A single key ("grep:broad") → once every ~30 min via nudge.py's
    # cap/cooldown.
    is_broad, reason = _grep_breadth(tool_input)
    if is_broad and should_nudge(PROJECT_ROOT, "grep:broad"):
        emit(
            f"Tokengram tip: that looks like an exploratory codebase-wide search "
            f"({reason}). The `search_code` MCP tool does semantic search across "
            f"the project and usually finds the relevant code — plus related code "
            f"a text pattern misses — in fewer tokens than scanning Grep hits. "
            f"Grep stays best for an exact string/symbol you already know.",
            event="PostToolUse",
        )

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

    # On a large file DON'T do a full read_bytes() — reading the whole file
    # (without a size cap) just for a baseline/line estimate was extra disk IO on
    # every Grep. Estimate with stat; do a real read only on small files (so the
    # line-threshold decision is accurate).
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
    return 0


if __name__ == "__main__":
    sys.exit(main())

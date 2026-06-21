#!/usr/bin/env python3
"""PostToolUse hook — Grep indeksli fayl üzərində call olduqda
'grep_search' entry-ni session_log-a yaz.

Grep = "Read-ə alternativ" hesab olunur:
  baseline = (lines * 10) — tam Read olsa nə qədər token gedərdi
  actual   ≈ 15% baseline  — Grep matched lines + context (heuristik)
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
ESTIMATED_ACTUAL_RATIO = 0.15
AVG_CHARS_PER_LINE = 80  # böyük faylda stat→sətir təxmini üçün

# Grep çox vaxt DOĞRU alətdir (artıq bildiyin dəqiq simvol/sətir). Yönləndirmə
# yalnız GENİŞ / kəşfiyyat tipli grep-də olur — search_code-un parladığı yer:
# repo/qovluq-boyu axtarış VƏ (3+ alternativli pattern, və ya konseptual çox-sözlü
# sorğu). Tək faylda və ya tək dəqiq simvolda grep "dar"dır → ona toxunmuruq.
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _grep_breadth(tool_input):
    """(is_broad, reason): bu grep search_code-a yönləndiriləcək qədər genişdir?

    Dar (nudge YOX): tək fayl scope, və ya tək qısa dəqiq token.
    Geniş (nudge): repo/qovluq-boyu VƏ (çox-alternativ pattern / konseptual sorğu).
    Mühafizəkar — şübhədə nudge ETMƏ (False qaytar)."""
    pattern = (tool_input.get("pattern") or "").strip()
    if not pattern:
        return (False, "")
    # Tək mövcud fayla yönəlmiş grep → dar (bildiyi faylda axtarır).
    path = tool_input.get("path") or ""
    if path:
        try:
            if Path(path).resolve().is_file():
                return (False, "")
        except (OSError, ValueError):
            pass
    # Repo / qovluq-boyu: pattern formasına bax.
    alts = [a for a in pattern.split("|") if a.strip()]
    if len(alts) >= 3:
        return (True, f"{len(alts)}-alternative codebase-wide pattern")
    segments = [s for s in re.split(r"\s+|\.\*", pattern) if s]
    words = _WORD_RE.findall(pattern)
    if len(segments) >= 3 and len(words) >= 3:
        return (True, "multi-word codebase-wide query")
    # Tək dəqiq token repo-boyu → çox güman bildiyi simvol; Grep doğrudur.
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

    # GENİŞ / kəşfiyyat grep yönləndirməsi (BLOKLAMIR) — single-file accounting-dən
    # ƏVVƏL gəlir, çünki o `path` tələb edir, geniş repo-boyu grep-də isə adətən
    # `path` OLMUR (köhnə kod belə grep-ləri tamamilə gözardı edirdi). Tək açar
    # ("grep:broad") → nudge.py cap/cooldown ilə ~30 dəq-də bir dəfə.
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
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""PostToolUse hook — Bash inspection komandalarını izlənir.
İndeksli layihə faylı üzərində call olduqda 'bash_inspect' entry session_log-a yazılır.

Tutulan komandalar:
  POSIX:      cat, head, tail, wc, less, more, awk, sed
  Windows:    type (cmd), findstr
  PowerShell: gc, Get-Content, Select-String, sls
  Git:        git show <ref>:<path>

baseline = lines * 10
actual   ≈ 20% baseline (heuristik subset)
"""
import json
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSION_LOG = PROJECT_ROOT / ".mla_session_log.jsonl"
ENFORCEMENT_FLAG = PROJECT_ROOT / ".mla_enforcement.flag"

THRESHOLD_LINES = 50
INDEXED_EXTS = {".py", ".md", ".sol", ".sql"}
ESTIMATED_ACTUAL_RATIO = 0.20

# Hər seqment (| ; && || ilə ayrılmış) inspeksiya açar sözü üçün skan olunur,
# sonra qalan token-lərdən birinin indeksli layihə faylı kimi resolve oluna
# biləcəyi yoxlanır. Bu yanaşma argument-order variasiyalarını avtomatik tutur:
#   cat foo.py            | foo.py keyword-dən sonra
#   Select-String x foo.py| eyni
#   findstr "x" foo.py    | pattern quoted, foo.py yenə token-dir
INSPECT_KEYWORD_RE = re.compile(
    r"\b(cat|head|tail|wc|less|more|awk|sed|type|findstr|gc|Get-Content|Select-String|sls|git\s+show)\b",
    re.IGNORECASE,
)
SEGMENT_SPLIT_RE = re.compile(r"\|\||&&|[|;]")
TOKEN_RE = re.compile(r"[^\s|;&<>]+")
# `git show HEAD:path/to/file.py` — ref:path birlikdə bir token-dir.
GIT_REF_PATH_RE = re.compile(r"\S+:([^\s|;&<>]+)")


def _is_enforcement_on() -> bool:
    if not ENFORCEMENT_FLAG.exists():
        return False
    try:
        return ENFORCEMENT_FLAG.read_text(encoding="utf-8").strip().lower() == "on"
    except OSError:
        return False


_MSYS_RE = re.compile(r"^/([a-zA-Z])/(.*)$")


def _msys_to_windows(raw: str) -> str:
    """`/c/Users/...` → `C:/Users/...` (Git Bash style)."""
    m = _MSYS_RE.match(raw)
    if m:
        return f"{m.group(1).upper()}:/{m.group(2)}"
    return raw


def _resolve_in_project(raw: str):
    raw = raw.strip("\"'")
    windows_form = _msys_to_windows(raw)
    candidates = [raw, windows_form, str(PROJECT_ROOT / raw)]
    for candidate in candidates:
        try:
            p = Path(candidate).resolve()
        except (OSError, ValueError):
            continue
        try:
            p.relative_to(PROJECT_ROOT)
        except ValueError:
            continue
        if not p.is_file():
            continue
        if p.suffix.lower() not in INDEXED_EXTS:
            continue
        return p
    return None


def _iter_inspection_paths(cmd: str):
    """Yields (keyword_fragment, raw_path) seqment-bə-seqment.

    Hər `| ; && ||` ilə ayrılmış seqmentdə inspect açar sözü axtarır;
    tapsa, açar sözündən sonra gələn token-ləri path namizədi kimi qaytarır.
    `git show ref:path` xüsusi tutulur.
    """
    for segment in SEGMENT_SPLIT_RE.split(cmd):
        m = INSPECT_KEYWORD_RE.search(segment)
        if not m:
            continue
        keyword = m.group(1).lower().split()[0]
        tail = segment[m.end():]

        if keyword == "git":
            gm = GIT_REF_PATH_RE.search(tail)
            if gm:
                yield m.group(0), gm.group(1)
            continue

        for tok in TOKEN_RE.findall(tail):
            if tok.startswith("-"):
                continue
            yield m.group(0), tok


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0

    if not _is_enforcement_on():
        return 0

    if payload.get("tool_name") != "Bash":
        return 0

    cmd = payload.get("tool_input", {}).get("command", "")
    if not cmd:
        return 0

    seen = set()
    for keyword_frag, raw in _iter_inspection_paths(cmd):
        file_path = _resolve_in_project(raw)
        if file_path is None or str(file_path) in seen:
            continue
        seen.add(str(file_path))

        try:
            line_count = sum(1 for _ in file_path.open("rb"))
        except OSError:
            continue
        if line_count < THRESHOLD_LINES:
            continue

        estimated_baseline = line_count * 10
        estimated_actual = int(estimated_baseline * ESTIMATED_ACTUAL_RATIO)

        record = {
            "ts": time.time(),
            "type": "bash_inspect",
            "file": str(file_path),
            "lines": line_count,
            "command_fragment": keyword_frag[:80],
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

"""
============================================
hooks/savings_report.py — Stop Hook (Token Savings)
============================================
Runs at the end of every task (when Claude finishes its response).
Reads .mla_session_log.jsonl, computes total savings,
shows them to the user, then clears the log.

Example output:
    [mla-agent] This task: 3 searches, 1,818 tok / 5,742 baseline → 68.3% saved
"""

import json
import os
import sys
import time
from pathlib import Path

# Windows' default stderr encoding is cp1252, where non-ASCII letters get
# escaped (test phase3 caught this bug). Force UTF-8.
if sys.platform == "win32":
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

_INSTALL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_INSTALL_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from i18n import tr
    from license_gate import enforcement_active
    from project_root import find_project_root
    from atomic_write import append_atomic
except Exception:
    # A dependency import failed — silently skip the Stop hook, block nothing.
    sys.exit(0)

PROJECT_ROOT = find_project_root()
SESSION_LOG = PROJECT_ROOT / ".mla_session_log.jsonl"
# Per-task savings history — so Claude/Claude Code can read it back.
SAVINGS_HISTORY = PROJECT_ROOT / ".mla_savings_history.jsonl"

# Per-event baseline cap = a realistic "chunked Read" value (~1000 lines × 10 tok).
# Model: without MLA, an agent usually doesn't read a huge file in full, it does a
# targeted chunked Read. A larger cap (20k = full Read) doesn't match the
# "50% real reduction" empirical data.
# search_code, grep, bash_inspect, read_block all use the same cap.
MAX_BASELINE_PER_EVENT = 10_000


def _norm(p) -> str:
    """Normalize for path comparison: absolute posix + lowercase.

    search_code records files in canonical posix form (`c:/x/y.py`), whereas hooks
    use `Path.resolve()` (backslash on Windows). For comparison we bring both sides
    to the same form so the B1 correlation can match files.
    """
    try:
        return Path(str(p)).resolve(strict=False).as_posix().lower()
    except (OSError, ValueError):
        return str(p).replace("\\", "/").lower()



def main() -> int:
    # Read stdin and discard it (we don't need it in the Stop hook)
    try:
        sys.stdin.read()
    except Exception:
        pass

    # MLA OFF → in off-mode the hooks don't write to session_log anyway,
    # and a delete attempt could race with a parallel write → skip.
    if not enforcement_active(PROJECT_ROOT):
        return 0

    if not SESSION_LOG.exists():
        return 0

    # Atomic rename: between read and delete another hook could write to
    # session_log; the rename turns it into our own `.processing.<pid>` file,
    # new events go to a freshly recreated empty SESSION_LOG, and this run loses
    # nothing.
    pid_log = SESSION_LOG.parent / f".mla_session_log.jsonl.processing.{os.getpid()}"
    try:
        os.replace(SESSION_LOG, pid_log)
    except OSError:
        return 0

    try:
        lines = pid_log.read_text(encoding="utf-8").strip().splitlines()
    except IOError:
        pid_log.unlink(missing_ok=True)
        return 0

    if not lines:
        pid_log.unlink(missing_ok=True)
        return 0

    # Parse all calls
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not entries:
        SESSION_LOG.unlink(missing_ok=True)
        return 0

    # Entry types:
    # search_code:  {"query", "files": {...}, "actual_tokens"}
    # read_block:   {"type": "read_block", "file", "lines", "estimated_baseline_tokens"}
    # read_warn:    {"type": "read_warn", "file", "lines", "estimated_baseline_tokens"}
    #               — soft warning, NOT included in BASELINE (the Read may actually
    #                 happen), only for count + audit
    # grep_search:  {"type": "grep_search", "file", "lines",
    #                "estimated_baseline_tokens", "estimated_actual_tokens"}
    # bash_inspect: same as grep_search
    total_actual = 0
    search_count = 0
    block_count = 0
    block_baseline = 0
    grep_count = 0
    grep_baseline = 0
    grep_actual = 0
    bash_count = 0
    bash_baseline = 0
    bash_actual = 0
    warn_count = 0
    warn_baseline = 0  # for information only, not included in baseline
    # New real-spend buckets — for the bar's "real %" calculation
    read_pass_count = 0
    read_pass_tokens = 0
    bash_output_count = 0
    bash_output_tokens = 0
    # Chunked Read events — yield both baseline (saved) and spent (real_spent).
    chunked_count = 0
    chunked_baseline = 0
    chunked_spent = 0
    # We accumulate the search_code baseline per-event (instead of unique_files)
    # — each event is capped separately at accumulation time, so if the same file
    # appears in two searches the second search isn't counted as a "free saving",
    # because without MLA the agent wouldn't read it twice either.
    search_baseline = 0
    unique_files_for_count = set()

    # B1 — search→read correlation: if the agent searched a file and THEN read it
    # in full (read_pass = silent/warn/large allow), that search saved NOTHING —
    # on the contrary, chunk + full file = EXTRA cost. Below we zero out the
    # baseline (the fake saving) of those searches. This way the "shows 90%, real
    # 20%" inflation is eliminated mathematically. grep/bash/chunked-Read are
    # themselves a saving alternative → not counted (only a full Read = read_pass
    # cancels).
    fully_read = {
        _norm(e.get("file"))
        for e in entries
        if e.get("type") == "read_pass" and e.get("file")
    }
    search_cancelled = 0
    cancelled_spent = 0  # chunk tokens of cancelled searches (real cost)

    for e in entries:
        entry_type = e.get("type", "search_code")
        if entry_type == "read_block":
            block_count += 1
            block_baseline += min(e.get("estimated_baseline_tokens", 0), MAX_BASELINE_PER_EVENT)
        elif entry_type == "read_warn":
            warn_count += 1
            warn_baseline += min(e.get("estimated_baseline_tokens", 0), MAX_BASELINE_PER_EVENT)
        elif entry_type == "grep_search":
            grep_count += 1
            raw_b = e.get("estimated_baseline_tokens", 0)
            raw_a = e.get("estimated_actual_tokens", 0)
            capped_b = min(raw_b, MAX_BASELINE_PER_EVENT)
            # shrink actual by the same ratio so the heuristic percentage is preserved
            capped_a = int(raw_a * capped_b / raw_b) if raw_b > 0 else 0
            grep_baseline += capped_b
            grep_actual += capped_a
        elif entry_type == "bash_inspect":
            bash_count += 1
            raw_b = e.get("estimated_baseline_tokens", 0)
            raw_a = e.get("estimated_actual_tokens", 0)
            capped_b = min(raw_b, MAX_BASELINE_PER_EVENT)
            capped_a = int(raw_a * capped_b / raw_b) if raw_b > 0 else 0
            bash_baseline += capped_b
            bash_actual += capped_a
        elif entry_type == "read_pass":
            read_pass_count += 1
            read_pass_tokens += int(e.get("estimated_tokens", 0))
        elif entry_type == "bash_output":
            bash_output_count += 1
            bash_output_tokens += int(e.get("estimated_tokens", 0))
        elif entry_type == "read_chunked":
            chunked_count += 1
            raw_b = e.get("estimated_baseline_tokens", 0)
            raw_s = e.get("estimated_spent_tokens", 0)
            capped_b = min(raw_b, MAX_BASELINE_PER_EVENT)
            capped_s = int(raw_s * capped_b / raw_b) if raw_b > 0 else 0
            chunked_baseline += capped_b
            chunked_spent += capped_s
        else:
            search_count += 1
            # Take the TOP file's baseline for this event (rank order preserved)
            # and cap the event. Without MLA the agent would do 1 chunked Read, not N.
            files = e.get("files", {})
            cancelled = False
            if files:
                # Ranked: the first file is the best match. Credit only that one.
                top_file, top_tokens = next(iter(files.items()))
                # B1: if this file was later read in full, the search saved nothing —
                # count it neutrally (0% contribution): neither credit to baseline
                # nor saving. Its chunk tokens are added to the cost of the
                # subsequent Read (cancelled_spent → real cost), so the denominator
                # stays honest but no fake saving (or negative spike) appears.
                if _norm(top_file) in fully_read:
                    cancelled = True
                    search_cancelled += 1
                    cancelled_spent += e.get("actual_tokens", 0)
                else:
                    search_baseline += min(top_tokens, MAX_BASELINE_PER_EVENT)
                unique_files_for_count.update(files.keys())
            if not cancelled:
                total_actual += e.get("actual_tokens", 0)

    has_search = search_count > 0
    has_block = block_count > 0
    has_grep = grep_count > 0
    has_bash = bash_count > 0
    has_warn = warn_count > 0
    has_read_pass = read_pass_count > 0
    has_bash_output = bash_output_count > 0
    has_chunked = chunked_count > 0

    if not (has_search or has_block or has_grep or has_bash or has_warn
            or has_read_pass or has_bash_output or has_chunked):
        pid_log.unlink(missing_ok=True)
        return 0

    baseline = (
        search_baseline + block_baseline + grep_baseline
        + bash_baseline + chunked_baseline
    )
    actual = total_actual + grep_actual + bash_actual + chunked_spent  # blocks 0 actual
    saving = baseline - actual

    # Real-spend = the actual MLA observed + bypass/silent/warn reads +
    # bash output (npm/vsce/ls etc. long stdout). bash_actual is already
    # in actual (bash_inspect heuristic); we count bash_output IN ADDITION,
    # not INSTEAD of it — because bash_inspect doesn't show the file content,
    # the inspect heuristic was 20% × baseline, while the real value could be the
    # full file. For real usage bash_output is the measured value; bash_actual is
    # a temporary double-count, and bash_inspect could be removed entirely later.
    untracked_spent = read_pass_tokens + bash_output_tokens + cancelled_spent
    total_spent = actual + untracked_spent
    # "Real %" — the ratio of the tokens MLA diverted over the whole session to
    # TOTAL session spend (saved + actual + untracked). In an edit-heavy refactor
    # this number is around 5-15%; in Q&A it's 60-80%.
    real_total = saving + total_spent
    pct = (saving / real_total * 100) if real_total > 0 else 0.0

    # Activity summary (localized)
    parts = []
    if search_count:
        key = "activity_searches_plural" if search_count > 1 else "activity_searches"
        parts.append(tr(key, n=search_count))
    if grep_count:
        parts.append(tr("activity_greps", n=grep_count))
    if bash_count:
        parts.append(tr("activity_bash", n=bash_count))
    if block_count:
        key = "activity_blocks_plural" if block_count > 1 else "activity_blocks"
        parts.append(tr(key, n=block_count))
    if chunked_count:
        parts.append(f"{chunked_count} chunked Read")
    activity = ", ".join(parts) if parts else tr("activity_none")

    # `baseline` field — `actual + saved` (preserves the old semantics).
    # `total` field — the real session denominator (saved + actual + untracked).
    msg = tr(
        "savings_summary",
        activity=activity,
        actual=actual,
        baseline=baseline,
        pct=pct,
    )
    sys.stderr.write(msg + "\n")

    try:
        record = {
            "ts": time.time(),
            "searches": search_count,
            "blocks": block_count,
            "greps": grep_count,
            "actual_tokens": actual,
            "baseline_tokens": baseline,
            "search_baseline_tokens": search_baseline,
            "block_baseline_tokens": block_baseline,
            "grep_baseline_tokens": grep_baseline,
            "grep_actual_tokens": grep_actual,
            "bash_inspects": bash_count,
            "bash_baseline_tokens": bash_baseline,
            "bash_actual_tokens": bash_actual,
            "read_warns": warn_count,
            "warn_baseline_tokens": warn_baseline,
            # New fields (savingsReader.ts treats these as optional)
            "read_passes": read_pass_count,
            "read_pass_tokens": read_pass_tokens,
            "bash_outputs": bash_output_count,
            "bash_output_tokens": bash_output_tokens,
            "read_chunked": chunked_count,
            "chunked_baseline_tokens": chunked_baseline,
            "chunked_spent_tokens": chunked_spent,
            "untracked_spent_tokens": untracked_spent,
            "total_spent_tokens": total_spent,
            "real_total_tokens": real_total,
            "saving_tokens": saving,
            "saving_pct": round(pct, 2),
            "file_count": len(unique_files_for_count),
            # B1: how many searches had their saving cancelled because the file was later read in full.
            "search_cancelled": search_cancelled,
        }
        append_atomic(SAVINGS_HISTORY, json.dumps(record, ensure_ascii=False))
    except IOError:
        # Even if archiving fails, the report has already been written to stderr
        pass
    finally:
        # Always clean up the `.processing.<pid>` file (it's ours via the rename).
        pid_log.unlink(missing_ok=True)

    # Clear the log (for the next task)
    try:
        SESSION_LOG.unlink(missing_ok=True)
    except IOError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())

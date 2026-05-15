"""
============================================
hooks/savings_report.py — Stop Hook (Token Qənaəti)
============================================
Hər task bitəndə (Claude cavabı bitirəndə) işə düşür.
.mla_session_log.jsonl-i oxuyur, ümumi qənaəti hesablayır,
istifadəçiyə göstərir, sonra log-u təmizləyir.

Çıxış nümunəsi:
    [mla-agent] Bu task: 3 axtarış, 1,818 tok / 5,742 baseline → 68.3% qənaət
"""

import json
import sys
import time
from pathlib import Path

# Windows-un default stderr encoding-i cp1252-dir, Azərbaycan hərfləri
# `ş` kimi escape olunur (test phase3 bu bug-u tutdu). UTF-8-ə force.
if sys.platform == "win32":
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from i18n import tr

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSION_LOG = PROJECT_ROOT / ".mla_session_log.jsonl"
# Per-task savings tarixçəsi — Claude/Claude Code yenidən oxuya bilsin deyə.
SAVINGS_HISTORY = PROJECT_ROOT / ".mla_savings_history.jsonl"
ENFORCEMENT_FLAG = PROJECT_ROOT / ".mla_enforcement.flag"

# Per-fayl baseline cap: 2000 sətirlik bir default Read çağırışı (~20k token).
# 100k+ token generated fayllar (Cython .c) əks halda metrikanı şişirdir.
MAX_BASELINE_PER_FILE = 20_000


def _is_enforcement_on() -> bool:
    if not ENFORCEMENT_FLAG.exists():
        return False
    try:
        return ENFORCEMENT_FLAG.read_text(encoding="utf-8").strip().lower() == "on"
    except OSError:
        return False


def main() -> int:
    # Stdin-i oxuyub at (Stop hook-da bizə lazım deyil)
    try:
        sys.stdin.read()
    except Exception:
        pass

    # MLA OFF → history yazma, mövcud session_log-u sil (data yığma)
    if not _is_enforcement_on():
        try:
            SESSION_LOG.unlink(missing_ok=True)
        except OSError:
            pass
        return 0

    if not SESSION_LOG.exists():
        return 0

    try:
        lines = SESSION_LOG.read_text(encoding="utf-8").strip().splitlines()
    except IOError:
        return 0

    if not lines:
        SESSION_LOG.unlink(missing_ok=True)
        return 0

    # Bütün çağırışları parse et
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not entries:
        SESSION_LOG.unlink(missing_ok=True)
        return 0

    # Entry tipləri:
    # search_code:  {"query", "files": {...}, "actual_tokens"}
    # read_block:   {"type": "read_block", "file", "lines", "estimated_baseline_tokens"}
    # read_warn:    {"type": "read_warn", "file", "lines", "estimated_baseline_tokens"}
    #               — soft warning, BASELINE-a daxil olmur (Read faktiki ola bilər),
    #                 yalnız count + audit üçün
    # grep_search:  {"type": "grep_search", "file", "lines",
    #                "estimated_baseline_tokens", "estimated_actual_tokens"}
    # bash_inspect: eyni grep_search ilə
    unique_files = {}  # file_path -> token_count (max)
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
    warn_baseline = 0  # informasiya üçün, baseline-a daxil olmur
    for e in entries:
        entry_type = e.get("type", "search_code")
        if entry_type == "read_block":
            block_count += 1
            block_baseline += min(e.get("estimated_baseline_tokens", 0), MAX_BASELINE_PER_FILE)
        elif entry_type == "read_warn":
            warn_count += 1
            warn_baseline += min(e.get("estimated_baseline_tokens", 0), MAX_BASELINE_PER_FILE)
        elif entry_type == "grep_search":
            grep_count += 1
            raw_b = e.get("estimated_baseline_tokens", 0)
            raw_a = e.get("estimated_actual_tokens", 0)
            capped_b = min(raw_b, MAX_BASELINE_PER_FILE)
            # heuristic faiz qorunsun deyə actual da eyni nisbətdə kiçilsin
            capped_a = int(raw_a * capped_b / raw_b) if raw_b > 0 else 0
            grep_baseline += capped_b
            grep_actual += capped_a
        elif entry_type == "bash_inspect":
            bash_count += 1
            raw_b = e.get("estimated_baseline_tokens", 0)
            raw_a = e.get("estimated_actual_tokens", 0)
            capped_b = min(raw_b, MAX_BASELINE_PER_FILE)
            capped_a = int(raw_a * capped_b / raw_b) if raw_b > 0 else 0
            bash_baseline += capped_b
            bash_actual += capped_a
        else:
            search_count += 1
            for fp, tc in e.get("files", {}).items():
                capped_tc = min(tc, MAX_BASELINE_PER_FILE)
                unique_files[fp] = max(unique_files.get(fp, 0), capped_tc)
            total_actual += e.get("actual_tokens", 0)

    has_search = bool(unique_files)
    has_block = block_count > 0
    has_grep = grep_count > 0
    has_bash = bash_count > 0
    has_warn = warn_count > 0

    # Heç bir tipdə aktivlik yoxdursa skip et
    if not (has_search or has_block or has_grep or has_bash or has_warn):
        SESSION_LOG.unlink(missing_ok=True)
        return 0

    search_baseline = sum(unique_files.values())
    baseline = search_baseline + block_baseline + grep_baseline + bash_baseline
    actual = total_actual + grep_actual + bash_actual  # blocks 0 actual
    saving = baseline - actual
    pct = (saving / baseline * 100) if baseline > 0 else 0.0

    # Aktivlik xülasəsi (lokalizəli)
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
    activity = ", ".join(parts) if parts else tr("activity_none")

    msg = tr(
        "savings_summary",
        activity=activity,
        actual=actual,
        baseline=baseline,
        pct=pct,
    )
    sys.stderr.write(msg + "\n")

    # Tarixçəni arşivlə — sonradan cumulative qənaət hesabatı üçün.
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
            "saving_tokens": saving,
            "saving_pct": round(pct, 2),
            "file_count": len(unique_files),
        }
        with open(SAVINGS_HISTORY, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except IOError:
        # Arşivləmə uğursuz olsa belə, hesabat artıq stderr-ə yazılıb
        pass

    # Log-u təmizlə (sonrakı task üçün)
    try:
        SESSION_LOG.unlink(missing_ok=True)
    except IOError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())

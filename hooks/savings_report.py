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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSION_LOG = PROJECT_ROOT / ".mla_session_log.jsonl"
# Per-task savings tarixçəsi — Claude/Claude Code yenidən oxuya bilsin deyə.
SAVINGS_HISTORY = PROJECT_ROOT / ".mla_savings_history.jsonl"
ENFORCEMENT_FLAG = PROJECT_ROOT / ".mla_enforcement.flag"


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

    # Üç tip entry:
    # search_code:  {"query", "files": {...}, "actual_tokens"}
    # read_block:   {"type": "read_block", "file", "lines", "estimated_baseline_tokens"}
    # grep_search:  {"type": "grep_search", "file", "lines",
    #                "estimated_baseline_tokens", "estimated_actual_tokens"}
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
    for e in entries:
        entry_type = e.get("type", "search_code")
        if entry_type == "read_block":
            block_count += 1
            block_baseline += e.get("estimated_baseline_tokens", 0)
        elif entry_type == "grep_search":
            grep_count += 1
            grep_baseline += e.get("estimated_baseline_tokens", 0)
            grep_actual += e.get("estimated_actual_tokens", 0)
        elif entry_type == "bash_inspect":
            bash_count += 1
            bash_baseline += e.get("estimated_baseline_tokens", 0)
            bash_actual += e.get("estimated_actual_tokens", 0)
        else:
            search_count += 1
            for fp, tc in e.get("files", {}).items():
                unique_files[fp] = max(unique_files.get(fp, 0), tc)
            total_actual += e.get("actual_tokens", 0)

    has_search = bool(unique_files)
    has_block = block_count > 0
    has_grep = grep_count > 0
    has_bash = bash_count > 0

    # Heç bir tipdə baseline yoxdursa skip et
    if not (has_search or has_block or has_grep or has_bash):
        SESSION_LOG.unlink(missing_ok=True)
        return 0

    search_baseline = sum(unique_files.values())
    baseline = search_baseline + block_baseline + grep_baseline + bash_baseline
    actual = total_actual + grep_actual + bash_actual  # blocks 0 actual
    saving = baseline - actual
    pct = (saving / baseline * 100) if baseline > 0 else 0.0

    # Aktivlik xülasəsi
    parts = []
    if search_count:
        parts.append(f"{search_count} axtarış")
    if grep_count:
        parts.append(f"{grep_count} Grep")
    if bash_count:
        parts.append(f"{bash_count} bash-inspect")
    if block_count:
        parts.append(f"{block_count} Read-block")
    activity = ", ".join(parts) if parts else "0 hadisə"

    msg = (
        f"[mla-agent] Bu task: {activity}, "
        f"{actual:,} tok istifadə (baseline: {baseline:,} tok) "
        f"→ {pct:.1f}% qənaət"
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

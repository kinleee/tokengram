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
import os
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

_INSTALL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_INSTALL_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from i18n import tr
from license_gate import enforcement_active

PROJECT_ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
SESSION_LOG = PROJECT_ROOT / ".mla_session_log.jsonl"
# Per-task savings tarixçəsi — Claude/Claude Code yenidən oxuya bilsin deyə.
SAVINGS_HISTORY = PROJECT_ROOT / ".mla_savings_history.jsonl"

# Per-event baseline cap = realistik "chunked Read" dəyəri (~1000 sətir × 10 tok).
# Model: MLA-sız agent adətən nəhəng faylı tam oxumur, target-li chunked Read edir.
# Daha böyük cap (20k = tam Read) "50% real reduction" empirikası ilə uyğun gəlmir.
# search_code, grep, bash_inspect, read_block hamısı eyni cap-i istifadə edir.
MAX_BASELINE_PER_EVENT = 10_000



def main() -> int:
    # Stdin-i oxuyub at (Stop hook-da bizə lazım deyil)
    try:
        sys.stdin.read()
    except Exception:
        pass

    # MLA OFF → history yazma, mövcud session_log-u sil (data yığma)
    if not enforcement_active(PROJECT_ROOT):
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
    # Yeni real-spend bucket-ləri — bar-ın "real %" hesablaması üçün
    read_pass_count = 0
    read_pass_tokens = 0
    bash_output_count = 0
    bash_output_tokens = 0
    # Chunked Read events — həm baseline (saved), həm spent (real_spent) verir.
    chunked_count = 0
    chunked_baseline = 0
    chunked_spent = 0
    # search_code baseline-ı per-event yığırıq (unique_files əvəzinə)
    # — yığım sonu hər event ayrıca cap-lanır, eyni fayl iki search-də gələrsə
    # ikinci search "free saving" sayılmır, çünki MLA-sız agent də iki dəfə oxumazdı.
    search_baseline = 0
    unique_files_for_count = set()
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
            # heuristic faiz qorunsun deyə actual da eyni nisbətdə kiçilsin
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
            # Bu event üçün TOP fayl baseline-ı götür (rank order qorunur)
            # və event-i cap-lə. Agent MLA-sız 1 chunked Read edərdi, N deyil.
            files = e.get("files", {})
            if files:
                # Ranked: ilk fayl ən yaxşı match. Yalnız onu credit et.
                top_tokens = next(iter(files.values()))
                search_baseline += min(top_tokens, MAX_BASELINE_PER_EVENT)
                unique_files_for_count.update(files.keys())
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
        SESSION_LOG.unlink(missing_ok=True)
        return 0

    baseline = (
        search_baseline + block_baseline + grep_baseline
        + bash_baseline + chunked_baseline
    )
    actual = total_actual + grep_actual + bash_actual + chunked_spent  # blocks 0 actual
    saving = baseline - actual

    # Real-spend = MLA-nın gördüyü actual + bypass/silent/warn read-lər +
    # bash output-u (npm/vsce/ls və s. uzun stdout). bash_actual artıq
    # actual-da-dır (bash_inspect heuristik), bash_output-u onun YERİNƏ deyil
    # ƏLAVƏ olaraq sayırıq — çünki bash_inspect-də fayl content-i göstərmir,
    # inspect heuristic 20% × baseline idi, real isə tam fayl ola bilərdi.
    # Real istifadə üçün bash_output ölçülmüş dəyərdir; bash_actual müvəqqəti
    # double-count-dur, gələcəkdə bash_inspect-i tamamilə sökmək olar.
    untracked_spent = read_pass_tokens + bash_output_tokens
    total_spent = actual + untracked_spent
    # "Real %" — sessiya boyu MLA-nın diversiya etdiyi token-lərin TOTAL sessiya
    # spend-ə (saved + actual + untracked) nisbəti. Edit-heavy refactor-da
    # bu rəqəm 5-15% civarındadır; Q&A-da 60-80%.
    real_total = saving + total_spent
    pct = (saving / real_total * 100) if real_total > 0 else 0.0

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
    if chunked_count:
        parts.append(f"{chunked_count} chunked Read")
    activity = ", ".join(parts) if parts else tr("activity_none")

    # `baseline` field — `actual + saved` (köhnə semantika qoruyur).
    # `total` field — real session denominator-ı (saved + actual + untracked).
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
            # Yeni field-lər (savingsReader.ts bunları opsional sayır)
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

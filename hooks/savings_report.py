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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSION_LOG = PROJECT_ROOT / ".mla_session_log.jsonl"
# Per-task savings tarixçəsi — Claude/Claude Code yenidən oxuya bilsin deyə.
SAVINGS_HISTORY = PROJECT_ROOT / ".mla_savings_history.jsonl"


def main() -> int:
    # Stdin-i oxuyub at (Stop hook-da bizə lazım deyil)
    try:
        sys.stdin.read()
    except Exception:
        pass

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

    # Aggregate: unikal fayllar (eyni fayl çoxlu çağırışda baxılırsa, bir dəfə sayılır)
    unique_files = {}  # file_path -> token_count (max)
    total_actual = 0
    for e in entries:
        for fp, tc in e.get("files", {}).items():
            unique_files[fp] = max(unique_files.get(fp, 0), tc)
        total_actual += e.get("actual_tokens", 0)

    if not unique_files or total_actual == 0:
        SESSION_LOG.unlink(missing_ok=True)
        return 0

    baseline = sum(unique_files.values())
    saving = baseline - total_actual
    pct = (saving / baseline * 100) if baseline > 0 else 0.0

    # Stderr-ə yaz — Claude Code istifadəçiyə göstərir
    msg = (
        f"[mla-agent] Bu task: {len(entries)} axtarış, "
        f"{total_actual:,} tok istifadə (baseline: {baseline:,} tok) "
        f"→ {pct:.1f}% qənaət"
    )
    sys.stderr.write(msg + "\n")

    # Tarixçəni arşivlə — sonradan cumulative qənaət hesabatı üçün.
    # Bir sətir = bir task. JSONL formatı append-safe-dir.
    try:
        record = {
            "ts": time.time(),
            "searches": len(entries),
            "actual_tokens": total_actual,
            "baseline_tokens": baseline,
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

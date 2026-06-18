#!/usr/bin/env python3
"""PreToolUse hook — Read tool-u indekslənmiş fayllar üçün tənzimləyir.

WARN-ONLY (heç vaxt block etmir — block redaktəni sındırırdı):
  >= THRESHOLD_WARN   → exit 0 (allow) + yumşaq məsləhət: search_code daha sərfəli (stderr)
  < THRESHOLD_WARN    → exit 0 (silent allow)
chunked Read (limit) və hər ölçü fayl həmişə icazəlidir.
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
try:
    from mla_constants import SUPPORTED_EXTENSIONS as INDEXED_EXTS, estimate_tokens
    from i18n import tr
    from license_gate import enforcement_active
    from project_root import find_project_root
    from atomic_write import append_atomic
except Exception:
    # Dependency moduldan biri tapılmadı (natamam install və s.) — Read-i HEÇ
    # vaxt block etmə. Fail open: səssiz icazə ver (exit 0 = allow).
    sys.exit(0)

# DİQQƏT: artıq HARD-BLOCK YOXDUR. Əvvəl 50+ sətirlik faylın tam Read-i
# bloklanırdı (exit 2) → Edit əvvəlcə Read tələb etdiyi üçün redaktə tamamilə
# sınırdı, istifadəçi /MlaOff-a məcbur olurdu. Bu səhv idi: enforcement-in
# məqsədi böyük EXPLORATION oxumalarını search_code-a yönləndirib token qənaət
# etməkdir — redaktəni dağıtmaq YOX.
#
# İndi hook YALNIZ XƏBƏRDARLIQ edir (heç vaxt block): böyük faylda "search_code
# daha sərfəlidir" deyir, amma oxumağa həmişə icazə verir. Qənaət agent
# təklifə əməl edib search_code/chunked Read işlədəndə gəlir.
THRESHOLD_WARN = 250

# Average chars per line for estimating "limit-bounded Read" cost when only
# `limit` is specified but actual content isn't measured yet. ~80 chars/line.
AVG_CHARS_PER_LINE = 80


def _log_read_pass(session_log, file_path, estimated_tokens, reason):
    """Bypassed / silent-allowed Read-i real-spend bucket-inə salır."""
    record = {
        "ts": time.time(),
        "type": "read_pass",
        "file": str(file_path),
        "reason": reason,
        "estimated_tokens": int(estimated_tokens),
    }
    append_atomic(session_log, json.dumps(record, ensure_ascii=False))


def _log_read_chunked(session_log, file_path, lines, limit, baseline, spent):
    """Limit-bounded Read — agent qənaət etdi, faylın bir hissəsini oxudu.

    Həm baseline (tam-oxuma alternativi), həm spent (faktiki oxuduğu hissə)
    qeydə alınır. savings_report.py bunları həm "saved", həm "real_spent"
    bucket-lərinə düzgün böləcək.
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

    # Stat-əsaslı early-out: faylın 1MB-dan böyükdürsə, hətta read_bytes
    # 30-100ms IO əlavə edir (5 paralel Read = 500ms görünən Claude lag).
    # Limit yoxdursa və fayl çox böyükdürsə block ediləcəyi onsuz da
    # bəllidir — full read əvəzinə baseline-i stat.st_size ilə təxmin et.
    try:
        file_size = file_path.stat().st_size
    except OSError:
        sys.exit(0)

    # ~80 char/line ortalama → byte-based heuristic line count.
    # Real read yalnız böyük fayllarda və ya limit-bounded Read-də olsun.
    if limit_val is None and file_size > 200_000:
        # Çox böyük fayl — HARD-BLOCK ETMİRİK (block redaktəni sındırır).
        # Yalnız xəbərdarlıq + icazə. Perf üçün read_bytes etmirik, baseline-i
        # stat ilə təxmin edirik. Read faktiki baş verir → real spend kimi say.
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
        sys.exit(0)

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

    if line_count >= THRESHOLD_WARN:
        # Soft warning — user (və ya AI) hələ də Read edə bilər, amma biz
        # event-i log-a salırıq ki, savings_report "soft" kateqoriyasında
        # tracking aparsın. Bu BASELINE-a əlavə olunmur (Read faktiki baş
        # verə bilər), yalnız MLA-nın guidance işini sayır.
        record = {
            "ts": time.time(),
            "type": "read_warn",
            "file": str(file_path),
            "lines": line_count,
            "estimated_baseline_tokens": estimated_baseline,
        }
        append_atomic(session_log, json.dumps(record, ensure_ascii=False))

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

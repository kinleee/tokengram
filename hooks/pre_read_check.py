#!/usr/bin/env python3
"""PreToolUse hook — Read tool-u indekslənmiş fayllar üçün tənzimləyir.

İki səviyyə:
  >= THRESHOLD_BLOCK  → exit 2 (block) + search_code istifadəsi tələb olunur
  >= THRESHOLD_WARN   → exit 0 (allow) + yumşaq məsləhət (stderr)
  < THRESHOLD_WARN    → exit 0 (silent allow)
"""
import json
import sys
import time
from pathlib import Path

THRESHOLD_BLOCK = 50
THRESHOLD_WARN = 30
INDEXED_EXTS = {".py", ".md", ".sol", ".sql"}


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        sys.exit(0)

    project_root = Path(__file__).resolve().parent.parent
    flag = project_root / ".mla_enforcement.flag"
    if not flag.exists() or flag.read_text(encoding="utf-8").strip().lower() != "on":
        sys.exit(0)

    if payload.get("tool_name") != "Read":
        sys.exit(0)

    file_path_str = payload.get("tool_input", {}).get("file_path", "")
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

    try:
        line_count = sum(1 for _ in file_path.open("rb"))
    except OSError:
        sys.exit(0)

    if line_count >= THRESHOLD_BLOCK:
        # Block hadisəsini session_log-a yaz — savings_report təxmini qənaəti
        # baseline-ə əlavə edəcək (Read-də ~10 tok/sətir, biz 0 işlətdik).
        session_log = project_root / ".mla_session_log.jsonl"
        try:
            record = {
                "ts": time.time(),
                "type": "read_block",
                "file": str(file_path),
                "lines": line_count,
                "estimated_baseline_tokens": line_count * 10,
            }
            with open(session_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

        msg = (
            f"MLA enforcement: '{file_path.name}' {line_count} setir, ChromaDB-de indeksli.\n"
            f"   Evvel: mcp__mla-agent__search_code mode=fast query=\"...\"\n"
            f"   Bypass lazimdirsa: /MlaOff (sonra /MlaOn ile geri qaytar)."
        )
        print(msg, file=sys.stderr)
        sys.exit(2)

    if line_count >= THRESHOLD_WARN:
        tip = (
            f"TIP: '{file_path.name}' {line_count} setir oxunur. "
            f"search_code mode=fast adeten eyni cavabi 200-500 token ile verir, "
            f"Read-de ise ~{line_count * 10} token gedir. (Block deyil, mesleht.)"
        )
        print(tip, file=sys.stderr)
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()

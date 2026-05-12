#!/usr/bin/env python3
"""PreToolUse hook — Read tool-u indekslənmiş fayllar üçün tənzimləyir.

İki səviyyə:
  >= THRESHOLD_BLOCK  → exit 2 (block) + search_code istifadəsi tələb olunur
  >= THRESHOLD_WARN   → exit 0 (allow) + yumşaq məsləhət (stderr)
  < THRESHOLD_WARN    → exit 0 (silent allow)
"""
import json
import sys
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

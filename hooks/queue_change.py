"""
============================================
hooks/queue_change.py — PostToolUse Hook (Sürətli)
============================================
MƏRHƏLƏ 8b: Claude Code Edit/Write/MultiEdit-dən sonra
çağırır. Bu skript yalnız fayl yolunu pending növbəsinə
yazır — ChromaDB və ya embedding modelini yükləmir.

Niyə belə? Hər redaktədə 3-5 saniyəlik Python+Chroma
yüklənməsi Claude Code-u yavaşladar. Növbə strategiyası:
- Bu skript: ~50ms (yalnız fayl yazır)
- Stop hook (flush_queue.py): bir dəfə işləyir, hamısını birləşdirir

Stdin-dən gələn JSON formatı:
{
  "tool_name": "Edit" | "Write" | "MultiEdit",
  "tool_input": {"file_path": "..."},
  "cwd": "...",
  ...
}
"""

import json
import sys
from pathlib import Path

# Layihə kökü = bu skriptin valideyninin valideyni
PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUEUE_FILE = PROJECT_ROOT / ".mla_pending.txt"

# Layihəmizin config-indən import etmədən sadə siyahı
# DİQQƏT: config.py-dəki EXCLUDED_DIRS ilə sinxron saxlamaq lazımdır.
SUPPORTED_EXTENSIONS = {".py", ".sol", ".sql", ".md"}
EXCLUDED_DIRS = {
    "chroma_db", "__pycache__", ".git", "node_modules",
    "venv", ".venv", "env", ".env", "dist", "build",
    ".eggs", "models_cache", ".idea", ".vscode",
    ".claude", ".aider", ".cursor", ".antigravity", ".mla",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "site-packages", "target", "out", ".next", ".nuxt",
}
EXCLUDED_FILE_PATTERNS = (".mla_pending", ".mla_session_log", ".file_hashes")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Pis JSON — sakit çıx, Claude Code-u bloklamayaq
        return 0

    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not file_path:
        return 0

    p = Path(file_path)

    # Filtrlər
    if p.suffix not in SUPPORTED_EXTENSIONS:
        return 0
    if any(part in EXCLUDED_DIRS for part in p.parts):
        return 0
    if any(p.name.startswith(pat) for pat in EXCLUDED_FILE_PATTERNS):
        return 0

    # Növbəyə əlavə et (idempotent — eyni yol çoxlu dəfə ola bilər,
    # flush_queue.py duplikatları silir)
    try:
        with open(QUEUE_FILE, "a", encoding="utf-8") as f:
            f.write(str(p.resolve()) + "\n")
    except IOError:
        # Yazıla bilmirsə, sakit çıx
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())

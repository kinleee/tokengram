"""
============================================
hooks/queue_change.py — PostToolUse Hook (Fast)
============================================
PHASE 8b: runs after Claude Code Edit/Write/MultiEdit.
This script only writes the file path into the pending
queue — it does NOT load ChromaDB or the embedding model.

Why? Loading Python+Chroma for 3-5 seconds on every edit
would slow Claude Code down. Queue strategy:
- This script: ~50ms (only writes a file)
- Stop hook (flush_queue.py): runs once, merges everything

JSON format received from stdin:
{
  "tool_name": "Edit" | "Write" | "MultiEdit",
  "tool_input": {"file_path": "..."},
  "cwd": "...",
  ...
}
"""

import json
import os
import sys
from pathlib import Path

# Central lists — in the install layout mla_constants sits next to the hook.
_INSTALL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_INSTALL_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from mla_constants import (
        SUPPORTED_EXTENSIONS,
        EXCLUDED_DIRS,
        EXCLUDED_FILE_PATTERNS,
        EXCLUDED_FILE_SUFFIXES,
    )
    from license_gate import enforcement_active
    from project_root import find_project_root
    from atomic_write import append_atomic
except Exception:
    # Dependency import failed — skip the queue hook silently, block nothing.
    sys.exit(0)

PROJECT_ROOT = find_project_root()
QUEUE_FILE = PROJECT_ROOT / ".mla_pending.txt"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Bad JSON — exit quietly, don't block Claude Code
        return 0

    # In off-mode don't grow the queue (so flush_queue doesn't run forever).
    if not enforcement_active(PROJECT_ROOT):
        return 0

    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not file_path:
        return 0

    p = Path(file_path)

    # Don't queue files in temporary directories. When ChromaDB/test scripts
    # created and edited a .py file under AppData\Local\Temp the hook wrote them
    # to the queue; the file is later deleted, but the line stayed as a "ghost".
    try:
        import tempfile
        _tmp = Path(tempfile.gettempdir()).resolve()
        _rp = p.resolve()
        if _rp == _tmp or _tmp in _rp.parents:
            return 0
    except Exception:
        pass

    # Filters (lowercase suffix to handle the Windows `.PY` != `.py` problem)
    if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return 0
    if any(part in EXCLUDED_DIRS for part in p.parts):
        return 0
    if any(p.name.startswith(pat) for pat in EXCLUDED_FILE_PATTERNS):
        return 0
    if any(p.name.endswith(sfx) for sfx in EXCLUDED_FILE_SUFFIXES):
        return 0

    # If already in the queue (.txt) or being drained (.processing), don't write
    # again — editing the same file repeatedly inflated the queue. The drainer
    # dedups anyway, but the counter/re-embed work grew. Case-sensitive (Windows).
    resolved = str(p.resolve())
    want = resolved.lower()
    processing = PROJECT_ROOT / ".mla_pending.processing"
    for qf in (QUEUE_FILE, processing):
        try:
            with open(qf, "r", encoding="utf-8") as fh:
                if any(line.strip().lower() == want for line in fh):
                    return 0
        except OSError:
            pass
    append_atomic(QUEUE_FILE, resolved)
    return 0


if __name__ == "__main__":
    sys.exit(main())

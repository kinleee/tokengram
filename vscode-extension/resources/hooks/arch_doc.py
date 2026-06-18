#!/usr/bin/env python3
"""Stop hook (1-ci sira): .mla_arch.md auto-maintained architecture doc.

`savings_report.py`-dən ƏVVƏL işləməlidir, çünki session_log-u oxuyur.
State `.mla_arch_state.json`-da saxlanır, hər run-da render olunur.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Windows-da gələcəkdə stderr-ə Azərbaycanca log yazsaq, savings_report
# ilə eyni cp1252 escape problemi olmasın. Defensive default.
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
from project_root import find_project_root
from atomic_write import write_atomic

PROJECT_ROOT = find_project_root()
SESSION_LOG = PROJECT_ROOT / ".mla_session_log.jsonl"
ARCH_STATE = PROJECT_ROOT / ".mla_arch_state.json"
ARCH_DOC = PROJECT_ROOT / ".mla_arch.md"

MAX_RECENT_SEARCHES = 20


def _normalize_path(raw: str) -> str:
    """Windows case-insensitive path normalize: lowercase forward-slash POSIX."""
    try:
        p = Path(raw).resolve()
        try:
            rel = p.relative_to(PROJECT_ROOT)
            return rel.as_posix()
        except ValueError:
            return p.as_posix().lower()
    except (OSError, ValueError):
        return raw.replace("\\", "/")


def load_state() -> dict:
    if not ARCH_STATE.exists():
        return {"files": {}, "recent_searches": [], "total_searches": 0}
    try:
        data = json.loads(ARCH_STATE.read_text(encoding="utf-8"))
        data.setdefault("files", {})
        data.setdefault("recent_searches", [])
        data.setdefault("total_searches", 0)
        return data
    except (json.JSONDecodeError, OSError):
        return {"files": {}, "recent_searches": [], "total_searches": 0}


def save_state(state: dict) -> None:
    # Atomic: kill -9 və ya power loss-da `.mla_arch_state.json` korrupt qalmasın
    # (load_state silent reset edirdi — bütün files/recent_searches itirdik).
    write_atomic(ARCH_STATE, json.dumps(state, ensure_ascii=False, indent=2))


def render_doc(state: dict) -> None:
    files_sorted = sorted(
        state["files"].items(),
        key=lambda kv: (-kv[1], kv[0]),
    )
    recent = state["recent_searches"]

    lines = [
        f"# {tr('arch_title')}",
        "",
        f"*{tr('arch_meta_last_updated')}: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*  ",
        f"*{tr('arch_meta_files')}: {len(state['files'])}*  ",
        f"*{tr('arch_meta_total_searches')}: {state['total_searches']}*  ",
        f"*{tr('arch_meta_recent')}: {len(recent)} ({tr('arch_meta_max')} {MAX_RECENT_SEARCHES})*",
        "",
        tr("arch_intro"),
        "",
        "---",
        "",
        tr("arch_files_heading"),
        "",
    ]
    if not files_sorted:
        lines.append(tr("arch_files_empty"))
    else:
        for path, count in files_sorted:
            lines.append(tr("arch_files_entry", path=path, count=count))

    lines.extend([
        "",
        "---",
        "",
        tr("arch_recent_heading", n=len(recent)),
        "",
    ])
    if not recent:
        lines.append(tr("arch_recent_empty"))
    else:
        no_results = tr("arch_recent_no_results")
        for entry in reversed(recent):
            ts_raw = entry.get("ts", 0)
            try:
                ts = datetime.fromtimestamp(ts_raw).strftime("%m-%d %H:%M")
            except (OSError, ValueError):
                ts = "??-?? ??:??"
            query = entry.get("query", "")
            files = entry.get("files", [])
            files_str = ", ".join(files[:5]) if files else no_results
            extra = f" +{len(files)-5}" if len(files) > 5 else ""
            lines.append(f"- **{ts}** — `\"{query}\"` → {files_str}{extra}")

    write_atomic(ARCH_DOC, "\n".join(lines) + "\n")


def main() -> int:
    try:
        sys.stdin.read()
    except Exception:
        pass

    # MLA OFF → arch doc-u yeniləmə, heç nə etmə
    if not enforcement_active(PROJECT_ROOT):
        return 0

    if not SESSION_LOG.exists():
        return 0

    try:
        text = SESSION_LOG.read_text(encoding="utf-8")
    except OSError:
        return 0

    state = load_state()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Yalnız search_code event-ləri arch doc-a düşür — read_block /
        # grep_search / bash_inspect / read_pass arch-da yer tutmasın
        # (əvvəl recent_searches boş "no results" sətirləri ilə dolurdu).
        if entry.get("type", "search_code") != "search_code":
            continue

        files_raw = entry.get("files", {})
        normalized = sorted({_normalize_path(f) for f in files_raw.keys()})

        for f in normalized:
            state["files"][f] = state["files"].get(f, 0) + 1

        state["total_searches"] += 1
        state["recent_searches"].append({
            "ts": entry.get("ts", 0),
            "query": entry.get("query", ""),
            "files": normalized,
        })

    state["recent_searches"] = state["recent_searches"][-MAX_RECENT_SEARCHES:]

    save_state(state)
    render_doc(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())

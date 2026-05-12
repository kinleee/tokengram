#!/usr/bin/env python3
"""Stop hook (1-ci sira): .mla_arch.md auto-maintained architecture doc.

`savings_report.py`-dən ƏVVƏL işləməlidir, çünki session_log-u oxuyur.
State `.mla_arch_state.json`-da saxlanır, hər run-da render olunur.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSION_LOG = PROJECT_ROOT / ".mla_session_log.jsonl"
ARCH_STATE = PROJECT_ROOT / ".mla_arch_state.json"
ARCH_DOC = PROJECT_ROOT / ".mla_arch.md"
ENFORCEMENT_FLAG = PROJECT_ROOT / ".mla_enforcement.flag"

MAX_RECENT_SEARCHES = 20


def _is_enforcement_on() -> bool:
    if not ENFORCEMENT_FLAG.exists():
        return False
    try:
        return ENFORCEMENT_FLAG.read_text(encoding="utf-8").strip().lower() == "on"
    except OSError:
        return False


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
    ARCH_STATE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def render_doc(state: dict) -> None:
    files_sorted = sorted(
        state["files"].items(),
        key=lambda kv: (-kv[1], kv[0]),
    )
    recent = state["recent_searches"]

    lines = [
        "# MLA Auto-Generated Architecture",
        "",
        f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*  ",
        f"*Files discovered: {len(state['files'])}*  ",
        f"*Total `search_code` calls processed: {state['total_searches']}*  ",
        f"*Recent search history kept: {len(recent)} (max {MAX_RECENT_SEARCHES})*",
        "",
        "Bu fayl `search_code` çağırışlarından avtomatik tərtib olunur. ",
        "İnsan yazısı deyil — Stop hook hər task sonunda yeniləyir. ",
        "Manual redaktə yox; faydalı olsa silinə bilər (yenidən qurulacaq).",
        "",
        "---",
        "",
        "## Tapılmış Fayllar (search_code-da görsənmə tezliyinə görə)",
        "",
    ]
    if not files_sorted:
        lines.append("*(Hələ heç bir fayl tapılmayıb. İlk search_code çağırışından sonra doldurulacaq.)*")
    else:
        for path, count in files_sorted:
            lines.append(f"- `{path}` — {count} dəfə")

    lines.extend([
        "",
        "---",
        "",
        f"## Son {len(recent)} Axtarış Mövzusu (yeni → köhnə)",
        "",
    ])
    if not recent:
        lines.append("*(Hələ heç bir axtarış tarixçəsi yoxdur.)*")
    else:
        for entry in reversed(recent):
            ts_raw = entry.get("ts", 0)
            try:
                ts = datetime.fromtimestamp(ts_raw).strftime("%m-%d %H:%M")
            except (OSError, ValueError):
                ts = "??-?? ??:??"
            query = entry.get("query", "")
            files = entry.get("files", [])
            files_str = ", ".join(files[:5]) if files else "*(nəticə yox)*"
            extra = f" +{len(files)-5}" if len(files) > 5 else ""
            lines.append(f"- **{ts}** — `\"{query}\"` → {files_str}{extra}")

    ARCH_DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    try:
        sys.stdin.read()
    except Exception:
        pass

    # MLA OFF → arch doc-u yeniləmə, heç nə etmə
    if not _is_enforcement_on():
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

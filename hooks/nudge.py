#!/usr/bin/env python3
"""NON-BLOCKING steering (nudge) helper for Tokengram hooks.

Goal: when the agent reads a full file / does a broad Grep, deliver a short
MODEL-VISIBLE message telling it to "use search_code next time" — but WITHOUT
ever blocking the tool or raising an error.

Mechanism (Claude Code official contract):
  writing {"hookSpecificOutput": {"hookEventName": ..,
  "additionalContext": ..}} to stdout with exit 0 → the tool runs normally + the
  text reaches the model.
  `permissionDecision: "deny"` / exit 2 are NEVER used (those block).

Rate-limit: to avoid filling the model's context
  * at most GLOBAL_CAP nudges per window (shared across all hooks),
  * the same key is not nudged again within FILE_COOLDOWN.
State is stored per-machine in `chroma_db/.nudge_state.json` (chroma_db is already
gitignored in every project → no new gitignore line needed). If chroma_db is
missing, it falls back to the project root.

Every function is fully guarded: any error → NO nudge, but the hook never breaks.
"""
import json
import sys
import time
from pathlib import Path

GLOBAL_WINDOW = 3600   # seconds — rate-limit window
GLOBAL_CAP = 6         # max number of nudges within the window (all combined)
FILE_COOLDOWN = 1800   # the same key is not nudged again within this period


def _state_path(project_root: Path) -> Path:
    chroma = project_root / "chroma_db"
    if chroma.is_dir():
        return chroma / ".nudge_state.json"
    return project_root / ".mla_nudge_state.json"


def _load(p: Path) -> dict:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"events": [], "keys": {}}


def should_nudge(project_root, key) -> bool:
    """May we nudge for `key` now? If allowed, records it and returns True.

    Rate-limit: <= GLOBAL_CAP nudges within GLOBAL_WINDOW AND the same key is
    not repeated sooner than FILE_COOLDOWN. Best-effort — in a race the worst
    case is one extra nudge (harmless). Any error -> False (no nudge); the hook
    never breaks.
    """
    try:
        now = time.time()
        p = _state_path(Path(project_root))
        st = _load(p)
        events = [t for t in st.get("events", []) if isinstance(t, (int, float)) and now - t < GLOBAL_WINDOW]
        keys = {
            k: t for k, t in st.get("keys", {}).items()
            if isinstance(t, (int, float)) and now - t < GLOBAL_WINDOW
        }
        if len(events) >= GLOBAL_CAP:
            _save(p, {"events": events, "keys": keys})
            return False
        last = keys.get(key)
        if last is not None and now - last < FILE_COOLDOWN:
            return False
        events.append(now)
        keys[key] = now
        _save(p, {"events": events, "keys": keys})
        return True
    except Exception:
        return False


def _save(p: Path, state: dict) -> None:
    try:
        p.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


def emit(additional_context, event="PreToolUse") -> None:
    """Write the non-blocking additionalContext JSON to stdout (then exit 0).

    `permissionDecision` is NOT set -> the tool runs through its normal flow.
    Only text is added for the model. Any error is swallowed — the hook never
    breaks.
    """
    try:
        sys.stdout.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": additional_context,
            }
        }))
        sys.stdout.flush()
    except Exception:
        pass

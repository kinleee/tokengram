"""Shared walk-up helper for enforcement hooks.

CLAUDE_PROJECT_DIR (or os.getcwd()) only matches when the user opens the
project's true root. If the user opens a subfolder (e.g. `vscode-extension/`
within a monorepo) the hooks would scope to that subfolder and reject Read
events on parent files. The bar's `savingsReader.findProjectRoot()` already
walks up; we mirror it here so hooks and the bar agree on one project root.

Priority order matches savingsReader.ts:
  1. .mla_savings_history.jsonl  (strongest signal — real data lives here)
  2. .claude/settings.json       (hooks are configured here)
  3. .mcp.json                   (MCP server is configured here)
  4. .mla_enforcement.flag       (last resort; can appear in many places)
"""
import os
from pathlib import Path

_MAX_DEPTH = 8


def find_project_root(start_dir: Path | str | None = None) -> Path:
    start = Path(start_dir or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()

    def walk_up(predicate) -> Path | None:
        cur = start
        for _ in range(_MAX_DEPTH):
            if predicate(cur):
                return cur
            parent = cur.parent
            if parent == cur:
                return None
            cur = parent
        return None

    def _nonempty_history(d: Path) -> bool:
        h = d / ".mla_savings_history.jsonl"
        try:
            return h.exists() and h.stat().st_size > 0
        except OSError:
            return False

    return (
        walk_up(_nonempty_history)
        or walk_up(lambda d: (d / ".claude" / "settings.json").exists())
        or walk_up(lambda d: (d / ".mcp.json").exists())
        or walk_up(lambda d: (d / ".mla_enforcement.flag").exists())
        or start
    )

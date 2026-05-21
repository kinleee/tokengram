---
description: Re-index ChromaDB for the current project from scratch (apply new extension list, refresh stale embeddings)
---

Re-index the workspace using the Tokengram MCP server, not a direct `python main.py` call.

Steps:

1. Resolve the absolute path of the current workspace root (use `$CLAUDE_PROJECT_DIR`).
2. Call the MCP tool `mcp__mla-agent__index_directory` with arguments `path=<absolute workspace root>` and `fresh=true`.
3. Report the result in one sentence: chunk/file count and elapsed time, or the error if any.

Fallback if MCP is not connected ("Connection closed" or tool not found):
- Tell the user the MCP server is not running and they should reload Claude Code (so the MCP stdio handshake re-runs), then re-invoke `/MlaReindex`.
- Do NOT shell out to `python "$CLAUDE_PROJECT_DIR/main.py"` — `main.py` only exists in the Tokengram source tree, not in user projects.

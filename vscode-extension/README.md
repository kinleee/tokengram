# Tokengram — Token-saving memory layer for AI coding assistants

Stop paying for AI to re-read your codebase. **Tokengram** indexes your project locally and serves only the relevant chunks to Claude Code (and other MCP-capable assistants) via hybrid RAG search.

> **Measured token savings: ~70%** on a typical Python project. Local-only. Your code never leaves the machine.
>
> **Free 3-day trial, then $3/month** to keep the license active. Subscribe at [tokengram.click](https://tokengram.click). One key per machine; cancel anytime.

---

## Why Tokengram

When you ask Claude a question, it normally reads whole files into its context window — 5–10K input tokens per query. Tokengram pre-vectorizes your project and returns only the **3–5 most relevant chunks** when Claude asks. So:

- ⚡ **~70% fewer input tokens** → cheaper API calls
- 🔒 **Local-only** — embeddings + search run on your machine
- ♻️ **Auto re-index** — saved files are picked up automatically
- 🎯 **Hybrid search** — semantic (meaning) + BM25 (keyword) + cross-encoder reranker
- 📊 **Live status bar** — see real-time savings as you code

## When it works

- ✅ Medium-to-large Python / JS / TS / Go / Rust / C# projects (50+ files)
- ✅ Contextual questions: *"where is this function called from?"*
- ✅ Refactoring (gathering all touch points)

## When it doesn't (yet)

- ❌ Projects with < 20 files — Claude can just read them all
- ❌ Machines with < 4 GB RAM
- ❌ Systems without Python 3.12+ installed
- ❌ macOS — not supported yet (Windows & Linux today; macOS in progress)

---

## Quick start

1. **Install this extension** from the Marketplace.
2. Open a workspace and run **`Tokengram: Open menu`** from the Command Palette (`Ctrl+Shift+P`).
3. Follow the setup wizard:
   - Tokengram detects Python 3.12+
   - Creates an isolated environment in `~/.tokengram/`
   - Asks for your license key
   - Configures Claude Code hooks for the workspace
4. Open Claude Code and start asking questions — savings appear in the status bar.

## Requirements

- **Platform** — Windows (x64) or Linux (x64). macOS support is in progress.
- **VS Code** 1.85+
- **Python** 3.12 or newer ([download](https://www.python.org/downloads/))
- **Claude Code** (or any MCP-compatible assistant)
- **License key** — $3/month, [get one at tokengram.click](https://tokengram.click/buy)

## Status bar

A live odometer in the bottom-right shows tokens saved in real time:

```
● Tokengram: 10.0k saved · 73%  ⚡+7.4k now
```

Hover for the full breakdown (search, grep, read-block, bash inspect, today's totals). Click the bar for the action menu — toggle enforcement, refresh, reindex, set license, reset history.

## Privacy

Tokengram is **fully local**. No code, no queries, no embeddings ever leave your machine. The only network call is one-time license validation (cached for 7 days offline).

## License

Commercial. See [LICENSE.txt](./LICENSE.txt). $3/month subscription required for activation after a 3-day trial.

## Support

- Issues: [github.com/kinleee/tokengram/issues](https://github.com/kinleee/tokengram/issues)
- Email: n.ilkin.humbatov@gmail.com

---

*Built by Ilkin Humbatov.*

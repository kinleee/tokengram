# Tokengram — Hybrid RAG Memory Layer for AI Assistants

> Azərbaycanca versiya: [README.az.md](README.az.md)

Local MCP server that lets Claude Code (and other MCP-capable AI assistants)
search your project via hybrid RAG instead of `Read`-ing whole files.
On search/Read-heavy workflows we measure **up to ~70% fewer input tokens**;
savings drop on edit-heavy refactors (Edit, raw `Bash` output, and
system-prompt overhead are not routed through Tokengram).

**Progressive RAM:** 93 MB (BM25-only) → 700 MB (semantic) → 900 MB (+ reranker).

## What it is

When you ask Claude Code a question about your code, the assistant normally
reads whole files into its context window — 5–10K input tokens per query. Tokengram
pre-vectorizes your project and returns only the **3–5 most relevant
chunks** when Claude asks. So:

- ⚡ **Up to ~70% fewer input tokens on search/Read-heavy work** → cheaper API calls
- 🔒 **Local-only** — your code never leaves the machine (local embeddings,
  local search)
- ♻️ **Auto re-index** — saved files are picked up by the MCP server
  automatically
- 🎯 **Hybrid search** — semantic (meaning) + BM25 (keyword) + cross-encoder
  reranker

## When it works
- ✅ Medium-to-large Python / JS / Go / Rust projects (50+ files)
- ✅ Contextual questions: *"where is this function called from?"*
- ✅ Refactoring (gathering all touch points)

## When it doesn't (yet)
- ❌ Projects with < 20 files — Claude can just read them all
- ❌ Machines with < 4 GB RAM (embedding + reranker need headroom)
- ❌ Systems without Python installed

---

## Install (~3 minutes)

### Requirements
- Python 3.10+
- VS Code + Claude Code extension
- 4 GB RAM (8 GB recommended)
- ~500 MB disk (for model cache)

### Windows
```powershell
git clone <repo-url> mla-agent
cd mla-agent
./setup.ps1
```

### macOS / Linux
```bash
git clone <repo-url> mla-agent
cd mla-agent
./setup.sh
```

### After install
1. **Close VS Code completely and reopen it** (so it picks up the new MCP
   server entry).
2. In Claude Code, run `/mcp` — `mla-agent` should appear as `connected`.
3. Ask a question:
   > "Use mla-agent.search_code — where is authentication handled?"

Claude calls the MCP tool automatically, receives the top-4 matching chunks
as context, and answers.

---

## Indexing another project

Each project needs its own index.

### Option 1 — run setup again with a project path
```powershell
./setup.ps1 -ProjectDir "C:\path\to\my-project"
```

### Option 2 — direct command
```bash
python main.py index /path/to/my-project --fresh
```

> **Note:** `chroma_db/` currently lives inside the Tokengram folder, so only
> one project can be indexed at a time. Multi-project support is on the
> roadmap.

---

## CLI

```bash
python main.py index <dir> [--fresh]    # Index a project
python main.py stats                     # Index statistics
python main.py route <dir>               # Smart router suggestion
python main.py reset --yes               # Wipe the index
python main.py watch <dir>               # Auto re-index (Ctrl+C to stop)
python main.py ask "question"            # CLI-only (requires API key)
```

---

## MCP tools

Claude Code discovers these automatically and calls them on demand:

| Tool | What it does |
|---|---|
| `search_code(query, top_k, mode, file_type)` | 3-tier search (see below) |
| `index_directory(path, fresh)` | Index a project |
| `index_file(path)` | Re-index a single file |
| `get_stats()` | Index statistics |
| `route_project(path)` | Project-size-aware recommendation |

### `search_code` modes (progressive RAM)

| `mode` | RAM delta | First call | Best for |
|---|---|---|---|
| `"fast"` (default) | **0 MB** | ~50 ms | Function / class / file-name lookup, syntactic search |
| `"semantic"` | +400–700 MB | 30–60 s cold | Conceptual queries (*"how does auth work?"*) |
| `"rerank"` | +200 MB | +30 s first | Maximum ranking quality |

Ideally Claude defaults to `"fast"`. If a syntactic result is enough, it
stops. For conceptual answers it escalates to `"semantic"`. Reranker is
reserved for the highest-stakes picks.

---

## Slash commands

Drop-in actions inside Claude Code (each wraps the back-end Python script
of the same name; the VS Code status-bar QuickPick calls them too):

| Command | What it does |
|---|---|
| `/MlaOn` | Enable Read-enforcement (block large indexed files) |
| `/MlaOff` | Disable enforcement |
| `/MlaRefreshBar` | Force the status bar to refresh |
| `/MlaResetBar` | Reset savings history (old history is backed up) |
| `/MlaArch` | Show the auto-generated architecture doc |
| `/MlaSync` | Manually flush session log → history |
| `/MlaReindex` | Full re-index after extension list changes |

See [SLASH_COMMANDS.md](SLASH_COMMANDS.md) for behaviour details and the
4-source token-tracking model.

---

## Supported file types (36 extensions)

```
.py .sol .sql .md
.ts .tsx .js .jsx .mjs .cjs
.go .rs .java .kt .cs .cpp .cc .cxx .c .h .hpp
.rb .php .swift .dart
.html .css .scss
.json .yaml .yml .toml
.sh .bash .ps1 .tf
```

Excluded by default: `node_modules/`, `dist/`, `build/`, `target/`,
`.venv/`, `.next/`, … plus lock files (`package-lock.json`, `Cargo.lock`,
`go.sum`, …), minified bundles (`*.min.js`, `*.bundle.js`), source maps,
and any file > **1 MB**. All filters live in `mla_constants.py`.

---

## Localization

User-facing strings are localized. Two languages are bundled out of the
box: **English** (default) and **Azerbaijani**.

```bash
# Linux / macOS
export MLA_LANG=az   # Azerbaijani
export MLA_LANG=en   # English (default)

# Windows PowerShell
$env:MLA_LANG = 'az'
```

The VS Code extension picks its locale from `vscode.env.language` (your
VS Code display language).

**To add another language**: copy `messages/en.json` to
`messages/<code>.json`, translate the values, and add the code to
`_SUPPORTED` in [i18n.py](i18n.py). For the extension, add a new entry to
`MESSAGES` and to `detectLocale()` in
[vscode-extension/src/i18n.ts](vscode-extension/src/i18n.ts).

---

## VS Code status bar

The widget at the bottom-right shows a live `X.Xk saved · YY%` counter
based on the last 24 hours of activity. Hovering reveals a breakdown
(search / Grep / Read-block) plus lifetime totals.

Click the widget to open a QuickPick with all 6 actions (toggle, refresh,
arch doc, sync, re-index, reset) — no terminal typing needed.

---

## Auto re-index

Two parallel mechanisms feed the same queue (`.mla_pending.txt`); the
MCP server's background worker drains it:

### 1. Built-in watcher (default; works in **every IDE**)
The MCP server uses `watchdog` to watch the project folder. VS Code,
Antigravity, Cursor, plain editors — all good. No hooks needed.

- Override the watched directory: `MLA_WATCH_DIR=/path/to/project`
- Disable: `MLA_DISABLE_WATCHER=1`
- Debounce: 2 s (rapid saves are coalesced)

### 2. Claude Code hooks (Claude Code only)
- `PostToolUse` (~50 ms) after every `Edit` / `Write` / `MultiEdit` —
  queues the file
- `Stop` — drains the queue and updates the architecture doc

Both mechanisms cooperate: the drainer hashes + deduplicates, so no file
is re-indexed twice.

---

## FAQ

### Do I need an API key?
**No.** When you use Tokengram via the MCP server inside Claude Code, all
reasoning happens in Claude. An API key is only needed for the standalone
CLI command `python main.py ask`.

### Why is the first search slow?
The first MCP `search_code` call takes 10–30 s — the embedding model
loads into RAM. Subsequent calls are ~100 ms.

### What's the disk footprint?
- Embedding model: ~130 MB (`bge-small-en-v1.5`)
- Reranker model: ~90 MB (`ms-marco-MiniLM-L-6-v2`)
- ChromaDB index: ~5–10 KB per file
- Total for a 100-file project: ~220 MB.

### Something broke?
Check [PROBLEMS.md](PROBLEMS.md) — 14 issues encountered during
development and how each was resolved. The test pass record is in
[TEST_REPORT.md](TEST_REPORT.md) (66/66 green).

---

## Project layout

```
mla-agent/
├── config.py              # All parameters (re-exports from mla_constants)
├── mla_constants.py       # Single source for extension / dir / file filters
├── i18n.py                # tr() — localized message lookup
├── messages/
│   ├── en.json            # English strings (default)
│   └── az.json            # Azerbaijani strings
├── document_loader.py     # AST + regex + fallback chunking
├── vector_store.py        # ChromaDB wrapper
├── search_engine.py       # Hybrid (semantic + BM25 + reranker)
├── llm_agent.py           # Standalone CLI agent (optional)
├── smart_router.py        # Project-size-aware mode selector
├── file_watcher.py        # Standalone watchdog (optional)
├── main.py                # CLI entry point
├── mcp_server.py          # MCP server for Claude Code
├── hooks/                 # All Stop / PreToolUse / PostToolUse hooks
├── tests/                 # 5 phase suites, 66 cases total
├── vscode-extension/      # Status-bar widget + QuickPick menu
├── .mcp.json              # Claude Code MCP registration
├── .claude/
│   ├── settings.json      # Hook configuration
│   └── commands/          # Slash command definitions
├── setup.ps1, setup.sh    # Install scripts
├── TEST_PLAN.md, TEST_REPORT.md
└── PROBLEMS.md
```

---

## License

Commercial. See [vscode-extension/LICENSE.txt](vscode-extension/LICENSE.txt). Feedback: n.ilkin.humbatov@gmail.com

# MLA Agent — Slash Commands

Ready-to-use slash commands inside Claude Code. All definitions live in
`.claude/commands/`. Each one is a thin wrapper around the back-end
Python script of the same name — the VS Code status-bar QuickPick calls
the very same scripts, so behaviour stays identical across UIs.

| Command | What it does | Script |
|---|---|---|
| `/MlaOn` | Enable Read-enforcement — block large (≥50 lines) indexed files, force the assistant to use `search_code` | `hooks/toggle_mla.py on` |
| `/MlaOff` | Disable enforcement — `Read` is unrestricted, `search_code` is optional | `hooks/toggle_mla.py off` |
| `/MlaRefreshBar` | Force the VS Code status bar to refresh immediately (`mtime` touch) | `hooks/refresh_bar.py` |
| `/MlaResetBar` | Reset the savings history (old history is moved to a backup); the bar starts from zero | `hooks/reset_savings.py` |
| `/MlaArch` | Show the auto-generated architecture doc — file map sorted by `search_code` occurrence + last 20 search topics | `hooks/show_arch.py` |
| `/MlaSync` | Manually flush pending `.mla_session_log.jsonl` entries into the history (recovery when the Stop hook is skipped) | `hooks/savings_report.py` |
| `/MlaReindex` | Full `--fresh` ChromaDB re-index for the current project. Run after adding a new language/extension or when the index is stale | `main.py index . --fresh` |

## Enforcement behaviour

The PreToolUse hook `hooks/pre_read_check.py` inspects every `Read` call
and only acts on files inside the project tree with an indexed extension
— the list lives in `mla_constants.SUPPORTED_EXTENSIONS` (Python, TS/JS,
Go, Rust, Java, Kotlin, C/C++/C#, Ruby, PHP, Swift, Dart, HTML/CSS/SCSS,
JSON/YAML/TOML, shell, Terraform). After adding a new extension, run
`/MlaReindex` so ChromaDB actually contains content for that file type.

| Line count | Behaviour |
|---|---|
| ≥ 50 | **Block** (exit 2) — assistant must use `search_code` |
| 30 – 49 | **Allow + soft tip** (stderr) — `search_code` would be cheaper |
| < 30 | **Silent allow** — savings are minimal |

State file: `.mla_enforcement.flag` (`on` / `off`). When **OFF**, none of
`arch_doc.py`, `savings_report.py`, `pre_read_check.py` do anything — the
counter freezes and the session log stops accumulating.

## Token-tracking sources (4 types)

The Stop hook `savings_report.py` reads `.mla_session_log.jsonl` after
each task and sums these four event types:

| Type | Source | Baseline | Actual |
|---|---|---|---|
| **search_code** | MCP tool call | total size of all returned files | tokens in the returned chunks |
| **Grep** (`post_grep_check.py`) | Grep tool on indexed file (≥30 lines) | `lines * 10` | `baseline * 15%` (heuristic) |
| **Bash-inspect** (`post_bash_check.py`) | Inspect command on indexed file (≥50 lines). Detected keywords: `cat / head / tail / wc / less / more / awk / sed / type / findstr / gc / Get-Content / Select-String / sls / git show <ref>:<path>` | `lines * 10` | `baseline * 20%` (heuristic) |
| **Read-block** (`pre_read_check.py`) | A block event (≥50 lines) | `lines * 10` | 0 (file was not read) |

Each baseline contributes to the total; **actual** is recorded only when
the assistant actually consumed tokens (blocks have 0 actual). The status
bar shows the total; hovering the widget reveals the search / Grep /
Read-block breakdown (bash-inspect is folded into the total).

The 15 % / 20 % ratios are heuristics — true Grep/Bash output token counts
aren't known to the hook, so we estimate against the Read alternative.
The estimate skews conservative; real savings are usually higher.

## Localization (`MLA_LANG`)

User-facing strings produced by the hooks (block message, savings
summary, missing-arch-doc note, etc.) are routed through `i18n.py`. The
default locale is **English**. Switch to Azerbaijani:

```bash
export MLA_LANG=az     # Linux / macOS
$env:MLA_LANG = 'az'   # Windows PowerShell
```

The VS Code extension picks its locale from `vscode.env.language`. See
the README for details on adding more languages.

## Auto-generated architecture doc

`hooks/arch_doc.py` runs as the first Stop hook (before
`savings_report.py`) and incrementally folds the day's `search_code`
calls into:

- `.mla_arch.md` — human-readable file map + recent searches
- `.mla_arch_state.json` — internal counters

**Structure of the doc:**
- **Files discovered** — sorted by occurrence in `search_code` results;
  files seen most often are the highest-signal entry points.
- **Last 20 search topics** — newest → oldest, with the files each query
  returned. Skim this at the start of a session to recover context
  without burning tokens.

Repeated questions sometimes get answered from the doc alone, allowing
`search_code` to be skipped → extra savings.

**Local-only files (in `.gitignore`):**
- `.mla_arch.md` (auto-generated, per-machine)
- `.mla_arch_state.json` (internal state)
- `.mla_enforcement.flag` (runtime state)
- `.mla_savings_history.jsonl{,.bak*}` (per-machine analytics)

## VS Code extension

The status-bar widget (`erp-intel.mla-agent`) reads
`.mla_savings_history.jsonl` and shows the last-24-hour savings. A
**filled green dot** means enforcement is ON, an **empty outline** means
OFF.

`FileSystemWatcher`s on both `.mla_enforcement.flag` and
`.mla_savings_history.jsonl` ensure the bar updates immediately when
either file changes, with a 30-second poll as a safety net.

Click the widget to open a QuickPick with all seven actions above —
no terminal typing required.

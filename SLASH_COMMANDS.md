# MLA Agent — Slash Commands

Ready-to-use slash commands inside Claude Code. All definitions live in
`.claude/commands/`. Each one is a thin wrapper around the back-end
Python script of the same name — the VS Code status-bar QuickPick calls
the very same scripts, so behaviour stays identical across UIs.

| Command | What it does | Script |
|---|---|---|
| `/MlaOn` | Enable Read-guidance — nudge the assistant toward `search_code` on large indexed files (warn-only, nothing is blocked) | `hooks/toggle_mla.py on` |
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

There is **no hard block** (an earlier ≥50-line block broke editing —
`Edit` requires a prior `Read`). The hook only warns and logs:

| Read call | Behaviour |
|---|---|
| with `limit`/`offset` (chunked) | **Silent allow** — logged as `read_chunked` (baseline + spent) |
| full read, ≥ 250 lines | **Allow + tip** (stderr) — logged as `read_warn` + `read_pass` |
| full read, < 250 lines | **Silent allow** — logged as `read_pass` (real spend) |

State file: `.mla_enforcement.flag` (`on` / `off`). When **OFF** the hooks
do nothing — the counter freezes and the session log stops accumulating
(the log itself is left untouched to avoid racing a parallel writer).

## Token tracking — evidence-based attribution ("method 2", 2026-07-06)

The Stop hook `savings_report.py` reads `.mla_session_log.jsonl` after
each task. An event earns savings credit **only when the session itself
shows Tokengram caused the saving** — heuristic credits with no steering
evidence earn 0 (the old chunked/grep heuristics minted ~72% of the
displayed total with no evidence; that inflation is gone).

Credit tiers (strongest first):

| Tier | Evidence | Credit |
|---|---|---|
| **Tier 1 — replaced a read** | `search_code` surfaced a file that the agent later **edited without ever reading it** | full file size (capped at 10k/event), deduped per file |
| **Steered chunk/grep** | a search surfaced the file **before** the chunked Read / Grep happened | full-read alternative (capped); the chunk's own cost counts as spend |
| **Hunt** | search results never touched and the task completed — the snippets alone answered | server-computed `hunt_tokens` (keyword-rank simulation of finding the file without MLA) |
| **B1 — cancelled** | the agent read a surfaced file **in full** anyway | 0 — the search was pure overhead; its cost goes to the denominator |
| **Un-steered chunk/grep/bash** | the agent chunked/grepped on its own habit; no search pointed it there | 0 credit; the spend still counts (`ungated_spent_tokens`) |

Every history record is stamped `"method": 2`. The status bar sums
**only `method >= 2` records** — older records (written under the
inflationary heuristics) stay in `.mla_savings_history.jsonl` for audit
but are excluded from all displayed totals. Full reads, bash output and
cancelled searches all count as real spend, so the percentage is honest:
`saved / (saved + spent + untracked)`.

## Localization (`MLA_LANG`)

User-facing hook strings are routed through `i18n.py`
(`messages/en.json`). The product is currently **English-only** — the
`az.json` locale was removed before launch. `MLA_LANG` is still honored
for future locales; an unsupported value silently falls back to English.

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

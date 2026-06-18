# Changelog

All notable changes to the Tokengram VS Code extension will be documented here.

## [0.1.59] — 2026-06-17 — ships wheel 0.1.30

### Fixed — the per-file index queue (`⟳ N`) now actually starts and drains to zero
Three latent engine bugs meant a normally-launched MCP server never ran its background indexer — so edited files queued (`⟳ N`) but nothing ever indexed them, and the count stuck forever:
- **Background worker never started.** The `-m tokengram` entrypoint looked for a `serve()` function that didn't exist and silently fell back to a no-op path that started no drain worker. Added `serve()` so the worker, file watcher, and lazy model warm-up all start on every launch.
- **Queue watched the wrong folder (split-brain).** The pending-queue / state sidecar files were resolved relative to the compiled package directory instead of the project root, so the drainer watched an empty path while the real queue piled up at the project root. They now resolve to the same project root the hooks and status bar use.
- **Server was killed before it could serve (30 s handshake timeout).** A heavy model pre-import ran on the main thread *before* the MCP handshake; on low-RAM machines that import (10–40 s) pushed the MCP `initialize` past Claude Code's 30 s connection deadline, so the server was killed before it could connect or drain. The pre-import is removed; the model now loads lazily on a background thread *after* the handshake. The server now connects in ~1–3 s.

Net effect: a single edit shows `⟳ 1` and ticks down to `0`; the spinner disappears when indexing finishes.

### Fixed — stale dead-process lock files are cleaned across both lock locations
- Dead-process leftover lock files (`.tokengram.*.lock`) are now swept from both the canonical project-root location **and** the legacy package directory, so an orphaned lock from an old build can no longer wedge a live server. Only dead-PID locks are removed; live locks are never touched.

### Changed — build/dev directories excluded from auto-indexing
- `build_tmp/`, `dist_compiled/`, and the `tokengram/` build-staging directory are now excluded from the file watcher, so rebuilding the engine no longer floods the queue with build-artifact paths.

## [0.1.58] — 2026-06-17 — ships wheel 0.1.29

### Fixed — the background index queue no longer freezes at "N files pending" (multi-window RAM livelock)
- On a memory-constrained machine with several VS Code windows open, the per-file indexing queue could get stuck (e.g. `⟳ 97` that never decreased). Root cause: the background drainer ran on **every** MCP server, so a non-leader server would cold-load the ~700 MB embedding model just to drain — with 3 windows that meant 2–3 concurrent model loads, the machine paged everything to swap, and the drainer wedged in native code holding the write lock. The no-progress self-heal then couldn't even execute its own `os._exit` (its thread was starved), so the frozen server held the locks indefinitely and the queue never drained.
- Fix (wheel 0.1.29): **only the leader server drains/indexes.** The leader is the single instance that already warms the embedding model, so indexing never triggers a second model load — eliminating the RAM thrash that caused the freeze. If the leader dies, a follower is promoted within seconds and resumes draining; the `.processing` hand-off already prevents file loss. Result: the `⟳ N` count now ticks down to zero and the spinner disappears when indexing finishes, even with multiple windows open.

## [0.1.57] — 2026-06-17

### Fixed — `git add` no longer fails on the locked index lock file
- A held `.tokengram.writer.lock` (kept open by the running MCP server) cannot be read by `git`, so `git add .` failed **fatally** ("Permission denied … fatal: adding files failed") in any project where the lock file was not yet git-ignored — and it took the entire staging operation down with it, so even the files you *did* want to add were not staged. The extension now applies the Tokengram `.gitignore` block to **already-configured** projects on activation (previously only fresh setup got it), so existing projects are protected after one window reload. Idempotent (sentinel-guarded); only writes in a git repo or where a `.gitignore` already exists.

## [0.1.56] — 2026-06-17

### Fixed — status bar no longer flickers yellow during normal work
- The `DATA RESET` (yellow) warning used to strobe yellow↔green every few seconds: the Stop hook empties the session log after each task, which momentarily flipped the bar into the "data reset" state even while indexing was running and work was happening. The warning is now shown **only when the system is genuinely quiet** — no files indexing and no tasks in the last 24h — so a freshly-reset-but-actively-working project stays green. (The reset notice still appears on a truly idle bar, as intended.)

### Added — auto-index on editor save + visible pending count
- Saving a file in the VS Code editor (Ctrl+S) now **immediately** queues it for indexing and the status bar shows the spinning `⟳ N` badge the instant you save — previously only Claude Code edits (via the PostToolUse hook) and the slower Python file-watcher (2 s debounce) caught saves, so the spinner often never appeared. No new process is spawned: the save handler only appends to the index queue; the already-running MCP background worker does the embedding (no spawn-storm / RAM cost). Filters mirror the indexer (supported extensions, excluded dirs), respects the OFF toggle, and debounces rapid re-saves.
- The pending-files badge now appears for **any** pending file (was gated at ≥ 5, so small 1–3 file edits never showed it). The bar also watches `.mla_pending.processing`, so the badge clears promptly when the drain finishes instead of waiting for the 5 s poll.

### Changed — tidy project folder (artifacts no longer clutter the explorer or git)
- Tokengram's per-machine runtime files (`chroma_db/`, `.tokengram.*.lock`, `.bm25_index.pkl`, `.mla_*`, pending queue, savings history, …) are now **hidden from the VS Code Explorer by default** via the extension's `files.exclude` contribution — the project folder looks clean, the files still exist on disk and keep working.
- Setup now appends a guarded Tokengram block to the project's `.gitignore` (idempotent; only in a git repo / where a `.gitignore` already exists) so these artifacts never land in commits. The repo's own `.gitignore` also closed gaps (`.bm25_index.pkl`, the three `.tokengram.*.lock` files, `chroma_db.corrupt-*`, health JSON, flush temps).
- `Reset savings history` now keeps only the **2 most recent** `.bak` backups instead of accumulating one per reset (folders had grown a dozen+ stale backups).

## [0.1.55] — 2026-06-17

### Added — automatic server-side freeze recovery (ships wheel 0.1.28, from a 3-agent design)

The "Refresh Tokengram" button (0.1.54) recovers a frozen index on demand. This release makes recovery **automatic**, so end users never hit a dead-end even without clicking anything:

- **No-progress self-heal watchdog.** A server that holds the write lock but makes no database progress for over 150 s is treated as frozen: it writes a health event and restarts itself, and Claude Code respawns a clean server that clears the stale locks and resumes the queue. No data loss (writes are serialized + atomically renamed); it never fires when idle or during a normal cold model load, and the one-shot Re-index CLI is exempt.
- **Single-instance leader election.** When several windows spawn several servers, only the **leader** loads the ~700 MB embedding model; the others stay lightweight and answer searches in fast mode, loading the model lazily only if a semantic query actually arrives. This collapses the multi-window memory pressure (3×700 MB → 1×700 MB) that was the root of the index-freeze livelocks on low-RAM machines. Indexing still runs on every server (already single-writer–coordinated), so nothing is lost.
- Also in wheel 0.1.28: dead-process lock files (including orphan `.lock.tmp.<pid>` atomic-write leftovers) are swept on start/reindex, and the manual Re-index no longer races the background drainer for the write lock.

## [0.1.54] — 2026-06-17

### Changed — "Refresh status bar" → "Refresh Tokengram" (one-click freeze recovery)

- **The menu item is now a real recovery button.** Previously it only touched a file's mtime to repaint the status bar. Now, when the index is frozen — a server holds the write lock but the database has made no progress for over two minutes (the multi-window "another process is still indexing" / "wait a minute" dead-end) — the button **terminates the frozen server process(es)** so Claude Code respawns a clean one, **clears stale lock files left by dead processes** (including orphan `.tokengram.*.lock.tmp.<pid>` atomic-write leftovers), then offers a one-click **Re-index now**. No terminal required.
- The frozen process's PID is read even while the write lock is held (the lock pins only the first byte; the owner JSON lives at offset 1).
- When nothing is frozen, the button still refreshes the bar and silently sweeps any dead-process lock files.

## [0.1.53] — 2026-06-11

### Fixed (first-run reliability — from a 3-agent reindex audit). Ships wheel 0.1.27.

- **Re-index now repairs stale `.mcp.json` files.** Configs written by old extension versions lacked the offline environment flags (`HF_HUB_OFFLINE` etc.), which could hang the embedding phase on a HuggingFace network check. The Re-index button now patches the missing keys into the existing `tokengram` entry — user-set values, command and args are never touched.
- **Keyless machines get a trial offer right after Re-index** instead of a confusing search failure later. If no license key is present, a notification offers "Start free trial" (one-time internet needed) and the savings counter starts immediately.
- **Hooks no longer reach the network on keyless machines** (wheel 0.1.27). The license gate now returns instantly when no key file exists — previously the 0.1.26 trial flow could stall a hook for 10-20 s when offline. Trials are started only by the MCP server or the extension, never from a hook.

## [0.1.52] — 2026-06-11

### Added (free trial + closed dev-mode hole). Ships wheel 0.1.26.

- **Automatic free trial.** First run without a license key now requests a trial from the license server (one trial per machine, bound to the machine fingerprint server-side — deleting local files does not reset it; duration is server-controlled). The status bar shows a `trial Nd` countdown badge while the trial is active.
- **New `TRIAL ENDED` status-bar state.** When the trial expires the bar shows a calm conversion CTA instead of a red error — nothing breaks, the agent keeps working, only token savings stop. The tooltip shows your own savings from the trial.
- **Dev-mode bypass structurally closed in release builds** (wheel 0.1.26). `TOKENGRAM_DEV_MODE=1` no longer has any effect in the compiled wheel — dev mode is only possible in a source checkout. A release smoke test now asserts this on every build.
- **License server: expired subscriptions can no longer refresh tokens.** `/activate` and `/validate` now check the subscription period end — previously an expired `trialing`/manual subscription could renew its JWT forever.

## [0.1.51] — 2026-06-11

### Fixed (false "corruption" message on Re-index + lock starvation). Ships wheel 0.1.25.

- **Re-index no longer reports "Index corruption detected" when the index is healthy.** The CLI used exit code 3 for two very different failures — real corruption *and* a plain writer-lock timeout. When the background queue drain happened to hold the lock for more than 90 s (cold model load right after a reload), the button showed the scary corruption message even though nothing was corrupt. Lock timeout is now exit code 4 with an honest "another process is still indexing — wait a minute and try again" message.
- **The background drain can no longer starve the Re-index button.** The drain worker used to hold the inter-process writer lock for a whole batch (up to 20 files — minutes under a cold model). It now acquires/releases the lock per file, so a user-initiated re-index grabs the lock within seconds; the drain re-queues its remaining files and resumes after the re-index finishes.
- **Cython-generated `.c`/`.cpp` files are no longer indexed** (wheel 0.1.25). Files starting with the standard `Generated by Cython` banner are machine output, not source — on a machine that builds native wheels they accounted for 6 364 of 7 659 indexed chunks, drowning search results and quadrupling re-index time. Detected by content signature, so hand-written C projects are unaffected.

## [0.1.50] — 2026-06-11

### Fixed (orphan server processes + cold semantic search). Ships wheel 0.1.24.

- **MCP server processes no longer linger after their session ends.** The production entry path (`python -m tokengram`) called `mcp.run()` directly and skipped every startup routine — the parent-death watchdog, the model warm-up and the background re-index worker never started. On top of that, the old watchdog only watched `os.getppid()`, which on Windows is the venv *launcher* (it never dies before its child), so even when it did run it could never fire. Observed result: up to 4 zombie `-m tokengram` processes, ~700 MB RAM each.
- **New three-layer shutdown** (wheel 0.1.24): (1) the watchdog opens SYNCHRONIZE handles to both the launcher *and* its parent (the real owner — Claude Code/VS Code) and exits when either dies, immune to PID reuse; (2) a stdin-pipe sentinel (`PeekNamedPipe`) detects a broken/closed pipe even if the stdio reader thread is stuck; (3) after `mcp.run()` returns the process hard-exits (`os._exit`), so no stray non-daemon thread can keep it alive. Disable with `MLA_DISABLE_PARENT_WATCH=1`.
- **First semantic search is no longer minutes-cold.** Because warm-up never ran in production, the first `semantic` query paid the full model load on demand (50 s on an idle machine; ~10 min observed under multi-process contention). With `serve()` wiring warm-up at startup, a warm semantic query answers in ~1-2 s. *Known limitation (pre-existing, not new in this release):* on some Windows machines the in-server model load can stall for minutes (DLL loader-lock contention between torch/scipy extension loading and event-loop thread spawns — confirmed via py-spy; zero CPU, machine/timing-dependent). `auto` mode keeps falling back to fast (BM25) until the model is warm, so searches never block on it, and shutdown is unaffected (verified with a deliberately wedged warm-up thread).
- **Background re-index worker + built-in file watcher now actually start in production** — Edit/Write queue draining no longer depends on hook-side triggers alone (likely cause of historical "N files stuck in queue" reports).
- Verified by isolation tests against the installed wheel: stdin EOF → exit; launcher killed → child exits; owner killed abruptly → server exits; 20 s with a live owner → no false suicide.

## [0.1.49] — 2026-06-10

### Changed (latency: drop per-call Grep/Bash analytics hooks). Same wheel (0.1.23).

- **Terminal commands and Grep are no longer slowed by a hook.** The `Grep` and `Bash` PostToolUse hooks spawned a fresh Python process (~90 ms each) on *every* call purely to record savings analytics — they never affected the tool's behavior. They are now unwired, so Grep/Bash run with zero added latency. (`pre_read` on Read and the Edit/Write index-queue hook are unchanged.)
- **Savings bar now reflects code-search/reading savings.** With the Grep/Bash events gone, the savings counter is computed from `search_code` (logged in-process by the MCP server, no latency) plus Read events — i.e. the tokens Tokengram saves on getting code context. The full-read events (`read_pass`) still count as spend, so the percentage stays honest; it's now scoped to code retrieval rather than diluted by unrelated terminal output. No change to the savings math itself — it self-adjusts to the events present.
- The `post_grep_check.py` / `post_bash_check.py` scripts remain on disk (only unwired), so this is fully reversible by reinstalling the previous build.

## [0.1.48] — 2026-06-10

### Changed / Fixed (incremental re-index robustness + honest UI + queue hygiene). Ships wheel 0.1.23.

- **Interrupted re-index no longer restarts from zero.** The file-hash store was written only once at the very end of a re-index, so closing the window / Cancel / a parent-death exit mid-run lost all progress and the next run re-embedded everything. Hashes are now persisted **per batch** — a file's hash is saved as soon as all of its chunks are written — so an interrupted re-index resumes and only embeds what's left. (A file's chunks may span batches; its hash is recorded only after its last chunk lands, so a partially-indexed file is never wrongly skipped.)
- **The re-index menu item no longer claims "from scratch."** It is incremental (only changed files; first run is full); the label/description now say so in both English and Azerbaijani.
- **Stale "N files pending" badge cleared.** A successful re-index now clears the background queue (`.mla_pending.txt` / `.mla_pending.processing`), so ghost entries (e.g. deleted temp files, duplicates) stop inflating the spinning indexing badge. The queue hook also no longer enqueues files living under the OS temp directory.
- **Corrupt-but-locked re-index shows a clear message.** When the index is corrupt and another process holds it open, the button now says "Close Claude Code completely, then click Re-index again" instead of a generic "exited with code 3."

## [0.1.47] — 2026-06-10

### Fixed (corrupt-index self-heal — `Error loading hnsw index`). Ships wheel 0.1.22.

- **A corrupt vector index now repairs itself instead of dead-ending re-index.** If a previous indexing process was killed mid-write, the on-disk HNSW segment could be left corrupt; the next (incremental) re-index then failed with `chromadb … Error loading hnsw index / Error sending backfill request to compactor` and there was no recovery path short of manually deleting the database. The re-index CLI now **probes the index health up front** and, on detecting corruption, moves the broken database aside to `chroma_db.corrupt` and rebuilds a clean one from scratch — automatically, no data loss (the index is derived from your source; your code is never touched).
- **The recovery actually releases the database on Windows.** ChromaDB caches its client in a process-wide `SharedSystemClient`, so dropping the reference wasn't enough to free the SQLite/HNSW file handles — the move-aside step failed with `WinError 5 Access denied`. The repair now clears that cache (and retries the move with backoff) before renaming, so the rebuild succeeds in-process. (Validated: without the cache-clear the rename fails 5/5; with it, it succeeds.) If another live process is still holding the database open, it returns a clear "close Claude Code and re-index again" message instead of failing cryptically.

> This supersedes 0.1.45/0.1.46 (includes the `__main__.py` install-repair fix as well). Updating triggers a one-time venv reinstall.

## [0.1.45] — 2026-06-10

### Fixed (tester install repair — `No module named tokengram.__main__`)

- An older wheel shipped without `tokengram/__main__.py`, so `python -m tokengram` (which runs **both** the MCP server and the re-index CLI) failed with `No module named tokengram.__main__` — the server and re-index were dead on those machines. Three-part fix: (1) the wheel version is bumped so the extension re-installs the venv instead of short-circuiting on an equal version; (2) the extension now **detects a broken install** (missing `__main__.py`) and repairs the venv even when the version compare says "already up to date"; (3) the build pipeline now **guarantees** `__main__.py`/`__init__.py` are always present in the wheel (writes them if missing + fail-fast guard).

> Existing testers: updating to this version triggers a one-time venv repair on first activation — no manual steps.

## [0.1.44] — 2026-06-10

### Fixed (re-index reliability + a process leak). Ships wheel with three core fixes.

- **Re-index no longer produces an unreadable index.** The Re-index button runs the indexer as a separate one-shot process; on ChromaDB 1.5.8 that process wrote the vectors but exited before the HNSW segment was compacted, so the live MCP server then failed to open it (`Error loading hnsw index`) and search returned nothing. The indexer now forces a compaction query before exiting, so the on-disk index is always readable by the server. (Confirmed with a two-phase test: build+query+exit → reopens fine; build+exit → fails.)
- **Re-index is now incremental.** Previously every re-index wiped the whole database and re-embedded all files (minutes, even if nothing changed). It now skips unchanged files via an MD5 hash check and only re-embeds new/changed ones — routine re-index is seconds. Deleted files are pruned; the keyword (BM25) index still covers the full corpus. First run on an empty index still does a full build. (A full rebuild is still available via the `--reindex … --fresh` CLI for format changes/recovery.)
- **No more orphaned Python process after closing a window.** On Windows a child process isn't killed when its parent dies, so two things leaked: (1) a re-index spawned by the extension kept running if you closed the window mid-index — the extension now tracks and kills it on deactivate/cancel; (2) the MCP server itself lingered when Claude Code didn't terminate it on window close — the server now watches its parent and self-exits when the parent dies. Opt out with `MLA_DISABLE_PARENT_WATCH=1`.
- Model/tokenizer caches (`.fastembed_cache`) are excluded from indexing (were adding ~700 chunks of noise).

> Activation: reinstall (bundled wheel → venv) and reload. The re-index button is now cancellable and incremental.

## [0.1.43] — 2026-06-09

### Changed (token-savings engine — bigger real savings + an honest bar). Ships wheel 0.1.19.

- **Search picks its own mode now (`auto` default).** `search_code` routes each query automatically: symbol/identifier lookups → fast BM25; natural-language/conceptual questions → semantic embeddings. The old default was BM25-only, so conceptual queries returned weak hits and the agent fell back to reading whole files (zero savings). `auto` falls back to fast when the embedding model isn't warm, so it never blocks.
- **Embedding model warms up at server start.** The first semantic search used to cost 30–60 s (cold model load), which is why everyone stayed on keyword-only search. The model now loads in a background thread when the MCP server starts → semantic search is ready (~1 s). Opt out on low-RAM machines with `MLA_DISABLE_WARMUP=1`.
- **Results carry line anchors + a "don't read the whole file" nudge.** Each hit shows `path:start-end` and tells the agent to use a bounded `Read(offset, limit)` instead of re-reading the entire file — turning "search then full read" into "search then small read". (Re-index to populate anchors on existing code.)
- **The savings bar no longer counts phantom savings.** If the agent searched a file and then fully read it anyway, that search saved nothing — but the old math still credited it (a big part of "bar says 90%, invoice says 20%"). The Stop hook now zeroes a search's credited baseline when the same file is fully read in the same task, so the percentage reflects reality.

> Activation: reinstall (bundled wheel 0.1.19 → venv) and reload. The bar-accuracy fix applies as soon as hooks are reinstalled; the search changes apply once the MCP server restarts on the new wheel.

## [0.1.36] — 2026-06-04

### Fixed (license validation — kills `network_error:AbortError` for testers)

- **`https://tokengram.click` now resolves to a real license server** (TLS via Caddy → the API app). The extension already defaulted to this URL; it just had nothing listening before. Set up + verified this session.
- **Installer no longer carries a stale server URL/pubkey forward.** `migrate_legacy_mla_dir` used to copy `server_url.txt` + `pubkey.pem` from a legacy `~/.mla/` dir — often pointing at a now-dead endpoint — which then *overrode* the correct default and produced "License server rejected this key (network_error:AbortError). Key not saved." It now carries only the license key, and **pins `server_url.txt` to `https://tokengram.click`** on every install.
- **Self-heal on activation.** An existing install whose `~/.tokengram/server_url.txt` points at a known-stale value (a retired `*.workers.dev` worker or the raw EC2 IP) is rewritten to `https://tokengram.click` automatically at startup — no reinstall needed. A deliberate custom HTTPS URL is left untouched.
- `install.ps1` default server URL corrected to `https://tokengram.click` (was the retired Cloudflare worker).

> No wheel change. Root cause of the tester toast was a leftover/stale `server_url.txt` overriding the correct default — now both prevented (installer) and repaired (self-heal).

## [0.1.35] — 2026-06-04

### Changed (install shows a REAL download/progress percentage)

- **The first-time install bar now reflects real progress instead of a timer.** Before, the dominant ~300 MB dependency step just crept the bar on a fixed 7-minute time estimate (`Downloading dependencies — Xm Ys elapsed`) — if the network was slow the bar lied, if fast it lagged. Now:
  - **uv download** streams byte-by-byte and shows the true figure: `Downloading runtime (uv) — 12.3 / 23.3 MB · 53%` (was a silent ~24 MB stall).
  - **Dependency install** is driven by **real on-disk growth**: `installer.py` runs a background monitor thread that measures the venv growing and streams `[DL] <bytes> <target>` lines; the wizard turns these into `Installing dependencies — NN%`. A time component still gives early motion during the pure-network window (when the venv is briefly flat), then the real bytes take over.
- Calibrated the target against the real installed footprint (~1.20 GB: torch 2.12 + transformers + chromadb 1.5.8 + sentence-transformers). Over/under-estimate only changes fill speed, never correctness; the bar is capped < 100% until the install actually finishes.

> No change to *what* gets installed — only how honestly the progress bar reports it. Verified in isolation: uv streaming matched `content-length` exactly, and the disk monitor's `_dir_size` matched the OS byte count to the byte.

## [0.1.34] — 2026-06-02

### Fixed (the real tester blocker — "Python 3.12 yoxdur")

- **Install no longer requires the user to have Python 3.12.** The #1 tester failure ("Tokengram setup did not complete") was simply that the machine had no Python 3.12 — the old flow just popped a "Download Python 3.12" prompt and gave up, and testers either ignored it or installed 3.13 (which the cp312-only wheel rejects). The installer now bootstraps **[uv](https://docs.astral.sh/uv/)** (a single self-contained binary, downloaded once to `~/.tokengram/uv.exe` and cached) and lets uv **auto-provision a standalone CPython 3.12** — so install works on a machine with *no* Python, the wrong Python, or a broken Python. `detectPython()` and the "Download Python 3.12" prompt are gone.
- Dependency install now goes through **`uv pip install`** instead of pip — much faster and a stronger resolver, which also reduces the ~300 MB first-install timeout risk. Verified end-to-end: uv resolves the full tree (torch 2.12, transformers, chromadb 1.5.8, sentence-transformers) and produces `tokengram.exe`.
- **Installer Unicode crash fixed.** On Windows the installer's Azerbaijani log lines (`ə`, …) raised `UnicodeEncodeError` when stdout was piped (cp1252) — aborting the whole install before it finished. The installer now forces UTF-8 stdout/stderr (like the hooks), and the extension also passes `PYTHONIOENCODING=utf-8`/`PYTHONUTF8=1` to the installer process.

> Build pipeline unchanged (still a cp312 wheel); the difference is we now *bring* the matching Python instead of demanding the user already has it. Multi-version wheels (cp313, …) are no longer needed to onboard testers.

## [0.1.33] — 2026-06-02

### Added (install diagnostics — pin down tester-machine failures)
- **The installer now writes a full persistent transcript to `~/.tokengram/install.log` on every run.** Until now a failed install on a tester's machine ("Tokengram setup did not complete") dumped its real pip/venv error only to a transient output channel that was easily lost — so we could never see *why* it failed remotely. `installer.py` now tees all output (including pip's stderr, the exact command, the launcher Python version and platform) to a log file that survives, plus catches timeouts and unexpected errors so every failure mode is recorded.
- **The "setup did not complete" dialog gained a "Show install log" button** (when a log exists) so a tester can open the file and send it to support in one click. The install-failed toast and output channel now also point at `~/.tokengram/install.log`.

> Diagnostic-only release: no behavior change to a successful install. If a tester still hits "setup did not complete", have them click **Show install log** and send the file — the real cause (Python version, network/proxy, a dependency with no prebuilt wheel, etc.) will be in it.

## [0.1.32] — 2026-06-02

### Fixed (fresh-install audit batch — 3 critical + several high/medium)

**Critical (fresh-machine install blockers):**
- **Hooks crashed on a clean machine with `ModuleNotFoundError: mla_constants` / `i18n`.** The installer copied only `tokengram/hooks/` into `~/.tokengram/`, but every hook imports `mla_constants` / `i18n` as top-level modules (and `i18n` loads `messages/*.json`) from that dir. In the wheel these live only inside the package as compiled `.pyd`, so a fresh install left them unreachable — silently disabling all enforcement, savings logging, and the Stop flush. `installer.py:install_hooks_locally` now also copies the compiled `mla_constants`/`i18n` modules and the `messages/` dir next to `hooks/`. (Was masked on dev machines by stale legacy files.)
- **`.mcp.json` was missing the three offline env vars** (`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, `ANONYMIZED_TELEMETRY`). Without them the sentence-transformers HuggingFace online check hangs the indexing worker thread (`queue_stuck`). Restored in the live config and in **both** generators (`setupWizard.ts` and `menu.ts`).
- **The setup wizard never provisioned `pubkey.pem`, so a fresh user could never validate a license.** `license.from_env()` reads `~/.tokengram/pubkey.pem` to verify signed tokens; nothing wrote it. `saveLicenseKey` now fetches `GET /pubkey` from the license server and writes it before saving the key.

**High / medium:**
- **License negative-cache.** `license.ensure_license_cached()` only memoized success/dev-mode, so when validation failed (no pubkey, network error) every MCP tool call re-paid the 10s HTTP timeout. Failures are now negative-cached for 60s.
- **Extension license dir aligned to `~/.tokengram`.** `licenseStatus.ts` and `menu.ts` wrote/read `~/.mla`; reads now prefer canonical `~/.tokengram` with a `~/.mla` fallback, writes go to `~/.tokengram` (matches the MCP server's `from_env`).
- **`license_gate.project_root_from_env()`** now delegates to `project_root.find_project_root()` (walk-up) instead of bare `os.getcwd()`, so enforcement state is read from the same root the savings counter writes to (monorepo-subfolder safety).
- **Hook dependency imports fail open.** The five registered hooks wrap their `mla_constants`/`i18n`/`license_gate`/`project_root`/`atomic_write` imports in `try/except → sys.exit(0)`, so a future packaging regression can never hard-block a Read.
- Stale `install.ps1` references in user-facing re-index messages replaced with **"Tokengram: Setup"**.
- Removed a leftover `.mcp.json.bak-*` and added `.mcp.json.bak*` to `.gitignore`.

> Note: 0.1.31 was an internal bump with no released notes; its changes are folded into this entry.

## [0.1.30] — 2026-05-22

### Fixed
- **Install no longer crashes with `Package 'tokengram' requires a different Python: 3.13.x not in '<3.13,>=3.12'` on machines that have Python 3.13 but not 3.12.** Tester (Vusal) hit this immediately on 0.1.29: the extension's `detectPython()` fell through from `py -3.12` (missing) to `py -3.13`, the installer created a 3.13 venv, and pip then refused to install the cp312-only wheel — producing a confusing `installer exited with code 1` toast with the real reason buried in the output channel. Three coordinated changes:
  - **`detectPython()` now only accepts Python 3.12.x** (was 3.12+; the wheel is cp312-only and there is no cp313 build yet). 3.13 candidates removed from the search list entirely.
  - **The "Python missing" toast now names the exact required version and links to the 3.12.8 release page** (`https://www.python.org/downloads/release/python-3128/`) instead of the generic downloads page — users were grabbing the latest (3.13) and re-running into the same wall.
  - **`installer.py:create_venv` now validates the existing venv's Python version** and rebuilds it if it doesn't match. Previously, a tester who first installed with 3.13 (creating a 3.13 venv), then installed Python 3.12 and re-ran, kept failing forever because `venv already exists, reusing` silently kept the 3.13 venv. The installer now deletes the mismatched venv and creates a fresh 3.12 one with a clear `Existing venv is Python 3.13, rebuilding for 3.12...` log line.
- Python 3.13 support will arrive in a future release once we add a cp313 wheel build to the pipeline; this is tracked but blocked on having Python 3.13 installed on the build machine.

## [0.1.29] — 2026-05-22

### Fixed (launch-blocker batch — 8 critical + 23 high-severity audit findings)

**Launch blockers (8):**
- **`project_root.py` was missing from the wheel.** `build_pypi.py:HOOK_FILES` didn't list it, so the three hooks that `from project_root import find_project_root` (`pre_read_check`, `post_grep_check`, `post_bash_check`) raised `ModuleNotFoundError` on every Read/Grep/Bash after install — **every enforcement was silently disabled**. Added to `HOOK_FILES`.
- **License-server URL default switched to `https://tokengram.click`.** Was `http://54.163.13.24:3000` — license keys, JWT tokens, and machine fingerprints went over plain HTTP, MITM-interceptable on any untrusted network. The `install.ps1` script and the extension's `tokengram.licenseServerUrl` config now agree on HTTPS.
- **`/validate` endpoint now verifies the JWT signature** (with `ignoreExpiration` semantics so expired-but-real tokens can still refresh). Before, anyone could forge a JSON payload, base64-encode it, send it as a Bearer token, and — if the named `user_id` had an active subscription in the DB — get a freshly-signed real JWT back, bypassing fingerprint binding entirely.
- **`new_tester_key.ps1` no longer concatenates raw email into SQL.** A single quote in an email (`o'malley@x.com`) broke the INSERT; a crafted email would have executed arbitrary SQL. Added `SqlEscape` helper that doubles single quotes before interpolation.
- **`.mla_session_log.jsonl` concurrent writes are now atomic.** Claude Code fires up to 5 PreToolUse hooks in parallel; the old `open(..., "a")` + `f.write()` pattern interleaved writes producing partial JSON, which `savings_report.py:json.JSONDecodeError → continue` silently swallowed — every parallel-burst undercounted savings. New `atomic_write.append_atomic()` helper uses a single `O_APPEND` syscall on POSIX (atomic for sub-PIPE_BUF writes) and `msvcrt.locking` on Windows. Wired into `pre_read_check`, `post_grep_check`, `post_bash_check`, `queue_change`, `savings_report` (history append), and `arch_doc`.
- **`~/.mla/` is being migrated to `~/.tokengram/`** (canonical post-rebrand). On install, the installer now copies `license_key.txt`, `pubkey.pem`, `server_url.txt` from the legacy `~/.mla/` if they exist and the new files don't. Python `license.py.from_env()` reads from `~/.tokengram/` first, falls back to `~/.mla/` — so an extension/runtime split (extension wrote to `~/.mla/`, MCP read from `~/.tokengram/`) no longer silently loses the key.
- **`hooks/project_root.py` walk-up now stops at `Path.home()`.** Before, the walk-up climbed into `~/.claude/settings.json` (which virtually every Claude Code user has) and treated `$HOME` as the project root — so every workspace dropped `.mla_session_log.jsonl`, `.mla_enforcement.flag`, etc. into the user's home directory, with all unrelated projects' state merging.
- **Non-Windows now fails fast with a clear message** instead of installing a broken wheel. The bundled `tokengram-*.whl` is tagged `py3-none-any` but contains Windows-only `cp312-win_amd64.pyd` files; on macOS/Linux pip "installed" successfully but the runtime crashed with `ImportError` on first MCP call. The extension's `activate()` now refuses to run on `process.platform !== 'win32'`.

**High-severity (23):**
- `show_arch.py:17` was reading `ARCH_DOC` from the install dir (`~/.tokengram/.mla_arch.md`) instead of the project root where `arch_doc.py` writes it — `/MlaArch` always returned "arch_missing" on a real install. Fixed via `find_project_root()`.
- 7 hooks + `mcp_server.py` now use the same `find_project_root()` walk-up that `pre_read_check.py` and the TS bar use — subfolder workspaces no longer split-brain into "pre_read writes to /repo, savings_report reads from /repo/sub" (savings stayed at 0).
- `arch_doc.py:save_state`, `vector_store.py:HashStore._save`, `license.py:_save_cache`, `toggle_mla.py` now all write atomically via `tmp + os.replace` — `kill -9` or power loss mid-write no longer corrupts state files (which the old code then silently reset to defaults, losing accumulated data).
- `savings_report.py` now `os.replace`s `.mla_session_log.jsonl` to a `.processing.<pid>` file before reading; events fired by other hooks during Stop processing land in a fresh log instead of being silently wiped between the read and the unlink.
- `vector_store.py:index_documents` now pre-deletes per-file chunks before upsert — when a file is edited to drop a function, the old chunks no longer linger in the collection (search used to return deleted code).
- `license_gate.enforcement_active()` now caches its result to `~/.tokengram/.license_gate_cache` with a 5-minute TTL. The old code re-imported `cryptography` and re-validated the JWT on every hook invocation (~150–300 ms each → multi-second "Vibing" pauses on parallel-burst).
- `mcp_server.py` BM25 rebuild is now debounced: only rebuilt after the queue fully drains or 60 s have passed since the last rebuild. Long pending queues used to rebuild after every 20-file batch, blocking MCP stdio for ~10 s per batch.
- `mcp_server.py:_recover_stale_processing_queue` is now guarded by a `_recovery_done` flag — a hot restart no longer double-appends to PENDING_QUEUE.
- `pre_read_check.py` does a `stat().st_size` early-out: files larger than 200 KB without a `limit` are blocked from stat alone, skipping the 30–100 ms `read_bytes()` that was running 5× in parallel on every multi-Read burst.
- `installer.py` pip calls now pass `--retries 5 --timeout 60` and a 15-minute subprocess `timeout=` — slow corporate proxies no longer hang the install with no progress for an hour, and the user gets a clear "uninstall timeout (likely file-lock)" message instead of a swallowed error.
- TS status bar `setInterval` now pauses when the window loses focus, then resumes on focus — was burning 32 sync `fs.statSync` calls every 5 s on every open VS Code window (visible UI lag on network drives).
- Wheel selection in `setupWizard.runInstaller` now sorts by parsed semver descending and picks the highest version — `readdirSync` order is filesystem-dependent, and lexicographic "0.1.10" < "0.1.9" (ASCII "1" < "9"), so a leftover dev wheel could be installed instead of the bundled current one.
- `queue_change.py` now lowercase-compares the suffix (`.PY` was being silently skipped on Windows), and gates on `enforcement_active` (off-mode no longer grows `.mla_pending.txt` unbounded while the MCP server isn't started).
- `arch_doc.py` `recent_searches` is no longer filled with empty "no results" rows from non-search events (`read_block`, `grep_search`, etc.).
- `reset_savings.py` backup suffix now uses `time_ns()` nanosecond precision — two resets within the same second no longer overwrite the prior backup.
- `refresh_bar.py` now writes to stderr (was leaking into Claude's tool response noise) and forces `os.utime` with a different mtime to defeat macOS FSEvents' identical-mtime debounce.
- `license_gate._flag_on` retries once on transient `OSError` — Windows sharing-violation during atomic toggle-rewrite no longer flips enforcement OFF for one hook event.
- `license_gate._import_license_module` now leaves a breadcrumb at `~/.tokengram/.license_gate_import_error` when the import fails — silent-disabled enforcement is now debuggable.
- `make_distribution.py` / `installer.py` switched `datetime.utcnow()` → `datetime.now(timezone.utc)` (3.12 deprecation warning was visible in every install log).
- `package.json` `homepage` now points to the project repo, not the user profile (Marketplace listing showed a broken-looking "Homepage" link).

**Bundled wheel:** `tokengram-0.1.11` (replaces 0.1.10 — 0.1.10 shipped with missing `project_root.py`, every install since 0.1.10 was silently broken).

## [0.1.28] — 2026-05-22

### Fixed
- **Savings counter no longer silently stuck at 0 because the MCP server and the hooks disagreed on where to put their tracking files.** The compiled `mcp_server.pyd` was resolving `SESSION_LOG`, `ENFORCEMENT_FLAG`, and `PENDING_QUEUE` via `Path(__file__).parent`, which inside the wheel lands in `…\.tokengram\venv\Lib\site-packages\tokengram\` instead of the project root. The hooks (`toggle_mla.py`, `savings_report.py`, etc.) write/read those files relative to `CLAUDE_PROJECT_DIR` / `os.getcwd()`. Net effect: `toggle_mla` would write `.mla_enforcement.flag = "on"` to the project root, the MCP server would check the package directory, not find it, treat enforcement as off, and `_log_search` would return without writing the session log — so the Stop hook always saw an empty log and `.mla_savings_history.jsonl` stayed at zero. Bundled wheel bumped to `tokengram-0.1.10` with project-relative paths matching the hooks.

## [0.1.27] — 2026-05-21

### Fixed
- **Install failure now surfaces the real cause, not just `installer exited with code 1`.** The installer runner used to discard every pip/venv line as soon as the spawned process exited, so when `python -m pip install` failed the user only saw "installer exited with code 1" in the toast and had no way to diagnose. The runner now keeps the last 30 captured stdout/stderr lines, appends them to the rejection message, and the catch handler dumps the full transcript into a dedicated "Tokengram Install" output channel while the toast shows the last non-empty meaningful line.

## [0.1.26] — 2026-05-21

### Fixed
- **Re-index failure notification now shows the real cause, not a generic wrapper.** When the re-index button failed in 0.1.23/0.1.24 the user saw only `re-index failed — Command failed: ...` or `re-index failed — reindex exited with code 1` in the notification, with the actual stderr message hidden in the Output channel they had to open manually. The catch handler now scans the captured error message from the bottom up and picks the last non-empty line that is not the wrapper itself, so the toast surfaces the genuine failure reason (missing directory, license rejection, chromadb error, etc.) directly.
- **`reindex_conversations` MCP tool no longer hangs Claude for tens of minutes.** The tool used to call `_convo.index_conversations()` synchronously on the MCP stdio thread; for testers with large conversation histories or a cold HuggingFace model cache this could block Claude for 30+ minutes with no progress, leaving "Cogitating..." stuck. The tool now starts the re-index in a background thread, returns immediately with `{started, running, last_result, last_error}`, and is idempotent — repeated calls while a run is in flight return `already_running=true` instead of stacking workers. Bundled wheel bumped to `tokengram-0.1.9`.
- **Detect leftover "MLA Agent" extension (publisher `erp-intel`) and prompt for uninstall.** Testers who installed Tokengram on top of the pre-rebrand "MLA Agent" extension ended up with two status-bar widgets ("MLA: 0.0k saved" + "Tokengram: 0.0k saved") and two hook sets firing on every Read, so neither savings counter ever accumulated meaningful numbers. On activate, Tokengram now detects `erp-intel.mla-agent` and offers a one-click uninstall.

## [0.1.24] — 2026-05-21

### Fixed
- **The "ChromaDB re-index" button on the status-bar menu now shows a real determinate progress bar with stage labels** instead of the prior static "may take a minute" notification + indeterminate spinner. The wheel's `--reindex` CLI was already emitting `[1/3]` / `[2/3]` / `[3/3]` stage banners (added in 0.1.23 / wheel 0.1.8), but the extension was buffering the entire run via `execFile` and only writing the captured log to the output channel after the process exited. The button now spawns the CLI with `child_process.spawn`, streams stderr line by line, and routes each stage marker into `withProgress({ location: Notification })` — start 5%, `[1/3]` 25%, `[2/3]` 50% with elapsed-time slow-fill to 85% during the HuggingFace model download phase, `[3/3]` 90%, "Hazır" → 100%.

## [0.1.23] — 2026-05-21

### Changed
- **Install / update progress is now a real determinate 0–100% bar.** The previous notification only showed a spinner and the most-recent pip stdout line, leaving the user staring at "5–15 minutes" with no sense of how far along the install was. Each installer stage now jumps the bar to a defined %-target (Python check 13%, venv 22%, wheel install 32%, hook copy 92%, finalize 100%), and the dominant ~300 MB dependency download fills the bar against an elapsed-time budget so the user always sees forward motion plus a live `Downloading dependencies — Xm Ys elapsed` readout.
- **Update flow surfaces the previously-silent MCP-server kill step.** Notifications now read "Stopping any running MCP server processes..." → "MCP server stopped — starting upgrade..." instead of a 5–30 second blank pause.
- **Update notification title is realistic.** Was "~10 seconds" — now `Tokengram: updating (~30–60s — restarting MCP server, swapping wheel)`.
- **Silent workspace wiring now shows a toast.** When the extension drops `.claude/settings.json` + `.mcp.json` into a newly-opened project (no full reinstall required), the user gets a "Tokengram: this workspace was wired up — reload Claude Code so the hooks activate" notification instead of finding new config files with no explanation.

### Fixed
- **CLI reindex output is no longer a wall of HuggingFace HTTP HEAD requests.** Stage banners (`[1/3] Fayllar skan edilir` / `[2/3] Embedding modeli hazırlanır` / `[3/3] N chunk indekslənir`) plus a `✓ Hazır` completion line replace the prior ~50 lines of `httpx` log spam and an unactionable "unauthenticated requests to the HF Hub" warning.
- `installer.py` no longer runs `pip install --quiet` for the pip-upgrade step. The previous `--quiet` left a silent 5–10 second gap inside `[3/5]`.

### Changed
- Bundled wheel bumped to `tokengram-0.1.8` (carries the CLI reindex log clean-up).

## [0.1.16] — 2026-05-19

### Fixed
- **Install crash on Windows** — `pip install tokengram` aborted with `AssertionError` deep in `wheel._install_wheel`. Root cause: the wheel's `license-files` spec pointed at `vscode-extension/LICENSE.txt`, which produced a nested `dist-info/licenses/vscode-extension/LICENSE.txt` path that pip on Windows refuses to write. Wheel rebuilt with `LICENSE.txt` at the project root (`dist-info/licenses/LICENSE.txt`). Verified end-to-end: pip install of the bundled wheel succeeds in a clean venv.

### Changed
- Bundled wheel bumped to `tokengram-0.1.4`. Includes the privacy filter (no secrets indexed) and `chromadb==1.5.8` hard pin.

## [0.1.15] — 2026-05-19

### Changed
- The extension now bundles the `tokengram` wheel under `resources/` and installs from it directly. No PyPI round-trip is required, so a fresh install no longer depends on PyPI availability or version drift between the extension and the wheel.
- Marketplace homepage / pyproject project URLs now point to `github.com/kinleee` (the working user page) instead of a not-yet-deployed domain.

## [0.1.14] — 2026-05-19

### Changed
- Setup wizard now writes `.mcp.json` with the `tokengram` server key (was `mla-agent`). Legacy `mla-agent`/`mla_agent` entries are removed when the wizard re-runs; `menu.ts:readMcpConfig` continues to accept both names so existing installs keep working until next setup.

## [0.1.13] — 2026-05-19

### Fixed
- **Subfolder workspace launch blocker** — opening a sub-folder of a Tokengram-configured project (e.g. monorepo `apps/web/`) now mirrors the parent `.claude/settings.json` and `.mcp.json` on activation, so hooks fire in the sub-folder the same way they do in the parent.

### Changed
- Status-bar tooltip and marketplace description now state explicitly that the savings percentage covers Tokengram-routed operations (search / Read / Grep / Bash inspect) and excludes Edit, raw Bash output, and system-prompt overhead. Removes the previously misleading "~70%" headline claim.

## [0.1.12] — 2026-05-18

### Added
- Status bar health states: `queue_stuck` and `data_reset` surface silent backend failures as yellow warnings.

## [0.1.5] — 2026-05-18

### Added
- Seven-state status bar (active / idle / enforcement-off / no-license / data-reset / queue-stuck / error).
- Event breakdown menu on status-bar click — shows per-event-type savings and counts.

### Fixed
- Hooks now correctly resolve `PROJECT_ROOT` from sub-folder workspaces by walking up.

## [0.1.4] — 2026-05-18

### Added
- `hooks/license_gate.py` — runtime enforcement gate. Without a valid license, hooks become silent allow.

## [0.1.1 – 0.1.3] — 2026-05-15 → 2026-05-17

### Added
- Per-event baseline cap; top-file-only search baseline for realistic numbers.
- Bounded `Read` (limit < 50) bypasses the indexed-file block.
- Live status-bar refresh from `.mla_session_log.jsonl`.
- Per-category baseline accounting + `estimate_tokens` helper.

## [0.1.0] — 2026-05-15

Initial public release.

### Added
- One-click setup wizard (detects Python, creates venv, installs `tokengram`, configures Claude Code hooks).
- Status-bar odometer showing live token savings.
- Command palette menu (toggle, refresh, reset, view architecture, reindex, sync, license).
- License key entry stored via VS Code SecretStorage.
- AZ / EN localization.

### Known issues
- Windows fully supported. macOS / Linux experimental (Python install detection only).
- First-time indexing on a 1000-file repo takes ~30–60s.

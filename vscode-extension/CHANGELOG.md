# Changelog

All notable changes to the Tokengram VS Code extension will be documented here.

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

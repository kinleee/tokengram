# Changelog

All notable changes to the Tokengram VS Code extension will be documented here.

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

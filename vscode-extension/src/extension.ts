import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';
import { startPeriodicRecheck } from './licenseStatus';
import { registerMenuCommand, registerSetLicenseKeyCommand, killActiveReindexChildren } from './menu';
import { createStatusBar } from './statusBar';
import { findProjectRoot } from './savingsReader';
import { ensureAutoInstall, registerSetupCommand, pinServerUrl, ensureGitignore, promptReload } from './setupWizard';

export function activate(context: vscode.ExtensionContext) {
  // Platform gate. Each platform-specific VSIX bundles a wheel compiled for that
  // platform — Windows ships .pyd, Linux ships .so. macOS (.so/.dylib) is not
  // built yet, so we still fail-fast there: the Marketplace should not serve a
  // Windows/Linux VSIX to a Mac, but a sideloaded build would otherwise install
  // and then crash on import. Windows and Linux are supported.
  if (process.platform !== 'win32' && process.platform !== 'linux') {
    void vscode.window.showErrorMessage(
      'Tokengram supports Windows and Linux. A macOS build is on the roadmap — please follow https://github.com/kinleee/tokengram for updates.',
    );
    return;
  }
  warnIfLegacyMlaExtensionPresent();
  mirrorParentWorkspaceHooks();
  // Ensure the .gitignore exists in existing (already set-up) projects too. Critical:
  // the lock file (.tokengram.writer.lock) is OS-locked by the running server, so
  // `git add .` cannot read it → "Permission denied" → the ENTIRE add fails fatally.
  // Once gitignored, git does not touch it. ensureGitignore is idempotent (sentinel)
  // and only writes when there is a git repo / an existing .gitignore.
  ensureProjectGitignoreIfTokengram();
  // Self-heal a stale license-server URL (old ~/.mla migration / parked-domain
  // era) so already-installed testers don't stay stuck on a dead endpoint.
  pinServerUrl();
  context.subscriptions.push(registerMenuCommand(context));
  context.subscriptions.push(registerSetLicenseKeyCommand());
  context.subscriptions.push(registerSetupCommand(context));
  const statusBar = createStatusBar(context);
  context.subscriptions.push(statusBar);
  context.subscriptions.push(startPeriodicRecheck());
  registerSaveIndexer(context);
  // Get off the activation tick: let `activate()` return immediately so VS Code
  // and other extensions (especially Claude Code's startup model/storage load)
  // do not wait on our setup check. ensureAutoInstall is fire-and-forget anyway.
  setTimeout(() => void ensureAutoInstall(context), 0);
}

// When a file is saved in the VS Code editor, we write it to the index queue
// (.mla_pending.txt) — Claude Code edits are already captured by the PostToolUse
// hook (queue_change.py), but when the user presses Ctrl+S directly in the editor,
// only the Python watchdog (2s debounce) caught it. This listener writes to the
// queue IMMEDIATELY on save → the status bar FS watcher sees the .mla_pending.txt
// change and shows the spinner+counter at that moment. WE DO NOT INDEX OURSELVES —
// we only write to the queue; the already-running MCP server background drainer
// embeds the files (NO new process spawn → no spawn-storm/RAM risk). The filters
// mirror mla_constants.py.
const INDEXABLE_EXTENSIONS = new Set([
  '.py', '.sol', '.sql', '.md',
  '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs',
  '.go', '.rs', '.java', '.kt', '.cs',
  '.cpp', '.cc', '.cxx', '.c', '.h', '.hpp',
  '.rb', '.php', '.swift', '.dart',
  '.html', '.css', '.scss',
  '.json', '.yaml', '.yml', '.toml',
  '.sh', '.bash', '.ps1', '.tf',
]);

const INDEX_EXCLUDED_DIRS = new Set([
  'chroma_db', '__pycache__', '.git', '.svn', '.hg',
  'models_cache', '.fastembed_cache',
  'node_modules', 'venv', '.venv', 'env', '.env',
  'site-packages', 'vendor', 'bower_components',
  '.gradle', '.m2', 'Pods', '.dart_tool', '.pub-cache', '.terraform',
  'dist', 'build', 'out', 'target', '.next', '.nuxt', '.eggs',
  '.cache', '.parcel-cache', '.turbo',
  'coverage', 'htmlcov', '.nyc_output', 'storage',
  '.idea', '.vscode', '.claude', '.aider', '.cursor', '.antigravity', '.mla',
  '.pytest_cache', '.mypy_cache', '.ruff_cache', '.tox',
]);

// File-name matches (name.startsWith) — mirrors mla_constants.EXCLUDED_FILE_PATTERNS.
// Includes secret/credential files too: not even a secret's PATH should end up in
// the queue file (Tokengram claims "local · private").
const INDEX_EXCLUDED_FILE_PATTERNS = [
  '.mla_pending', '.mla_session_log', '.file_hashes',
  'TEST_PROMPT', 'test_prompt', 'PROMPT_', 'prompts.', 'FIXTURE_', 'fixture_',
  'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
  'Cargo.lock', 'go.sum', 'composer.lock', 'Gemfile.lock',
  'poetry.lock', 'uv.lock', 'bun.lockb',
  '.env', 'secrets.', 'credentials.', 'credential.',
  'service-account', 'firebase-adminsdk', 'google-services.json',
];

// Suffix exclusions — mirrors mla_constants.EXCLUDED_FILE_SUFFIXES (minified
// bundle, source map, generated code).
const INDEX_EXCLUDED_FILE_SUFFIXES = [
  '.min.js', '.min.css', '.bundle.js', '.bundle.css', '.map',
  '.pb.go', '.pb.ts', '_pb2.py', '_pb2_grpc.py',
  '.gen.go', '.gen.ts', '.generated.ts', '.generated.go',
];

// Trailing (idle) debounce per file: every save RESETS the timer; the file is
// written to the queue only ONCE, after SAVE_IDLE_MS of no touches. Reason: the old
// 3s "leading" debounce queued each save separately when typing slowly at 3-4s
// intervals → dozens of lines for the same file + the spinner spun on every keystroke.
// Now we wait until typing stops, then enqueue once (with dedup).
const pendingTimers = new Map<string, NodeJS.Timeout>();
const SAVE_IDLE_MS = 6000;

// Do not re-write if it is already in the queue (.mla_pending.txt + .processing).
// The drainer dedups anyway, but if we do not dedup here the queue bloats and ⟳N
// looks falsely large. The comparison accounts for case-insensitivity on Windows.
function alreadyQueued(projectRoot: string, filePath: string): boolean {
  const want = filePath.toLowerCase();
  for (const name of ['.mla_pending.txt', '.mla_pending.processing']) {
    try {
      const data = fs.readFileSync(path.join(projectRoot, name), 'utf-8');
      for (const line of data.split('\n')) {
        if (line.trim().toLowerCase() === want) return true;
      }
    } catch {
      /* skip if the file does not exist */
    }
  }
  return false;
}

// venv interpreter path — we only grow the queue if there is an interpreter that
// can actually drain it. Otherwise (a broken/partial venv) writing to the queue
// fills the disk and nothing drains (2026-06-19 partial-venv: 1194 files queued,
// 0 indexed).
const VENV_PYTHON =
  process.platform === 'win32'
    ? path.join(os.homedir(), '.tokengram', 'venv', 'Scripts', 'python.exe')
    : path.join(os.homedir(), '.tokengram', 'venv', 'bin', 'python');

function registerSaveIndexer(context: vscode.ExtensionContext): void {
  const enqueue = (filePath: string): void => {
    pendingTimers.delete(filePath);
    try {
      // If the drainer (venv python) is missing, do not write to the queue —
      // nobody will index it anyway, only .mla_pending.txt grows unbounded.
      if (!fs.existsSync(VENV_PYTHON)) return;
      const projectRoot = findProjectRoot(path.dirname(filePath));
      // Do not grow the queue when enforcement is OFF (mirrors queue_change.py:58).
      // We re-check at fire time — the user may have toggled it while typing.
      let on = false;
      try {
        on =
          fs
            .readFileSync(path.join(projectRoot, '.mla_enforcement.flag'), 'utf-8')
            .trim()
            .toLowerCase() === 'on';
      } catch {
        on = false;
      }
      if (!on) return;
      if (!alreadyQueued(projectRoot, filePath)) {
        fs.appendFileSync(path.join(projectRoot, '.mla_pending.txt'), filePath + '\n', 'utf-8');
      }
      // An editor save is not tied to a task (the Stop hook will not fire) — so
      // WE drop the drain marker ourselves so the running MCP server drains the
      // queue immediately (~1s) with its warm model. (Claude edits accumulate via
      // queue_change.py and are drained by the Stop hook at task end — we do not
      // drop a marker there.) We drop the marker AFTER the 6s idle debounce for a
      // single editor save → no continuous drain churn, one drain at the end of a
      // write burst.
      try {
        fs.writeFileSync(path.join(projectRoot, '.mla_drain.now'), '', 'utf-8');
      } catch {
        /* best-effort */
      }
    } catch {
      // Best-effort — never block the save operation.
    }
  };

  const listener = vscode.workspace.onDidSaveTextDocument((doc) => {
    try {
      const filePath = doc.uri.fsPath;
      if (INDEXABLE_EXTENSIONS.has(path.extname(filePath).toLowerCase()) === false) return;
      const parts = filePath.split(/[\\/]/);
      if (parts.some((p) => INDEX_EXCLUDED_DIRS.has(p))) return;
      const base = path.basename(filePath);
      // Do not queue Tokengram's own state files (avoid an infinite loop)...
      if (
        base.startsWith('.mla_') ||
        base.startsWith('.tokengram') ||
        base.startsWith('.bm25_index')
      )
        return;
      // ...and package-manager lock / secret / generated files (parity with queue_change.py).
      if (INDEX_EXCLUDED_FILE_PATTERNS.some((pat) => base.startsWith(pat))) return;
      if (INDEX_EXCLUDED_FILE_SUFFIXES.some((sfx) => base.endsWith(sfx))) return;

      // Trailing debounce: reset the pending timer for this file, set a new one.
      const existing = pendingTimers.get(filePath);
      if (existing) clearTimeout(existing);
      const timer = setTimeout(() => enqueue(filePath), SAVE_IDLE_MS);
      // Do not keep the Node process alive when VS Code is closing.
      if (typeof timer.unref === 'function') timer.unref();
      pendingTimers.set(filePath, timer);
    } catch {
      // Best-effort — never block the save operation.
    }
  });
  context.subscriptions.push(listener);
  context.subscriptions.push(
    new vscode.Disposable(() => {
      for (const t of pendingTimers.values()) clearTimeout(t);
      pendingTimers.clear();
    }),
  );
}

// Tokengram is the rebrand of "MLA Agent" (publisher.id `erp-intel.mla-agent`).
// If both extensions are installed side-by-side, VS Code shows two status-bar
// widgets, two sets of hooks fire on every Read, and the savings counter is
// split across two files. Prompt the user to uninstall the legacy one.
function warnIfLegacyMlaExtensionPresent(): void {
  const legacy = vscode.extensions.getExtension('erp-intel.mla-agent');
  if (!legacy) return;
  void vscode.window
    .showWarningMessage(
      'Tokengram: the legacy "MLA Agent" extension is still installed. ' +
        'Two status-bar widgets and two hook sets are running side-by-side — ' +
        'please uninstall the old one to avoid double-indexing.',
      'Uninstall MLA Agent',
      'Later',
    )
    .then((choice) => {
      if (choice === 'Uninstall MLA Agent') {
        void vscode.commands.executeCommand(
          'workbench.extensions.uninstallExtension',
          'erp-intel.mla-agent',
        );
      }
    });
}

// Subfolder workspace fix: if the user opens a sub-folder of a Tokengram-configured
// project (e.g. monorepo `apps/web/`), Claude Code looks for `.claude/settings.json`
// only in the workspace root and never walks up. Mirror parent settings down so
// hooks fire in the sub-folder the same way they do in the parent.
function mirrorParentWorkspaceHooks(): void {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) return;
  const ws = folders[0].uri.fsPath;
  if (fs.existsSync(path.join(ws, '.claude', 'settings.json'))) return;

  let dir = path.dirname(ws);
  for (let i = 0; i < 8; i++) {
    const parentSettings = path.join(dir, '.claude', 'settings.json');
    if (fs.existsSync(parentSettings)) {
      try {
        fs.mkdirSync(path.join(ws, '.claude'), { recursive: true });
        fs.copyFileSync(parentSettings, path.join(ws, '.claude', 'settings.json'));
        const parentMcp = path.join(dir, '.mcp.json');
        if (fs.existsSync(parentMcp) && !fs.existsSync(path.join(ws, '.mcp.json'))) {
          fs.copyFileSync(parentMcp, path.join(ws, '.mcp.json'));
        }
        void promptReload(
          'Tokengram: mirrored parent workspace hooks into this sub-folder. Reload to activate.',
        );
      } catch {
        // Best-effort — never block activation.
      }
      return;
    }
    const next = path.dirname(dir);
    if (next === dir) return;
    dir = next;
  }
}

// If the opened project is a Tokengram project (.mcp.json / savings history /
// chroma_db present), ensure the runtime-artifact block is in its .gitignore. This
// runs on every activation (idempotent) so that OLD projects are protected too —
// not just fresh setups. Reason: if the locked .tokengram.*.lock file is not
// gitignored, `git add .` fails fatally.
function ensureProjectGitignoreIfTokengram(): void {
  try {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders || folders.length === 0) return;
    const root = findProjectRoot(folders[0].uri.fsPath);
    const isTokengramProject =
      fs.existsSync(path.join(root, '.mcp.json')) ||
      fs.existsSync(path.join(root, '.mla_savings_history.jsonl')) ||
      fs.existsSync(path.join(root, '.mla_enforcement.flag')) ||
      fs.existsSync(path.join(root, 'chroma_db'));
    if (!isTokengramProject) return;
    ensureGitignore(root);
  } catch {
    /* best-effort — never block activation */
  }
}

export function deactivate() {
  // Kill the spawned reindex CLI children when the window closes —
  // otherwise on Windows the python process orphans and keeps running in the background.
  killActiveReindexChildren();
}

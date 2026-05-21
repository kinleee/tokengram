import * as cp from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';

const TOKENGRAM_HOME = path.join(os.homedir(), '.tokengram');
const VENV_DIR = path.join(TOKENGRAM_HOME, 'venv');
const MIN_PYTHON = [3, 12] as const;

interface PythonInfo {
  path: string;
  version: [number, number, number];
}

// Silent auto-install on activation. No webview. License key is collected
// later via the status-bar menu button — not part of this flow.
export async function ensureAutoInstall(context: vscode.ExtensionContext): Promise<void> {
  if (venvHasTokengram()) {
    // venv exists, but maybe with a stale wheel. Only short-circuit when the
    // installed wheel version is at least as new as the wheel bundled with
    // this extension. Otherwise we need to upgrade.
    const installed = installedWheelVersion();
    const bundled = bundledWheelVersion(context);
    if (installed && bundled && compareSemver(installed, bundled) >= 0) {
      // Even when no install is needed, a freshly-opened workspace may still
      // be missing the Tokengram hook wiring in .claude/settings.json. Without
      // this, Read enforcement silently no-ops in every new project the user
      // opens after the initial install.
      if (workspaceMissingTokengramHooks()) {
        try {
          writeWorkspaceHooks();
          // Surface the silent config-write so the user knows why their newly-
          // opened project suddenly has .claude/settings.json + .mcp.json.
          vscode.window.showInformationMessage(
            'Tokengram: this workspace was wired up — hooks + .mcp.json written. Reload Claude Code so the hooks activate.',
          );
        } catch {
          /* non-fatal — user can re-run setup from the status-bar menu */
        }
      }
      return;
    }
    // fall through — installer with --upgrade swaps the wheel in-place
  }

  const py = await detectPython(context);
  if (!py) {
    // Only cooldown the Python-missing prompt: showing it on every restart is annoying.
    // The install path itself is not cooldowned.
    const last = context.globalState.get<number>('tokengram.pythonPromptCooldown') ?? 0;
    if (Date.now() - last < 10 * 60 * 1000) return;
    await context.globalState.update('tokengram.pythonPromptCooldown', Date.now());
    const dl = 'Download Python 3.12';
    const action = await vscode.window.showWarningMessage(
      'Tokengram needs Python 3.12 or newer. Install it, then reload VS Code.',
      dl,
    );
    if (action === dl) {
      void vscode.env.openExternal(vscode.Uri.parse('https://www.python.org/downloads/'));
    }
    return;
  }

  const isUpgrade = venvHasTokengram();
  try {
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: isUpgrade
          ? 'Tokengram: updating'
          : 'Tokengram: first-time install (~300 MB download)',
        cancellable: false,
      },
      async (progress) => {
        const tracker = makeProgressTracker(progress);

        // STAGE 0 (update only): stop the running MCP server before pip can swap
        // mcp_server.pyd on Windows. Used to be a silent ~5–30s pause.
        if (isUpgrade) {
          tracker.jumpTo(3, 'Stopping any running MCP server processes...');
          await killTokengramVenvProcesses();
          tracker.jumpTo(7, 'MCP server stopped — starting upgrade...');
        }

        tracker.jumpTo(isUpgrade ? 10 : 1, 'Launching installer...');

        // Pip's dependency download is the dominant wait. We can't read pip's
        // real percentage, but we can fill the bar against an elapsed-time
        // budget so the user always sees forward motion. First install pulls
        // ~300MB fresh; an update just re-resolves cached wheels (~15s).
        setExpectedDepsMs(isUpgrade ? 20_000 : 7 * 60_000);
        // Holder pattern so TS doesn't narrow the slow-fill stop fn to null
        // after we clear it once. The closure reassigns inside callbacks.
        const fill: { stop: (() => void) | null } = { stop: null };
        const stopFill = () => {
          if (fill.stop) {
            fill.stop();
            fill.stop = null;
          }
        };

        await runInstaller(context, py.path, (line) => {
          const stageMatch = line.match(/^\[(\d)\/5\]\s*(.*)$/);
          if (stageMatch) {
            const n = stageMatch[1];
            const tail = stageMatch[2];
            handleStageLine(n, tail, tracker, stopFill, (target, durationMs) => {
              stopFill();
              fill.stop = tracker.fillSlowlyTo(target, durationMs);
            });
            return;
          }

          if (line.trim() === 'done') {
            stopFill();
            tracker.jumpTo(95, 'Finalizing...');
            return;
          }

          // Raw pip noise:
          //   - Skip "Requirement already satisfied" deluge from update mode.
          //   - During slow-fill, the timer owns the message (elapsed time);
          //     drop pip chatter so it doesn't flicker over the timer text.
          //     Always let errors through.
          if (/Requirement already satisfied/.test(line)) return;
          const isError = /(error[: ]|ERROR|Failed|failed:)/.test(line);
          if (fill.stop && !isError) return;
          const trimmed = line.length > 80 ? line.slice(0, 77) + '…' : line;
          if (trimmed.trim()) progress.report({ message: trimmed });
        });

        stopFill();
        tracker.jumpTo(97, 'Writing workspace hooks and .mcp.json...');
      },
    );
    // Drop hooks + .mcp.json into the current workspace so Claude Code wires
    // Tokengram in automatically — no follow-up button-click required.
    try {
      writeWorkspaceHooks();
    } catch {
      /* non-fatal — user can still re-run setup or click reindex */
    }
    if (isUpgrade) {
      vscode.window.showInformationMessage('Tokengram updated. Restart Claude Code to pick up the new version.');
      return;
    }
    const setLic = 'Enter license key';
    const action = await vscode.window.showInformationMessage(
      'Tokengram installed. Click the status bar (bottom-right) or use the button to add your license key.',
      setLic,
    );
    if (action === setLic) {
      void vscode.commands.executeCommand('tokengram.menu');
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    vscode.window.showErrorMessage(`Tokengram install failed: ${msg.split('\n')[0]}`);
  }
}

// VS Code's withProgress accepts `increment` (added to current %, 0–100 total).
// Tracker tracks the running total so callers can think in absolute targets.
interface ProgressTracker {
  current(): number;
  jumpTo(target: number, message?: string): void;
  fillSlowlyTo(target: number, durationMs: number): () => void;
}

function makeProgressTracker(
  progress: vscode.Progress<{ message?: string; increment?: number }>,
): ProgressTracker {
  let value = 0;
  return {
    current: () => value,
    jumpTo(target, message) {
      const clamped = Math.max(0, Math.min(100, target));
      if (clamped <= value) {
        if (message !== undefined) progress.report({ message });
        return;
      }
      const inc = clamped - value;
      value = clamped;
      progress.report({ increment: inc, message });
    },
    fillSlowlyTo(target, durationMs) {
      const start = value;
      const cap = Math.min(target, 100);
      const startedAt = Date.now();
      const tickMs = 600;
      const timer = setInterval(() => {
        const elapsed = Date.now() - startedAt;
        const frac = Math.min(1, elapsed / durationMs);
        const projected = start + (cap - start) * frac;
        if (projected > value) {
          const inc = projected - value;
          value = projected;
          progress.report({
            increment: inc,
            message: `Downloading dependencies — ${formatElapsed(elapsed)} elapsed`,
          });
        } else if (elapsed % 3000 < tickMs) {
          // Time-based heartbeat when capped: keep elapsed visible.
          progress.report({
            message: `Downloading dependencies — ${formatElapsed(elapsed)} elapsed`,
          });
        }
        if (frac >= 1) clearInterval(timer);
      }, tickMs);
      return () => clearInterval(timer);
    },
  };
}

function formatElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

// Map installer.py's `[N/5]` markers to concrete progress %-targets. Stage 4
// has multiple sub-steps so we branch on the tail text. The biggest chunk —
// dependency download — kicks off a slow-fill against expectedDepsMs.
function handleStageLine(
  n: string,
  tail: string,
  tracker: ProgressTracker,
  stopFill: () => void,
  startFill: (target: number, durationMs: number) => void,
): void {
  switch (n) {
    case '1':
      stopFill();
      tracker.jumpTo(13, '[1/5] Checking Python version');
      return;
    case '2':
      stopFill();
      tracker.jumpTo(16, '[2/5] Preparing ~/.tokengram directory');
      return;
    case '3':
      stopFill();
      tracker.jumpTo(22, '[3/5] Creating venv + upgrading pip');
      return;
    case '4':
      if (/Removing/i.test(tail)) {
        stopFill();
        tracker.jumpTo(26, '[4/5] Removing previous tokengram install');
      } else if (/Installing tokengram package/i.test(tail)) {
        stopFill();
        tracker.jumpTo(32, '[4/5] Installing tokengram wheel');
      } else if (/Resolving and downloading/i.test(tail)) {
        // The big one. Slow-fill from current value up to 88% over the
        // expected duration. expectedDepsMs is set by the caller.
        tracker.jumpTo(34, '[4/5] Downloading dependencies...');
        startFill(88, getExpectedDepsMs());
      } else {
        // Unknown sub-step under stage 4 — nudge progress so something moves.
        tracker.jumpTo(Math.min(tracker.current() + 1, 88), `[4/5] ${tail}`);
      }
      return;
    case '5':
      stopFill();
      tracker.jumpTo(92, '[5/5] Installing hook scripts');
      return;
    default:
      tracker.jumpTo(tracker.current(), tail);
  }
}

// handleStageLine doesn't know whether we're in install or update mode. The
// caller picks the value; we stash it on a module-level slot updated per-run.
let _expectedDepsMs = 7 * 60_000;
function getExpectedDepsMs(): number {
  return _expectedDepsMs;
}
function setExpectedDepsMs(ms: number): void {
  _expectedDepsMs = ms;
}

export function registerSetupCommand(context: vscode.ExtensionContext): vscode.Disposable {
  // Manual fallback: user can re-run install from Command Palette if the auto path failed.
  return vscode.commands.registerCommand('tokengram.setup', () => ensureAutoInstall(context));
}

function venvHasTokengram(): boolean {
  const binDir = process.platform === 'win32' ? 'Scripts' : 'bin';
  const exe = process.platform === 'win32' ? 'tokengram.exe' : 'tokengram';
  return fs.existsSync(path.join(VENV_DIR, binDir, exe));
}

function installedWheelVersion(): string | null {
  const py = process.platform === 'win32'
    ? path.join(VENV_DIR, 'Scripts', 'python.exe')
    : path.join(VENV_DIR, 'bin', 'python');
  if (!fs.existsSync(py)) return null;
  try {
    const out = cp.execFileSync(
      py,
      ['-c', "import importlib.metadata as m;print(m.version('tokengram'))"],
      { encoding: 'utf-8', timeout: 5000 },
    );
    return out.trim() || null;
  } catch {
    return null;
  }
}

function bundledWheelVersion(context: vscode.ExtensionContext): string | null {
  const resourcesDir = path.join(context.extensionPath, 'resources');
  if (!fs.existsSync(resourcesDir)) return null;
  const wheel = fs
    .readdirSync(resourcesDir)
    .find((f) => f.startsWith('tokengram-') && f.endsWith('.whl'));
  if (!wheel) return null;
  const m = wheel.match(/^tokengram-(\d+\.\d+\.\d+)-/);
  return m?.[1] ?? null;
}

async function killTokengramVenvProcesses(): Promise<void> {
  if (process.platform !== 'win32') return;
  try {
    const script =
      "Get-Process python,pythonw -ErrorAction SilentlyContinue | " +
      "Where-Object { try { $_.Path -and $_.Path.ToLower().Contains('\\.tokengram\\venv\\') } catch { $false } } | " +
      "Select-Object -ExpandProperty Id";
    const out = cp.execFileSync(
      'powershell',
      ['-NoProfile', '-NonInteractive', '-Command', script],
      { encoding: 'utf-8', timeout: 8000 },
    );
    const pids = out.trim().split(/\s+/).filter((s) => /^\d+$/.test(s));
    for (const pidStr of pids) {
      try {
        process.kill(Number(pidStr));
      } catch {
        /* already gone */
      }
    }
    if (pids.length > 0) {
      // Give Windows a moment to release the file handles before pip starts.
      await new Promise((r) => setTimeout(r, 500));
    }
  } catch {
    /* couldn't enumerate processes — fall through; pip will surface the lock error */
  }
}

function compareSemver(a: string, b: string): number {
  const pa = a.split('.').map((n) => parseInt(n, 10) || 0);
  const pb = b.split('.').map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const diff = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

async function detectPython(context: vscode.ExtensionContext): Promise<PythonInfo | null> {
  const override = vscode.workspace.getConfiguration('tokengram').get<string>('pythonPath');
  const candidates: string[] = [];
  if (override) candidates.push(override);
  if (process.platform === 'win32') {
    candidates.push('py -3.12', 'py -3.13', 'python', 'python3');
  } else {
    candidates.push('python3.12', 'python3.13', 'python3', 'python');
  }
  for (const cmd of candidates) {
    const info = await tryPython(cmd);
    if (info && satisfies(info.version, MIN_PYTHON)) {
      return info;
    }
  }
  return null;
}

function tryPython(cmd: string): Promise<PythonInfo | null> {
  return new Promise((resolve) => {
    const parts = cmd.split(' ');
    const child = cp.spawn(parts[0], [...parts.slice(1), '-c', 'import sys,json;print(json.dumps({"v":list(sys.version_info[:3]),"p":sys.executable}))'], { shell: false });
    let out = '';
    child.stdout.on('data', (d) => (out += d.toString()));
    child.on('error', () => resolve(null));
    child.on('close', () => {
      try {
        const j = JSON.parse(out.trim().split('\n').pop() ?? '');
        resolve({ path: j.p, version: j.v });
      } catch {
        resolve(null);
      }
    });
  });
}

function satisfies(actual: [number, number, number], min: readonly [number, number]): boolean {
  if (actual[0] > min[0]) return true;
  if (actual[0] < min[0]) return false;
  return actual[1] >= min[1];
}

async function runInstaller(
  context: vscode.ExtensionContext,
  pythonPath: string,
  onLine: (line: string) => void,
): Promise<void> {
  const installerScript = path.join(context.extensionPath, 'resources', 'installer.py');
  if (!fs.existsSync(installerScript)) {
    throw new Error(`installer.py missing at ${installerScript}`);
  }
  await new Promise<void>((resolve, reject) => {
    // Prefer the wheel bundled with the extension (resources/*.whl). This means
    // a fresh install never depends on PyPI availability or version sync.
    // Falls back to PyPI only when no bundled wheel is present.
    const resourcesDir = path.join(context.extensionPath, 'resources');
    const wheels = fs.existsSync(resourcesDir)
      ? fs.readdirSync(resourcesDir).filter((f) => f.endsWith('.whl'))
      : [];
    const args = ['--tokengram-home', TOKENGRAM_HOME];
    if (wheels.length > 0) {
      args.push('--source', path.join(resourcesDir, wheels[0]));
    }
    const child = cp.spawn(pythonPath, [installerScript, ...args], {
      shell: false,
    });
    const buffer = { stdout: '', stderr: '' };
    const flush = (key: 'stdout' | 'stderr') => {
      const lines = buffer[key].split('\n');
      buffer[key] = lines.pop() ?? '';
      for (const l of lines) if (l) onLine(l);
    };
    child.stdout.on('data', (d) => {
      buffer.stdout += d.toString();
      flush('stdout');
    });
    child.stderr.on('data', (d) => {
      buffer.stderr += d.toString();
      flush('stderr');
    });
    child.on('close', (code) => {
      if (buffer.stdout) onLine(buffer.stdout);
      if (buffer.stderr) onLine(buffer.stderr);
      code === 0 ? resolve() : reject(new Error(`installer exited with code ${code}`));
    });
  });
}

function workspaceMissingTokengramHooks(): boolean {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) return false;
  const settingsPath = path.join(folders[0].uri.fsPath, '.claude', 'settings.json');
  if (!fs.existsSync(settingsPath)) return true;
  try {
    const raw = fs.readFileSync(settingsPath, 'utf-8');
    return !raw.includes('pre_read_check.py');
  } catch {
    return true;
  }
}

export function writeWorkspaceHooks(): boolean {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) return false;
  const root = folders[0].uri.fsPath;
  const claudeDir = path.join(root, '.claude');
  const settingsPath = path.join(claudeDir, 'settings.json');
  fs.mkdirSync(claudeDir, { recursive: true });

  const venvPython =
    process.platform === 'win32'
      ? path.join(VENV_DIR, 'Scripts', 'python.exe')
      : path.join(VENV_DIR, 'bin', 'python');
  const hooksDir = path.join(TOKENGRAM_HOME, 'hooks');

  const hookCmd = (script: string): string =>
    `"${venvPython}" "${path.join(hooksDir, script)}"`;

  const hookConfig = {
    hooks: {
      PreToolUse: [
        {
          matcher: 'Read',
          hooks: [{ type: 'command', command: hookCmd('pre_read_check.py') }],
        },
      ],
      PostToolUse: [
        {
          matcher: 'Edit|Write|MultiEdit',
          hooks: [{ type: 'command', command: hookCmd('queue_change.py') }],
        },
        {
          matcher: 'Grep',
          hooks: [{ type: 'command', command: hookCmd('post_grep_check.py') }],
        },
        {
          matcher: 'Bash',
          hooks: [{ type: 'command', command: hookCmd('post_bash_check.py') }],
        },
      ],
      Stop: [
        {
          hooks: [{ type: 'command', command: hookCmd('savings_report.py') }],
        },
      ],
    },
  };

  let existing: Record<string, unknown> = {};
  if (fs.existsSync(settingsPath)) {
    try {
      existing = JSON.parse(fs.readFileSync(settingsPath, 'utf-8')) as Record<string, unknown>;
    } catch {
      const backup = settingsPath + '.bak-' + Date.now();
      fs.copyFileSync(settingsPath, backup);
    }
  }
  const merged = { ...existing, ...hookConfig };
  fs.writeFileSync(settingsPath, JSON.stringify(merged, null, 2), 'utf-8');

  const mcpPath = path.join(root, '.mcp.json');
  // Use `-m tokengram` (goes through __main__.py) — the canonical entry that
  // sets up sys.path before loading .pyd modules. server.py works too post-fix,
  // but __main__.py has always been the documented entry point.
  const tokengramEntry = {
    command: venvPython,
    args: ['-m', 'tokengram'],
    env: {
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
    },
  };
  // Merge with any existing .mcp.json so we don't clobber other MCP servers the
  // user has configured (e.g. their own custom servers).
  let mcpConfig: { mcpServers: Record<string, unknown> } = { mcpServers: {} };
  if (fs.existsSync(mcpPath)) {
    fs.copyFileSync(mcpPath, mcpPath + '.bak-' + Date.now());
    try {
      mcpConfig = JSON.parse(fs.readFileSync(mcpPath, 'utf-8'));
      if (!mcpConfig.mcpServers) mcpConfig.mcpServers = {};
    } catch {
      mcpConfig = { mcpServers: {} };
    }
  }
  delete mcpConfig.mcpServers['mla-agent'];
  delete mcpConfig.mcpServers['mla_agent'];
  mcpConfig.mcpServers['tokengram'] = tokengramEntry;
  fs.writeFileSync(mcpPath, JSON.stringify(mcpConfig, null, 2), 'utf-8');
  return true;
}


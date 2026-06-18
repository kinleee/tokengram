import * as cp from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';

const TOKENGRAM_HOME = path.join(os.homedir(), '.tokengram');
const VENV_DIR = path.join(TOKENGRAM_HOME, 'venv');
// Wheel cp312-only; cp313 hələ yoxdur, ona görə EXACT 3.12 tələbi.
const REQUIRED_PYTHON = [3, 12] as const;

// Canonical license-server URL. Pinned into ~/.tokengram/server_url.txt on every
// activation so a stale leftover (old parked domain / Cloudflare worker / raw IP)
// can never override it and resurrect the "network_error:AbortError" license toast.
const LICENSE_SERVER_URL = 'https://tokengram.click';

// Self-heal: rewrite server_url.txt only when it's missing or a KNOWN-stale value
// (the old workers.dev worker or the raw EC2 IP). A deliberate custom HTTPS URL is
// left untouched. Runs on activation; never throws.
export function pinServerUrl(): void {
  try {
    const f = path.join(TOKENGRAM_HOME, 'server_url.txt');
    const cur = fs.existsSync(f) ? fs.readFileSync(f, 'utf-8').trim() : '';
    const stale = cur === '' || /workers\.dev|54\.163\.13\.24/i.test(cur);
    if (stale && cur !== LICENSE_SERVER_URL) {
      fs.mkdirSync(TOKENGRAM_HOME, { recursive: true });
      fs.writeFileSync(f, LICENSE_SERVER_URL, 'utf-8');
    }
  } catch {
    /* best effort — must never block activation */
  }
}

interface PythonInfo {
  path: string;
  version: [number, number, number];
}

// Track an in-progress install so the status-bar menu can show "please wait"
// instead of the misleading "not installed yet — open wizard" modal that used
// to fire when a tester clicked the bar during the first-time download.
let installInFlight = false;
export function isInstalling(): boolean {
  return installInFlight;
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
    if (installed && bundled && compareSemver(installed, bundled) >= 0 && !installedTokengramBroken()) {
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

  // uv özü Python 3.12-ni provision edir — artıq sistemdə 3.12 axtarmırıq.
  // "Python 3.12 yoxdur" problemi bununla aradan qalxır (testerlərdə əsas fail).
  const isUpgrade = venvHasTokengram();
  installInFlight = true;
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

        // uv-ni təmin et (yoxdursa bir dəfə endir + cache). uv sonra Python
        // 3.12-ni provision edəcək — user-də heç bir Python olmasa belə.
        tracker.jumpTo(isUpgrade ? 8 : 1, 'Preparing runtime (uv)...');
        const uvPath = await ensureUv((m) => progress.report({ message: m }));
        tracker.jumpTo(isUpgrade ? 10 : 3, 'Launching installer...');

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

        // Real download/install progress: installer.py streams `[DL] <done> <target>`
        // byte counts (venv growth on disk) while uv installs deps. These drive the
        // bar for real; the time component below only gives early motion during the
        // network window when venv is still ~flat.
        let depsDone = 0;
        let depsTarget = 0;
        const startDeps = (durationMs: number) => {
          stopFill();
          const startVal = tracker.current(); // ~34 after the stage-4 jump
          const band = 88 - startVal;
          const startedAt = Date.now();
          const timer = setInterval(() => {
            const timePct = Math.min((Date.now() - startedAt) / durationMs, 1);
            const diskPct = depsTarget > 0 ? Math.min(depsDone / depsTarget, 0.99) : 0;
            // Whichever is further along wins; cap < 100% so we never claim done early.
            const pct = Math.min(Math.max(timePct, diskPct), 0.99);
            tracker.jumpTo(
              startVal + pct * band,
              `[4/5] Installing dependencies — ${Math.round(pct * 100)}%`,
            );
          }, 700);
          fill.stop = () => clearInterval(timer);
        };

        await runInstaller(context, uvPath, (line) => {
          const stageMatch = line.match(/^\[(\d)\/5\]\s*(.*)$/);
          if (stageMatch) {
            const n = stageMatch[1];
            const tail = stageMatch[2];
            handleStageLine(n, tail, tracker, stopFill, startDeps);
            return;
          }

          // Real byte progress from installer.py's monitor thread. Must be
          // handled before the noise filter below (which drops lines while the
          // deps timer is running).
          const dlMatch = line.match(/^\[DL\]\s+(\d+)\s+(\d+)/);
          if (dlMatch) {
            depsDone = Number(dlMatch[1]);
            depsTarget = Number(dlMatch[2]);
            return;
          }

          if (line.trim() === 'done') {
            stopFill();
            tracker.jumpTo(95, 'Finalizing...');
            return;
          }

          // Raw pip noise:
          //   - Skip "Requirement already satisfied" deluge from update mode.
          //   - While the deps timer is running it owns the message (the live
          //     "Installing dependencies — NN%"); drop pip/uv chatter so it
          //     doesn't flicker over it. Always let errors through.
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
    // Open the license input directly — testers were previously clicking the
    // status bar mid-install and getting a misleading "not installed yet" modal.
    // Skipping the intermediate confirmation removes one click and one chance
    // to misroute.
    void vscode.commands.executeCommand('tokengram.setLicenseKey');
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    // Mirror the reindex flow: the first line is usually a generic wrapper
    // ("installer exited with code N"); the real cause is the last non-empty
    // line of the captured pip/venv output. Show that in the toast and dump
    // the full transcript into a dedicated channel for follow-up.
    const lines = msg.split('\n').map((l) => l.trim()).filter(Boolean);
    const summary =
      lines
        .slice()
        .reverse()
        .find((l) => !/^installer exited with code/i.test(l)) ?? lines[0] ?? msg;
    const channel = vscode.window.createOutputChannel('Tokengram Install');
    channel.appendLine(msg);
    const logPath = path.join(os.homedir(), '.tokengram', 'install.log');
    if (fs.existsSync(logPath)) {
      channel.appendLine('');
      channel.appendLine(`Full persistent transcript: ${logPath}`);
      channel.appendLine('(send this file to support to pinpoint the cause)');
    }
    channel.show(true);
    vscode.window.showErrorMessage(
      `Tokengram install failed: ${summary} (full log: ~/.tokengram/install.log)`,
    );
  } finally {
    installInFlight = false;
  }
}

// VS Code's withProgress accepts `increment` (added to current %, 0–100 total).
// Tracker tracks the running total so callers can think in absolute targets.
interface ProgressTracker {
  current(): number;
  jumpTo(target: number, message?: string): void;
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
  };
}

// Map installer.py's `[N/5]` markers to concrete progress %-targets. Stage 4
// has multiple sub-steps so we branch on the tail text. The biggest chunk —
// dependency download — kicks off a slow-fill against expectedDepsMs.
function handleStageLine(
  n: string,
  tail: string,
  tracker: ProgressTracker,
  stopFill: () => void,
  startDeps: (durationMs: number) => void,
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
        // The big one. Drive the bar 34→88% from real on-disk byte growth
        // (installer.py's `[DL]` lines), with a time fallback for early motion.
        tracker.jumpTo(34, '[4/5] Installing dependencies — 0%');
        startDeps(getExpectedDepsMs());
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

// `python -m tokengram` (həm MCP server, həm reindex CLI buradan keçir) paketdə
// `__main__.py` TƏLƏB edir. Bəzi köhnə wheel-lər onsuz ship olunmuşdu → "No
// module named tokengram.__main__" və həm server, həm reindex sınırdı. Versiya
// müqayisəsi "güncəldir" desə belə, bu sınıq vəziyyəti aşkar edib təmir edirik.
function installedTokengramBroken(): boolean {
  const pkgDir = path.join(VENV_DIR, 'Lib', 'site-packages', 'tokengram');
  if (!fs.existsSync(pkgDir)) return false; // paket yoxdursa "sınıq" demə
  return !fs.existsSync(path.join(pkgDir, '__main__.py'));
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
  // Yalnız 3.12 axtarırıq. `py -3.13` və ya plain `python` (3.13 ola bilər)
  // namizədləri çıxardıq — wheel cp312-only-dir, 3.13 venv-də install fail edir
  // (`Package 'tokengram' requires a different Python: 3.13.x not in '<3.13,>=3.12'`).
  if (process.platform === 'win32') {
    candidates.push('py -3.12');
  } else {
    candidates.push('python3.12');
  }
  for (const cmd of candidates) {
    const info = await tryPython(cmd);
    if (info && exactPython(info.version, REQUIRED_PYTHON)) {
      return info;
    }
  }
  return null;
}

function exactPython(actual: [number, number, number], required: readonly [number, number]): boolean {
  return actual[0] === required[0] && actual[1] === required[1];
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
  // legacy helper, retained for any callers; current code uses exactPython()
  if (actual[0] > min[0]) return true;
  if (actual[0] < min[0]) return false;
  return actual[1] >= min[1];
}

const UV_EXE = path.join(TOKENGRAM_HOME, 'uv.exe');
const UV_URL =
  'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip';

// uv-ni təmin et: ~/.tokengram/uv.exe varsa onu qaytar, yoxdursa bir dəfə endir
// (retry-lı) + Expand-Archive ilə çıxar + cache et. uv tək binary-dir (Python
// tələb etmir) və sonra Python 3.12-ni özü provision edir.
async function ensureUv(onMsg: (m: string) => void): Promise<string> {
  if (fs.existsSync(UV_EXE)) return UV_EXE;
  fs.mkdirSync(TOKENGRAM_HOME, { recursive: true });
  const zipPath = path.join(TOKENGRAM_HOME, 'uv-download.zip');
  onMsg('Downloading uv (one-time, ~24 MB)...');

  let lastErr: unknown = null;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const res = await fetch(UV_URL, { redirect: 'follow' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // Stream the body so we can show a REAL byte percentage instead of a
      // silent ~24 MB stall. Content-Length is present on GitHub releases.
      const total = Number(res.headers.get('content-length')) || 0;
      const totalMb = total > 0 ? (total / 1_000_000).toFixed(1) : '?';
      const chunks: Buffer[] = [];
      let received = 0;
      let lastReport = 0;
      if (res.body) {
        const reader = res.body.getReader();
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          chunks.push(Buffer.from(value));
          received += value.length;
          const now = Date.now();
          if (now - lastReport > 150) {
            lastReport = now;
            const mb = (received / 1_000_000).toFixed(1);
            onMsg(
              total > 0
                ? `Downloading runtime (uv) — ${mb} / ${totalMb} MB · ${Math.round((received / total) * 100)}%`
                : `Downloading runtime (uv) — ${mb} MB`,
            );
          }
        }
        fs.writeFileSync(zipPath, Buffer.concat(chunks));
      } else {
        // No streamable body (shouldn't happen on Node fetch) — fall back.
        fs.writeFileSync(zipPath, Buffer.from(await res.arrayBuffer()));
      }
      lastErr = null;
      break;
    } catch (e) {
      lastErr = e;
      onMsg(`uv download failed (attempt ${attempt}/3), retrying...`);
    }
  }
  if (lastErr) {
    throw new Error(
      `Could not download uv from ${UV_URL}: ` +
        `${lastErr instanceof Error ? lastErr.message : String(lastErr)}. ` +
        'Check your internet connection / proxy, then retry install.',
    );
  }

  onMsg('Extracting uv...');
  await new Promise<void>((resolve, reject) => {
    const ps = cp.spawn(
      'powershell.exe',
      [
        '-NoProfile',
        '-NonInteractive',
        '-Command',
        `Expand-Archive -LiteralPath '${zipPath}' -DestinationPath '${TOKENGRAM_HOME}' -Force`,
      ],
      { shell: false },
    );
    let err = '';
    ps.stderr.on('data', (d) => (err += d.toString()));
    ps.on('error', reject);
    ps.on('close', (code) =>
      code === 0
        ? resolve()
        : reject(new Error(`Expand-Archive failed (${code}): ${err.trim()}`)),
    );
  });
  try {
    fs.unlinkSync(zipPath);
  } catch {
    /* ignore cleanup failure */
  }
  if (!fs.existsSync(UV_EXE)) {
    throw new Error('uv.exe not found after extracting the uv archive.');
  }
  return UV_EXE;
}

async function runInstaller(
  context: vscode.ExtensionContext,
  uvPath: string,
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
    // readdirSync sırası FS-asılıdır; alphabetic "0.1.10" < "0.1.9" (ASCII).
    // Bütün wheel-ləri tap, semver ilə descending sort, ən yenisini seç.
    const wheels = fs.existsSync(resourcesDir)
      ? fs.readdirSync(resourcesDir).filter((f) => f.startsWith('tokengram-') && f.endsWith('.whl'))
      : [];
    const wheelVersion = (name: string): string => {
      const m = name.match(/^tokengram-(\d+\.\d+\.\d+)/);
      return m?.[1] ?? '0.0.0';
    };
    wheels.sort((a, b) => compareSemver(wheelVersion(b), wheelVersion(a)));
    // `uv run --python 3.12` installer.py-ni uv-nin provision etdiyi 3.12 ilə
    // işə salır (sistemdə 3.12 yoxdursa avtomatik endirir). --no-project/--no-config
    // cwd-dəki yad pyproject.toml/uv.toml-un götürülməsinin qarşısını alır.
    const args = [
      'run',
      '--python',
      '3.12',
      '--no-project',
      '--no-config',
      installerScript,
      '--uv',
      uvPath,
      '--tokengram-home',
      TOKENGRAM_HOME,
    ];
    if (wheels.length > 0) {
      args.push('--source', path.join(resourcesDir, wheels[0]));
    }
    const child = cp.spawn(uvPath, args, {
      shell: false,
      cwd: TOKENGRAM_HOME,
      // installer.py Azərbaycan hərfli log yazır; pipe-da default cp1252
      // UnicodeEncodeError verir. UTF-8 məcbur et (installer özü də reconfigure edir).
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
    });
    const buffer = { stdout: '', stderr: '' };
    // Keep every line we've seen so the catch handler can surface the real
    // failure cause — without this, a non-zero exit was reported as just
    // "installer exited with code 1" with the actual pip/venv error lost.
    const captured: string[] = [];
    const flush = (key: 'stdout' | 'stderr') => {
      const lines = buffer[key].split('\n');
      buffer[key] = lines.pop() ?? '';
      for (const l of lines)
        if (l) {
          captured.push(l);
          onLine(l);
        }
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
      if (buffer.stdout) {
        captured.push(buffer.stdout);
        onLine(buffer.stdout);
      }
      if (buffer.stderr) {
        captured.push(buffer.stderr);
        onLine(buffer.stderr);
      }
      if (code === 0) {
        resolve();
      } else {
        reject(
          new Error(
            `installer exited with code ${code}\n` +
              captured.slice(-30).join('\n'),
          ),
        );
      }
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
        // PERF (0.1.49): Grep və Bash PostToolUse hook-ları çıxarıldı. Onlar yalnız
        // qənaət-analitikası yazırdı (funksional iş yox), amma hər Grep/Bash-a soyuq
        // Python prosesi (~90ms) əlavə edirdi. Qənaət barı indi YALNIZ search_code
        // (MCP server, gecikməsiz) + Read (pre_read) event-lərindən hesablanır —
        // yəni "kod axtarışı/oxuması" üzrə qənaət. savings_report.py riyaziyyatı
        // dəyişmir: bu event-lər gəlmədikdə onları həm qənaətdən, həm xərcdən
        // avtomatik çıxarır. (post_grep_check.py / post_bash_check.py faylları
        // diskdə qalır — yalnız işə salınmır.)
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
      // sentence-transformers/HF online check işçi thread-i hang edir (queue_stuck).
      // Offline məcburi olmasa indexing dayanır — bu üç var mütləqdir.
      HF_HUB_OFFLINE: '1',
      TRANSFORMERS_OFFLINE: '1',
      ANONYMIZED_TELEMETRY: 'False',
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

  // Tokengram bu layihədə chroma_db/, kilidlər, növbə, qənaət tarixçəsi və s.
  // per-machine runtime faylları yaradır — onlar user-in commit-lərinə düşməməlidir.
  ensureGitignore(root);
  return true;
}

// Layihənin .gitignore-una Tokengram bloku əlavə et ki, per-machine artefaktlar
// (chroma_db/, .tokengram.*.lock, .mla_*, .bm25_index.pkl, ...) git-ə getməsin.
// Idempotent: sentinel comment təkrar yazılmanın qarşısını alır. Setup action-ına
// (writeWorkspaceHooks) bağlıdır — activation-da səssiz yazı DEYİL. Git layihəsi
// deyilsə (nə .git, nə .gitignore var) toxunmuruq — boş qovluğa fayl atmırıq.
export function ensureGitignore(root: string): void {
  const SENTINEL = '# >>> Tokengram (auto-managed) — runtime artifacts, do not commit >>>';
  try {
    const isGitRepo = fs.existsSync(path.join(root, '.git'));
    const giPath = path.join(root, '.gitignore');
    const hasGitignore = fs.existsSync(giPath);
    if (!isGitRepo && !hasGitignore) return;

    let cur = '';
    try {
      cur = fs.readFileSync(giPath, 'utf-8');
    } catch {
      cur = '';
    }
    if (cur.includes('# >>> Tokengram (auto-managed)')) return; // artıq yazılıb

    const block =
      SENTINEL + '\n' +
      'chroma_db/\n' +
      'chroma_db.broken-*/\n' +
      'chroma_db.corrupt-*/\n' +
      '.bm25_index.pkl\n' +
      '.file_hashes.json\n' +
      '.mla_pending.txt\n' +
      '.mla_pending.processing\n' +
      '.mla_session_log.jsonl\n' +
      '.mla_session_log.jsonl.processing.*\n' +
      '.mla_savings_history.jsonl\n' +
      '.mla_savings_history.jsonl.bak.*\n' +
      '.mla_enforcement.flag\n' +
      '.mla_arch.md\n' +
      '.mla_arch_state.json\n' +
      '.mla_db_health.json\n' +
      '.tokengram.writer.lock\n' +
      '.tokengram.drainer.lock\n' +
      '.tokengram.leader.lock\n' +
      '.tokengram.reindex.want\n' +
      '.tokengram.*.lock.tmp.*\n' +
      '*.quarantine_pending\n' +
      '# <<< Tokengram (auto-managed) <<<\n';
    const sep = cur === '' ? '' : cur.endsWith('\n') ? '\n' : '\n\n';
    fs.appendFileSync(giPath, sep + block, 'utf-8');
  } catch {
    // Best-effort — heç vaxt setup-u bloklama.
  }
}


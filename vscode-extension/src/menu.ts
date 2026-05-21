import * as cp from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';
import { tr } from './i18n';
import {
  activate as activateLicense,
  checkKey,
  effectiveStatus,
  readServerUrl,
  refreshStatus,
} from './licenseStatus';
import { findProjectRoot } from './savingsReader';

interface MenuItem extends vscode.QuickPickItem {
  action:
    | 'toggle'
    | 'refresh'
    | 'reset'
    | 'arch'
    | 'reindex'
    | 'sync'
    | 'license'
    | 'breakdown';
}

function venvHasTokengram(): boolean {
  const binDir = process.platform === 'win32' ? 'Scripts' : 'bin';
  const exe = process.platform === 'win32' ? 'tokengram.exe' : 'tokengram';
  return fs.existsSync(path.join(os.homedir(), '.tokengram', 'venv', binDir, exe));
}

async function setLicenseKey(): Promise<void> {
  if (!venvHasTokengram()) {
    const openWizard = 'Open setup wizard';
    const action = await vscode.window.showWarningMessage(
      'Tokengram is not installed yet. Setup must complete before a license key can be saved.',
      { modal: true },
      openWizard,
    );
    if (action === openWizard) {
      await vscode.commands.executeCommand('tokengram.setup');
    }
    return;
  }

  const input = await vscode.window.showInputBox({
    prompt: tr('license.prompt'),
    placeHolder: tr('license.placeholder'),
    password: false,
    ignoreFocusOut: true,
    validateInput: (v) => {
      const t = (v ?? '').trim();
      if (!t) return tr('license.empty');
      if (!t.startsWith('mla_live_') && !t.startsWith('mla_test_')) {
        return tr('license.invalidFormat');
      }
      return null;
    },
  });
  if (!input) return;
  const trimmed = input.trim();

  const serverUrl = readServerUrl();
  if (!serverUrl) {
    vscode.window.showErrorMessage(tr('license.noServerUrl'));
    return;
  }

  // Two-step validation:
  //   1. /check-key — fast "is this key in the DB and tied to an active subscription?"
  //   2. /activate  — authoritative device-binding check ("can THIS machine use this key?")
  // Both must succeed before we touch the local key file.
  const outcome = await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: tr('license.validating'),
      cancellable: false,
    },
    async () => {
      const check = await checkKey(trimmed, serverUrl);
      if (!check.valid) return { kind: 'check_failed' as const, check };
      const act = await activateLicense(trimmed, serverUrl);
      return { kind: 'activated' as const, check, activate: act };
    },
  );

  if (outcome.kind === 'check_failed') {
    vscode.window.showErrorMessage(
      tr('license.invalidByServer', {
        reason: outcome.check.reason ?? 'unknown',
      }),
    );
    return;
  }

  const act = outcome.activate;
  if (!act.ok) {
    let msg: string;
    switch (act.reason) {
      case 'machine_mismatch':
        msg = tr('license.machineMismatch');
        break;
      case 'no_active_subscription':
      case 'invalid_license':
        msg = tr('license.invalidByServer', { reason: act.reason });
        break;
      case 'missing_venv':
        msg = tr('license.venvMissing');
        break;
      case 'fingerprint_error':
        msg = tr('license.fingerprintError', { detail: act.detail ?? '' });
        break;
      case 'network_error':
        msg = tr('license.activateNetworkError', { detail: act.detail ?? '' });
        break;
      default:
        msg = tr('license.invalidByServer', { reason: act.detail ?? 'unknown' });
    }
    vscode.window.showErrorMessage(msg);
    return;
  }

  const mlaDir = path.join(os.homedir(), '.mla');
  fs.mkdirSync(mlaDir, { recursive: true });
  fs.writeFileSync(path.join(mlaDir, 'license_key.txt'), trimmed, {
    encoding: 'utf-8',
    mode: 0o600,
  });
  fs.writeFileSync(path.join(mlaDir, 'server_url.txt'), serverUrl, {
    encoding: 'utf-8',
  });

  // Cache the just-validated status so statusBar reflects "valid" immediately.
  await refreshStatus();

  vscode.window.showInformationMessage(tr('license.saved'));
}

async function ensureLicenseActiveForToggle(): Promise<boolean> {
  // Force a fresh server check rather than trusting a stale local cache —
  // the user is explicitly asking to turn enforcement on right now.
  const fresh = await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Window,
      title: tr('license.validating'),
    },
    async () => refreshStatus(),
  );
  return fresh.valid;
}

function readFlag(root: string): 'on' | 'off' {
  try {
    const v = fs
      .readFileSync(path.join(root, '.mla_enforcement.flag'), 'utf-8')
      .trim()
      .toLowerCase();
    return v === 'on' ? 'on' : 'off';
  } catch {
    return 'off';
  }
}

function execFile(
  bin: string,
  args: string[],
  cwd: string,
  extraEnv: Record<string, string> = {},
): Promise<{ stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    cp.execFile(
      bin,
      args,
      {
        cwd,
        encoding: 'utf-8',
        env: { ...process.env, CLAUDE_PROJECT_DIR: cwd, ...extraEnv },
        // Reindex can produce hundreds of KB of log output (chromadb / hf logs)
        // — default 1MB is fine but we set it explicitly to avoid surprises.
        maxBuffer: 16 * 1024 * 1024,
      },
      (err, stdout, stderr) => {
        if (err) {
          reject(new Error(`${err.message}\n${stderr}`));
        } else {
          resolve({ stdout, stderr });
        }
      },
    );
  });
}

interface McpServerEntry {
  command: string;
  args?: string[];
  env?: Record<string, string>;
}

interface ResolvedMcp {
  server: McpServerEntry;
  cwd: string;
}

function resolveMcpServer(workspace: string): ResolvedMcp | null {
  // Tokengram MCP-i konkret olaraq running olduğu konfiqurasiya ilə çağırırıq:
  // həm dev (system python + mcp_server.py), həm install (venv + run_mcp_server.py)
  // eyni `--reindex <path> --fresh` CLI rejimini dəstəkləyir.
  // `command`/`args` adətən relativ yollardır — `.mcp.json` qovluğunu cwd kimi
  // qaytarırıq ki, "python mcp_server.py" düzgün resolve olsun.

  // 1) Walk up from workspace looking for .mcp.json (Claude Code's own
  //    discovery does the same thing).
  let dir = workspace;
  for (let i = 0; i < 8; i++) {
    const hit = readMcpConfig(path.join(dir, '.mcp.json'));
    if (hit) return { server: hit, cwd: dir };
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }

  // 2) Fall back to Claude settings (project-scoped, then user-scoped).
  const fallbacks = [
    path.join(workspace, '.claude', 'settings.json'),
    path.join(os.homedir(), '.claude', 'settings.json'),
  ];
  for (const p of fallbacks) {
    const hit = readMcpConfig(p);
    if (hit) return { server: hit, cwd: path.dirname(path.dirname(p)) };
  }

  return null;
}

function readMcpConfig(p: string): McpServerEntry | null {
  try {
    const raw = fs.readFileSync(p, 'utf-8');
    const cfg = JSON.parse(raw);
    const servers = cfg.mcpServers ?? {};
    const entry =
      servers['mla-agent'] ??
      servers['tokengram'] ??
      servers['mla_agent'];
    if (entry && typeof entry.command === 'string') {
      return entry as McpServerEntry;
    }
  } catch {
    /* skip */
  }
  return null;
}

// Hooks və lazımi modullar `~/.tokengram/`-da yoxdursa, VSIX bundle-dakı
// resources/hooks/-dan kopyalayır. Hooks artıq mövcuddursa toxunmur.
function ensureGlobalHooks(extensionPath: string): boolean {
  const homeHooks = path.join(TOKENGRAM_HOME, 'hooks');
  const homeMessages = path.join(TOKENGRAM_HOME, 'messages');
  const homeMlaConsts = path.join(TOKENGRAM_HOME, 'mla_constants.py');
  const homeI18n = path.join(TOKENGRAM_HOME, 'i18n.py');

  const allPresent =
    fs.existsSync(path.join(homeHooks, 'pre_read_check.py')) &&
    fs.existsSync(homeMlaConsts) &&
    fs.existsSync(homeI18n);
  if (allPresent) return true;

  const srcHooks = path.join(extensionPath, 'resources', 'hooks');
  const srcMessages = path.join(extensionPath, 'resources', 'messages');
  const srcMlaConsts = path.join(extensionPath, 'resources', 'mla_constants.py');
  const srcI18n = path.join(extensionPath, 'resources', 'i18n.py');

  if (!fs.existsSync(srcHooks)) return false;

  try {
    fs.mkdirSync(TOKENGRAM_HOME, { recursive: true });
    fs.cpSync(srcHooks, homeHooks, { recursive: true });
    if (fs.existsSync(srcMessages)) {
      fs.cpSync(srcMessages, homeMessages, { recursive: true });
    }
    if (fs.existsSync(srcMlaConsts)) fs.copyFileSync(srcMlaConsts, homeMlaConsts);
    if (fs.existsSync(srcI18n)) fs.copyFileSync(srcI18n, homeI18n);
    return true;
  } catch {
    return false;
  }
}

// Layihənin `.claude/settings.json`-na Tokengram hook bağlamaları əlavə edir.
// Mövcud field-lərə (model, effortLevel, və s.) toxunmur — yalnız `hooks`
// sahəsi yazılır. Köhnə Tokengram hook konfiqi varsa, yeniləyir.
function ensureProjectHookSettings(workspace: string): void {
  const claudeDir = path.join(workspace, '.claude');
  const settingsPath = path.join(claudeDir, 'settings.json');
  fs.mkdirSync(claudeDir, { recursive: true });

  const hooksDir = path.join(TOKENGRAM_HOME, 'hooks');
  const py = fs.existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python';
  const hookCmd = (script: string): string =>
    `"${py}" "${path.join(hooksDir, script)}"`;

  const hookConfig = {
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
        hooks: [
          { type: 'command', command: hookCmd('savings_report.py') },
          { type: 'command', command: hookCmd('flush_queue.py') },
        ],
      },
    ],
  };

  let existing: { hooks?: unknown; [k: string]: unknown } = {};
  if (fs.existsSync(settingsPath)) {
    try {
      existing = JSON.parse(fs.readFileSync(settingsPath, 'utf-8'));
    } catch {
      fs.copyFileSync(settingsPath, settingsPath + '.bak-' + Date.now());
    }
  }
  existing.hooks = hookConfig;
  fs.writeFileSync(settingsPath, JSON.stringify(existing, null, 2), 'utf-8');
}

// Re-index düyməsi əksik `.mcp.json`-u öz-özünə yaradır ki, hər layihə üçün
// installer-i ProjectPath ilə təkrar işlətməyə ehtiyac qalmasın. Yalnız fayl
// həqiqətən yoxdursa yazırıq — mövcud config-i heç vaxt üzərinə yazmırıq.
function ensureMcpConfigForReindex(workspace: string): ResolvedMcp | null {
  const target = path.join(workspace, '.mcp.json');
  if (fs.existsSync(target)) return null; // mövcud fayla toxunma — istifadəçinin öz konfigi var

  // Qlobal install-da `~/.tokengram/venv` olmalıdır. Olmayanda yaradacaq config
  // işləməyəcək, ona görə də setup-suz mühitə fayl yazmırıq.
  if (!fs.existsSync(VENV_PYTHON)) return null;

  const cfg = {
    mcpServers: {
      tokengram: {
        command: VENV_PYTHON,
        args: ['-m', 'tokengram'],
        env: {
          PYTHONUNBUFFERED: '1',
          PYTHONIOENCODING: 'utf-8',
        },
      },
    },
  };

  try {
    fs.writeFileSync(target, JSON.stringify(cfg, null, 2), { encoding: 'utf-8' });
  } catch {
    return null;
  }

  const entry = readMcpConfig(target);
  return entry ? { server: entry, cwd: workspace } : null;
}

const TOKENGRAM_HOME = path.join(os.homedir(), '.tokengram');
const VENV_PYTHON =
  process.platform === 'win32'
    ? path.join(TOKENGRAM_HOME, 'venv', 'Scripts', 'python.exe')
    : path.join(TOKENGRAM_HOME, 'venv', 'bin', 'python');

function resolvePython(): string {
  return fs.existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python';
}

function resolveHookScript(rel: string, workspace: string): string {
  // Prefer the canonical install location (~/.tokengram/hooks/...)
  const installed = path.join(TOKENGRAM_HOME, rel);
  if (fs.existsSync(installed)) return installed;
  // Dev fallback: hooks inside the workspace (legacy install.ps1 layout)
  const local = path.join(workspace, rel);
  if (fs.existsSync(local)) return local;
  return installed; // surface the canonical path in the "not found" error
}

function pythonScript(root: string, rel: string, args: string[] = []) {
  return execFile(resolvePython(), [resolveHookScript(rel, root), ...args], root);
}

function projectRoot(): string | undefined {
  // Walk-up to the real Tokengram root so menu actions (reset / toggle /
  // refresh) touch the same files the status bar reads. If the user opens a
  // subfolder of a Tokengram-managed repo, `workspaceFolders[0]` is that
  // subfolder; without walk-up, reset writes an empty history next to it
  // while the bar keeps reading the populated one in the parent.
  const ws = vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath;
  return ws ? findProjectRoot(ws) : undefined;
}

async function runAction(action: MenuItem['action'], root: string, extensionPath: string) {
  const channel = vscode.window.createOutputChannel('MLA Agent');
  switch (action) {
    case 'toggle': {
      const cur = readFlag(root);
      const next = cur === 'on' ? 'off' : 'on';
      if (next === 'on') {
        const ok = await ensureLicenseActiveForToggle();
        if (!ok) {
          const state = effectiveStatus();
          const msg =
            state === 'no_key'
              ? tr('menu.toggleNeedsLicense')
              : tr('menu.toggleLicenseInvalid');
          const action = await vscode.window.showErrorMessage(
            msg,
            tr('menu.setLicense'),
          );
          if (action === tr('menu.setLicense')) {
            await setLicenseKey();
          }
          break;
        }
      }
      fs.writeFileSync(path.join(root, '.mla_enforcement.flag'), next, {
        encoding: 'utf-8',
      });
      vscode.window.showInformationMessage(
        tr('menu.toggleResult', { output: `MLA enforcement: ${next.toUpperCase()}` }),
      );
      break;
    }
    case 'refresh': {
      const history = path.join(root, '.mla_savings_history.jsonl');
      try {
        const now = new Date();
        fs.utimesSync(history, now, now);
      } catch {
        fs.writeFileSync(history, '', { encoding: 'utf-8', flag: 'a' });
      }
      vscode.window.showInformationMessage(tr('menu.refreshResult'));
      break;
    }
    case 'reset': {
      const choice = await vscode.window.showWarningMessage(
        tr('menu.resetConfirm'),
        { modal: true },
        tr('menu.resetConfirmYes'),
      );
      if (choice !== tr('menu.resetConfirmYes')) return;
      const history = path.join(root, '.mla_savings_history.jsonl');
      let summary: string;
      if (!fs.existsSync(history) || fs.statSync(history).size === 0) {
        fs.writeFileSync(history, '', 'utf-8');
        summary = 'Savings history already empty.';
      } else {
        let backup = history + '.bak';
        if (fs.existsSync(backup)) {
          const ts = new Date()
            .toISOString()
            .replace(/[-:TZ.]/g, '')
            .slice(0, 15);
          backup = `${history}.bak.${ts}`;
        }
        fs.copyFileSync(history, backup);
        fs.writeFileSync(history, '', 'utf-8');
        summary = `Savings history reset. Backup: ${path.basename(backup)}`;
      }
      // Also wipe the in-flight session log so the bar's "live badge"
      // doesn't keep showing pending savings from the turn before reset.
      const sessionLog = path.join(root, '.mla_session_log.jsonl');
      try {
        fs.unlinkSync(sessionLog);
      } catch {
        /* not present or already empty — fine */
      }
      vscode.window.showInformationMessage(
        tr('menu.resetResult', { output: summary }),
      );
      break;
    }
    case 'arch': {
      const archDoc = path.join(root, '.mla_arch.md');
      channel.clear();
      if (fs.existsSync(archDoc)) {
        channel.appendLine(fs.readFileSync(archDoc, 'utf-8'));
      } else {
        channel.appendLine(tr('menu.archMissing'));
      }
      channel.show(true);
      break;
    }
    case 'reindex': {
      // Tam layihə setup-u: hooks (~/.tokengram), per-project hook bindings,
      // .mcp.json və nəhayət `--reindex` çağırışı. Hər addım yalnız əksik
      // olduqda işləyir — mövcud user faylları üzərinə yazılmır.
      const hooksOk = ensureGlobalHooks(extensionPath);
      if (!hooksOk && !fs.existsSync(path.join(TOKENGRAM_HOME, 'hooks', 'pre_read_check.py'))) {
        vscode.window.showWarningMessage(tr('menu.reindexHooksMissing'));
      } else {
        ensureProjectHookSettings(root);
      }

      let resolved = resolveMcpServer(root);
      if (!resolved) {
        resolved = ensureMcpConfigForReindex(root);
        if (!resolved) {
          vscode.window.showErrorMessage(tr('menu.reindexNoRoot'));
          break;
        }
        vscode.window.showInformationMessage(tr('menu.reindexCreatedConfig'));
      }
      const { server, cwd: serverCwd } = resolved;
      const serverArgs = server.args ?? [];
      const reindexArgs = [...serverArgs, '--reindex', root, '--fresh'];
      const serverEnv = server.env ?? {};
      try {
        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: tr('menu.reindexTitle'),
            cancellable: false,
          },
          async (progress) => {
            const captured: string[] = [];
            await streamingReindex(
              server.command,
              reindexArgs,
              serverCwd,
              serverEnv,
              progress,
              captured,
            );
            channel.clear();
            channel.appendLine(captured.join('\n'));
          },
        );
        vscode.window.showInformationMessage(tr('menu.reindexDone'));
      } catch (e) {
        const msg = (e as Error).message ?? String(e);
        channel.clear();
        channel.appendLine(msg);
        channel.show(true);
        vscode.window.showErrorMessage(
          tr('menu.reindexFailed', { output: msg.split('\n')[0] }),
        );
      }
      break;
    }
    case 'sync': {
      const { stderr } = await pythonScript(root, 'hooks/savings_report.py');
      const summary = stderr.split('\n').find((l) => l.includes('[mla-agent]'));
      vscode.window.showInformationMessage(
        summary ?? tr('menu.syncDoneFallback'),
      );
      break;
    }
    case 'license': {
      await setLicenseKey();
      break;
    }
    case 'breakdown': {
      const sessionLog = path.join(root, '.mla_session_log.jsonl');
      const history = path.join(root, '.mla_savings_history.jsonl');
      const lastCheck = path.join(os.homedir(), '.mla', 'last_check.json');

      const readSafe = (p: string, tailLines?: number): string => {
        if (!fs.existsSync(p)) return tr('breakdown.missing');
        try {
          const txt = fs.readFileSync(p, 'utf-8');
          if (!txt.trim()) return tr('breakdown.empty');
          if (tailLines) {
            const lines = txt.trim().split('\n');
            return lines.slice(-tailLines).join('\n');
          }
          return txt.trim();
        } catch (e) {
          return `(read error: ${(e as Error).message})`;
        }
      };

      channel.clear();
      channel.appendLine(`# ${tr('breakdown.title')}`);
      channel.appendLine(`# generated: ${new Date().toLocaleString()}`);
      channel.appendLine(`# workspace: ${root}`);
      channel.appendLine('');
      channel.appendLine(tr('breakdown.sessionLogHeading'));
      channel.appendLine(`# path: ${sessionLog}`);
      channel.appendLine(readSafe(sessionLog));
      channel.appendLine('');
      channel.appendLine(tr('breakdown.historyHeading'));
      channel.appendLine(`# path: ${history}`);
      channel.appendLine(readSafe(history, 5));
      channel.appendLine('');
      channel.appendLine(tr('breakdown.licenseHeading'));
      channel.appendLine(`# path: ${lastCheck}`);
      channel.appendLine(readSafe(lastCheck));
      channel.show(true);
      break;
    }
  }
}

export function registerMenuCommand(
  context: vscode.ExtensionContext,
): vscode.Disposable {
  return vscode.commands.registerCommand('tokengram.menu', async () => {
    const root = projectRoot();
    if (!root) {
      vscode.window.showErrorMessage(tr('menu.noWorkspace'));
      return;
    }
    const flag = readFlag(root);
    const items: MenuItem[] = [
      {
        label: flag === 'on' ? tr('menu.toggleOff') : tr('menu.toggleOn'),
        description: tr('menu.currentState', { state: flag.toUpperCase() }),
        action: 'toggle',
      },
      {
        label: tr('menu.refresh'),
        description: tr('menu.refreshDesc'),
        action: 'refresh',
      },
      {
        label: tr('menu.arch'),
        description: tr('menu.archDesc'),
        action: 'arch',
      },
      {
        label: tr('menu.sync'),
        description: tr('menu.syncDesc'),
        action: 'sync',
      },
      {
        label: tr('menu.reindex'),
        description: tr('menu.reindexDesc'),
        action: 'reindex',
      },
      {
        label: tr('menu.license'),
        description: tr('menu.licenseDesc'),
        action: 'license',
      },
      {
        label: tr('menu.breakdown'),
        description: tr('menu.breakdownDesc'),
        action: 'breakdown',
      },
      {
        label: tr('menu.reset'),
        description: tr('menu.resetDesc'),
        action: 'reset',
      },
    ];
    const pick = await vscode.window.showQuickPick(items, {
      placeHolder: tr('menu.placeholder'),
      matchOnDescription: true,
    });
    if (!pick) return;
    try {
      await runAction(pick.action, root, context.extensionPath);
    } catch (err) {
      vscode.window.showErrorMessage(
        tr('menu.error', {
          action: pick.action,
          message: (err as Error).message,
        }),
      );
    }
  });
}

// Streaming reindex runner — spawns the wheel's `--reindex` CLI and routes its
// `[N/3]` stage banners into vscode.window.withProgress so the notification
// shows real progress instead of a static "may take a minute" message with an
// indeterminate spinner.
//
// Stage map (matches the banners printed by mcp_server._cli_reindex):
//   start        →  5%   "Starting Tokengram..."
//   [1/3] scan   → 25%   "Files being scanned"
//   [2/3] model  → 50%, slow-fill to 85% over ~45s for first-run HF download
//   [3/3] index  → 90%   "N chunks being indexed"
//   ✓ Hazır       → 100% (success)
function streamingReindex(
  bin: string,
  args: string[],
  cwd: string,
  extraEnv: Record<string, string>,
  progress: vscode.Progress<{ message?: string; increment?: number }>,
  captured: string[],
): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = cp.spawn(bin, args, {
      cwd,
      env: { ...process.env, CLAUDE_PROJECT_DIR: cwd, ...extraEnv },
    });

    let value = 0;
    const jumpTo = (target: number, message?: string) => {
      const clamped = Math.max(0, Math.min(100, target));
      if (clamped <= value) {
        if (message !== undefined) progress.report({ message });
        return;
      }
      const inc = clamped - value;
      value = clamped;
      progress.report({ increment: inc, message });
    };

    let modelFillTimer: NodeJS.Timeout | null = null;
    const stopModelFill = () => {
      if (modelFillTimer) {
        clearInterval(modelFillTimer);
        modelFillTimer = null;
      }
    };
    const startModelFill = () => {
      stopModelFill();
      const startedAt = Date.now();
      const cap = 85;
      const expectedMs = 45_000; // first-run HF model download; cached is ~2s
      const start = value;
      modelFillTimer = setInterval(() => {
        const elapsed = Date.now() - startedAt;
        const frac = Math.min(1, elapsed / expectedMs);
        const projected = start + (cap - start) * frac;
        if (projected > value) {
          const inc = projected - value;
          value = projected;
          progress.report({
            increment: inc,
            message: `Embedding model loading — ${Math.floor(elapsed / 1000)}s elapsed`,
          });
        }
        if (frac >= 1) stopModelFill();
      }, 600);
    };

    jumpTo(5, 'Starting Tokengram...');

    let buf = '';
    const onChunk = (data: Buffer | string) => {
      buf += data.toString();
      const lines = buf.split('\n');
      buf = lines.pop() ?? '';
      for (const line of lines) {
        const trimmed = line.trimEnd();
        if (!trimmed) continue;
        captured.push(trimmed);

        const stage = trimmed.match(/\[(\d)\/3\]\s*(.*)$/);
        if (stage) {
          const [, n, tail] = stage;
          if (n === '1') {
            stopModelFill();
            jumpTo(25, `[1/3] ${cleanTail(tail) || 'Scanning files'}`);
          } else if (n === '2') {
            jumpTo(50, `[2/3] ${cleanTail(tail) || 'Loading embedding model'}`);
            startModelFill();
          } else if (n === '3') {
            stopModelFill();
            jumpTo(90, `[3/3] ${cleanTail(tail) || 'Indexing chunks'}`);
          }
          continue;
        }

        if (/^\s*✓\s*Haz[ıi]r/i.test(trimmed) || /Hazır:.*indeksl/i.test(trimmed)) {
          stopModelFill();
          jumpTo(100, 'Done');
        }
      }
    };

    child.stdout.on('data', onChunk);
    child.stderr.on('data', onChunk);
    child.on('error', (err) => {
      stopModelFill();
      reject(err);
    });
    child.on('close', (code) => {
      stopModelFill();
      if (buf.trim()) captured.push(buf.trim());
      if (code === 0) {
        jumpTo(100);
        resolve();
      } else {
        reject(
          new Error(`reindex exited with code ${code}\n${captured.slice(-20).join('\n')}`),
        );
      }
    });
  });
}

// Strip emoji + leading icons so the progress message stays compact on Windows
// notifications where emoji may render as boxes.
function cleanTail(s: string): string {
  return s
    .replace(/^[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]+\s*/u, '')
    .replace(/:\s*.*$/, '')
    .trim();
}

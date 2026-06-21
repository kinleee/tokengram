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
  fetchPubkey,
  readServerUrl,
  refreshStatus,
  startTrial,
} from './licenseStatus';
import { findProjectRoot } from './savingsReader';
import { isInstalling, promptReload, ensureClaudeMdGuidance } from './setupWizard';

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
  // python.exe-ni də tələb et (setupWizard.venvHasTokengram güzgüsü): interpreter
  // karantinə düşmüş qalıq venv "sağlam" sayılmasın → setLicenseKey təzə qurulum
  // təklif etsin (2026-06-19 partial-venv insidenti).
  const py = process.platform === 'win32' ? 'python.exe' : 'python';
  const root = path.join(os.homedir(), '.tokengram', 'venv', binDir);
  return fs.existsSync(path.join(root, exe)) && fs.existsSync(path.join(root, py));
}

async function setLicenseKey(): Promise<void> {
  if (!venvHasTokengram()) {
    if (isInstalling()) {
      // Install is already running (progress notification visible bottom-right).
      // Don't offer a "wizard" button that just spawns a duplicate install —
      // the license dialog will open automatically when setup finishes.
      vscode.window.showInformationMessage(
        'Tokengram is still installing — please wait. The license key dialog will open automatically when setup finishes.',
      );
      return;
    }
    const retry = 'Retry install';
    const showLog = 'Show install log';
    const logPath = path.join(os.homedir(), '.tokengram', 'install.log');
    const hasLog = fs.existsSync(logPath);
    const buttons = hasLog ? [retry, showLog] : [retry];
    const action = await vscode.window.showWarningMessage(
      hasLog
        ? 'Tokengram setup did not complete. Run install again — if it keeps failing, click "Show install log" and send the file to support so we can pinpoint the cause.'
        : 'Tokengram setup did not complete. Run install again, then enter your license key.',
      { modal: true },
      ...buttons,
    );
    if (action === retry) {
      await vscode.commands.executeCommand('tokengram.setup');
    } else if (action === showLog) {
      await vscode.window.showTextDocument(vscode.Uri.file(logPath));
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

  const tokengramDir = path.join(os.homedir(), '.tokengram');
  fs.mkdirSync(tokengramDir, { recursive: true });
  fs.writeFileSync(path.join(tokengramDir, 'license_key.txt'), trimmed, {
    encoding: 'utf-8',
    mode: 0o600,
  });
  fs.writeFileSync(path.join(tokengramDir, 'server_url.txt'), serverUrl, {
    encoding: 'utf-8',
  });

  // JWT public key-i endir — license.from_env() onu ~/.tokengram/pubkey.pem-dən
  // oxuyur. Fayl olmasa MCP server hər validation-da xəta atır (təmiz install
  // heç vaxt "valid" olmaz). Best-effort: alınmasa istifadəçiyə xəbər ver.
  const pubkeyOk = await fetchPubkey(serverUrl);
  if (!pubkeyOk) {
    vscode.window.showWarningMessage(
      'Tokengram: public key endirilmədi (server əlçatmaz?). Açar saxlanıldı, ' +
        'amma server bərpa olunanda re-index/setup-u təkrar işlət.',
    );
  }

  // Cache the just-validated status so statusBar reflects "valid" immediately.
  await refreshStatus();

  void promptReload(tr('license.saved'));
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

// Tokengram MCP girişinin MÜTLƏQ ehtiyac duyduğu env dəyişənləri.
// Offline flag-lar olmadan sentence-transformers HF online check-də worker
// thread-i asır (queue_stuck insidenti) — embedding fazası heç bitmir.
const REQUIRED_MCP_ENV: Record<string, string> = {
  PYTHONUNBUFFERED: '1',
  PYTHONIOENCODING: 'utf-8',
  HF_HUB_OFFLINE: '1',
  TRANSFORMERS_OFFLINE: '1',
  ANONYMIZED_TELEMETRY: 'False',
};

// Köhnə extension versiyalarının yazdığı `.mcp.json`-larda offline env-lər yox
// idi və Re-index onları heç vaxt təmir etmirdi — köhnə tester embedding-də
// HF şəbəkə yoxlamasına ilişirdi. İndi yalnız ƏSKİK env açarlarını əlavə
// edirik; command/args/istifadəçinin öz dəyərlərinə toxunulmur.
function repairMcpEnv(target: string): void {
  try {
    const raw = fs.readFileSync(target, 'utf-8');
    const cfg = JSON.parse(raw) as {
      mcpServers?: Record<string, { env?: Record<string, string> }>;
    };
    const entry = cfg.mcpServers?.tokengram;
    if (!entry) return;
    const env = entry.env ?? {};
    let changed = false;
    for (const [k, v] of Object.entries(REQUIRED_MCP_ENV)) {
      if (!(k in env)) {
        env[k] = v;
        changed = true;
      }
    }
    if (!changed) return;
    entry.env = env;
    fs.writeFileSync(target, JSON.stringify(cfg, null, 2), { encoding: 'utf-8' });
  } catch {
    /* təmir best-effort-dur — pozulmuş JSON-a toxunmuruq */
  }
}

// Re-index düyməsi əksik `.mcp.json`-u öz-özünə yaradır ki, hər layihə üçün
// installer-i ProjectPath ilə təkrar işlətməyə ehtiyac qalmasın. Mövcud faylda
// yalnız əskik məcburi env açarları tamamlanır (repairMcpEnv) — qalanı user-indir.
function ensureMcpConfigForReindex(workspace: string): ResolvedMcp | null {
  const target = path.join(workspace, '.mcp.json');
  if (fs.existsSync(target)) {
    repairMcpEnv(target);
    return null; // command/args-a toxunmuruq — resolveMcpServer mövcud faylı oxuyacaq
  }

  // Qlobal install-da `~/.tokengram/venv` olmalıdır. Olmayanda yaradacaq config
  // işləməyəcək, ona görə də setup-suz mühitə fayl yazmırıq.
  if (!fs.existsSync(VENV_PYTHON)) return null;

  const cfg = {
    mcpServers: {
      tokengram: {
        command: VENV_PYTHON,
        args: ['-m', 'tokengram'],
        env: { ...REQUIRED_MCP_ENV },
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

// Açar yoxdursa trial təklif et (reindex uğurundan sonra çağırılır).
// MCP server ilk tool çağırışında trial-ı onsuz da özü başlada bilir, amma
// o an offline-dırsa search sadəcə xəta verir — burada istifadəçiyə aydın
// "bir dəfəlik internet lazımdır" konteksti ilə düymə veririk.
async function offerTrialIfKeyless(): Promise<void> {
  if (effectiveStatus() !== 'no_key') return;
  const startBtn = tr('trial.startButton');
  const action = await vscode.window.showInformationMessage(tr('trial.offer'), startBtn);
  if (action !== startBtn) return;

  const serverUrl = readServerUrl() ?? 'https://tokengram.click';
  const outcome = await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: tr('trial.starting'),
      cancellable: false,
    },
    () => startTrial(serverUrl),
  );
  if (outcome.ok) {
    const days = outcome.trial_ends_at
      ? Math.max(1, Math.ceil((outcome.trial_ends_at - Date.now() / 1000) / 86400))
      : null;
    vscode.window.showInformationMessage(
      tr('trial.started', { days: days === null ? '—' : String(days) }),
    );
  } else if (outcome.reason === 'trial_expired') {
    vscode.window.showWarningMessage(tr('trial.expired'));
  } else {
    vscode.window.showErrorMessage(
      tr('trial.failed', { detail: outcome.detail ?? outcome.reason }),
    );
  }
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

// ── Deep recovery — kritik donmadan terminal olmadan çıxış ───────────────
// Uzunömürlü MCP serverləri Claude Code spawn edir (.mcp.json) — extension
// onları birbaşa restart edə bilmir. AMMA donmuş prosesi PID ilə öldürə bilir;
// öləndə Claude Code MCP disconnect-i görüb təzə server spawn edir. Recovery:
//   1) writer/drainer kilidini CANLI tutub irəliləməyən (DB N saniyə yazılmayıb)
//      donmuş server(lər)i tap və öldür,
//   2) ölü-PID stale lock + orfan `.tmp.<pid>` fayllarını sil (idempotent),
//   3) savings history-ni touch edib status bar-ı dərhal yenilə.
const LOCK_NAMES = ['.tokengram.writer.lock', '.tokengram.drainer.lock'];
// Donmuş server LEADER lock-u tuta bilər (writer/drainer YOX) — onu da kill +
// stale-clear namizədinə qat. 2026-06-18 insidenti: server model-yükündə
// C-extension (torch/HNSW) GIL-i tutub donmuşdu, yalnız `.tokengram.leader.lock`
// saxlayırdı → köhnə detektor (writer/drainer-ə baxırdı) "healthy" deyirdi,
// içəri-proses watchdog isə GIL boşalmadığı üçün os._exit edə bilmirdi. Yeganə
// etibarlı xilas: extension (ayrı proses) prosesi PID ilə öldürsün.
const HOLDER_LOCK_NAMES = [
  '.tokengram.writer.lock',
  '.tokengram.drainer.lock',
  '.tokengram.leader.lock',
];
// İndeksləmə bu qədər saniyə irəliləmirsə (chroma.sqlite3 / .processing mtime
// yenilənmir) = donub. Soyuq model yükü (~70s) eşikdən aşağıdır ki, canlı uzun
// indeks yanlışlıqla öldürülməsin (2026-06-17: real donma 13 dəq idi).
const DB_NOPROGRESS_SEC = 120;

function isPidAlive(pid: number): boolean {
  if (!pid || pid <= 0) return false;
  try {
    // sig 0 = yalnız mövcudluq yoxlaması. Node-da ÖLDÜRMÜR (Python os.kill-dən
    // fərqli — orada Windows-da sig 0 prosesi öldürür).
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return (e as NodeJS.ErrnoException).code === 'EPERM'; // var, amma icazə yox
  }
}

function killPid(pid: number): boolean {
  try {
    if (process.platform === 'win32') {
      cp.execFileSync('taskkill', ['/F', '/T', '/PID', String(pid)], {
        stdio: 'ignore',
      });
    } else {
      process.kill(pid, 'SIGKILL');
    }
    return true;
  } catch {
    return false;
  }
}

// Kilid faylından {pid, ts} oxu. KRİTİK: canlı writer.lock yalnız 0-cı baytı
// kilidləyir, JSON isə offset 1-dədir (db_guard._acquire_lock). Bütün faylı
// oxumaq kilidli 0-cı bayta görə fail olur — ona görə offset 1-dən də sınayırıq.
// drainer.lock (advisory) tam oxunur. Beləcə DONMUŞ writer.lock sahibinin
// PID-ni belə (kilid tutulu ikən) ala bilirik.
function readLockOwner(p: string): { pid?: number; ts?: number } | null {
  const parse = (s: string): { pid?: number; ts?: number } | null => {
    const a = s.indexOf('{');
    const b = s.lastIndexOf('}');
    if (a >= 0 && b > a) {
      try {
        return JSON.parse(s.slice(a, b + 1));
      } catch {
        /* torn/partial */
      }
    }
    return null;
  };
  try {
    const r = parse(fs.readFileSync(p, 'utf-8'));
    if (r) return r;
  } catch {
    /* byte 0 kilidli ola bilər — aşağıda offset 1-dən sına */
  }
  try {
    const fd = fs.openSync(p, 'r');
    try {
      const buf = Buffer.alloc(256);
      const n = fs.readSync(fd, buf, 0, 256, 1); // faylda offset 1-dən oxu
      return parse(buf.toString('utf-8', 0, n));
    } finally {
      fs.closeSync(fd);
    }
  } catch {
    /* yox */
  }
  return null;
}

// Ölü-PID lock faylları + orfan `.tokengram.*.lock.tmp.<pid>` (kəsilmiş atomik
// yazı) sil. Yalnız sahib PID ÖLÜBSƏ — canlıya toxunma. db_guard.clear_stale_locks
// ilə eyni məntiq (TS tərəfi, server rebuild olmadan dərhal işləsin deyə).
function clearStaleLocks(root: string): string[] {
  const cleared: string[] = [];
  let entries: string[] = [];
  try {
    entries = fs.readdirSync(root);
  } catch {
    return cleared;
  }
  for (const name of entries) {
    const full = path.join(root, name);
    if (HOLDER_LOCK_NAMES.includes(name)) {
      const owner = readLockOwner(full);
      // Oxunmursa (canlı byte-lock) və ya sahib canlıdırsa → toxunma.
      if (owner && typeof owner.pid === 'number' && !isPidAlive(owner.pid)) {
        try {
          fs.unlinkSync(full);
          cleared.push(name);
        } catch {
          /* başqası tutub — keç */
        }
      }
      continue;
    }
    const m = name.match(/^\.tokengram\.(?:writer|drainer|leader)\.lock\.tmp\.(\d+)$/);
    if (m && !isPidAlive(parseInt(m[1], 10))) {
      try {
        fs.unlinkSync(full);
        cleared.push(name);
      } catch {
        /* keç */
      }
    }
  }
  return cleared;
}

// Növbədə gözləyən UNİKAL fayl sayı (.mla_pending.txt + .processing birləşib).
// Bar-dakı ⟳N ilə eyni — dublikatlar bir sayılır.
function uniquePendingCount(root: string): number {
  const set = new Set<string>();
  for (const name of ['.mla_pending.txt', '.mla_pending.processing']) {
    try {
      for (const line of fs.readFileSync(path.join(root, name), 'utf-8').split('\n')) {
        const t = line.trim().toLowerCase();
        if (t) set.add(t);
      }
    } catch {
      /* fayl yoxdur */
    }
  }
  return set.size;
}

// İndeksləmə fəaliyyətindən keçən saniyə: drain irəlilədikcə chroma.sqlite3
// (yazı) və/və ya .processing (növbə təhvili) mtime-ı yenilənir. Ən təzə
// toxunuşdan keçən vaxt — bu DB_NOPROGRESS-dən böyükdürsə drain dayanıb.
function indexingActivityAgeSec(root: string): number {
  let newest = 0;
  const paths = [
    path.join(root, 'chroma_db', 'chroma.sqlite3'),
    path.join(root, '.mla_pending.processing'),
  ];
  for (const p of paths) {
    try {
      const m = fs.statSync(p).mtimeMs;
      if (m > newest) newest = m;
    } catch {
      /* yox */
    }
  }
  if (newest === 0) return Infinity;
  return (Date.now() - newest) / 1000;
}

// Bütün lock fayllarını (writer + drainer + LEADER) tutan CANLI PID-lər.
function liveLockHolders(root: string): number[] {
  const pids = new Set<number>();
  for (const name of HOLDER_LOCK_NAMES) {
    const full = path.join(root, name);
    if (!fs.existsSync(full)) continue;
    const owner = readLockOwner(full);
    if (owner && typeof owner.pid === 'number' && isPidAlive(owner.pid)) {
      pids.add(owner.pid);
    }
  }
  return [...pids];
}

interface RecoveryResult {
  killed: number[];
  cleared: string[];
  pending: number;
  activityAgeSec: number;
  stuck: boolean;
}

// Növbə-əsaslı donma aşkarı (köhnə yalnız-writer/drainer-lock yanaşmasını əvəz
// edir): görüləsi iş var (pending>0) AMMA indeksləmə DB_NOPROGRESS-dir irəliləmir
// → donub. Donmuş halda: bütün CANLI lock sahiblərini (LEADER daxil) öldür,
// ölü-PID stale lock + orfanları sil. Drenləmənin ÖZÜ (reindex) çağıran tərəfdə
// edilir (extensionPath lazımdır) — kill yalnız donmuş prosesi azad edir.
function deepRecover(root: string): RecoveryResult {
  const pending = uniquePendingCount(root);
  const activityAgeSec = indexingActivityAgeSec(root);
  // "Donmuş" üçün ÜÇ şərt birlikdə lazımdır: (1) görüləsi iş var (pending>0),
  // (2) indeksləmə DB_NOPROGRESS-dir irəliləmir, (3) CANLI bir proses lock tutub.
  // 3-cü şərt kritikdir: canlı lock sahibi yoxdursa öldürüləsi DONMUŞ proses də
  // yoxdur — ya server ümumiyyətlə işləmir, ya növbə orfandır. O halda "stuck"
  // demək = "killed 0 frozen process(es)" kimi YALANÇI alarm. holders-i kill-dən
  // ƏVVƏL bir dəfə oxuyuruq (kill onları öldürəndən sonra siyahı boşalır).
  const holders = liveLockHolders(root);
  const stuck =
    pending > 0 && activityAgeSec > DB_NOPROGRESS_SEC && holders.length > 0;
  const killed: number[] = [];
  if (stuck) {
    for (const pid of holders) {
      if (killPid(pid)) killed.push(pid);
    }
  }
  // Öldürdükdən sonra: indi-ölü sahiblərin lock faylları + orfanları təmizlə.
  const cleared = clearStaleLocks(root);
  // Status bar-ı dərhal yenilə (heç vaxt "heç nə etmədi" olmasın).
  const history = path.join(root, '.mla_savings_history.jsonl');
  try {
    const now = new Date();
    fs.utimesSync(history, now, now);
  } catch {
    try {
      fs.writeFileSync(history, '', { encoding: 'utf-8', flag: 'a' });
    } catch {
      /* yox */
    }
  }
  return { killed, cleared, pending, activityAgeSec, stuck };
}

// Avtomatik recovery (autoRecoverIfStuck) SİLİNDİ (2026-06-19 yenidən-qurma):
// köhnə davamlı poll-drain + watchdog/self-heal qülləsi getdi → "GIL-donmuş
// server" halı artıq mövcud deyil, ona görə bar dövründən avtomatik kill+reindex
// də lazım deyil. Növbə task sonu Stop hook-da (server bağlısa onun soyuq
// fallback-ı ilə) drenlənir. Manual eskalasiya: aşağıdakı `refresh` (deepRecover)
// və `reindex` düymələri qalır.

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
      // venv interpreter yoxdursa (qırıq/partial venv) bərpa mənasızdır — drenləyən
      // proses ola bilməz. "İndeksləyirəm..." deyib sonra Setup-a atmaq əvəzinə
      // dərhal tək aydın mesaj ver (2026-06-19 partial-venv UX).
      if (!fs.existsSync(VENV_PYTHON)) {
        const setupBtn = tr('menu.runSetupButton');
        const action = await vscode.window.showWarningMessage(
          tr('menu.reindexNoRoot'),
          setupBtn,
        );
        if (action === setupBtn) {
          await vscode.commands.executeCommand('tokengram.setup');
        }
        break;
      }
      const result = await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: tr('menu.refreshTitle'),
          cancellable: false,
        },
        async () => deepRecover(root),
      );

      if (result.stuck) {
        // Donmuş drain — sahibləri öldürdük (varsa). İNDİ avtomatik reindex ilə
        // drenlə: "healthy deyir amma N fayl ilişib" UX-i bitir, düymə ƏSL düzəldir.
        const mins = Math.floor(result.activityAgeSec / 60);
        vscode.window.showWarningMessage(
          tr('menu.refreshRecovered', {
            n: result.killed.length,
            mins: Number.isFinite(mins) ? mins : 0,
            pending: result.pending,
          }),
        );
        await runAction('reindex', root, extensionPath);
      } else if (result.pending > 0) {
        // Növbə var, amma donma yox. İki hal:
        //  - canlı sahib var → server aktiv drenləyir (soyuq yük/aktiv drain),
        //    nə öldür nə reindex; sadəcə "gedir" de.
        //  - canlı sahib yox → orfan növbə (server işləmir). İstifadəçi dərin
        //    bərpa düyməsinə basıb — növbəni özümüz incremental reindex ilə
        //    drenləyirik (collision yox, çünki canlı indeksləyici yoxdur).
        if (liveLockHolders(root).length === 0) {
          vscode.window.showInformationMessage(
            tr('menu.refreshDraining', { pending: result.pending }),
          );
          await runAction('reindex', root, extensionPath);
        } else {
          vscode.window.showInformationMessage(
            tr('menu.refreshInProgress', { pending: result.pending }),
          );
        }
      } else if (result.cleared.length > 0) {
        // Növbə boş, amma ölü-proses qalıq kilidləri təmizləndi.
        vscode.window.showInformationMessage(
          tr('menu.refreshCleared', { cleared: result.cleared.length }),
        );
      } else {
        // Hər şey sağlam — sadəcə bar yeniləndi.
        vscode.window.showInformationMessage(tr('menu.refreshResult'));
      }
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
        // search_code-a yönləndirən idarə olunan CLAUDE.md bloku (setupWizard
        // ilə eyni). Re-index yolu da activation yolu ilə paritet olsun.
        ensureClaudeMdGuidance(root);
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
      let { server } = resolved;
      const { cwd: serverCwd } = resolved;
      // .mcp.json mütləq python.exe yoluna işarə edə bilər, amma o interpreter
      // fiziki olaraq YOXDUR (venv silinib/yarımçıq qalıb) → cp.spawn xam
      // "ENOENT" verir, istifadəçi səbəbi anlamır (2026-06-19 tester insidenti).
      // Spawn-dan ƏVVƏL yoxla: command bir yol (path-separator var) və mövcud
      // deyilsə, canlı VENV_PYTHON ilə əvəz et; o da yoxdursa Setup-a yönəlt.
      const cmdIsPath = /[\\/]/.test(server.command);
      if (cmdIsPath && !fs.existsSync(server.command)) {
        if (fs.existsSync(VENV_PYTHON)) {
          // venv var, sadəcə .mcp.json köhnə/yanlış yola baxır — canlı yolla işlət.
          server = { ...server, command: VENV_PYTHON };
        } else {
          const setupBtn = tr('menu.runSetupButton');
          const action = await vscode.window.showWarningMessage(
            tr('menu.reindexNoRoot'),
            setupBtn,
          );
          if (action === setupBtn) {
            await vscode.commands.executeCommand('tokengram.setup');
          }
          break;
        }
      }
      const serverArgs = server.args ?? [];
      // İncremental (default): yalnız dəyişən faylları yenidən embed edir
      // (dəyişməyənləri hash ilə atlayır). İlk dəfə (boş index) onsuz da hamısını
      // qurur. `--fresh` (tam silmə) yalnız format dəyişikliyi/korrupsiya üçündür.
      const reindexArgs = [...serverArgs, '--reindex', root];
      const serverEnv = server.env ?? {};
      try {
        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: tr('menu.reindexTitle'),
            cancellable: true,
          },
          async (progress, token) => {
            const captured: string[] = [];
            await streamingReindex(
              server.command,
              reindexArgs,
              serverCwd,
              serverEnv,
              progress,
              captured,
              token,
            );
            channel.clear();
            channel.appendLine(captured.join('\n'));
          },
        );
        vscode.window.showInformationMessage(tr('menu.reindexDone'));
        // Açarsız maşında reindex uğurla bitir, amma search_code lisenziya
        // xətası verəcək — tester "reindex pozdu" düşünür. Burada trial
        // təklif edirik ki, axtarış işləməyə başlasın.
        void offerTrialIfKeyless();
      } catch (e) {
        const msg = (e as Error).message ?? String(e);
        // Spawn ENOENT (interpreter yoxdur — pre-check tutmayıbsa, məs. PATH-dakı
        // `python` tapılmır): xam "ENOENT" əvəzinə aydın Setup yönləndirməsi ver.
        if ((e as NodeJS.ErrnoException).code === 'ENOENT' || /\bENOENT\b/.test(msg)) {
          channel.clear();
          channel.appendLine(msg);
          channel.show(true);
          const setupBtn = tr('menu.runSetupButton');
          const action = await vscode.window.showWarningMessage(
            tr('menu.reindexNoRoot'),
            setupBtn,
          );
          if (action === setupBtn) {
            await vscode.commands.executeCommand('tokengram.setup');
          }
          break;
        }
        channel.clear();
        channel.appendLine(msg);
        channel.show(true);
        // Notification: prefer the last meaningful stderr line (the real
        // failure cause) over the first line, which is usually a generic
        // "exited with code N" or "Command failed:" wrapper.
        const lines = msg.split('\n').map((l) => l.trim()).filter(Boolean);
        const summary =
          lines.reverse().find(
            (l) =>
              !/^Command failed:/i.test(l) &&
              !/^reindex exited with code/i.test(l),
          ) ?? lines[0] ?? msg;
        vscode.window.showErrorMessage(
          tr('menu.reindexFailed', { output: summary }),
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

export function registerSetLicenseKeyCommand(): vscode.Disposable {
  // Standalone command so the auto-installer can open the license input
  // directly after install completes, without bouncing through the menu.
  return vscode.commands.registerCommand('tokengram.setLicenseKey', setLicenseKey);
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
      const m = (err as Error).message ?? String(err);
      // İstənilən action-da interpreter ENOENT-i (məs. 'sync' → savings_report.py
      // qırıq venv python ilə): xam "spawn python ENOENT" əvəzinə Setup yönləndir.
      if ((err as NodeJS.ErrnoException).code === 'ENOENT' || /\bENOENT\b/.test(m)) {
        const setupBtn = tr('menu.runSetupButton');
        const action = await vscode.window.showWarningMessage(
          tr('menu.reindexNoRoot'),
          setupBtn,
        );
        if (action === setupBtn) {
          await vscode.commands.executeCommand('tokengram.setup');
        }
        return;
      }
      vscode.window.showErrorMessage(
        tr('menu.error', {
          action: pick.action,
          message: m,
        }),
      );
    }
  });
}

// Spawn olunan reindex CLI child-ları izlənir ki, pəncərə bağlananda (extension
// deactivate) və ya istifadəçi ləğv edəndə orphan qalmasınlar. Windows-da parent
// (extension host) öləndə uşaq proses avtomatik ölmür → Task Manager-də python
// asılı qalırdı. deactivate() bunları kill edir.
const _activeReindexChildren = new Set<cp.ChildProcess>();

export function killActiveReindexChildren(): void {
  for (const child of _activeReindexChildren) {
    try {
      child.kill();
    } catch {
      /* artıq ölüb — əhəmiyyətsiz */
    }
  }
  _activeReindexChildren.clear();
}

// Streaming reindex runner — spawns the wheel's `--reindex` CLI and routes its
// `[N/3]` stage banners into vscode.window.withProgress so the notification
// shows real progress instead of a static "may take a minute" message with an
// indeterminate spinner.
//
// Stage map (matches the banners printed by mcp_server._cli_reindex):
//   start          →  5%   "Starting Tokengram..."
//   [1/3] scan     → 20%   "Files being scanned"
//   [KEYWORD]      → 45%   "Keyword search ready" (faza 1 bitdi)
//   [2/3] model    → 55%, slow-fill to 70% over ~45s for first-run HF download
//   [3/3] N chunk  → 72%   "Indexing chunks" (banner, rəqəmsiz)
//   [3/3] done/tot → 72→99% canlı embedding progress (hər batch-da)
//   ✓ Hazır         → 100% (success)
function streamingReindex(
  bin: string,
  args: string[],
  cwd: string,
  extraEnv: Record<string, string>,
  progress: vscode.Progress<{ message?: string; increment?: number }>,
  captured: string[],
  token?: vscode.CancellationToken,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = cp.spawn(bin, args, {
      cwd,
      env: { ...process.env, CLAUDE_PROJECT_DIR: cwd, ...extraEnv },
    });
    // Orphan qarşısı: izlə + ləğv/bağlanışda kill.
    _activeReindexChildren.add(child);
    const cancelSub = token?.onCancellationRequested(() => {
      try {
        child.kill();
      } catch {
        /* ignore */
      }
    });
    const untrack = () => {
      _activeReindexChildren.delete(child);
      cancelSub?.dispose();
    };

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
      const cap = 70; // embedding stream (72→99%) buradan götürür; üst-üstə düşməsin
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

        // Faza 1 — keyword indeksi hazırdır (embedding hələ davam edir).
        // İstifadəçi bu nöqtədə artıq keyword axtarışı edə bilər.
        if (/^\[KEYWORD\]/.test(trimmed)) {
          stopModelFill();
          const kf = trimmed.match(/(\d+)\s*fayl/);
          const kc = trimmed.match(/(\d+)\s*chunk/);
          const detail =
            kf && kc ? ` (${kf[1]} files · ${kc[1]} chunks)` : '';
          jumpTo(45, `Keyword search ready${detail} — embeddings continue`);
          continue;
        }

        const stage = trimmed.match(/\[(\d)\/3\]\s*(.*)$/);
        if (stage) {
          const [, n, tail] = stage;
          if (n === '1') {
            stopModelFill();
            jumpTo(20, `[1/3] ${cleanTail(tail) || 'Scanning files'}`);
          } else if (n === '2') {
            jumpTo(55, `[2/3] ${cleanTail(tail) || 'Loading embedding model'}`);
            startModelFill();
          } else if (n === '3') {
            stopModelFill();
            // Streaming "done/total chunk (pct%) · N fayl" — canlı sür (72→99%).
            const m = tail.match(/(\d+)\s*\/\s*(\d+)/);
            if (m) {
              const done = parseInt(m[1], 10);
              const total = parseInt(m[2], 10) || 1;
              const frac = Math.min(1, done / total);
              const pct = Math.round(frac * 100);
              const filesM = tail.match(/(\d+)\s*fayl/);
              const filesPart = filesM ? ` · ${filesM[1]} files` : '';
              jumpTo(
                72 + Math.round((99 - 72) * frac),
                `Embedding ${done}/${total} chunks (${pct}%)${filesPart}`,
              );
            } else {
              jumpTo(72, `[3/3] ${cleanTail(tail) || 'Indexing chunks'}`);
            }
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
      untrack();
      reject(err);
    });
    child.on('close', (code) => {
      stopModelFill();
      untrack();
      if (buf.trim()) captured.push(buf.trim());
      if (code === 0) {
        jumpTo(100);
        resolve();
      } else if (code === 3) {
        // mcp_server._cli_reindex: indeks korlanıb VƏ başqa proses onu açıq
        // saxlayır (self-heal köçürə bilmədi). Ümumi "exited with code 3"
        // əvəzinə aydın bərpa addımı göstər.
        reject(
          new Error(
            'Index corruption detected and the database is locked by another process. ' +
              'Close Claude Code completely, then click Re-index again.',
          ),
        );
      } else if (code === 4) {
        // Yalnız kilid timeout-u — korrupsiya yoxdur. Fon işçisi (leader drain)
        // onsuz da növbəni indeksləyir. Əvvəlki "wait a minute, click again"
        // mesajı user-i çaşdırırdı; indi onları status bar-dakı CANLI ⟳ sayğacına
        // yönəldirik — indeksləmə öz-özünə bitir və spinner itir (manual təkrar
        // Re-index lazım deyil).
        reject(
          new Error(
            'Tokengram is already indexing in the background — watch the ⟳ count in the ' +
              'status bar. It finishes on its own and the spinner disappears; no need to re-index.',
          ),
        );
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

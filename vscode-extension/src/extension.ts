import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { startPeriodicRecheck } from './licenseStatus';
import { registerMenuCommand, registerSetLicenseKeyCommand, killActiveReindexChildren } from './menu';
import { createStatusBar } from './statusBar';
import { findProjectRoot } from './savingsReader';
import { ensureAutoInstall, registerSetupCommand, pinServerUrl, ensureGitignore } from './setupWizard';

export function activate(context: vscode.ExtensionContext) {
  // Bundled wheel `py3-none-any` taglənib amma daxili .pyd Windows-only.
  // macOS/Linux-də pip silent install edir, sonra import-da crash; user
  // "extension installed" görür amma heç bir hook işləmir. Fail-fast.
  if (process.platform !== 'win32') {
    void vscode.window.showErrorMessage(
      'Tokengram currently supports Windows only. macOS and Linux builds are on the roadmap — please follow https://github.com/kinleee/tokengram for updates.',
    );
    return;
  }
  warnIfLegacyMlaExtensionPresent();
  mirrorParentWorkspaceHooks();
  // Mövcud (artıq qurulmuş) layihələrdə də .gitignore-u təmin et. Kritik: kilid
  // faylı (.tokengram.writer.lock) işləyən server tərəfindən OS-lock-landığı üçün
  // `git add .` onu oxuya bilmir → "Permission denied" → BÜTÜN add fatal sınır.
  // gitignore olunca git ona toxunmur. ensureGitignore idempotentdir (sentinel)
  // və yalnız git repo / mövcud .gitignore olanda yazır.
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
  void ensureAutoInstall(context);
}

// VS Code editor-də fayl save olunanda onu indeks növbəsinə (.mla_pending.txt)
// yazırıq — Claude Code redaktələri PostToolUse hook (queue_change.py) ilə artıq
// tutulur, amma user birbaşa editor-də Ctrl+S edəndə yalnız Python watchdog (2s
// debounce) tuturdu. Bu listener save anında DƏRHAL növbəyə yazır → status bar
// FS watcher-i .mla_pending.txt dəyişikliyini görüb spinner+sayğacı o anda
// göstərir. İNDEKSLƏMƏNİ ÖZÜMÜZ ETMİRİK — sadəcə növbəyə yazırıq; onsuz da işləyən
// MCP server background drainer faylları embed edir (yeni proses spawn YOX →
// spawn-storm/RAM riski yox). Filtrlər mla_constants.py güzgüsüdür.
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

// Fayl-adı uyğunluqları (name.startsWith) — mla_constants.EXCLUDED_FILE_PATTERNS
// güzgüsü. Secret/credential fayllarını da daxil edir: queue faylına secret YOLU
// belə düşməməlidir (Tokengram "local · private" iddia edir).
const INDEX_EXCLUDED_FILE_PATTERNS = [
  '.mla_pending', '.mla_session_log', '.file_hashes',
  'TEST_PROMPT', 'test_prompt', 'PROMPT_', 'prompts.', 'FIXTURE_', 'fixture_',
  'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
  'Cargo.lock', 'go.sum', 'composer.lock', 'Gemfile.lock',
  'poetry.lock', 'uv.lock', 'bun.lockb',
  '.env', 'secrets.', 'credentials.', 'credential.',
  'service-account', 'firebase-adminsdk', 'google-services.json',
];

// Suffix istisnaları — mla_constants.EXCLUDED_FILE_SUFFIXES güzgüsü (minified
// bundle, source map, generated kod).
const INDEX_EXCLUDED_FILE_SUFFIXES = [
  '.min.js', '.min.css', '.bundle.js', '.bundle.css', '.map',
  '.pb.go', '.pb.ts', '_pb2.py', '_pb2_grpc.py',
  '.gen.go', '.gen.ts', '.generated.ts', '.generated.go',
];

// Trailing (idle) debounce per fayl: hər save timer-i SIFIRLAYIR; növbəyə yalnız
// fayl SAVE_IDLE_MS müddətində toxunulmadıqda BİR DƏFƏ yazılır. Səbəb: köhnə 3s
// "leading" debounce 3-4s aralıqla yavaş yazanda hər save-i ayrıca növbəyə salırdı
// → eyni fayl üçün onlarla sətir + spinner hər simvolda fırlanırdı. İndi yazmağı
// dayandırana qədər gözləyirik, sonra bir dəfə (dedup ilə) növbəyə qoyuruq.
const pendingTimers = new Map<string, NodeJS.Timeout>();
const SAVE_IDLE_MS = 6000;

// Növbədə (.mla_pending.txt + .processing) artıq varsa təkrar yazma. Drainer
// onsuz da dedup edir, amma burada da dedup etməsək növbə şişir və ⟳N saxta böyük
// görünür. Müqayisə Windows-da hərf-həssaslığını nəzərə alır.
function alreadyQueued(projectRoot: string, filePath: string): boolean {
  const want = filePath.toLowerCase();
  for (const name of ['.mla_pending.txt', '.mla_pending.processing']) {
    try {
      const data = fs.readFileSync(path.join(projectRoot, name), 'utf-8');
      for (const line of data.split('\n')) {
        if (line.trim().toLowerCase() === want) return true;
      }
    } catch {
      /* fayl yoxdursa keç */
    }
  }
  return false;
}

function registerSaveIndexer(context: vscode.ExtensionContext): void {
  const enqueue = (filePath: string): void => {
    pendingTimers.delete(filePath);
    try {
      const projectRoot = findProjectRoot(path.dirname(filePath));
      // Enforcement OFF olanda növbəni böyütmə (queue_change.py:58 güzgüsü).
      // Fire anında yenidən yoxlayırıq — istifadəçi yazarkən toggle etmiş ola bilər.
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
      if (alreadyQueued(projectRoot, filePath)) return;
      fs.appendFileSync(path.join(projectRoot, '.mla_pending.txt'), filePath + '\n', 'utf-8');
    } catch {
      // Best-effort — heç vaxt save əməliyyatını bloklama.
    }
  };

  const listener = vscode.workspace.onDidSaveTextDocument((doc) => {
    try {
      const filePath = doc.uri.fsPath;
      if (INDEXABLE_EXTENSIONS.has(path.extname(filePath).toLowerCase()) === false) return;
      const parts = filePath.split(/[\\/]/);
      if (parts.some((p) => INDEX_EXCLUDED_DIRS.has(p))) return;
      const base = path.basename(filePath);
      // Tokengram-ın öz state fayllarını növbəyə salma (sonsuz dövrə düşməsin)...
      if (
        base.startsWith('.mla_') ||
        base.startsWith('.tokengram') ||
        base.startsWith('.bm25_index')
      )
        return;
      // ...və paket-menecer lock / secret / generated faylları (queue_change.py paritisi).
      if (INDEX_EXCLUDED_FILE_PATTERNS.some((pat) => base.startsWith(pat))) return;
      if (INDEX_EXCLUDED_FILE_SUFFIXES.some((sfx) => base.endsWith(sfx))) return;

      // Trailing debounce: bu fayl üçün gözləyən timer-i sıfırla, yenisini qur.
      const existing = pendingTimers.get(filePath);
      if (existing) clearTimeout(existing);
      const timer = setTimeout(() => enqueue(filePath), SAVE_IDLE_MS);
      // VS Code bağlananda Node prosesini canlı saxlamasın.
      if (typeof timer.unref === 'function') timer.unref();
      pendingTimers.set(filePath, timer);
    } catch {
      // Best-effort — heç vaxt save əməliyyatını bloklama.
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
        vscode.window.showInformationMessage(
          'Tokengram: mirrored parent workspace hooks into this sub-folder. Reload Claude Code to activate.',
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

// Açılan layihə tokengram-ın işlədiyi layihədirsə (.mcp.json / qənaət tarixçəsi /
// chroma_db var), onun .gitignore-una runtime-artefakt blokunu təmin et. Bu, hər
// activation-da işləyir (idempotent) ki, KÖHNƏ layihələr də qorunsun — yalnız
// fresh setup deyil. Səbəb: kilidli .tokengram.*.lock faylı gitignore olunmasa
// `git add .` fatal sınır.
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
    /* best-effort — heç vaxt activation-u bloklama */
  }
}

export function deactivate() {
  // Pəncərə bağlananda spawn olunmuş reindex CLI child-larını kill et —
  // əks halda Windows-da python orphan qalıb fonda işləməyə davam edir.
  killActiveReindexChildren();
}

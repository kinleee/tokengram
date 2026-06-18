import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { tr } from './i18n';
import { effectiveStatus, trialDaysLeft } from './licenseStatus';
import { autoRecoverIfStuck } from './menu';
import { findHistoryFile, findProjectRoot, readSavings } from './savingsReader';

const REFRESH_MS = 5_000;

// Bar state machine — visual ayrı, behavior ayrı.
// Bütün "license problemləri" hooks işləmir demək deyil; tooltip-də göstərilir.
type BarState =
  | 'no_project'
  | 'no_key'
  | 'invalid'
  | 'trial_expired' // trial bitdi — konversiya CTA (heç nə sınmır, qənaət dayanır)
  | 'stale'
  | 'off'
  | 'queue_stuck'   // background worker dayanıb, yeni indekslə baş tutmur
  | 'data_reset'    // history son 1 saatda 0 byte-a sıfırlanıb
  | 'idle'
  | 'active'
  | 'live';

// `.mla_pending.processing` faylının yaşı bu eşikdən böyük olarsa, worker
// crash sayılır. 30 dəq — adi indekslə kifayət edən ən uzun reallıq vaxtı.
const QUEUE_STUCK_THRESHOLD_SEC = 1800;
// History sıfırdırsa, reset yeni olmuşsa user-ə deyirik. 1 saat — natural
// "yeni başlatma" pəncərəsi; daha köhnəsi yəqin ki uzun-müddətli idle olub.
const DATA_RESET_FRESH_THRESHOLD_SEC = 3600;

function readEnforcement(workspacePath: string): boolean {
  try {
    const flagPath = path.join(workspacePath, '.mla_enforcement.flag');
    return fs.readFileSync(flagPath, 'utf-8').trim().toLowerCase() === 'on';
  } catch {
    return false;
  }
}

function fileMtimeIso(p: string): string {
  try {
    return new Date(fs.statSync(p).mtimeMs).toLocaleTimeString();
  } catch {
    return '—';
  }
}

export function createStatusBar(context: vscode.ExtensionContext): vscode.Disposable {
  const item = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100,
  );
  item.command = 'tokengram.menu';
  item.show();

  const refresh = () => {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders || folders.length === 0) {
      item.text = tr('bar.noProject');
      item.tooltip = tr('bar.noProjectTip');
      item.color = undefined;
      return;
    }

    const workspacePath = folders[0].uri.fsPath;
    // Workspace bəzən project_root-un subfolder-i ola bilər (mono-repo).
    // Hooks `.claude/settings.json`-ın bağlı olduğu kökə yazır — biz də orada axtaraq.
    const projectRoot = findProjectRoot(workspacePath);
    const flagOn = readEnforcement(projectRoot);
    // İstifadəçi HEÇ düyməyə basmamalıdır: növbə ilişibsə (pending>0 + indeksləmə
    // no-progress) avtomatik bərpa et — GIL-donmuş server özünü qurtara bilmir,
    // ona görə xarici proses (bu extension) onu öldürüb reindex ilə drenləyir.
    // autoRecoverIfStuck ucuz yoxlama + 5dəq cooldown ilə qorunur (churn yox).
    if (flagOn) void autoRecoverIfStuck(projectRoot, context.extensionPath);
    const licenseState = effectiveStatus();
    const historyPath =
      findHistoryFile() ??
      path.join(projectRoot, '.mla_savings_history.jsonl');
    const sessionLogPath = path.join(projectRoot, '.mla_session_log.jsonl');
    const summary = readSavings(historyPath);

    // 1) Determine bar state — license problems take precedence ONLY when they
    // block enforcement. Stale license keeps a previously-valid cache, so hooks
    // still work — surface it as a subtle warning, not a scary red blocker.
    //
    // Health states (queue_stuck / data_reset) outrank `live`/`active` because
    // they indicate the backend is silently broken — showing "$(green) 12k
    // saved" while the worker has been dead for 4 hours misleads the user.
    let state: BarState;
    if (licenseState === 'no_key') state = 'no_key';
    else if (licenseState === 'invalid') state = 'invalid';
    else if (licenseState === 'trial_expired') state = 'trial_expired';
    else if (!flagOn) state = 'off';
    else if (
      summary &&
      summary.queueStuckAgeSec >= QUEUE_STUCK_THRESHOLD_SEC &&
      summary.indexingPending > 0
    )
      state = 'queue_stuck';
    else if (
      summary &&
      summary.historyEmpty &&
      summary.historyMtimeAgeSec < DATA_RESET_FRESH_THRESHOLD_SEC &&
      summary.pendingActivityCount === 0 &&
      // Yalnız sistem HƏQİQƏTƏN sakit olanda "reset" sarı xəbərdarlığı göstər.
      // Əks halda: Stop hook hər task bitəndə session log-u boşaldır →
      // pendingActivityCount bir anda 0 olur → bar data_reset(sarı) ↔ live(yaşıl)
      // arasında hər neçə saniyədən bir titrəyir (user "nəsə sınıb" sanır).
      // İndekslənmə gedirsə və ya son 24s-də task olubsa, bu reset deyil, normal
      // işdir → yaşıl active/idle göstər.
      summary.indexingPending === 0 &&
      summary.recent24hTasks === 0
    )
      state = 'data_reset';
    else if (summary && summary.pendingActivityCount > 0) state = 'live';
    else if (summary && (summary.savedTokens24h > 0 || summary.recent24hTasks > 0))
      state = 'active';
    else if (licenseState === 'stale') state = 'stale';
    else state = 'idle';

    // 2) Visual mapping. Reserve red for genuinely-broken states.
    const stateLabel = tr(`bar.state.${state}`);
    let icon: string;
    let color: vscode.ThemeColor | undefined;
    switch (state) {
      case 'no_key':
      case 'invalid':
        icon = '$(warning)';
        color = new vscode.ThemeColor('charts.red');
        break;
      case 'trial_expired':
        // Qırmızı yox — trial bitməsi xəta deyil, gözlənilən lifecycle anıdır.
        icon = '$(clock)';
        color = new vscode.ThemeColor('charts.yellow');
        break;
      case 'queue_stuck':
      case 'data_reset':
        icon = '$(warning)';
        color = new vscode.ThemeColor('charts.yellow');
        break;
      case 'stale':
        icon = '$(sync)';
        color = new vscode.ThemeColor('charts.yellow');
        break;
      case 'off':
        icon = '$(circle-large-outline)';
        color = undefined;
        break;
      case 'idle':
        icon = '$(circle-outline)';
        color = new vscode.ThemeColor('charts.green');
        break;
      case 'active':
      case 'live':
        icon = '$(circle-filled)';
        color = new vscode.ThemeColor('charts.green');
        break;
      default:
        icon = '$(circle-large-outline)';
        color = undefined;
    }

    // 3) For broken license states the savings number is meaningless — show CTA.
    if (state === 'no_key' || state === 'invalid') {
      item.text = tr(`bar.cta.${state}`, { icon });
      item.tooltip = tr(`bar.tip.${state}`);
      item.color = color;
      return;
    }
    if (state === 'trial_expired') {
      // Konversiya anı: qənaət rəqəmi burada ən güclü arqumentdir —
      // "bu ay X qənaət etdin, davam etmək üçün lisenziya al".
      const savedTotalK = summary ? (summary.savedTokens24h / 1000).toFixed(1) : '0.0';
      item.text = tr('bar.cta.trial_expired', { icon });
      item.tooltip = tr('bar.tip.trial_expired', { savedK: savedTotalK });
      item.color = color;
      return;
    }
    if (state === 'off') {
      item.text = tr('bar.cta.off', { icon });
      item.tooltip = tr('bar.tip.off');
      item.color = color;
      return;
    }
    // Health states: backend silently broken — surface the cause so user
    // notices instead of seeing a misleading "0.0k green idle".
    if (state === 'queue_stuck') {
      const mins = Math.floor((summary?.queueStuckAgeSec ?? 0) / 60);
      item.text = tr('bar.cta.queue_stuck', { icon, n: summary?.indexingPending ?? 0 });
      item.tooltip = tr('bar.tip.queue_stuck', { mins, n: summary?.indexingPending ?? 0 });
      item.color = color;
      return;
    }
    if (state === 'data_reset') {
      const mins = Math.floor((summary?.historyMtimeAgeSec ?? 0) / 60);
      item.text = tr('bar.cta.data_reset', { icon });
      item.tooltip = tr('bar.tip.data_reset', { mins });
      item.color = color;
      return;
    }

    // 4) ON / idle / active / live / stale — show numbers. `summary` is
    // guaranteed by readSavings, but be defensive against old bundles.
    const safeSummary = summary ?? {
      savedTokens24h: 0,
      savedPct24h: -1,
      pendingSavedTokens: 0,
      pendingActivityCount: 0,
      indexingPending: 0,
      recent24hTasks: 0,
      recent24hBlocks: 0,
      recent24hGreps: 0,
      recent24hBashInspects: 0,
      recent24hWarns: 0,
      recent24hFiles: 0,
      savedFromSearch24h: 0,
      savedFromBlocks24h: 0,
      savedFromGreps24h: 0,
      savedFromBash24h: 0,
      totalTasks: 0,
      totalSearches: 0,
      totalBlocks: 0,
      totalGreps: 0,
      totalBashInspects: 0,
      totalWarns: 0,
      totalFiles: 0,
      historyEmpty: true,
      historyMtimeAgeSec: Number.MAX_SAFE_INTEGER,
      queueStuckAgeSec: 0,
    };
    const savedK = (safeSummary.savedTokens24h / 1000).toFixed(1);
    const pendingK = safeSummary.pendingSavedTokens / 1000;
    const liveBadge =
      safeSummary.pendingActivityCount > 0
        ? tr('bar.liveBadge', {
            saved: pendingK >= 0.1 ? `+${pendingK.toFixed(1)}k` : '+',
            count: safeSummary.pendingActivityCount,
          })
        : '';
    // İstənilən pending fayl (1 belə) spinner+sayğac göstərsin — əvvəl `>= 5`
    // idi, ona görə kiçik edit-lər (1-3 fayl) heç vaxt görünmürdü. İndi fayl
    // edit olan kimi "⟳ N" çıxır, drain bitəndə itir.
    const indexingBadge =
      safeSummary.indexingPending > 0
        ? tr('bar.indexingBadge', { n: safeSummary.indexingPending })
        : '';
    // Bar text shows absolute tokens only — the % is structurally a partial
    // accounting (denominator can't capture system-prompt / cache / context
    // refill costs), so we keep it out of the headline. Tooltip still surfaces
    // it for power users.
    const calibrating = safeSummary.savedPct24h < 0;
    const pctFull = calibrating ? tr('bar.calibrating') : `${safeSummary.savedPct24h.toFixed(1)}%`;
    // Aktiv trial: bar normal işləyir, amma qalan günlər həmişə görünür —
    // "qalan gün + öz qənaət rəqəmin" cütlüyü konversiyanın əsas alətidir.
    const trialDays = licenseState === 'trialing' ? trialDaysLeft() : null;
    const trialBadge = trialDays !== null ? tr('bar.trialBadge', { days: trialDays }) : '';
    const tail = [liveBadge, indexingBadge, trialBadge].filter(Boolean).join(' ');
    item.text = tr('bar.summary', { icon, savedK })
      + (tail ? ' ' + tail : '');
    item.color = color;

    // Stale lisenziya keşi — bar 'active' olsa belə tooltip-də xəbər ver.
    const staleNote =
      licenseState === 'stale'
        ? '\n' + tr('bar.tip.staleNote')
        : '';
    const trialNote =
      trialDays !== null
        ? '\n' + tr('bar.tip.trialNote', { days: trialDays })
        : '';
    item.tooltip = tr('bar.tipFull', {
      state: stateLabel,
      tasks: safeSummary.recent24hTasks,
      saved: safeSummary.savedTokens24h.toLocaleString(),
      pct: pctFull,
      search: safeSummary.savedFromSearch24h.toLocaleString(),
      searches: safeSummary.totalSearches,
      grep: safeSummary.savedFromGreps24h.toLocaleString(),
      greps: safeSummary.recent24hGreps,
      bash: safeSummary.savedFromBash24h.toLocaleString(),
      bashes: safeSummary.recent24hBashInspects,
      block: safeSummary.savedFromBlocks24h.toLocaleString(),
      blocks: safeSummary.recent24hBlocks,
      warns: safeSummary.recent24hWarns,
      files: safeSummary.recent24hFiles,
      totalTasks: safeSummary.totalTasks,
      totalSearches: safeSummary.totalSearches,
      totalGreps: safeSummary.totalGreps,
      totalBashInspects: safeSummary.totalBashInspects,
      totalBlocks: safeSummary.totalBlocks,
      totalWarns: safeSummary.totalWarns,
      totalFiles: safeSummary.totalFiles,
    }) + '\n' + tr('bar.tip.lastUpdate', {
      history: fileMtimeIso(historyPath),
      session: fileMtimeIso(sessionLogPath),
    }) + staleNote + trialNote;
  };

  refresh();
  let interval: NodeJS.Timeout | null = setInterval(refresh, REFRESH_MS);

  // Fokus olmayan window-da hər 5s 32 sync stat → SMB drive-də UI laggy.
  // Pəncərə blur olduqda timer-i dayandırırıq; focus qayıdanda bir dəfə
  // refresh + interval-ı yenidən qururuq.
  const focusListener = vscode.window.onDidChangeWindowState((state) => {
    if (state.focused) {
      if (interval === null) {
        refresh();
        interval = setInterval(refresh, REFRESH_MS);
      }
    } else if (interval !== null) {
      clearInterval(interval);
      interval = null;
    }
  });
  context.subscriptions.push(focusListener);

  const folders = vscode.workspace.workspaceFolders;
  if (folders && folders.length > 0) {
    // FS watcher base = real project_root (workspace deyil). String pattern
    // istifadə edirik ki, base workspace-dən kənar ola bilsin.
    const projectRoot = findProjectRoot(folders[0].uri.fsPath);

    const watcherFiles = [
      '.mla_enforcement.flag',
      '.mla_savings_history.jsonl',
      '.mla_session_log.jsonl',
      '.mla_pending.txt',
      // Drain başlayanda (.txt → .processing) və bitəndə (.processing silinir)
      // bar dərhal yenilənsin ki, spinner+sayğac vaxtında çıxsın/itsin —
      // əks halda yalnız 5s interval-ı gözləyirdi.
      '.mla_pending.processing',
    ];
    for (const name of watcherFiles) {
      const w = vscode.workspace.createFileSystemWatcher(
        new vscode.RelativePattern(projectRoot, name),
      );
      w.onDidChange(refresh);
      w.onDidCreate(refresh);
      w.onDidDelete(refresh);
      context.subscriptions.push(w);
    }
  }

  return new vscode.Disposable(() => {
    if (interval !== null) clearInterval(interval);
    item.dispose();
  });
}

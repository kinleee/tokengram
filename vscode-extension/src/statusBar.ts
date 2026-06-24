import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { tr } from './i18n';
import { effectiveStatus, trialDaysLeft } from './licenseStatus';
import { findHistoryFile, findProjectRoot, readSavings } from './savingsReader';

const REFRESH_MS = 5_000;

// Bar state machine — visual separate, behavior separate.
// Not all "license problems" mean hooks stop working; this is shown in the tooltip.
type BarState =
  | 'no_project'
  | 'no_key'
  | 'invalid'
  | 'trial_expired' // trial ended — conversion CTA (nothing breaks, savings stop)
  | 'stale'
  | 'off'
  | 'queue_stuck'   // background worker stalled, new indexing not completing
  | 'data_reset'    // history reset to 0 bytes within the last 1 hour
  | 'idle'
  | 'active'
  | 'live';

// If the `.mla_pending.processing` file's age exceeds this threshold, the worker
// is considered crashed. 30 min — the longest realistic time a normal index takes.
const QUEUE_STUCK_THRESHOLD_SEC = 1800;
// If history is empty, we tell the user when the reset is recent. 1 hour — a natural
// "fresh start" window; anything older has probably just been idle for a long time.
const DATA_RESET_FRESH_THRESHOLD_SEC = 3600;

// The project root is constant for the workspace's lifetime (it changes only when the
// workspace folder changes), but refresh() was recomputing findProjectRoot from scratch
// every 5s + on every watcher event (worst-case 4×8 stat). We cache it with a short-TTL
// memo; the TTL provides self-heal (e.g. when setup creates .claude later).
let _rootMemo: { ws: string; root: string; at: number } | null = null;
const _ROOT_MEMO_TTL_MS = 30_000;

function cachedProjectRoot(workspacePath: string): string {
  const now = Date.now();
  if (
    _rootMemo &&
    _rootMemo.ws === workspacePath &&
    now - _rootMemo.at < _ROOT_MEMO_TTL_MS
  ) {
    return _rootMemo.root;
  }
  const root = findProjectRoot(workspacePath);
  _rootMemo = { ws: workspacePath, root, at: now };
  return root;
}

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
    // The workspace can sometimes be a subfolder of project_root (mono-repo).
    // Hooks write to the root that `.claude/settings.json` is bound to — so we look there too.
    const projectRoot = cachedProjectRoot(workspacePath);
    const flagOn = readEnforcement(projectRoot);
    // Automatic recovery (autoRecoverIfStuck) was REMOVED (2026-06-19): the old continuous
    // poll-drain + watchdog/self-heal tower is gone, so the "GIL-frozen server"
    // case no longer exists. The queue is drained at the end of a task in the Stop hook
    // (or, if the server is down, by its cold fallback). The queue_stuck bar state still
    // remains informative; the manual "Refresh"/"Re-index" buttons are the escalation path.
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
      // Only show the "reset" yellow warning when the system is TRULY quiet.
      // Otherwise: the Stop hook empties the session log at the end of every task →
      // pendingActivityCount momentarily becomes 0 → the bar flickers between
      // data_reset (yellow) ↔ live (green) every few seconds (the user thinks "something broke").
      // If indexing is running, or there was a task in the last 24s, this is not a reset but normal
      // work → show green active/idle.
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
        // Not red — trial expiry is not an error, it's an expected lifecycle moment.
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
      // Conversion moment: the savings number is the strongest argument here —
      // "you saved X this month, buy a license to keep going".
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
    // Any pending file (even 1) should show the spinner+counter — it used to be `>= 5`,
    // so small edits (1-3 files) were never visible. Now "⟳ N" appears as soon as a file
    // is edited, and disappears when the drain finishes.
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
    // Active trial: the bar works normally, but the remaining days are always visible —
    // the "days left + your own savings number" pair is the main conversion tool.
    const trialDays = licenseState === 'trialing' ? trialDaysLeft() : null;
    const trialBadge = trialDays !== null ? tr('bar.trialBadge', { days: trialDays }) : '';
    const tail = [liveBadge, indexingBadge, trialBadge].filter(Boolean).join(' ');
    item.text = tr('bar.summary', { icon, savedK })
      + (tail ? ' ' + tail : '');
    item.color = color;

    // Stale license cache — notify in the tooltip even if the bar is 'active'.
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

  // In an unfocused window, 32 sync stats every 5s → laggy UI on SMB drives.
  // When the window is blurred we stop the timer; when focus returns we run a single
  // refresh and re-establish the interval.
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
    // FS watcher base = real project_root (not the workspace). We use a string
    // pattern so the base can be outside the workspace.
    const projectRoot = findProjectRoot(folders[0].uri.fsPath);

    const watcherFiles = [
      '.mla_enforcement.flag',
      '.mla_savings_history.jsonl',
      '.mla_session_log.jsonl',
      '.mla_pending.txt',
      // When the drain starts (.txt → .processing) and finishes (.processing is deleted)
      // the bar should refresh immediately so the spinner+counter appears/disappears on time —
      // otherwise it only waited for the 5s interval.
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

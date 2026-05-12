import * as vscode from 'vscode';

/**
 * Tiny i18n for the MLA extension. Locale is `vscode.env.language` (e.g. "en",
 * "en-US", "az", "tr"). We default to English if the locale isn't in our table.
 *
 * Strings are embedded in the bundle — no external file loading, no
 * vscode.l10n boilerplate. Adding a new language is one entry in `MESSAGES`.
 */

type Messages = Record<string, string>;

const EN: Messages = {
  'menu.placeholder': 'Pick an MLA action',
  'menu.toggleOn': '$(circle-filled) Turn ON',
  'menu.toggleOff': '$(circle-large-outline) Turn OFF',
  'menu.currentState': 'current: {state}',
  'menu.refresh': '$(refresh) Refresh status bar',
  'menu.refreshDesc': 'touch mtime — bar updates immediately',
  'menu.arch': '$(book) Show arch doc',
  'menu.archDesc': '.mla_arch.md in the side panel',
  'menu.sync': '$(save) Sync session log → history',
  'menu.syncDesc': 'manual run when the Stop hook is skipped',
  'menu.reindex': '$(database) ChromaDB re-index',
  'menu.reindexDesc': 'main.py index . --fresh (60-120s)',
  'menu.reset': '$(trash) Reset savings history',
  'menu.resetDesc': 'old history is moved to a backup file',
  'menu.toggleResult': 'MLA: {output}',
  'menu.refreshResult': 'MLA: status bar refresh triggered',
  'menu.resetConfirm':
    'Reset savings history? (old history will be backed up)',
  'menu.resetConfirmYes': 'Reset',
  'menu.resetResult': 'MLA: {output}',
  'menu.reindexTitle': 'MLA: re-indexing ChromaDB (may take a minute)',
  'menu.reindexDone': 'MLA: re-index complete',
  'menu.syncDoneFallback': 'MLA: sync complete (no new events)',
  'menu.error': 'MLA: {action} failed — {message}',
  'menu.noWorkspace': 'MLA: no workspace folder open',

  'bar.noProject': '$(database) MLA: no project',
  'bar.noProjectTip': 'No workspace folder open',
  'bar.noData': '{icon} MLA: no data · {state}',
  'bar.starting': '{icon} MLA: starting… · {state}',
  'bar.summary': '{icon} MLA: {savedK}k saved · {pct}%',
  'bar.tipNoData': 'Enforcement: {state}\nNo .mla_savings_history.jsonl yet',
  'bar.tipStarting': 'Enforcement: {state}\nIndexing or no recent activity',
  'bar.tipFull':
    'Enforcement: {state}\n' +
    'Last 24h: {tasks} tasks, {saved} tokens saved ({pct}%)\n' +
    '  • search_code: {search} tok\n' +
    '  • Grep: {grep} tok ({greps} greps)\n' +
    '  • Read-block: {block} tok ({blocks} blocks)\n' +
    'Lifetime: {totalTasks} tasks, {totalSearches} searches, ' +
    '{totalGreps} greps, {totalBlocks} blocks',
};

const AZ: Messages = {
  'menu.placeholder': 'MLA komandası seç',
  'menu.toggleOn': '$(circle-filled) Yandır (ON)',
  'menu.toggleOff': '$(circle-large-outline) Söndür (OFF)',
  'menu.currentState': 'cari: {state}',
  'menu.refresh': '$(refresh) Status bar yenilə',
  'menu.refreshDesc': 'mtime touch — bar dərhal refresh edir',
  'menu.arch': '$(book) Arch doc göstər',
  'menu.archDesc': '.mla_arch.md yan paneldə',
  'menu.sync': '$(save) Session log → history (sync)',
  'menu.syncDesc': 'Stop hook fire olmayıbsa manual çağır',
  'menu.reindex': '$(database) ChromaDB re-index',
  'menu.reindexDesc': 'main.py index . --fresh (60-120 san)',
  'menu.reset': '$(trash) Savings history sıfırla',
  'menu.resetDesc': 'köhnəsi backup-a köçürülür',
  'menu.toggleResult': 'MLA: {output}',
  'menu.refreshResult': 'MLA: status bar refresh triggered',
  'menu.resetConfirm':
    'Savings history-i sıfırlayaq? (köhnə history backup-a köçürüləcək)',
  'menu.resetConfirmYes': 'Reset',
  'menu.resetResult': 'MLA: {output}',
  'menu.reindexTitle': 'MLA: ChromaDB re-index (bir-iki dəqiqə çəkə bilər)',
  'menu.reindexDone': 'MLA: re-index tamamlandı',
  'menu.syncDoneFallback': 'MLA: sync tamamlandı (yeni hadisə yox idi)',
  'menu.error': 'MLA: {action} uğursuz — {message}',
  'menu.noWorkspace': 'MLA: workspace folder açılmayıb',

  'bar.noProject': '$(database) MLA: layihə yox',
  'bar.noProjectTip': 'Workspace folder açılmayıb',
  'bar.noData': '{icon} MLA: data yox · {state}',
  'bar.starting': '{icon} MLA: başlayır… · {state}',
  'bar.summary': '{icon} MLA: {savedK}k qənaət · {pct}%',
  'bar.tipNoData':
    'Enforcement: {state}\n.mla_savings_history.jsonl hələ yoxdur',
  'bar.tipStarting': 'Enforcement: {state}\nİndekslənir və ya son aktivlik yox',
  'bar.tipFull':
    'Enforcement: {state}\n' +
    'Son 24 saat: {tasks} task, {saved} token qənaət ({pct}%)\n' +
    '  • search_code: {search} tok\n' +
    '  • Grep: {grep} tok ({greps} grep)\n' +
    '  • Read-block: {block} tok ({blocks} block)\n' +
    'Cəmi: {totalTasks} task, {totalSearches} search, ' +
    '{totalGreps} grep, {totalBlocks} block',
};

const MESSAGES: Record<string, Messages> = { en: EN, az: AZ };

function detectLocale(): string {
  const lang = (vscode.env.language || 'en').toLowerCase();
  if (lang.startsWith('az')) return 'az';
  return 'en';
}

const _locale = detectLocale();

export function tr(key: string, vars?: Record<string, string | number>): string {
  const table = MESSAGES[_locale] ?? EN;
  let template = table[key] ?? EN[key] ?? key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      template = template.split(`{${k}}`).join(String(v));
    }
  }
  return template;
}

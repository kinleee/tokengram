import * as vscode from 'vscode';

/**
 * Tiny i18n for the Tokengram extension. Locale is `vscode.env.language` (e.g. "en",
 * "en-US", "az", "tr"). We default to English if the locale isn't in our table.
 *
 * Strings are embedded in the bundle — no external file loading, no
 * vscode.l10n boilerplate. Adding a new language is one entry in `MESSAGES`.
 */

type Messages = Record<string, string>;

const EN: Messages = {
  'menu.placeholder': 'Pick an Tokengram action',
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
  'menu.reindexDesc': 'Re-index the current workspace from scratch (60-120s)',
  'menu.reset': '$(trash) Reset savings history',
  'menu.resetDesc': 'old history is moved to a backup file',
  'menu.toggleResult': 'Tokengram: {output}',
  'menu.refreshResult': 'Tokengram: status bar refresh triggered',
  'menu.archMissing': 'No .mla_arch.md yet — it appears after the first Read of an indexable file.',
  'menu.toggleNeedsLicense':
    'Tokengram cannot be turned ON without a license key. Set your license key first.',
  'menu.toggleLicenseInvalid':
    'Your Tokengram license is invalid or no longer active. Replace it before turning ON.',
  'menu.setLicense': 'Set license key',
  'menu.resetConfirm':
    'Reset savings history? (old history will be backed up)',
  'menu.resetConfirmYes': 'Reset',
  'menu.resetResult': 'Tokengram: {output}',
  'menu.reindexTitle': 'Tokengram: re-indexing ChromaDB (may take a minute)',
  'menu.reindexDone': 'Tokengram: re-index complete',
  'menu.reindexCreatedConfig':
    'Tokengram: .mcp.json created for this project — re-index starting.',
  'menu.reindexHooksMissing':
    'Tokengram: hook scripts could not be installed at ~/.tokengram/hooks. Re-index will run but enforcement/savings hooks may be inactive.',
  'menu.reindexNoRoot':
    'Tokengram: Tokengram is not installed (~/.tokengram/venv missing). Run install.ps1 first, then click re-index again.',
  'menu.reindexFailed': 'Tokengram: re-index failed — {output}',
  'menu.syncDoneFallback': 'Tokengram: sync complete (no new events)',
  'menu.error': 'Tokengram: {action} failed — {message}',
  'menu.noWorkspace': 'Tokengram: no workspace folder open',

  'menu.license': '$(key) Set license key',
  'menu.licenseDesc': 'enter Tokengram license key (mla_live_xxx)',
  'license.prompt': 'Paste your Tokengram license key',
  'license.placeholder': 'mla_live_xxxxxxxxxxxxxxxxxxxxxxxx',
  'license.invalidFormat': 'License key should start with "mla_live_"',
  'license.saved': 'License saved. Restart Claude Code to apply.',
  'license.empty': 'License key is empty',
  'license.validating': 'Validating license key against Tokengram server…',
  'license.invalidByServer':
    'License server rejected this key ({reason}). Key not saved.',
  'license.noServerUrl':
    'No Tokengram license server URL configured. Run the setup wizard first.',
  'license.machineMismatch':
    'This license key is already activated on another device. Each Tokengram key is bound to one machine — contact support to release the previous device, or use a different key.',
  'license.venvMissing':
    'Tokengram venv not found at ~/.tokengram/venv. Run the setup wizard before setting a license key.',
  'license.fingerprintError':
    "Could not compute this machine's fingerprint ({detail}). Re-run the setup wizard.",
  'license.activateNetworkError':
    'Could not reach the Tokengram license server to activate this device ({detail}). Check your connection.',

  'bar.noProject': '$(database) Tokengram: no project',
  'bar.noProjectTip': 'No workspace folder open',
  'bar.summary': '{icon} Tokengram: {savedK}k saved',
  'bar.liveBadge': '$(zap) {saved} now',
  'bar.indexingBadge': '$(sync~spin) {n}',
  'bar.calibrating': 'calibrating',

  'bar.state.no_project': 'NO PROJECT',
  'bar.state.no_key': 'NO KEY',
  'bar.state.invalid': 'INVALID',
  'bar.state.stale': 'STALE',
  'bar.state.off': 'OFF',
  'bar.state.queue_stuck': 'QUEUE STUCK',
  'bar.state.data_reset': 'DATA RESET',
  'bar.state.idle': 'IDLE',
  'bar.state.active': 'ACTIVE',
  'bar.state.live': 'LIVE',

  'bar.cta.no_key': '{icon} Tokengram: set license key',
  'bar.cta.invalid': '{icon} Tokengram: invalid license',
  'bar.cta.off': '{icon} Tokengram: OFF · click to enable',
  'bar.cta.queue_stuck': '{icon} Tokengram: index queue stuck ({n})',
  'bar.cta.data_reset': '{icon} Tokengram: savings data reset',
  'bar.tip.no_key':
    'No license key found.\n' +
    'Click → Set license key. Enforcement and savings tracking start once activated.',
  'bar.tip.invalid':
    'License server rejected your key.\n' +
    'Click → Set license key with a fresh one, or contact support.',
  'bar.tip.off':
    'Enforcement is OFF — hooks are silent, no savings accrued.\n' +
    'Click → Turn ON to start saving.',
  'bar.tip.queue_stuck':
    '{n} files have been waiting to be re-indexed for {mins} min.\n' +
    'The MCP server background worker likely crashed.\n' +
    'Fix: restart Claude Code, or run /MlaReindex.',
  'bar.tip.data_reset':
    'Savings history was emptied {mins} min ago.\n' +
    'A backup is kept in .mla_savings_history.jsonl.bak.*.\n' +
    'New tasks will start accumulating again.',
  'bar.tip.staleNote':
    '⚠ License last-check is stale (offline mode). Hooks keep using the cached result.',
  'bar.tip.lastUpdate':
    'Files: history mtime {history} · session-log mtime {session}',

  'bar.tipFull':
    'State: {state}\n' +
    'Last 24h: {tasks} tasks, {saved} tokens saved ({pct} on tracked ops) · {files} files\n' +
    '  • search_code: {search} tok\n' +
    '  • Grep: {grep} tok ({greps} greps)\n' +
    '  • Bash inspect: {bash} tok ({bashes} inspects)\n' +
    '  • Read-block: {block} tok ({blocks} blocks)\n' +
    '  • Read-warn: {warns} soft warnings (not in total)\n' +
    'Lifetime: {totalTasks} tasks, {totalSearches} searches, ' +
    '{totalGreps} greps, {totalBashInspects} bash, {totalBlocks} blocks, ' +
    '{totalWarns} warns, {totalFiles} files saved\n' +
    'Note: percentage covers search/Read/Grep/Bash routed through Tokengram; ' +
    'Edit, raw Bash output, and system-prompt overhead are not counted.',

  'menu.breakdown': '$(list-tree) Event breakdown',
  'menu.breakdownDesc': 'open Output panel with raw session-log + history details',
  'breakdown.title': 'Tokengram event breakdown',
  'breakdown.noWorkspace': '(no workspace open)',
  'breakdown.sessionLogHeading': '## Pending session log',
  'breakdown.historyHeading': '## History (last 5 records)',
  'breakdown.licenseHeading': '## License cache',
  'breakdown.empty': '(empty — no events yet this turn)',
  'breakdown.missing': '(file does not exist)',
};

const AZ: Messages = {
  'menu.placeholder': 'Tokengram komandası seç',
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
  'menu.reindexDesc': 'Cari workspace-i sıfırdan yenidən indekslə (60-120 san)',
  'menu.reset': '$(trash) Savings history sıfırla',
  'menu.resetDesc': 'köhnəsi backup-a köçürülür',
  'menu.toggleResult': 'Tokengram: {output}',
  'menu.refreshResult': 'Tokengram: status bar refresh triggered',
  'menu.archMissing': '.mla_arch.md hələ yoxdur — ilk indekslənən faylın Read-indən sonra yaranır.',
  'menu.toggleNeedsLicense':
    'Tokengram-i lisenziya açarı olmadan ON-a keçirmək olmaz. Əvvəlcə açar daxil et.',
  'menu.toggleLicenseInvalid':
    'Tokengram lisenziyan etibarsızdır və ya aktiv deyil. ON-a keçirməzdən əvvəl yenilə.',
  'menu.setLicense': 'Lisenziya açarı yaz',
  'menu.resetConfirm':
    'Savings history-i sıfırlayaq? (köhnə history backup-a köçürüləcək)',
  'menu.resetConfirmYes': 'Reset',
  'menu.resetResult': 'Tokengram: {output}',
  'menu.reindexTitle': 'Tokengram: ChromaDB re-index (bir-iki dəqiqə çəkə bilər)',
  'menu.reindexDone': 'Tokengram: re-index tamamlandı',
  'menu.reindexCreatedConfig':
    'Tokengram: bu layihə üçün .mcp.json yaradıldı — re-index başlayır.',
  'menu.reindexHooksMissing':
    'Tokengram: hook skriptləri ~/.tokengram/hooks-a quraşdırıla bilmədi. Re-index işləyəcək, amma enforcement/savings hooks deaktiv ola bilər.',
  'menu.reindexNoRoot':
    'Tokengram qurulmayıb (~/.tokengram/venv yoxdur). Əvvəlcə install.ps1-i işlət, sonra re-index düyməsinə təkrar bas.',
  'menu.reindexFailed': 'Tokengram: re-index uğursuz — {output}',
  'menu.syncDoneFallback': 'Tokengram: sync tamamlandı (yeni hadisə yox idi)',
  'menu.error': 'Tokengram: {action} uğursuz — {message}',
  'menu.noWorkspace': 'Tokengram: workspace folder açılmayıb',

  'menu.license': '$(key) Lisenziya açarı yaz',
  'menu.licenseDesc': 'Tokengram lisenziya açarı daxil et (mla_live_xxx)',
  'license.prompt': 'Tokengram lisenziya açarını paste et',
  'license.placeholder': 'mla_live_xxxxxxxxxxxxxxxxxxxxxxxx',
  'license.invalidFormat': 'Lisenziya açarı "mla_live_" ilə başlamalıdır',
  'license.saved': 'Lisenziya yadda saxlandı. Claude Code-u yenidən başlat.',
  'license.empty': 'Lisenziya açarı boşdur',
  'license.validating': 'Lisenziya açarı Tokengram server-də yoxlanır…',
  'license.invalidByServer':
    'Lisenziya server-i bu açarı qəbul etmədi ({reason}). Açar saxlanmadı.',
  'license.noServerUrl':
    'Tokengram lisenziya server URL-i konfiqurasiya olunmayıb. Əvvəlcə setup wizard-ı işə sal.',
  'license.machineMismatch':
    'Bu lisenziya açarı artıq başqa cihazda aktivləşdirilib. Hər Tokengram açarı bir cihaza bağlıdır — köhnə cihazı azad etmək üçün dəstəyə müraciət edin və ya başqa açar istifadə edin.',
  'license.venvMissing':
    'Tokengram venv ~/.tokengram/venv yolunda tapılmadı. Lisenziya açarı yazmazdan əvvəl setup wizard-ı işə sal.',
  'license.fingerprintError':
    'Bu cihazın fingerprint-i hesablana bilmədi ({detail}). Setup wizard-ı yenidən işə sal.',
  'license.activateNetworkError':
    'Bu cihazı aktivləşdirmək üçün Tokengram lisenziya server-inə çıxış olmadı ({detail}). Bağlantını yoxla.',

  'bar.noProject': '$(database) Tokengram: layihə yox',
  'bar.noProjectTip': 'Workspace folder açılmayıb',
  'bar.summary': '{icon} Tokengram: {savedK}k qənaət',
  'bar.liveBadge': '$(zap) {saved} indi',
  'bar.indexingBadge': '$(sync~spin) {n}',
  'bar.calibrating': 'kalibrləyir',

  'bar.state.no_project': 'LAYİHƏ YOX',
  'bar.state.no_key': 'AÇAR YOX',
  'bar.state.invalid': 'ETIBARSIZ',
  'bar.state.stale': 'OFFLINE',
  'bar.state.off': 'SÖNÜK',
  'bar.state.queue_stuck': 'QUEUE DAYANIB',
  'bar.state.data_reset': 'DATA SIFIRLANIB',
  'bar.state.idle': 'BOŞ',
  'bar.state.active': 'AKTIV',
  'bar.state.live': 'CANLI',

  'bar.cta.no_key': '{icon} Tokengram: lisenziya açarı yaz',
  'bar.cta.invalid': '{icon} Tokengram: etibarsız lisenziya',
  'bar.cta.off': '{icon} Tokengram: SÖNÜK · aktivləşdirmək üçün klik',
  'bar.cta.queue_stuck': '{icon} Tokengram: index queue dayanıb ({n})',
  'bar.cta.data_reset': '{icon} Tokengram: qənaət data sıfırlanıb',
  'bar.tip.no_key':
    'Lisenziya açarı tapılmadı.\n' +
    'Klik → açar daxil et. Aktivləşmə sonra başlayır.',
  'bar.tip.invalid':
    'Lisenziya server bu açarı qəbul etmir.\n' +
    'Klik → yeni açar daxil et və ya dəstəyə müraciət et.',
  'bar.tip.off':
    'Enforcement SÖNÜKDÜR — hook-lar səssiz, qənaət sayılmır.\n' +
    'Klik → ON et və qənaət başlasın.',
  'bar.tip.queue_stuck':
    '{n} fayl {mins} dəqiqədir yenidən indekslənməyi gözləyir.\n' +
    'MCP server background worker yəqin ki crash etmiş.\n' +
    'Düzəliş: Claude Code-u yenidən başlat və ya /MlaReindex işə sal.',
  'bar.tip.data_reset':
    'Qənaət tarixçəsi {mins} dəq əvvəl boşaldılıb.\n' +
    'Backup .mla_savings_history.jsonl.bak.* faylında saxlanılır.\n' +
    'Yeni task-lar yenidən toplanacaq.',
  'bar.tip.staleNote':
    '⚠ Lisenziya yoxlanışı köhnəlmiş (offline). Hook-lar keş ilə işləyir.',
  'bar.tip.lastUpdate':
    'Fayllar: history mtime {history} · session-log mtime {session}',

  'bar.tipFull':
    'Durum: {state}\n' +
    'Son 24 saat: {tasks} task, {saved} token qənaət ({pct} izlənən əməliyyatlar üzrə) · {files} fayl\n' +
    '  • search_code: {search} tok\n' +
    '  • Grep: {grep} tok ({greps} grep)\n' +
    '  • Bash inspect: {bash} tok ({bashes} yoxlama)\n' +
    '  • Read-block: {block} tok ({blocks} block)\n' +
    '  • Read-warn: {warns} soft xəbərdarlıq (cəmiyə daxil deyil)\n' +
    'Cəmi: {totalTasks} task, {totalSearches} search, ' +
    '{totalGreps} grep, {totalBashInspects} bash, {totalBlocks} block, ' +
    '{totalWarns} warn, {totalFiles} fayl qənaət\n' +
    'Qeyd: faiz Tokengram üzərindən gedən search/Read/Grep/Bash-i ölçür; ' +
    'Edit, xam Bash output və sistem-prompt overhead-i daxil deyil.',

  'menu.breakdown': '$(list-tree) Event breakdown',
  'menu.breakdownDesc': 'Output paneldə xam session-log + history detalları',
  'breakdown.title': 'Tokengram event breakdown',
  'breakdown.noWorkspace': '(workspace açılmayıb)',
  'breakdown.sessionLogHeading': '## Cari turn session log',
  'breakdown.historyHeading': '## History (son 5 record)',
  'breakdown.licenseHeading': '## Lisenziya keşi',
  'breakdown.empty': '(boş — bu turn-də hələ event yoxdur)',
  'breakdown.missing': '(fayl yoxdur)',
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

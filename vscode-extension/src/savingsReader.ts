import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

interface SavingsRecord {
  ts: number;
  searches: number;
  blocks?: number;
  greps?: number;
  bash_inspects?: number;
  read_warns?: number;
  actual_tokens: number;
  baseline_tokens: number;
  search_baseline_tokens?: number;
  block_baseline_tokens?: number;
  grep_baseline_tokens?: number;
  grep_actual_tokens?: number;
  bash_baseline_tokens?: number;
  bash_actual_tokens?: number;
  warn_baseline_tokens?: number;
  saving_tokens: number;
  saving_pct: number;
  file_count: number;
}

export interface SavingsSummary {
  totalTasks: number;
  totalSearches: number;
  totalBlocks: number;
  totalGreps: number;
  totalBashInspects: number;
  totalWarns: number;
  totalFiles: number;
  savedTokens24h: number;
  savedFromSearch24h: number;
  savedFromBlocks24h: number;
  savedFromGreps24h: number;
  savedFromBash24h: number;
  savedPct24h: number;
  recent24hTasks: number;
  recent24hBlocks: number;
  recent24hGreps: number;
  recent24hBashInspects: number;
  recent24hWarns: number;
  recent24hFiles: number;
  // Bar UX: 24h aggregate kifayət deyil — kiçik turn-dəlişikliklər görünmür.
  // Bunlar session_log-dan oxunur (Stop hook hələ flush etməyib):
  pendingSavedTokens: number;     // bu turn-də indi səviyyəsində qənaət
  pendingActivityCount: number;   // search + grep + bash + block + warn cəm
  // Background worker queue (index re-build pending):
  indexingPending: number;        // .mla_pending.txt-də fayl sayı
}

export function findHistoryFile(): string | null {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders) return null;
  for (const folder of folders) {
    const p = path.join(folder.uri.fsPath, '.mla_savings_history.jsonl');
    if (fs.existsSync(p)) return p;
  }
  return null;
}

interface SessionLogEntry {
  ts: number;
  type?: string;
  files?: Record<string, number>;
  actual_tokens?: number;
  estimated_baseline_tokens?: number;
  estimated_actual_tokens?: number;
}

interface PendingDelta {
  searchCount: number;
  blockCount: number;
  grepCount: number;
  bashCount: number;
  warnCount: number;
  fileCount: number;
  searchBaseline: number;
  searchActual: number;
  blockBaseline: number;
  grepBaseline: number;
  grepActual: number;
  bashBaseline: number;
  bashActual: number;
  warnBaseline: number;
}

// Per-fayl baseline cap: bir default Read çağırışı qədər (2000 sətir × 10 tok).
// 100k+ token generated fayllar (Cython .c) əks halda metrikanı şişirdir.
// Stop hook savings_report.py-da eyni dəyər istifadə olunur.
const MAX_BASELINE_PER_FILE = 20_000;

function capProportional(rawBaseline: number, rawActual: number): [number, number] {
  if (rawBaseline <= MAX_BASELINE_PER_FILE) return [rawBaseline, rawActual];
  const scale = MAX_BASELINE_PER_FILE / rawBaseline;
  return [MAX_BASELINE_PER_FILE, Math.round(rawActual * scale)];
}

function readSessionLog(historyPath: string): PendingDelta | null {
  const sessionLogPath = path.join(
    path.dirname(historyPath),
    '.mla_session_log.jsonl',
  );
  let data: string;
  try {
    data = fs.readFileSync(sessionLogPath, 'utf-8');
  } catch {
    return null;
  }
  const uniqueFiles = new Map<string, number>();
  const d: PendingDelta = {
    searchCount: 0,
    blockCount: 0,
    grepCount: 0,
    bashCount: 0,
    warnCount: 0,
    fileCount: 0,
    searchBaseline: 0,
    searchActual: 0,
    blockBaseline: 0,
    grepBaseline: 0,
    grepActual: 0,
    bashBaseline: 0,
    bashActual: 0,
    warnBaseline: 0,
  };
  let hasAny = false;
  for (const line of data.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let e: SessionLogEntry;
    try {
      e = JSON.parse(trimmed);
    } catch {
      continue;
    }
    hasAny = true;
    const t = e.type ?? 'search_code';
    if (t === 'read_block') {
      d.blockCount += 1;
      d.blockBaseline += Math.min(e.estimated_baseline_tokens ?? 0, MAX_BASELINE_PER_FILE);
    } else if (t === 'read_warn') {
      d.warnCount += 1;
      d.warnBaseline += Math.min(e.estimated_baseline_tokens ?? 0, MAX_BASELINE_PER_FILE);
    } else if (t === 'grep_search') {
      d.grepCount += 1;
      const [cb, ca] = capProportional(
        e.estimated_baseline_tokens ?? 0,
        e.estimated_actual_tokens ?? 0,
      );
      d.grepBaseline += cb;
      d.grepActual += ca;
    } else if (t === 'bash_inspect') {
      d.bashCount += 1;
      const [cb, ca] = capProportional(
        e.estimated_baseline_tokens ?? 0,
        e.estimated_actual_tokens ?? 0,
      );
      d.bashBaseline += cb;
      d.bashActual += ca;
    } else {
      d.searchCount += 1;
      d.searchActual += e.actual_tokens ?? 0;
      const files = e.files ?? {};
      for (const [p, tok] of Object.entries(files)) {
        const capped = Math.min(tok, MAX_BASELINE_PER_FILE);
        const prev = uniqueFiles.get(p) ?? 0;
        if (capped > prev) uniqueFiles.set(p, capped);
      }
    }
  }
  if (!hasAny) return null;
  d.fileCount = uniqueFiles.size;
  for (const v of uniqueFiles.values()) d.searchBaseline += v;
  return d;
}

function readIndexingPending(historyPath: string): number {
  // Background worker drain etməyən fayllar — re-embed gözləyirlər.
  const pendingPath = path.join(
    path.dirname(historyPath),
    '.mla_pending.txt',
  );
  try {
    const data = fs.readFileSync(pendingPath, 'utf-8');
    return data.split('\n').filter((l) => l.trim()).length;
  } catch {
    return 0;
  }
}

export function readSavings(historyPath: string): SavingsSummary | null {
  let data: string;
  try {
    data = fs.readFileSync(historyPath, 'utf-8');
  } catch {
    data = '';
  }
  const records: SavingsRecord[] = [];
  for (const line of data.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      records.push(JSON.parse(trimmed));
    } catch {
      /* skip malformed */
    }
  }
  const pending = readSessionLog(historyPath);
  const indexingPending = readIndexingPending(historyPath);
  // Boş state-də də summary qaytar — bar "0.0k · 0%" göstərsin,
  // "başlayır..." state-i user-ə sonsuz yüklənmə kimi görünür.

  const cutoff = Date.now() / 1000 - 86400;
  const recent = records.filter((r) => r.ts >= cutoff);
  const actualR = recent.reduce((s, r) => s + r.actual_tokens, 0);
  const baseR = recent.reduce((s, r) => s + r.baseline_tokens, 0);
  const savedR = baseR - actualR;
  const pctR = baseR > 0 ? (savedR / baseR) * 100 : 0;

  const totalSearches = records.reduce((s, r) => s + r.searches, 0);
  const totalBlocks = records.reduce((s, r) => s + (r.blocks ?? 0), 0);
  const totalGreps = records.reduce((s, r) => s + (r.greps ?? 0), 0);
  const totalBashInspects = records.reduce(
    (s, r) => s + (r.bash_inspects ?? 0),
    0,
  );
  const totalWarns = records.reduce((s, r) => s + (r.read_warns ?? 0), 0);
  const totalFiles = records.reduce((s, r) => s + (r.file_count ?? 0), 0);
  const recent24hBlocks = recent.reduce((s, r) => s + (r.blocks ?? 0), 0);
  const recent24hGreps = recent.reduce((s, r) => s + (r.greps ?? 0), 0);
  const recent24hBashInspects = recent.reduce(
    (s, r) => s + (r.bash_inspects ?? 0),
    0,
  );
  const recent24hWarns = recent.reduce((s, r) => s + (r.read_warns ?? 0), 0);
  const recent24hFiles = recent.reduce((s, r) => s + (r.file_count ?? 0), 0);

  // Hər kateqoriya üçün baseline ayrıca, actual ayrıca — sonra subtract.
  // Bu cür hesablama "bash savings search sətrinə leak olur" bug-unun qarşısını alır.
  const searchBaseline24h = recent.reduce(
    (s, r) => s + (r.search_baseline_tokens ?? 0),
    0,
  );
  const grepBaseline24h = recent.reduce(
    (s, r) => s + (r.grep_baseline_tokens ?? 0),
    0,
  );
  const grepActual24h = recent.reduce(
    (s, r) => s + (r.grep_actual_tokens ?? 0),
    0,
  );
  const bashBaseline24h = recent.reduce(
    (s, r) => s + (r.bash_baseline_tokens ?? 0),
    0,
  );
  const bashActual24h = recent.reduce(
    (s, r) => s + (r.bash_actual_tokens ?? 0),
    0,
  );
  // read_block-ların actual-ı 0-dır — actualR-də yalnız search + grep + bash töhfə var.
  const searchActual24h = Math.max(0, actualR - grepActual24h - bashActual24h);

  const savedFromBlocksHistory = recent.reduce(
    (s, r) => s + (r.block_baseline_tokens ?? 0),
    0,
  );
  const savedFromGrepsHistory = Math.max(0, grepBaseline24h - grepActual24h);
  const savedFromBashHistory = Math.max(0, bashBaseline24h - bashActual24h);
  const savedFromSearchHistory = Math.max(
    0,
    searchBaseline24h - searchActual24h,
  );

  // Pending delta — in-flight session_log entries. Hooks bunlara yazır,
  // Stop hook isə history-yə dren edir. Bar promt zamanı livedir.
  const p = pending ?? {
    searchCount: 0,
    blockCount: 0,
    grepCount: 0,
    bashCount: 0,
    warnCount: 0,
    fileCount: 0,
    searchBaseline: 0,
    searchActual: 0,
    blockBaseline: 0,
    grepBaseline: 0,
    grepActual: 0,
    bashBaseline: 0,
    bashActual: 0,
    warnBaseline: 0,
  };
  const pendingSavedBlocks = p.blockBaseline;
  const pendingSavedGreps = Math.max(0, p.grepBaseline - p.grepActual);
  const pendingSavedBash = Math.max(0, p.bashBaseline - p.bashActual);
  const pendingSavedSearch = Math.max(0, p.searchBaseline - p.searchActual);
  const pendingSaved =
    pendingSavedBlocks +
    pendingSavedGreps +
    pendingSavedBash +
    pendingSavedSearch;
  const pendingBaseline =
    p.blockBaseline + p.grepBaseline + p.bashBaseline + p.searchBaseline;
  const pendingTask = pending ? 1 : 0;

  const savedTokens24h = savedR + pendingSaved;
  const baseline24h = baseR + pendingBaseline;
  const savedPct24h = baseline24h > 0 ? (savedTokens24h / baseline24h) * 100 : 0;

  return {
    totalTasks: records.length + pendingTask,
    totalSearches: totalSearches + p.searchCount,
    totalBlocks: totalBlocks + p.blockCount,
    totalGreps: totalGreps + p.grepCount,
    totalBashInspects: totalBashInspects + p.bashCount,
    totalWarns: totalWarns + p.warnCount,
    totalFiles: totalFiles + p.fileCount,
    savedTokens24h,
    savedFromSearch24h: savedFromSearchHistory + pendingSavedSearch,
    savedFromBlocks24h: savedFromBlocksHistory + pendingSavedBlocks,
    savedFromGreps24h: savedFromGrepsHistory + pendingSavedGreps,
    savedFromBash24h: savedFromBashHistory + pendingSavedBash,
    savedPct24h,
    recent24hTasks: recent.length + pendingTask,
    recent24hBlocks: recent24hBlocks + p.blockCount,
    recent24hGreps: recent24hGreps + p.grepCount,
    recent24hBashInspects: recent24hBashInspects + p.bashCount,
    recent24hWarns: recent24hWarns + p.warnCount,
    recent24hFiles: recent24hFiles + p.fileCount,
    pendingSavedTokens: pendingSaved,
    pendingActivityCount:
      p.searchCount + p.blockCount + p.grepCount + p.bashCount + p.warnCount,
    indexingPending,
  };
}

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
  // Real-spend buckets (yeni — 2026-05-15; köhnə qeydlər undefined verə bilər)
  read_passes?: number;
  read_pass_tokens?: number;
  bash_outputs?: number;
  bash_output_tokens?: number;
  // Chunked Read (yeni — 2026-05-18): hər limit-bounded Read həm saved, həm spent verir
  read_chunked?: number;
  chunked_baseline_tokens?: number;
  chunked_spent_tokens?: number;
  untracked_spent_tokens?: number;
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
  // Health signals — bar bu state-ləri user-ə görünən etmək üçün istifadə edir:
  historyEmpty: boolean;          // .mla_savings_history.jsonl 0 byte
  historyMtimeAgeSec: number;     // history-nin son dəyişikliyindən keçən saniyə
  queueStuckAgeSec: number;       // .mla_pending.processing yaşı (0 = yox)
}

// VS Code workspace bəzən Claude Code project_root-undan kiçikdir (məsələn user
// mono-repo-nun bir subfolder-ini açır). Hooks `$CLAUDE_PROJECT_DIR` kökündə yazır.
// Biz iki dəfə yuxarı qalxırıq:
//   1) Data faylı (.mla_savings_history.jsonl) — ən etibarlı işarə, real qeydlər orda.
//   2) Konfigurasiya faylı (.claude/settings.json / .mcp.json) — hooks
//      konfiqurasiyalı olduğu kök; bar oraya yazmaq üçün hələ ən düzgün vaxtdır.
// Yalnız `.mla_enforcement.flag` çox yerdə ola bilər, son seçim kimi istifadə edirik.
export function findProjectRoot(startDir: string): string {
  const exists = (dir: string, ...parts: string[]) =>
    fs.existsSync(path.join(dir, ...parts));

  // Empty history file = stale Stop-hook artifact in a subfolder. Skip it so
  // walk-up keeps climbing to the real root (where the populated history lives).
  const nonemptyHistory = (dir: string): boolean => {
    const h = path.join(dir, '.mla_savings_history.jsonl');
    try {
      return fs.existsSync(h) && fs.statSync(h).size > 0;
    } catch {
      return false;
    }
  };

  const walkUp = (predicate: (dir: string) => boolean): string | null => {
    let dir = startDir;
    for (let i = 0; i < 8; i++) {
      if (predicate(dir)) return dir;
      const parent = path.dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
    return null;
  };

  return (
    walkUp(nonemptyHistory) ??
    walkUp((d) => exists(d, '.claude', 'settings.json')) ??
    walkUp((d) => exists(d, '.mcp.json')) ??
    walkUp((d) => exists(d, '.mla_enforcement.flag')) ??
    startDir
  );
}

export function findHistoryFile(): string | null {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders) return null;
  for (const folder of folders) {
    const root = findProjectRoot(folder.uri.fsPath);
    const p = path.join(root, '.mla_savings_history.jsonl');
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
  estimated_spent_tokens?: number;  // read_chunked event-ləri üçün
  estimated_tokens?: number;  // read_pass / bash_output event-ləri üçün
}

interface PendingDelta {
  searchCount: number;
  blockCount: number;
  grepCount: number;
  bashCount: number;
  warnCount: number;
  chunkedCount: number;
  fileCount: number;
  searchBaseline: number;
  searchActual: number;
  blockBaseline: number;
  grepBaseline: number;
  grepActual: number;
  bashBaseline: number;
  bashActual: number;
  warnBaseline: number;
  chunkedBaseline: number;
  chunkedSpent: number;
  // Untracked real-spend
  readPassTokens: number;
  bashOutputTokens: number;
}

// Per-event baseline cap = realistik chunked Read dəyəri (~1000 sətir × 10 tok).
// Model: MLA-sız agent adətən nəhəng faylı tam oxumur, target-li chunked Read edir.
// savings_report.py-da eyni dəyər istifadə olunur.
const MAX_BASELINE_PER_EVENT = 10_000;

function capProportional(rawBaseline: number, rawActual: number): [number, number] {
  if (rawBaseline <= MAX_BASELINE_PER_EVENT) return [rawBaseline, rawActual];
  const scale = MAX_BASELINE_PER_EVENT / rawBaseline;
  return [MAX_BASELINE_PER_EVENT, Math.round(rawActual * scale)];
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
    chunkedCount: 0,
    fileCount: 0,
    searchBaseline: 0,
    searchActual: 0,
    blockBaseline: 0,
    grepBaseline: 0,
    grepActual: 0,
    bashBaseline: 0,
    bashActual: 0,
    warnBaseline: 0,
    chunkedBaseline: 0,
    chunkedSpent: 0,
    readPassTokens: 0,
    bashOutputTokens: 0,
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
      d.blockBaseline += Math.min(e.estimated_baseline_tokens ?? 0, MAX_BASELINE_PER_EVENT);
    } else if (t === 'read_warn') {
      d.warnCount += 1;
      d.warnBaseline += Math.min(e.estimated_baseline_tokens ?? 0, MAX_BASELINE_PER_EVENT);
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
    } else if (t === 'read_pass') {
      d.readPassTokens += e.estimated_tokens ?? 0;
    } else if (t === 'bash_output') {
      d.bashOutputTokens += e.estimated_tokens ?? 0;
    } else if (t === 'read_chunked') {
      d.chunkedCount += 1;
      const [cb, cs] = capProportional(
        e.estimated_baseline_tokens ?? 0,
        e.estimated_spent_tokens ?? 0,
      );
      d.chunkedBaseline += cb;
      d.chunkedSpent += cs;
    } else {
      d.searchCount += 1;
      d.searchActual += e.actual_tokens ?? 0;
      const files = e.files ?? {};
      // search_code: yalnız TOP fayl-ı baseline-a hesab et (rank order qorunur).
      // MLA-sız agent N fayl deyil, 1 chunked Read edərdi.
      const entries = Object.entries(files);
      if (entries.length > 0) {
        const topTokens = entries[0][1] as number;
        d.searchBaseline += Math.min(topTokens, MAX_BASELINE_PER_EVENT);
        for (const [p] of entries) uniqueFiles.set(p, 0);
      }
    }
  }
  if (!hasAny) return null;
  d.fileCount = uniqueFiles.size;
  return d;
}

function countQueueLines(filePath: string): number {
  try {
    const data = fs.readFileSync(filePath, 'utf-8');
    return data.split('\n').filter((l) => l.trim()).length;
  } catch {
    return 0;
  }
}

function readIndexingPending(historyPath: string): number {
  // Background worker drain etməyən fayllar — re-embed gözləyirlər.
  // Həm .pending.txt (növbədə), həm də .processing (drain mid-flight) sayılır
  // ki worker stuck olduqda da real "ilişib qalan" sayı düzgün görünsün.
  const dir = path.dirname(historyPath);
  return (
    countQueueLines(path.join(dir, '.mla_pending.txt')) +
    countQueueLines(path.join(dir, '.mla_pending.processing'))
  );
}

// `.mla_pending.processing` mövcud və **boş deyilsə**, MCP background worker
// queue-nu drain edir. Worker crash etsə, fayl qalır — yaşı 30 dəq+ olarsa
// stuck. Boş `.processing` (orphan marker) stuck sayılmır — drainer üçün
// sonrakı dövrdə avtomatik təmizlənən artıqdır.
function readQueueStuckAge(historyPath: string): number {
  const processingPath = path.join(
    path.dirname(historyPath),
    '.mla_pending.processing',
  );
  try {
    const st = fs.statSync(processingPath);
    if (st.size === 0) return 0;
    if (countQueueLines(processingPath) === 0) return 0;
    return Math.max(0, Math.floor((Date.now() - st.mtimeMs) / 1000));
  } catch {
    return 0;
  }
}

function readHistoryStats(historyPath: string): {
  empty: boolean;
  mtimeAgeSec: number;
} {
  try {
    const st = fs.statSync(historyPath);
    return {
      empty: st.size === 0,
      mtimeAgeSec: Math.max(0, Math.floor((Date.now() - st.mtimeMs) / 1000)),
    };
  } catch {
    return { empty: true, mtimeAgeSec: Number.MAX_SAFE_INTEGER };
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
  const queueStuckAgeSec = readQueueStuckAge(historyPath);
  const historyStats = readHistoryStats(historyPath);
  // Boş state-də də summary qaytar — bar "0.0k · 0%" göstərsin,
  // "başlayır..." state-i user-ə sonsuz yüklənmə kimi görünür.

  const cutoff = Date.now() / 1000 - 86400;
  const recent = records.filter((r) => r.ts >= cutoff);
  const actualR = recent.reduce((s, r) => s + r.actual_tokens, 0);
  const baseR = recent.reduce((s, r) => s + r.baseline_tokens, 0);
  const savedR = baseR - actualR;
  // Yeni real-spend bucket-ləri history-dən topla. Köhnə record-larda
  // (yeni hook-lardan əvvəl) bunlar undefined-dir, default 0.
  const readPassTokens24h = recent.reduce(
    (s, r) => s + (r.read_pass_tokens ?? 0),
    0,
  );
  const bashOutputTokens24h = recent.reduce(
    (s, r) => s + (r.bash_output_tokens ?? 0),
    0,
  );

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
    chunkedCount: 0,
    fileCount: 0,
    searchBaseline: 0,
    searchActual: 0,
    blockBaseline: 0,
    grepBaseline: 0,
    grepActual: 0,
    bashBaseline: 0,
    bashActual: 0,
    warnBaseline: 0,
    chunkedBaseline: 0,
    chunkedSpent: 0,
    readPassTokens: 0,
    bashOutputTokens: 0,
  };
  const pendingSavedBlocks = p.blockBaseline;
  const pendingSavedGreps = Math.max(0, p.grepBaseline - p.grepActual);
  const pendingSavedBash = Math.max(0, p.bashBaseline - p.bashActual);
  const pendingSavedSearch = Math.max(0, p.searchBaseline - p.searchActual);
  const pendingSavedChunked = Math.max(0, p.chunkedBaseline - p.chunkedSpent);
  const pendingSaved =
    pendingSavedBlocks +
    pendingSavedGreps +
    pendingSavedBash +
    pendingSavedSearch +
    pendingSavedChunked;
  const pendingBaseline =
    p.blockBaseline + p.grepBaseline + p.bashBaseline + p.searchBaseline +
    p.chunkedBaseline;
  const pendingTask = pending ? 1 : 0;

  const savedTokens24h = savedR + pendingSaved;
  const baseline24h = baseR + pendingBaseline;
  // Real session pct — saved / (saved + bütün real spend). Köhnə düstur
  // saved / baseline idi, amma baseline yalnız MLA-nın gördüyü ops üçündü.
  // İndi Edit-heavy / Bash-heavy refactor-da bypass və bash_output sayılır,
  // % rəqəmi real session reduction-u göstərir.
  const realSpent24h =
    actualR +
    readPassTokens24h +
    bashOutputTokens24h +
    p.searchActual +
    p.grepActual +
    p.bashActual +
    p.chunkedSpent +
    p.readPassTokens +
    p.bashOutputTokens;
  const realTotal24h = savedTokens24h + realSpent24h;
  // Low-sample guard: just after VS Code reload only "saved" events have
  // been recorded yet (chunked-Read / Edit / Bash actuals haven't fired),
  // so the naive ratio reads 100% even when no real work has happened.
  // Sentinel -1 signals "not enough data" — the status bar renders "—".
  const LOW_SAMPLE_THRESHOLD = 200;
  const savedPct24h =
    realSpent24h < LOW_SAMPLE_THRESHOLD
      ? -1
      : realTotal24h > 0
        ? (savedTokens24h / realTotal24h) * 100
        : 0;

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
    historyEmpty: historyStats.empty,
    historyMtimeAgeSec: historyStats.mtimeAgeSec,
    queueStuckAgeSec,
  };
}

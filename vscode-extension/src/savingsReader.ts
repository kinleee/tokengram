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

export function readSavings(historyPath: string): SavingsSummary | null {
  let data: string;
  try {
    data = fs.readFileSync(historyPath, 'utf-8');
  } catch {
    return null;
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
  if (records.length === 0) return null;

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

  const savedFromBlocks24h = recent.reduce(
    (s, r) => s + (r.block_baseline_tokens ?? 0),
    0,
  );
  const savedFromGreps24h = Math.max(0, grepBaseline24h - grepActual24h);
  const savedFromBash24h = Math.max(0, bashBaseline24h - bashActual24h);
  const savedFromSearch24h = Math.max(0, searchBaseline24h - searchActual24h);

  return {
    totalTasks: records.length,
    totalSearches,
    totalBlocks,
    totalGreps,
    totalBashInspects,
    totalWarns,
    totalFiles,
    savedTokens24h: savedR,
    savedFromSearch24h,
    savedFromBlocks24h,
    savedFromGreps24h,
    savedFromBash24h,
    savedPct24h: pctR,
    recent24hTasks: recent.length,
    recent24hBlocks,
    recent24hGreps,
    recent24hBashInspects,
    recent24hWarns,
    recent24hFiles,
  };
}

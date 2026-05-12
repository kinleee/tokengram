import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

interface SavingsRecord {
  ts: number;
  searches: number;
  actual_tokens: number;
  baseline_tokens: number;
  saving_tokens: number;
  saving_pct: number;
  file_count: number;
}

export interface SavingsSummary {
  totalTasks: number;
  totalSearches: number;
  savedTokens24h: number;
  savedPct24h: number;
  recent24hTasks: number;
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

  return {
    totalTasks: records.length,
    totalSearches,
    savedTokens24h: savedR,
    savedPct24h: pctR,
    recent24hTasks: recent.length,
  };
}

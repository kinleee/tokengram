import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { findHistoryFile, readSavings } from './savingsReader';

const REFRESH_MS = 30_000;

function readEnforcement(workspacePath: string): boolean {
  try {
    const flagPath = path.join(workspacePath, '.mla_enforcement.flag');
    return fs.readFileSync(flagPath, 'utf-8').trim().toLowerCase() === 'on';
  } catch {
    return false;
  }
}

export function createStatusBar(context: vscode.ExtensionContext): vscode.Disposable {
  const item = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100,
  );
  item.show();

  const refresh = () => {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders || folders.length === 0) {
      item.text = '$(database) MLA: no project';
      item.tooltip = 'No workspace folder open';
      item.color = undefined;
      return;
    }

    const workspacePath = folders[0].uri.fsPath;
    const enforcementOn = readEnforcement(workspacePath);
    const stateLabel = enforcementOn ? 'ON' : 'OFF';
    const icon = enforcementOn ? '$(circle-filled)' : '$(circle-large-outline)';
    const color = enforcementOn
      ? new vscode.ThemeColor('charts.green')
      : undefined;

    const historyPath = findHistoryFile();
    if (!historyPath) {
      item.text = `${icon} MLA: no data · ${stateLabel}`;
      item.tooltip = `Enforcement: ${stateLabel}\nNo .mla_savings_history.jsonl yet`;
      item.color = color;
      return;
    }

    const summary = readSavings(historyPath);
    if (!summary) {
      item.text = `${icon} MLA: starting… · ${stateLabel}`;
      item.tooltip = `Enforcement: ${stateLabel}\nIndexing or no recent activity`;
      item.color = color;
      return;
    }

    const savedK = (summary.savedTokens24h / 1000).toFixed(1);
    item.text = `${icon} MLA: ${savedK}k saved · ${summary.savedPct24h.toFixed(0)}%`;
    item.color = color;
    item.tooltip =
      `Enforcement: ${stateLabel}\n` +
      `Last 24h: ${summary.recent24hTasks} tasks, ` +
      `${summary.savedTokens24h.toLocaleString()} tokens saved ` +
      `(${summary.savedPct24h.toFixed(1)}%)\n` +
      `Lifetime: ${summary.totalTasks} tasks, ${summary.totalSearches} searches`;
  };

  refresh();
  const interval = setInterval(refresh, REFRESH_MS);

  const folders = vscode.workspace.workspaceFolders;
  if (folders && folders.length > 0) {
    const flagWatcher = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(folders[0], '.mla_enforcement.flag'),
    );
    flagWatcher.onDidChange(refresh);
    flagWatcher.onDidCreate(refresh);
    flagWatcher.onDidDelete(refresh);
    context.subscriptions.push(flagWatcher);

    const historyWatcher = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(folders[0], '.mla_savings_history.jsonl'),
    );
    historyWatcher.onDidChange(refresh);
    historyWatcher.onDidCreate(refresh);
    historyWatcher.onDidDelete(refresh);
    context.subscriptions.push(historyWatcher);
  }

  return new vscode.Disposable(() => {
    clearInterval(interval);
    item.dispose();
  });
}

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { tr } from './i18n';
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
  item.command = 'mla.menu';
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
    const enforcementOn = readEnforcement(workspacePath);
    const stateLabel = enforcementOn ? 'ON' : 'OFF';
    const icon = enforcementOn ? '$(circle-filled)' : '$(circle-large-outline)';
    const color = enforcementOn
      ? new vscode.ThemeColor('charts.green')
      : undefined;

    const historyPath = findHistoryFile();
    if (!historyPath) {
      item.text = tr('bar.noData', { icon, state: stateLabel });
      item.tooltip = tr('bar.tipNoData', { state: stateLabel });
      item.color = color;
      return;
    }

    const summary = readSavings(historyPath);
    if (!summary) {
      item.text = tr('bar.starting', { icon, state: stateLabel });
      item.tooltip = tr('bar.tipStarting', { state: stateLabel });
      item.color = color;
      return;
    }

    const savedK = (summary.savedTokens24h / 1000).toFixed(1);
    item.text = tr('bar.summary', {
      icon,
      savedK,
      pct: summary.savedPct24h.toFixed(0),
    });
    item.color = color;
    item.tooltip = tr('bar.tipFull', {
      state: stateLabel,
      tasks: summary.recent24hTasks,
      saved: summary.savedTokens24h.toLocaleString(),
      pct: summary.savedPct24h.toFixed(1),
      search: summary.savedFromSearch24h.toLocaleString(),
      grep: summary.savedFromGreps24h.toLocaleString(),
      greps: summary.recent24hGreps,
      block: summary.savedFromBlocks24h.toLocaleString(),
      blocks: summary.recent24hBlocks,
      totalTasks: summary.totalTasks,
      totalSearches: summary.totalSearches,
      totalGreps: summary.totalGreps,
      totalBlocks: summary.totalBlocks,
    });
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

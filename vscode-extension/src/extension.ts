import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { startPeriodicRecheck } from './licenseStatus';
import { registerMenuCommand } from './menu';
import { createStatusBar } from './statusBar';
import { ensureAutoInstall, registerSetupCommand } from './setupWizard';

export function activate(context: vscode.ExtensionContext) {
  mirrorParentWorkspaceHooks();
  context.subscriptions.push(registerMenuCommand(context));
  context.subscriptions.push(registerSetupCommand(context));
  const statusBar = createStatusBar(context);
  context.subscriptions.push(statusBar);
  context.subscriptions.push(startPeriodicRecheck());
  void ensureAutoInstall(context);
}

// Subfolder workspace fix: if the user opens a sub-folder of a Tokengram-configured
// project (e.g. monorepo `apps/web/`), Claude Code looks for `.claude/settings.json`
// only in the workspace root and never walks up. Mirror parent settings down so
// hooks fire in the sub-folder the same way they do in the parent.
function mirrorParentWorkspaceHooks(): void {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) return;
  const ws = folders[0].uri.fsPath;
  if (fs.existsSync(path.join(ws, '.claude', 'settings.json'))) return;

  let dir = path.dirname(ws);
  for (let i = 0; i < 8; i++) {
    const parentSettings = path.join(dir, '.claude', 'settings.json');
    if (fs.existsSync(parentSettings)) {
      try {
        fs.mkdirSync(path.join(ws, '.claude'), { recursive: true });
        fs.copyFileSync(parentSettings, path.join(ws, '.claude', 'settings.json'));
        const parentMcp = path.join(dir, '.mcp.json');
        if (fs.existsSync(parentMcp) && !fs.existsSync(path.join(ws, '.mcp.json'))) {
          fs.copyFileSync(parentMcp, path.join(ws, '.mcp.json'));
        }
        vscode.window.showInformationMessage(
          'Tokengram: mirrored parent workspace hooks into this sub-folder. Reload Claude Code to activate.',
        );
      } catch {
        // Best-effort — never block activation.
      }
      return;
    }
    const next = path.dirname(dir);
    if (next === dir) return;
    dir = next;
  }
}

export function deactivate() {
  /* nothing to clean up — disposables handled by context */
}

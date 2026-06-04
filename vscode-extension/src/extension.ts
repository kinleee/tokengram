import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { startPeriodicRecheck } from './licenseStatus';
import { registerMenuCommand, registerSetLicenseKeyCommand } from './menu';
import { createStatusBar } from './statusBar';
import { ensureAutoInstall, registerSetupCommand, pinServerUrl } from './setupWizard';

export function activate(context: vscode.ExtensionContext) {
  // Bundled wheel `py3-none-any` taglənib amma daxili .pyd Windows-only.
  // macOS/Linux-də pip silent install edir, sonra import-da crash; user
  // "extension installed" görür amma heç bir hook işləmir. Fail-fast.
  if (process.platform !== 'win32') {
    void vscode.window.showErrorMessage(
      'Tokengram currently supports Windows only. macOS and Linux builds are on the roadmap — please follow https://github.com/kinleee/tokengram for updates.',
    );
    return;
  }
  warnIfLegacyMlaExtensionPresent();
  mirrorParentWorkspaceHooks();
  // Self-heal a stale license-server URL (old ~/.mla migration / parked-domain
  // era) so already-installed testers don't stay stuck on a dead endpoint.
  pinServerUrl();
  context.subscriptions.push(registerMenuCommand(context));
  context.subscriptions.push(registerSetLicenseKeyCommand());
  context.subscriptions.push(registerSetupCommand(context));
  const statusBar = createStatusBar(context);
  context.subscriptions.push(statusBar);
  context.subscriptions.push(startPeriodicRecheck());
  void ensureAutoInstall(context);
}

// Tokengram is the rebrand of "MLA Agent" (publisher.id `erp-intel.mla-agent`).
// If both extensions are installed side-by-side, VS Code shows two status-bar
// widgets, two sets of hooks fire on every Read, and the savings counter is
// split across two files. Prompt the user to uninstall the legacy one.
function warnIfLegacyMlaExtensionPresent(): void {
  const legacy = vscode.extensions.getExtension('erp-intel.mla-agent');
  if (!legacy) return;
  void vscode.window
    .showWarningMessage(
      'Tokengram: the legacy "MLA Agent" extension is still installed. ' +
        'Two status-bar widgets and two hook sets are running side-by-side — ' +
        'please uninstall the old one to avoid double-indexing.',
      'Uninstall MLA Agent',
      'Later',
    )
    .then((choice) => {
      if (choice === 'Uninstall MLA Agent') {
        void vscode.commands.executeCommand(
          'workbench.extensions.uninstallExtension',
          'erp-intel.mla-agent',
        );
      }
    });
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

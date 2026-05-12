import * as cp from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { tr } from './i18n';

interface MenuItem extends vscode.QuickPickItem {
  action:
    | 'toggle'
    | 'refresh'
    | 'reset'
    | 'arch'
    | 'reindex'
    | 'sync';
}

function readFlag(root: string): 'on' | 'off' {
  try {
    const v = fs
      .readFileSync(path.join(root, '.mla_enforcement.flag'), 'utf-8')
      .trim()
      .toLowerCase();
    return v === 'on' ? 'on' : 'off';
  } catch {
    return 'off';
  }
}

function execFile(
  bin: string,
  args: string[],
  cwd: string,
): Promise<{ stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    cp.execFile(
      bin,
      args,
      { cwd, encoding: 'utf-8' },
      (err, stdout, stderr) => {
        if (err) {
          reject(new Error(`${err.message}\n${stderr}`));
        } else {
          resolve({ stdout, stderr });
        }
      },
    );
  });
}

function pythonScript(root: string, rel: string, args: string[] = []) {
  return execFile('python', [path.join(root, rel), ...args], root);
}

function projectRoot(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath;
}

async function runAction(action: MenuItem['action'], root: string) {
  const channel = vscode.window.createOutputChannel('MLA Agent');
  switch (action) {
    case 'toggle': {
      const cur = readFlag(root);
      const next = cur === 'on' ? 'off' : 'on';
      const { stdout } = await pythonScript(root, 'hooks/toggle_mla.py', [next]);
      vscode.window.showInformationMessage(
        tr('menu.toggleResult', { output: stdout.trim() }),
      );
      break;
    }
    case 'refresh': {
      await pythonScript(root, 'hooks/refresh_bar.py');
      vscode.window.showInformationMessage(tr('menu.refreshResult'));
      break;
    }
    case 'reset': {
      const choice = await vscode.window.showWarningMessage(
        tr('menu.resetConfirm'),
        { modal: true },
        tr('menu.resetConfirmYes'),
      );
      if (choice !== tr('menu.resetConfirmYes')) return;
      const { stdout } = await pythonScript(root, 'hooks/reset_savings.py');
      vscode.window.showInformationMessage(
        tr('menu.resetResult', { output: stdout.trim() }),
      );
      break;
    }
    case 'arch': {
      const { stdout } = await pythonScript(root, 'hooks/show_arch.py');
      channel.clear();
      channel.appendLine(stdout);
      channel.show(true);
      break;
    }
    case 'reindex': {
      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: tr('menu.reindexTitle'),
          cancellable: false,
        },
        async () => {
          await execFile('python', ['main.py', 'index', '.', '--fresh'], root);
        },
      );
      vscode.window.showInformationMessage(tr('menu.reindexDone'));
      break;
    }
    case 'sync': {
      const { stderr } = await pythonScript(root, 'hooks/savings_report.py');
      const summary = stderr.split('\n').find((l) => l.includes('[mla-agent]'));
      vscode.window.showInformationMessage(
        summary ?? tr('menu.syncDoneFallback'),
      );
      break;
    }
  }
}

export function registerMenuCommand(
  context: vscode.ExtensionContext,
): vscode.Disposable {
  return vscode.commands.registerCommand('mla.menu', async () => {
    const root = projectRoot();
    if (!root) {
      vscode.window.showErrorMessage(tr('menu.noWorkspace'));
      return;
    }
    const flag = readFlag(root);
    const items: MenuItem[] = [
      {
        label: flag === 'on' ? tr('menu.toggleOff') : tr('menu.toggleOn'),
        description: tr('menu.currentState', { state: flag.toUpperCase() }),
        action: 'toggle',
      },
      {
        label: tr('menu.refresh'),
        description: tr('menu.refreshDesc'),
        action: 'refresh',
      },
      {
        label: tr('menu.arch'),
        description: tr('menu.archDesc'),
        action: 'arch',
      },
      {
        label: tr('menu.sync'),
        description: tr('menu.syncDesc'),
        action: 'sync',
      },
      {
        label: tr('menu.reindex'),
        description: tr('menu.reindexDesc'),
        action: 'reindex',
      },
      {
        label: tr('menu.reset'),
        description: tr('menu.resetDesc'),
        action: 'reset',
      },
    ];
    const pick = await vscode.window.showQuickPick(items, {
      placeHolder: tr('menu.placeholder'),
      matchOnDescription: true,
    });
    if (!pick) return;
    try {
      await runAction(pick.action, root);
    } catch (err) {
      vscode.window.showErrorMessage(
        tr('menu.error', {
          action: pick.action,
          message: (err as Error).message,
        }),
      );
    }
  });
}

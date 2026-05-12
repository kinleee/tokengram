import * as cp from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

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
      vscode.window.showInformationMessage(`MLA: ${stdout.trim()}`);
      break;
    }
    case 'refresh': {
      await pythonScript(root, 'hooks/refresh_bar.py');
      vscode.window.showInformationMessage('MLA: status bar refresh triggered');
      break;
    }
    case 'reset': {
      const choice = await vscode.window.showWarningMessage(
        'Savings history-i sıfırlayaq? (köhnə history backup-a köçürüləcək)',
        { modal: true },
        'Reset',
      );
      if (choice !== 'Reset') return;
      const { stdout } = await pythonScript(root, 'hooks/reset_savings.py');
      vscode.window.showInformationMessage(`MLA: ${stdout.trim()}`);
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
          title: 'MLA: ChromaDB re-index (bir-iki dəqiqə çəkə bilər)',
          cancellable: false,
        },
        async () => {
          await execFile('python', ['main.py', 'index', '.', '--fresh'], root);
        },
      );
      vscode.window.showInformationMessage('MLA: re-index tamamlandı');
      break;
    }
    case 'sync': {
      const { stderr } = await pythonScript(root, 'hooks/savings_report.py');
      const summary = stderr.split('\n').find((l) => l.includes('[mla-agent]'));
      vscode.window.showInformationMessage(
        summary ?? 'MLA: sync tamamlandı (yeni hadisə yox idi)',
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
      vscode.window.showErrorMessage('MLA: workspace folder açılmayıb');
      return;
    }
    const flag = readFlag(root);
    const items: MenuItem[] = [
      {
        label:
          flag === 'on'
            ? '$(circle-large-outline) Söndür (OFF)'
            : '$(circle-filled) Yandır (ON)',
        description: `cari: ${flag.toUpperCase()}`,
        action: 'toggle',
      },
      {
        label: '$(refresh) Status bar yenilə',
        description: 'mtime touch — bar dərhal refresh edir',
        action: 'refresh',
      },
      {
        label: '$(book) Arch doc göstər',
        description: '.mla_arch.md yan paneldə',
        action: 'arch',
      },
      {
        label: '$(save) Session log → history (sync)',
        description: 'Stop hook fire olmayıbsa manual çağır',
        action: 'sync',
      },
      {
        label: '$(database) ChromaDB re-index',
        description: 'main.py index . --fresh (60-120 san)',
        action: 'reindex',
      },
      {
        label: '$(trash) Savings history sıfırla',
        description: 'köhnəsi backup-a köçürülür',
        action: 'reset',
      },
    ];
    const pick = await vscode.window.showQuickPick(items, {
      placeHolder: 'MLA komandası seç',
      matchOnDescription: true,
    });
    if (!pick) return;
    try {
      await runAction(pick.action, root);
    } catch (err) {
      vscode.window.showErrorMessage(
        `MLA: ${pick.action} uğursuz — ${(err as Error).message}`,
      );
    }
  });
}

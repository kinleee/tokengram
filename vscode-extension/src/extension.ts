import * as vscode from 'vscode';
import { registerMenuCommand } from './menu';
import { createStatusBar } from './statusBar';

export function activate(context: vscode.ExtensionContext) {
  context.subscriptions.push(registerMenuCommand(context));
  const statusBar = createStatusBar(context);
  context.subscriptions.push(statusBar);
}

export function deactivate() {
  /* nothing to clean up — disposables handled by context */
}

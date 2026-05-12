import * as vscode from 'vscode';
import { createStatusBar } from './statusBar';

export function activate(context: vscode.ExtensionContext) {
  const statusBar = createStatusBar(context);
  context.subscriptions.push(statusBar);
}

export function deactivate() {
  /* nothing to clean up — disposables handled by context */
}

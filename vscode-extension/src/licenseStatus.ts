import * as cp from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';

const MLA_DIR = path.join(os.homedir(), '.mla');
const KEY_FILE = path.join(MLA_DIR, 'license_key.txt');
const SERVER_URL_FILE = path.join(MLA_DIR, 'server_url.txt');
const STATUS_FILE = path.join(MLA_DIR, 'last_check.json');

const RECHECK_INTERVAL_MS = 60 * 60 * 1000; // 1 hour
const STALE_AFTER_MS = 2 * 60 * 60 * 1000; // 2 hours
const HTTP_TIMEOUT_MS = 10_000;

export type EffectiveState = 'valid' | 'invalid' | 'no_key' | 'stale';

export interface CheckResult {
  valid: boolean;
  reason?: string;
  email?: string;
  status?: string;
  expires_at?: number;
  checked_at: number; // unix seconds
}

export function readKey(): string | null {
  try {
    const t = fs.readFileSync(KEY_FILE, 'utf-8').trim();
    return t || null;
  } catch {
    return null;
  }
}

export function readServerUrl(): string | null {
  try {
    const t = fs.readFileSync(SERVER_URL_FILE, 'utf-8').trim();
    if (t) return t.replace(/\/+$/, '');
  } catch {
    /* fall through */
  }
  const fromConfig = vscode.workspace
    .getConfiguration('tokengram')
    .get<string>('licenseServerUrl', '')
    .replace(/\/+$/, '');
  return fromConfig || null;
}

export function readCachedStatus(): CheckResult | null {
  try {
    return JSON.parse(fs.readFileSync(STATUS_FILE, 'utf-8')) as CheckResult;
  } catch {
    return null;
  }
}

function writeCachedStatus(r: CheckResult): void {
  try {
    fs.mkdirSync(MLA_DIR, { recursive: true });
    fs.writeFileSync(STATUS_FILE, JSON.stringify(r, null, 2), 'utf-8');
  } catch {
    /* best effort */
  }
}

export type ActivateOutcome =
  | { ok: true; expires_at: number }
  | { ok: false; reason: 'machine_mismatch'; hint?: string }
  | { ok: false; reason: 'invalid_license' | 'no_active_subscription' }
  | { ok: false; reason: 'network_error'; detail?: string }
  | { ok: false; reason: 'missing_venv' }
  | { ok: false; reason: 'fingerprint_error'; detail?: string }
  | { ok: false; reason: 'unknown'; detail?: string };

const VENV_PYTHON =
  process.platform === 'win32'
    ? path.join(os.homedir(), '.tokengram', 'venv', 'Scripts', 'python.exe')
    : path.join(os.homedir(), '.tokengram', 'venv', 'bin', 'python');

/**
 * Compute the same machine fingerprint that `tokengram.license.machine_fingerprint()`
 * produces in Python. We shell out to the venv interpreter so the two sides are
 * guaranteed to agree — implementing the hash in TypeScript would be a second
 * source of truth that could drift.
 */
export function getMachineFingerprint(): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!fs.existsSync(VENV_PYTHON)) {
      reject(new Error('missing_venv'));
      return;
    }
    cp.execFile(
      VENV_PYTHON,
      ['-c', 'from tokengram import license; print(license.machine_fingerprint())'],
      { encoding: 'utf-8', timeout: HTTP_TIMEOUT_MS },
      (err, stdout, stderr) => {
        if (err) {
          reject(new Error(stderr.trim() || err.message));
          return;
        }
        const fp = stdout.trim();
        if (!/^[0-9a-f]{64}$/.test(fp)) {
          reject(new Error(`unexpected fingerprint format: ${fp.slice(0, 32)}`));
          return;
        }
        resolve(fp);
      },
    );
  });
}

/**
 * Bind this license key to this machine via the license server. The server is
 * authoritative on device binding: 403 here means the key is already attached
 * to a different physical machine and we must NOT save it locally.
 */
export async function activate(
  key: string,
  serverUrl: string,
): Promise<ActivateOutcome> {
  let fingerprint: string;
  try {
    fingerprint = await getMachineFingerprint();
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    if (msg === 'missing_venv') return { ok: false, reason: 'missing_venv' };
    return { ok: false, reason: 'fingerprint_error', detail: msg };
  }

  const url = `${serverUrl.replace(/\/+$/, '')}/activate`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), HTTP_TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        license_key: key,
        machine_fingerprint: fingerprint,
      }),
      signal: controller.signal,
    });
    const body = (await res.json().catch(() => ({}))) as {
      token?: string;
      expires_at?: number;
      error?: string;
      hint?: string;
    };
    if (res.ok && body.expires_at) {
      return { ok: true, expires_at: body.expires_at };
    }
    if (res.status === 403 && body.error === 'machine_mismatch') {
      return { ok: false, reason: 'machine_mismatch', hint: body.hint };
    }
    if (res.status === 401 && body.error === 'invalid_license') {
      return { ok: false, reason: 'invalid_license' };
    }
    if (res.status === 402 && body.error === 'no_active_subscription') {
      return { ok: false, reason: 'no_active_subscription' };
    }
    return {
      ok: false,
      reason: 'unknown',
      detail: `HTTP ${res.status}: ${body.error ?? ''}`,
    };
  } catch (e: unknown) {
    const detail = e instanceof Error ? e.message : String(e);
    return { ok: false, reason: 'network_error', detail };
  } finally {
    clearTimeout(timer);
  }
}

export async function checkKey(key: string, serverUrl: string): Promise<CheckResult> {
  const url = `${serverUrl.replace(/\/+$/, '')}/check-key`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), HTTP_TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ license_key: key }),
      signal: controller.signal,
    });
    const body = (await res.json().catch(() => ({}))) as Partial<CheckResult>;
    return {
      valid: !!body.valid,
      reason: body.reason,
      email: body.email,
      status: body.status,
      expires_at: body.expires_at,
      checked_at: Math.floor(Date.now() / 1000),
    };
  } catch (e: unknown) {
    const reason = e instanceof Error ? e.name : 'network_error';
    return {
      valid: false,
      reason: `network_error:${reason}`,
      checked_at: Math.floor(Date.now() / 1000),
    };
  } finally {
    clearTimeout(timer);
  }
}

/** Refreshes the cached status. Network errors preserve the previous "valid" cache. */
export async function refreshStatus(): Promise<CheckResult> {
  const key = readKey();
  if (!key) {
    const r: CheckResult = {
      valid: false,
      reason: 'no_key',
      checked_at: Math.floor(Date.now() / 1000),
    };
    writeCachedStatus(r);
    return r;
  }
  const serverUrl = readServerUrl();
  if (!serverUrl) {
    const r: CheckResult = {
      valid: false,
      reason: 'no_server_url',
      checked_at: Math.floor(Date.now() / 1000),
    };
    writeCachedStatus(r);
    return r;
  }
  const fresh = await checkKey(key, serverUrl);
  // On network error, don't clobber a previously-valid cache: that would force
  // an offline user into "NO KEY" the moment WiFi blinks. Keep the old result
  // unless it's also too old to trust.
  if (fresh.reason?.startsWith('network_error')) {
    const cached = readCachedStatus();
    if (cached && cached.valid) {
      return cached;
    }
  }
  writeCachedStatus(fresh);
  return fresh;
}

/** What should the UI show right now, based on the cached status. Cheap (no I/O beyond reading files). */
export function effectiveStatus(): EffectiveState {
  if (!readKey()) return 'no_key';
  const cached = readCachedStatus();
  if (!cached) return 'stale';
  const ageMs = Date.now() - cached.checked_at * 1000;
  if (ageMs > STALE_AFTER_MS) return 'stale';
  return cached.valid ? 'valid' : 'invalid';
}

/** Start the periodic recheck timer. Returns a Disposable that clears it. */
export function startPeriodicRecheck(
  onChange?: (r: CheckResult) => void,
): vscode.Disposable {
  let stopped = false;
  const tick = async () => {
    if (stopped) return;
    const r = await refreshStatus();
    if (onChange) onChange(r);
  };
  // Fire immediately so the user doesn't wait an hour after install.
  tick();
  const handle = setInterval(tick, RECHECK_INTERVAL_MS);
  return {
    dispose: () => {
      stopped = true;
      clearInterval(handle);
    },
  };
}

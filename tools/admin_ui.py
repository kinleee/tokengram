"""
Tokengram Admin UI — local web tool for managing license keys.

Run:
    python tools/admin_ui.py

Opens http://127.0.0.1:8765 in your browser.

Config: ~/.tokengram/admin_config.json
    {
      "server_url": "https://mla-license-server-production.....workers.dev",
      "admin_token": "<token set via wrangler secret put ADMIN_TOKEN>"
    }
"""
from __future__ import annotations

import json
import os
import sys
import webbrowser
from pathlib import Path
from typing import Optional

try:
    import requests
    from flask import Flask, jsonify, render_template_string, request
except ImportError:
    sys.stderr.write(
        "Missing deps. Install: pip install flask requests\n"
    )
    sys.exit(1)

# Windows-da default cp1252-dir, Unicode console output sındırır.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


CONFIG_DIR = Path.home() / ".tokengram"
CONFIG_FILE = CONFIG_DIR / "admin_config.json"
DEFAULT_PORT = 8765


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def first_run_setup() -> dict:
    """Interactive console prompt when config missing."""
    print("=" * 60)
    print("Tokengram Admin UI — first-run setup")
    print("=" * 60)
    print("\nThis tool talks to your Cloudflare Worker. You need:")
    print("  1) The worker URL (https://...workers.dev)")
    print("  2) ADMIN_TOKEN (set via: wrangler secret put ADMIN_TOKEN)")
    print()
    server_url = input("Worker URL: ").strip().rstrip("/")
    admin_token = input("ADMIN_TOKEN: ").strip()
    if not server_url or not admin_token:
        print("Both fields required. Aborting.")
        sys.exit(1)
    cfg = {"server_url": server_url, "admin_token": admin_token}
    save_config(cfg)
    print(f"\nSaved to {CONFIG_FILE}\n")
    return cfg


CFG: dict = {}


def admin_headers() -> dict:
    return {
        "X-Admin-Token": CFG["admin_token"],
        "Content-Type": "application/json",
    }


def server(path: str) -> str:
    return CFG["server_url"].rstrip("/") + path


app = Flask(__name__)


@app.route("/")
def index() -> str:
    return render_template_string(PAGE_HTML, server_url=CFG.get("server_url", ""))


@app.route("/api/keys", methods=["GET"])
def list_keys():
    try:
        r = requests.get(server("/admin/keys"), headers=admin_headers(), timeout=15)
        return (r.text, r.status_code, {"content-type": "application/json"})
    except requests.RequestException as e:
        return jsonify({"error": "network", "detail": str(e)}), 502


@app.route("/api/keys", methods=["POST"])
def create_key():
    body = request.get_json(silent=True) or {}
    try:
        r = requests.post(server("/admin/keys"), headers=admin_headers(), json=body, timeout=15)
        return (r.text, r.status_code, {"content-type": "application/json"})
    except requests.RequestException as e:
        return jsonify({"error": "network", "detail": str(e)}), 502


@app.route("/api/keys/<key>", methods=["PATCH"])
def patch_key(key: str):
    body = request.get_json(silent=True) or {}
    try:
        r = requests.patch(server(f"/admin/keys/{key}"), headers=admin_headers(), json=body, timeout=15)
        return (r.text, r.status_code, {"content-type": "application/json"})
    except requests.RequestException as e:
        return jsonify({"error": "network", "detail": str(e)}), 502


@app.route("/api/keys/<key>", methods=["DELETE"])
def delete_key(key: str):
    try:
        r = requests.delete(server(f"/admin/keys/{key}"), headers=admin_headers(), timeout=15)
        return (r.text, r.status_code, {"content-type": "application/json"})
    except requests.RequestException as e:
        return jsonify({"error": "network", "detail": str(e)}), 502


PAGE_HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Tokengram — Admin</title>
<style>
  :root {
    --bg: #0f1115;
    --panel: #181a21;
    --border: #2a2d36;
    --text: #e4e6ea;
    --muted: #8a8f9a;
    --accent: #7aa2f7;
    --ok: #9ece6a;
    --warn: #e0af68;
    --err: #f7768e;
    --row-hover: #1e2129;
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--text);
    margin: 0; padding: 24px;
  }
  h1 { margin: 0 0 4px 0; font-size: 1.6em; }
  .sub { color: var(--muted); margin-bottom: 24px; font-size: 0.9em; }
  .panel {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 8px; padding: 18px; margin-bottom: 20px;
  }
  .panel h2 { margin: 0 0 14px 0; font-size: 1.05em; font-weight: 600; }
  form.create {
    display: grid; grid-template-columns: 2fr 1fr 1fr auto; gap: 10px; align-items: end;
  }
  label { display: block; font-size: 0.8em; color: var(--muted); margin-bottom: 4px; }
  input, select {
    background: #0d0f14; color: var(--text); border: 1px solid var(--border);
    padding: 8px 10px; border-radius: 5px; width: 100%; font-size: 0.95em;
  }
  input:focus, select:focus { outline: 1px solid var(--accent); border-color: var(--accent); }
  button {
    background: var(--accent); color: #0f1115; border: 0;
    padding: 9px 16px; border-radius: 5px; font-weight: 600; cursor: pointer;
    font-size: 0.9em;
  }
  button:hover { filter: brightness(1.1); }
  button.ghost { background: transparent; color: var(--text); border: 1px solid var(--border); }
  button.ghost:hover { background: var(--row-hover); }
  button.danger { background: var(--err); color: #fff; }
  button.warn { background: var(--warn); color: #0f1115; }
  table { width: 100%; border-collapse: collapse; font-size: 0.88em; }
  th { text-align: left; padding: 10px 8px; color: var(--muted); border-bottom: 1px solid var(--border); font-weight: 500; font-size: 0.8em; text-transform: uppercase; letter-spacing: 0.05em; }
  td { padding: 10px 8px; border-bottom: 1px solid var(--border); }
  tr:hover td { background: var(--row-hover); }
  .key { font-family: ui-monospace, "Cascadia Code", monospace; font-size: 0.85em; }
  .status-active { color: var(--ok); }
  .status-revoked { color: var(--err); }
  .status-expired { color: var(--warn); }
  .status-cancelled { color: var(--muted); }
  .actions { display: flex; gap: 6px; }
  .actions button { padding: 5px 10px; font-size: 0.8em; }
  .toast {
    position: fixed; bottom: 24px; right: 24px;
    background: var(--panel); border: 1px solid var(--border);
    padding: 12px 18px; border-radius: 6px; max-width: 400px;
    transition: opacity 0.3s; opacity: 0;
  }
  .toast.show { opacity: 1; }
  .toast.ok { border-color: var(--ok); }
  .toast.err { border-color: var(--err); }
  .new-key {
    background: #1d2616; border: 1px solid var(--ok); padding: 14px;
    border-radius: 6px; margin-top: 14px; font-family: ui-monospace, monospace;
    display: flex; align-items: center; gap: 10px;
  }
  .new-key .k { color: var(--ok); flex: 1; word-break: break-all; }
  .truncated { color: var(--muted); cursor: help; }
  .empty { text-align: center; padding: 40px; color: var(--muted); }
</style>
</head>
<body>
  <h1>🔑 Tokengram — License Admin</h1>
  <div class="sub">Worker: <code>{{ server_url }}</code></div>

  <div class="panel">
    <h2>Create new key</h2>
    <form class="create" id="createForm">
      <div>
        <label>Email</label>
        <input type="email" id="email" placeholder="tester@example.com" required>
      </div>
      <div>
        <label>Duration (days)</label>
        <input type="number" id="duration" value="365" min="1" max="3650">
      </div>
      <div>
        <label>Plan</label>
        <select id="plan">
          <option value="alpha">alpha</option>
          <option value="pro_monthly">pro_monthly</option>
          <option value="lifetime">lifetime</option>
        </select>
      </div>
      <button type="submit">Generate</button>
    </form>
    <div id="newKey"></div>
  </div>

  <div class="panel">
    <h2>All keys (<span id="count">…</span>)</h2>
    <div id="tableWrap"><div class="empty">Loading…</div></div>
  </div>

  <div class="toast" id="toast"></div>

<script>
const fmt = (ts) => ts ? new Date(ts * 1000).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' }) : '—';
const fmtDate = (ts) => ts ? new Date(ts * 1000).toISOString().slice(0, 10) : '—';

function toast(msg, kind) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show ' + (kind || 'ok');
  setTimeout(() => { el.className = 'toast ' + (kind || 'ok'); }, 3500);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = { raw: text }; }
  if (!res.ok) throw new Error(data.error || data.detail || ('HTTP ' + res.status));
  return data;
}

function statusLabel(row) {
  if (row.revoked) return ['REVOKED', 'status-revoked'];
  if (row.expired) return ['EXPIRED', 'status-expired'];
  if (row.sub_status === 'cancelled') return ['CANCELLED', 'status-cancelled'];
  if (row.sub_status === 'active' || row.sub_status === 'trialing') return ['ACTIVE', 'status-active'];
  return [row.sub_status || 'unknown', 'status-cancelled'];
}

async function loadTable() {
  const wrap = document.getElementById('tableWrap');
  try {
    const data = await api('/api/keys');
    document.getElementById('count').textContent = data.count;
    if (!data.keys.length) {
      wrap.innerHTML = '<div class="empty">No keys yet. Create one above.</div>';
      return;
    }
    let html = '<table><thead><tr>'
      + '<th>Email</th><th>Key</th><th>Plan</th><th>Status</th><th>Expires</th><th>Machine</th><th>Actions</th>'
      + '</tr></thead><tbody>';
    for (const r of data.keys) {
      const [label, cls] = statusLabel(r);
      const machine = r.machine_bound ? `<span class="truncated" title="${r.machine_fingerprint || ''}">bound</span>` : '<span class="truncated">—</span>';
      const canDeactivate = !r.revoked;
      const canActivate = r.revoked;
      html += `<tr>
        <td>${r.email}</td>
        <td class="key">${r.license_key.slice(0, 16)}…<button class="ghost" style="margin-left:6px;padding:2px 8px;font-size:0.75em" onclick="copyKey('${r.license_key}')">copy</button></td>
        <td>${r.plan || '—'}</td>
        <td class="${cls}">${label}</td>
        <td>${fmtDate(r.expires_at)}</td>
        <td>${machine}</td>
        <td class="actions">
          ${canDeactivate ? `<button class="warn" onclick="act('${r.license_key}','deactivate')">deactivate</button>` : ''}
          ${canActivate ? `<button onclick="act('${r.license_key}','activate')">activate</button>` : ''}
          <button class="ghost" onclick="extend('${r.license_key}')">+30d</button>
          ${r.machine_bound ? `<button class="ghost" onclick="act('${r.license_key}','unbind')">unbind</button>` : ''}
        </td>
      </tr>`;
    }
    html += '</tbody></table>';
    wrap.innerHTML = html;
  } catch (e) {
    wrap.innerHTML = '<div class="empty" style="color:var(--err)">Error: ' + e.message + '</div>';
  }
}

async function act(key, action) {
  if (action === 'deactivate' && !confirm('Deactivate this license? User will be blocked on next tool call.')) return;
  try {
    await api('/api/keys/' + encodeURIComponent(key), {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ action }),
    });
    toast(action + ' OK', 'ok');
    loadTable();
  } catch (e) { toast(e.message, 'err'); }
}

async function extend(key) {
  const days = parseInt(prompt('Extend by how many days?', '30'), 10);
  if (!days || days < 1) return;
  try {
    await api('/api/keys/' + encodeURIComponent(key), {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ action: 'extend', days }),
    });
    toast('Extended by ' + days + ' days', 'ok');
    loadTable();
  } catch (e) { toast(e.message, 'err'); }
}

function copyKey(k) {
  navigator.clipboard.writeText(k).then(() => toast('Copied: ' + k.slice(0, 24) + '…', 'ok'));
}

document.getElementById('createForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = document.getElementById('email').value.trim();
  const duration = parseInt(document.getElementById('duration').value, 10);
  const plan = document.getElementById('plan').value;
  try {
    const data = await api('/api/keys', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ email, duration_days: duration, plan }),
    });
    const expires = fmtDate(data.expires_at);
    document.getElementById('newKey').innerHTML = `
      <div class="new-key">
        <div>
          <div style="color:var(--muted);font-size:0.8em">Generated for <b>${data.email}</b> · valid until ${expires}</div>
          <div class="k">${data.license_key}</div>
        </div>
        <button onclick="copyKey('${data.license_key}')">Copy</button>
      </div>`;
    document.getElementById('email').value = '';
    loadTable();
  } catch (e) { toast(e.message, 'err'); }
});

loadTable();
setInterval(loadTable, 30000);
</script>
</body>
</html>
"""


def main() -> int:
    global CFG
    CFG = load_config()
    if not CFG.get("server_url") or not CFG.get("admin_token"):
        CFG = first_run_setup()

    port = int(os.environ.get("TOKENGRAM_ADMIN_PORT", DEFAULT_PORT))
    url = f"http://127.0.0.1:{port}"
    print(f"\nTokengram Admin UI → {url}")
    print(f"Worker: {CFG['server_url']}")
    print("Press Ctrl+C to stop.\n")

    if "--no-browser" not in sys.argv:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    app.run(host="127.0.0.1", port=port, debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

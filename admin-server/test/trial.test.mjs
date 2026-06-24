// /trial endpoint + S5 geriyə-uyğunluq testi (A1 — launch plan).
//
// Run:  cd admin-server && node test/trial.test.mjs
//
// Real server.js prosesini müvəqqəti DB + efemer RSA açarları ilə qaldırır:
//   1.  POST /trial (yeni fingerprint)  → 200, mla_trial_ açar, ~30 gün
//   2.  POST /trial (eyni fingerprint)  → 200, EYNİ açar (reinstall halı)
//   3.  /validate trial tokeni ilə      → 200 (refresh işləyir)
//   4.  Trial vaxtı keçdikdən sonra:
//         /trial    → 403 trial_expired   (lokal fayl silmək reset vermir)
//         /validate → 401                 (bitmiş abunə refresh ala bilməz)
//   5.  S5 compat: köhnə client axını (admin açar → /activate → /validate)
//       yeni serverlə dəyişməz işləyir; cavab forması köhnə sahələri saxlayır.
//   6.  /check-key bitmiş trial açarı üçün no_active_subscription qaytarır
//       (extension trial_expired state-i bunun üstündə qurulub).

import { spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SERVER_DIR = path.join(__dirname, '..');
const require = createRequire(path.join(SERVER_DIR, 'package.json'));
const Database = require('better-sqlite3');

const PORT = 3979;
const BASE = `http://127.0.0.1:${PORT}`;
const ADMIN_TOKEN = 'test-admin-token';
const FP_A = 'a'.repeat(64);
const FP_B = 'b'.repeat(64);

let passed = 0;
let failed = 0;
function check(name, cond, detail = '') {
  if (cond) {
    passed++;
    console.log(`  ok   ${name}`);
  } else {
    failed++;
    console.log(`  FAIL ${name} ${detail}`);
  }
}

async function post(p, body, headers = {}) {
  const res = await fetch(`${BASE}${p}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...headers },
    body: JSON.stringify(body ?? {}),
  });
  return { status: res.status, body: await res.json().catch(() => ({})) };
}

async function main() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'tg-trial-test-'));
  const dbPath = path.join(tmp, 'test.db');

  // Efemer RSA cütü — server PKCS8 private + SPKI public PEM gözləyir.
  const { privateKey, publicKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
  const privPem = path.join(tmp, 'priv.pem');
  const pubPem = path.join(tmp, 'pub.pem');
  fs.writeFileSync(privPem, privateKey.export({ type: 'pkcs8', format: 'pem' }));
  fs.writeFileSync(pubPem, publicKey.export({ type: 'spki', format: 'pem' }));

  const server = spawn(process.execPath, ['server.js'], {
    cwd: SERVER_DIR,
    env: {
      ...process.env,
      PORT: String(PORT),
      DB_PATH: dbPath,
      JWT_PRIVATE_KEY_PATH: privPem,
      JWT_PUBLIC_KEY_PATH: pubPem,
      ADMIN_TOKEN,
      SESSION_SECRET: 'test-secret',
      TRIAL_DAYS: '30',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let serverLog = '';
  server.stdout.on('data', (d) => (serverLog += d));
  server.stderr.on('data', (d) => (serverLog += d));

  try {
    // Health gözlə (max ~10s)
    let up = false;
    for (let i = 0; i < 50; i++) {
      try {
        const r = await fetch(`${BASE}/health`);
        if (r.ok) { up = true; break; }
      } catch { /* hələ qalxır */ }
      await new Promise((r) => setTimeout(r, 200));
    }
    if (!up) throw new Error(`server qalxmadı:\n${serverLog}`);

    const now = Math.floor(Date.now() / 1000);

    // ---- 1. Yeni trial ----
    const t1 = await post('/trial', { machine_fingerprint: FP_A });
    check('yeni trial → 200', t1.status === 200, `status=${t1.status} ${JSON.stringify(t1.body)}`);
    check('açar mla_trial_ prefiksli', String(t1.body.license_key || '').startsWith('mla_trial_'));
    check('token verilir', typeof t1.body.token === 'string' && t1.body.token.split('.').length === 3);
    const endsIn = (t1.body.trial_ends_at ?? 0) - now;
    check('trial ~30 gün', endsIn > 29.9 * 86400 && endsIn < 30.1 * 86400, `endsIn=${endsIn}`);
    const claims1 = JSON.parse(Buffer.from(t1.body.token.split('.')[1], 'base64url').toString());
    check('claims: trialing + period_end', claims1.subscription_status === 'trialing' && claims1.period_end === t1.body.trial_ends_at);

    // ---- 2. Eyni fingerprint yenidən (reinstall) ----
    const t2 = await post('/trial', { machine_fingerprint: FP_A });
    check('təkrar /trial → 200 + EYNİ açar', t2.status === 200 && t2.body.license_key === t1.body.license_key);

    // ---- 3. Trial tokeni /validate ilə refresh olunur ----
    const v1 = await fetch(`${BASE}/validate`, {
      method: 'POST',
      headers: { authorization: `Bearer ${t1.body.token}` },
    });
    const v1body = await v1.json();
    check('/validate trial tokeni → 200', v1.status === 200, `status=${v1.status}`);
    check('refresh cavabı köhnə forma (token+expires_at)', !!v1body.token && !!v1body.expires_at);

    // ---- 4. Trial bitmiş kimi simulyasiya et ----
    const db = new Database(dbPath);
    db.prepare("UPDATE subscriptions SET current_period_end = ? WHERE plan = 'trial'").run(now - 10);
    db.close();

    const t3 = await post('/trial', { machine_fingerprint: FP_A });
    check('bitmiş trial → 403 trial_expired', t3.status === 403 && t3.body.error === 'trial_expired',
      `status=${t3.status} ${JSON.stringify(t3.body)}`);

    const v2 = await fetch(`${BASE}/validate`, {
      method: 'POST',
      headers: { authorization: `Bearer ${t1.body.token}` },
    });
    check('bitmiş trial /validate → 401', v2.status === 401, `status=${v2.status}`);

    // ---- 5. S5 compat: köhnə client axını yeni serverlə ----
    const adminKey = await post(
      '/admin/keys',
      { email: 'tester@example.com', plan: 'alpha', duration_days: 365 },
      { 'x-admin-token': ADMIN_TOKEN },
    );
    check('admin açar yaradılır', adminKey.status === 200 && !!adminKey.body.license_key,
      `status=${adminKey.status}`);

    const act = await post('/activate', {
      license_key: adminKey.body.license_key,
      machine_fingerprint: FP_B,
    });
    check('/activate köhnə axın → 200', act.status === 200, `status=${act.status} ${JSON.stringify(act.body)}`);
    check('activate cavabı köhnə forma (token+expires_at)', !!act.body.token && !!act.body.expires_at);
    const claims2 = JSON.parse(Buffer.from(act.body.token.split('.')[1], 'base64url').toString());
    check('alpha claims: active + period_end əlavə (köhnə client üçün zərərsiz)',
      claims2.subscription_status === 'active' && typeof claims2.period_end === 'number');

    const v3 = await fetch(`${BASE}/validate`, {
      method: 'POST',
      headers: { authorization: `Bearer ${act.body.token}` },
    });
    check('alpha açar /validate → 200', v3.status === 200, `status=${v3.status}`);

    // ---- 6. /check-key bitmiş trial → no_active_subscription ----
    const ck = await post('/check-key', { license_key: t1.body.license_key });
    check('/check-key bitmiş trial → 402 no_active_subscription',
      ck.status === 402 && ck.body.reason === 'no_active_subscription',
      `status=${ck.status} ${JSON.stringify(ck.body)}`);

    console.log(`\n${passed} passed, ${failed} failed`);
    process.exitCode = failed === 0 ? 0 : 1;
  } catch (e) {
    console.error('TEST CRASH:', e);
    process.exitCode = 1;
  } finally {
    server.kill();
    try { fs.rmSync(tmp, { recursive: true, force: true }); } catch { /* WAL faylı gecikə bilər */ }
  }
}

main();

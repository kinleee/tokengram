import { Hono } from 'hono';
import { SignJWT, importPKCS8, importSPKI, jwtVerify } from 'jose';

type Env = {
  DB: D1Database;
  CACHE: KVNamespace;
  JWT_PRIVATE_KEY: string;
  JWT_PUBLIC_KEY: string;
  POLAR_WEBHOOK_SECRET: string;
  POLAR_API_KEY: string;
  ADMIN_TOKEN: string;
  ENVIRONMENT: string;
};

const app = new Hono<{ Bindings: Env }>();

const JWT_TTL_SECONDS = 7 * 24 * 60 * 60;

// Polar.sh status → bizim DB status mapping
const POLAR_STATUS_MAP: Record<string, string> = {
  trialing: 'trialing',
  active: 'active',
  past_due: 'past_due',
  canceled: 'cancelled',
  cancelled: 'cancelled',
  incomplete: 'incomplete',
  incomplete_expired: 'cancelled',
  unpaid: 'past_due',
};

app.get('/', (c) => c.text('Tokengram License Server — OK'));

// ============================================================
// GET /pubkey
// JWT verify üçün public key — setup wizard onu yükləyir.
// ============================================================
app.get('/pubkey', (c) => {
  if (!c.env.JWT_PUBLIC_KEY) {
    return c.text('JWT_PUBLIC_KEY not configured', 500);
  }
  return c.text(c.env.JWT_PUBLIC_KEY, 200, { 'content-type': 'application/x-pem-file' });
});

// ============================================================
// POST /check-key
// Setup wizard üçün lightweight key validation — yalnız "key etibarlıdırmı?"
// Fingerprint binding etmir, JWT verməz. Real activation MCP server-də olur.
// ============================================================
app.post('/check-key', async (c) => {
  const body = await c.req.json<{ license_key?: string }>().catch(() => ({} as { license_key?: string }));
  const key = (body.license_key ?? '').trim();
  if (!key) return c.json({ valid: false, reason: 'missing_key' }, 400);

  const row = await c.env.DB.prepare(
    `SELECT l.revoked, u.email, s.status, s.current_period_end
     FROM licenses l
     JOIN users u ON u.id = l.user_id
     LEFT JOIN subscriptions s ON s.user_id = l.user_id
       AND s.status IN ('active', 'trialing')
       AND s.current_period_end > ?
     WHERE l.key = ?
     ORDER BY s.current_period_end DESC LIMIT 1`,
  )
    .bind(Math.floor(Date.now() / 1000), key)
    .first<{ revoked: number; email: string; status: string | null; current_period_end: number | null }>();

  if (!row) return c.json({ valid: false, reason: 'not_found' }, 404);
  if (row.revoked) return c.json({ valid: false, reason: 'revoked' }, 401);
  if (!row.status) return c.json({ valid: false, reason: 'no_active_subscription' }, 402);

  return c.json({
    valid: true,
    email: row.email,
    status: row.status,
    expires_at: row.current_period_end,
  });
});

// ============================================================
// POST /activate
// Extension license_key + machine_fingerprint göndərir,
// active subscription tapırsa JWT qaytarır.
// ============================================================
app.post('/activate', async (c) => {
  const body = await c.req.json<{
    license_key: string;
    machine_fingerprint: string;
  }>();

  if (!body.license_key || !body.machine_fingerprint) {
    return c.json({ error: 'missing_fields' }, 400);
  }

  // 1. License-ni tap
  const license = await c.env.DB.prepare(
    'SELECT key, user_id, machine_fingerprint, revoked FROM licenses WHERE key = ?'
  )
    .bind(body.license_key)
    .first<{ key: string; user_id: string; machine_fingerprint: string | null; revoked: number }>();

  if (!license || license.revoked) {
    return c.json({ error: 'invalid_license' }, 401);
  }

  // 2. Subscription aktivdirmi?
  const sub = await c.env.DB.prepare(
    `SELECT status, current_period_end FROM subscriptions
     WHERE user_id = ? AND status IN ('active', 'trialing')
     ORDER BY current_period_end DESC LIMIT 1`
  )
    .bind(license.user_id)
    .first<{ status: string; current_period_end: number }>();

  if (!sub) {
    return c.json({ error: 'no_active_subscription' }, 402);
  }

  // 3. Machine fingerprint binding
  if (license.machine_fingerprint && license.machine_fingerprint !== body.machine_fingerprint) {
    return c.json(
      { error: 'machine_mismatch', hint: 'License is bound to another machine. Use /deactivate first.' },
      403
    );
  }
  if (!license.machine_fingerprint) {
    await c.env.DB.prepare(
      'UPDATE licenses SET machine_fingerprint = ?, activated_at = ? WHERE key = ?'
    )
      .bind(body.machine_fingerprint, Math.floor(Date.now() / 1000), body.license_key)
      .run();
  }

  // 4. JWT yarad
  const token = await issueToken(c.env, {
    user_id: license.user_id,
    license_key: license.key,
    fingerprint: body.machine_fingerprint,
    subscription_status: sub.status,
  });

  return c.json({
    token,
    expires_at: Math.floor(Date.now() / 1000) + JWT_TTL_SECONDS,
  });
});

// ============================================================
// POST /validate
// Mövcud token-i yeniləyir (subscription hələ aktivdirsə).
// ============================================================
app.post('/validate', async (c) => {
  // Bu endpoint öncəki token-i RE-issue edir.
  // Köhnə token SIGNATURE doğrulanmalı (issuer biz olmuşuq), lakin EXPIRY
  // ignore olunur — expired refresh halal use-case-dir. Signature olmasa
  // istənilən şəxs sırf base64 payload qoyub yeni JWT ala bilərdi.
  const authHeader = c.req.header('Authorization');
  if (!authHeader?.startsWith('Bearer ')) {
    return c.json({ error: 'missing_token' }, 401);
  }
  const oldToken = authHeader.slice(7);

  if (!c.env.JWT_PUBLIC_KEY) {
    return c.json({ error: 'server_misconfigured' }, 500);
  }

  let claims: { user_id?: string; fingerprint?: string; license_key?: string };
  try {
    const publicKey = await importSPKI(c.env.JWT_PUBLIC_KEY, 'RS256');
    // currentDate çox uzaq keçmişə qoyularaq expired token qəbul olunur,
    // amma signature və issuer hələ yoxlanılır.
    const verified = await jwtVerify(oldToken, publicKey, {
      algorithms: ['RS256'],
      issuer: 'mla-license-server',
      currentDate: new Date(0),
    });
    claims = verified.payload as typeof claims;
  } catch (e) {
    return c.json({ error: 'invalid_token_signature' }, 401);
  }

  if (!claims.user_id || !claims.fingerprint || !claims.license_key) {
    return c.json({ error: 'malformed_claims' }, 400);
  }

  // DB-də subscription-u yenidən yoxla
  const sub = await c.env.DB.prepare(
    `SELECT status FROM subscriptions
     WHERE user_id = ? AND status IN ('active', 'trialing')
     ORDER BY current_period_end DESC LIMIT 1`
  )
    .bind(claims.user_id)
    .first<{ status: string }>();

  if (!sub) {
    return c.json({ error: 'subscription_inactive' }, 401);
  }

  // License hələ də həmin machine-ə bağlıdır?
  const license = await c.env.DB.prepare(
    'SELECT machine_fingerprint, revoked FROM licenses WHERE key = ?'
  )
    .bind(claims.license_key)
    .first<{ machine_fingerprint: string | null; revoked: number }>();

  if (!license || license.revoked || license.machine_fingerprint !== claims.fingerprint) {
    return c.json({ error: 'license_revoked' }, 401);
  }

  // Yeni token issue et
  const token = await issueToken(c.env, {
    user_id: claims.user_id,
    license_key: claims.license_key,
    fingerprint: claims.fingerprint,
    subscription_status: sub.status,
  });

  return c.json({
    token,
    expires_at: Math.floor(Date.now() / 1000) + JWT_TTL_SECONDS,
  });
});

// ============================================================
// POST /webhook/polar
// Polar.sh subscription event-lərini qəbul edir.
// ============================================================
app.post('/webhook/polar', async (c) => {
  const signature = c.req.header('webhook-signature');
  const timestamp = c.req.header('webhook-timestamp');
  const webhookId = c.req.header('webhook-id');
  const rawBody = await c.req.text();

  if (!signature || !timestamp || !webhookId) {
    return c.json({ error: 'missing_signature_headers' }, 401);
  }

  const valid = await verifyPolarSignature(
    webhookId,
    timestamp,
    rawBody,
    signature,
    c.env.POLAR_WEBHOOK_SECRET,
  );
  if (!valid) {
    return c.json({ error: 'invalid_signature' }, 401);
  }

  // Anti-replay: 5 dəq köhnəlik
  const ts = parseInt(timestamp, 10);
  if (Math.abs(Math.floor(Date.now() / 1000) - ts) > 300) {
    return c.json({ error: 'stale_timestamp' }, 401);
  }

  const event = JSON.parse(rawBody) as {
    id: string;
    type: string;
    data: any;
  };

  // Idempotency check
  const seen = await c.env.DB.prepare('SELECT 1 FROM webhook_events WHERE event_id = ?')
    .bind(event.id)
    .first();
  if (seen) {
    return c.json({ status: 'duplicate' });
  }

  switch (event.type) {
    case 'subscription.created':
    case 'subscription.updated':
      await upsertSubscription(c.env, event.data);
      break;
    case 'subscription.cancelled':
      await cancelSubscription(c.env, event.data);
      break;
    default:
      // log + ignore
      break;
  }

  await c.env.DB.prepare('INSERT INTO webhook_events (event_id, processed_at) VALUES (?, ?)')
    .bind(event.id, Math.floor(Date.now() / 1000))
    .run();

  return c.json({ status: 'ok' });
});

// ============================================================
// Helpers
// ============================================================
async function issueToken(env: Env, claims: Record<string, any>): Promise<string> {
  const privateKey = await importPKCS8(env.JWT_PRIVATE_KEY, 'RS256');
  return await new SignJWT(claims)
    .setProtectedHeader({ alg: 'RS256' })
    .setIssuedAt()
    .setExpirationTime(`${JWT_TTL_SECONDS}s`)
    .setIssuer('mla-license-server')
    .sign(privateKey);
}

async function upsertSubscription(env: Env, data: any) {
  // Polar.sh subscription event data sxemasından lazımi sahələri çıxar.
  // Sənəd: https://docs.polar.sh/api-reference/webhooks/subscription-created
  const now = Math.floor(Date.now() / 1000);
  const polarCustomerId = data.customer?.id ?? data.user?.id;
  const email = data.customer?.email ?? data.user?.email;
  const polarSubId = data.id;
  const status = POLAR_STATUS_MAP[data.status] ?? 'incomplete';
  const periodEnd = data.current_period_end
    ? Math.floor(new Date(data.current_period_end).getTime() / 1000)
    : now + 30 * 24 * 60 * 60;
  const plan = data.product?.id ?? data.price?.id ?? 'pro_monthly';

  if (!email || !polarSubId) {
    throw new Error('missing_required_fields: email or subscription id');
  }

  // 1. User upsert (email ilə)
  const userId = await ensureUser(env, email, polarCustomerId, now);

  // 2. Subscription upsert
  await env.DB.prepare(
    `INSERT INTO subscriptions
       (id, user_id, polar_subscription_id, status, current_period_end, plan, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(polar_subscription_id) DO UPDATE SET
       status = excluded.status,
       current_period_end = excluded.current_period_end,
       updated_at = excluded.updated_at`,
  )
    .bind(crypto.randomUUID(), userId, polarSubId, status, periodEnd, plan, now, now)
    .run();

  // 3. License key (yalnız ilk dəfə subscription yaradılanda)
  const existing = await env.DB.prepare(
    'SELECT key FROM licenses WHERE user_id = ? AND revoked = 0 LIMIT 1',
  )
    .bind(userId)
    .first<{ key: string }>();
  if (!existing && (status === 'active' || status === 'trialing')) {
    const licenseKey = generateLicenseKey();
    await env.DB.prepare(
      'INSERT INTO licenses (key, user_id, created_at) VALUES (?, ?, ?)',
    )
      .bind(licenseKey, userId, now)
      .run();
    // TODO: Resend ilə welcome email göndər, license_key-i daxil et
  }
}

async function ensureUser(
  env: Env,
  email: string,
  polarCustomerId: string | undefined,
  now: number,
): Promise<string> {
  const existing = await env.DB.prepare('SELECT id FROM users WHERE email = ?')
    .bind(email)
    .first<{ id: string }>();
  if (existing) {
    if (polarCustomerId) {
      await env.DB.prepare('UPDATE users SET polar_customer_id = ? WHERE id = ?')
        .bind(polarCustomerId, existing.id)
        .run();
    }
    return existing.id;
  }
  const id = crypto.randomUUID();
  await env.DB.prepare(
    'INSERT INTO users (id, email, polar_customer_id, created_at) VALUES (?, ?, ?, ?)',
  )
    .bind(id, email, polarCustomerId ?? null, now)
    .run();
  return id;
}

async function cancelSubscription(env: Env, data: any) {
  const now = Math.floor(Date.now() / 1000);
  await env.DB.prepare(
    `UPDATE subscriptions SET status = 'cancelled', updated_at = ?
     WHERE polar_subscription_id = ?`,
  )
    .bind(now, data.id)
    .run();
}

// Polar.sh webhook imzasını verify edir (Standard Webhooks spec).
// Format: "v1,base64sig v1,base64sig2 ..." — biri uyğun gəlsə kifayətdir.
async function verifyPolarSignature(
  webhookId: string,
  timestamp: string,
  body: string,
  signatureHeader: string,
  secret: string,
): Promise<boolean> {
  // Polar secret bəzən "whsec_" prefix-i ilə gəlir
  const rawSecret = secret.startsWith('whsec_')
    ? base64UrlDecode(secret.slice(6))
    : new TextEncoder().encode(secret);

  const toSign = `${webhookId}.${timestamp}.${body}`;
  const key = await crypto.subtle.importKey(
    'raw',
    rawSecret,
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(toSign));
  const expected = base64Encode(new Uint8Array(sig));

  return signatureHeader
    .split(' ')
    .map((s) => s.trim())
    .some((s) => {
      const [, value] = s.split(',');
      return value && timingSafeEqual(value, expected);
    });
}

function generateLicenseKey(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  const body = Array.from(bytes)
    .map((b) => b.toString(36).padStart(2, '0'))
    .join('')
    .slice(0, 32);
  return `mla_live_${body}`;
}

function base64Encode(bytes: Uint8Array): string {
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

function base64UrlDecode(s: string): Uint8Array {
  const norm = s.replace(/-/g, '+').replace(/_/g, '/');
  const padded = norm + '='.repeat((4 - (norm.length % 4)) % 4);
  const bin = atob(padded);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

// ============================================================
// POST /deactivate
// User license-ni başqa machine-də işlətmək istəyəndə fingerprint sıfırla.
// Authorization: valid Bearer token (mövcud machine-dən).
// ============================================================
app.post('/deactivate', async (c) => {
  const authHeader = c.req.header('Authorization');
  if (!authHeader?.startsWith('Bearer ')) {
    return c.json({ error: 'missing_token' }, 401);
  }
  let claims: { license_key?: string; user_id?: string };
  try {
    const [, payload] = authHeader.slice(7).split('.');
    claims = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')));
  } catch {
    return c.json({ error: 'malformed_token' }, 400);
  }
  if (!claims.license_key || !claims.user_id) {
    return c.json({ error: 'malformed_claims' }, 400);
  }

  await c.env.DB.prepare(
    'UPDATE licenses SET machine_fingerprint = NULL, activated_at = NULL WHERE key = ? AND user_id = ?',
  )
    .bind(claims.license_key, claims.user_id)
    .run();

  return c.json({ status: 'deactivated' });
});

// ============================================================
// ADMIN ENDPOINTS
// X-Admin-Token header tələb edir. Local admin UI bunlardan istifadə edir.
// ============================================================
function requireAdmin(c: any): Response | null {
  const expected = c.env.ADMIN_TOKEN;
  if (!expected) {
    return c.json({ error: 'admin_not_configured' }, 503);
  }
  const got = c.req.header('X-Admin-Token');
  if (!got || !timingSafeEqual(got, expected)) {
    return c.json({ error: 'unauthorized' }, 401);
  }
  return null;
}

// POST /admin/keys — yeni user + license + sub yarad
// body: { email, duration_days?, plan?, note? } → { license_key, user_id, expires_at, email }
app.post('/admin/keys', async (c) => {
  const fail = requireAdmin(c);
  if (fail) return fail;

  type CreateBody = { email?: string; duration_days?: number; plan?: string; note?: string };
  const body = await c.req.json<CreateBody>().catch(() => ({} as CreateBody));

  const email = (body.email ?? '').trim().toLowerCase();
  const durationDays = Math.max(1, Math.min(3650, body.duration_days ?? 365));
  const plan = body.plan ?? 'alpha';

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return c.json({ error: 'invalid_email' }, 400);
  }

  const now = Math.floor(Date.now() / 1000);
  const periodEnd = now + durationDays * 86400;
  const userId = await ensureUser(c.env, email, undefined, now);
  const licenseKey = generateLicenseKey();
  const subId = 'sub_' + crypto.randomUUID().replace(/-/g, '').slice(0, 16);
  const fakePolar = 'fake_polar_' + subId.slice(4);

  await c.env.DB.prepare(
    'INSERT INTO licenses (key, user_id, created_at) VALUES (?, ?, ?)',
  ).bind(licenseKey, userId, now).run();

  await c.env.DB.prepare(
    `INSERT INTO subscriptions
       (id, user_id, polar_subscription_id, status, current_period_end, plan, created_at, updated_at)
     VALUES (?, ?, ?, 'active', ?, ?, ?, ?)`,
  ).bind(subId, userId, fakePolar, periodEnd, plan, now, now).run();

  return c.json({
    license_key: licenseKey,
    user_id: userId,
    email,
    expires_at: periodEnd,
    plan,
  });
});

// GET /admin/keys — bütün user + key + sub join
app.get('/admin/keys', async (c) => {
  const fail = requireAdmin(c);
  if (fail) return fail;

  const { results } = await c.env.DB.prepare(
    `SELECT u.email,
            l.key            AS license_key,
            l.revoked,
            l.machine_fingerprint,
            l.activated_at,
            l.created_at     AS license_created_at,
            s.status         AS sub_status,
            s.current_period_end,
            s.plan
     FROM licenses l
     JOIN users u ON u.id = l.user_id
     LEFT JOIN subscriptions s ON s.user_id = l.user_id
     ORDER BY l.created_at DESC`,
  ).all();

  const now = Math.floor(Date.now() / 1000);
  const rows = (results as any[]).map((r) => ({
    email: r.email,
    license_key: r.license_key,
    plan: r.plan,
    revoked: !!r.revoked,
    sub_status: r.sub_status,
    expires_at: r.current_period_end,
    expired: r.current_period_end ? r.current_period_end <= now : true,
    machine_bound: !!r.machine_fingerprint,
    machine_fingerprint: r.machine_fingerprint
      ? String(r.machine_fingerprint).slice(0, 12) + '…'
      : null,
    activated_at: r.activated_at,
    created_at: r.license_created_at,
  }));

  return c.json({ count: rows.length, keys: rows });
});

// PATCH /admin/keys/:key — body: { action: "deactivate"|"activate"|"extend"|"unbind", days? }
app.patch('/admin/keys/:key', async (c) => {
  const fail = requireAdmin(c);
  if (fail) return fail;

  const key = c.req.param('key');
  type PatchBody = { action?: string; days?: number };
  const body = await c.req.json<PatchBody>().catch(() => ({} as PatchBody));
  const action = body.action;

  const lic = await c.env.DB.prepare(
    'SELECT user_id FROM licenses WHERE key = ?',
  ).bind(key).first<{ user_id: string }>();
  if (!lic) return c.json({ error: 'not_found' }, 404);

  const now = Math.floor(Date.now() / 1000);

  switch (action) {
    case 'deactivate':
      await c.env.DB.prepare('UPDATE licenses SET revoked = 1 WHERE key = ?').bind(key).run();
      return c.json({ status: 'deactivated' });

    case 'activate':
      await c.env.DB.prepare('UPDATE licenses SET revoked = 0 WHERE key = ?').bind(key).run();
      await c.env.DB.prepare(
        `UPDATE subscriptions SET status = 'active', updated_at = ?
         WHERE user_id = ? AND status = 'cancelled'`,
      ).bind(now, lic.user_id).run();
      return c.json({ status: 'activated' });

    case 'extend': {
      const days = Math.max(1, Math.min(3650, body.days ?? 30));
      const result = await c.env.DB.prepare(
        `UPDATE subscriptions
         SET current_period_end = MAX(current_period_end, ?) + ?,
             status = 'active',
             updated_at = ?
         WHERE user_id = ?`,
      ).bind(now, days * 86400, now, lic.user_id).run();
      return c.json({ status: 'extended', changed: result.meta.changes });
    }

    case 'unbind':
      await c.env.DB.prepare(
        'UPDATE licenses SET machine_fingerprint = NULL, activated_at = NULL WHERE key = ?',
      ).bind(key).run();
      return c.json({ status: 'unbound' });

    default:
      return c.json({ error: 'invalid_action', allowed: ['deactivate', 'activate', 'extend', 'unbind'] }, 400);
  }
});

// DELETE /admin/keys/:key — yalnız hard cleanup; adi flow deactivate istifadə etsin
app.delete('/admin/keys/:key', async (c) => {
  const fail = requireAdmin(c);
  if (fail) return fail;
  const key = c.req.param('key');
  const lic = await c.env.DB.prepare('SELECT user_id FROM licenses WHERE key = ?').bind(key).first<{ user_id: string }>();
  if (!lic) return c.json({ error: 'not_found' }, 404);
  await c.env.DB.prepare('DELETE FROM licenses WHERE key = ?').bind(key).run();
  return c.json({ status: 'deleted' });
});

export default app;

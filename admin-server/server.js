// Tokengram self-hosted license + admin server.
// Replaces the Cloudflare Worker — all data lives in local SQLite.

'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

(function loadDotEnv() {
    const envPath = path.join(__dirname, '.env');
    if (!fs.existsSync(envPath)) return;
    for (const raw of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
        const line = raw.trim();
        if (!line || line.startsWith('#')) continue;
        const eq = line.indexOf('=');
        if (eq < 0) continue;
        const k = line.slice(0, eq).trim();
        let v = line.slice(eq + 1).trim();
        if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
            v = v.slice(1, -1);
        }
        if (!(k in process.env)) process.env[k] = v;
    }
})();

const express = require('express');
const session = require('express-session');
const bcrypt = require('bcryptjs');
const Database = require('better-sqlite3');
const { SignJWT, importPKCS8 } = require('jose');

const PORT = parseInt(process.env.PORT || '3000', 10);
const DB_PATH = process.env.DB_PATH || path.join(__dirname, 'data', 'tokengram.db');
const JWT_PRIVATE_KEY_PATH = process.env.JWT_PRIVATE_KEY_PATH || path.join(__dirname, 'keys', 'jwt_private.pem');
const JWT_PUBLIC_KEY_PATH = process.env.JWT_PUBLIC_KEY_PATH || path.join(__dirname, 'keys', 'jwt_public.pem');
const SESSION_SECRET = process.env.SESSION_SECRET || crypto.randomBytes(32).toString('hex');
const ADMIN_TOKEN = (process.env.ADMIN_TOKEN || '').trim();
const JWT_TTL_SECONDS = 7 * 24 * 60 * 60;
const TRIAL_DAYS = parseInt(process.env.TRIAL_DAYS || '30', 10);

// ---- DB ----
fs.mkdirSync(path.dirname(DB_PATH), { recursive: true });
const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

// Schema (idempotent)
const schemaSql = fs.readFileSync(path.join(__dirname, 'schema.sql'), 'utf8');
db.exec(schemaSql);

// Admin bootstrap
(function bootstrapAdmin() {
    const email = (process.env.ADMIN_EMAIL || '').trim().toLowerCase();
    const password = process.env.ADMIN_PASSWORD || '';
    if (!email || !password) return;
    const existing = db.prepare('SELECT id FROM admin_users WHERE email = ?').get(email);
    if (existing) return;
    const hash = bcrypt.hashSync(password, 12);
    db.prepare('INSERT INTO admin_users (email, password_hash, created_at) VALUES (?, ?, ?)').run(
        email,
        hash,
        nowSec(),
    );
    console.log(`[bootstrap] admin yaradıldı: ${email}`);
})();

// ---- JWT keys ----
let jwtPrivateKeyPEM = '';
let jwtPublicKeyPEM = '';
try {
    jwtPrivateKeyPEM = fs.readFileSync(JWT_PRIVATE_KEY_PATH, 'utf8');
    jwtPublicKeyPEM = fs.readFileSync(JWT_PUBLIC_KEY_PATH, 'utf8');
} catch (e) {
    console.warn(`[jwt] PEM açarları tapılmadı (${e.message}). /activate işləməyəcək.`);
}

async function issueToken(claims, ttlSeconds = JWT_TTL_SECONDS) {
    const pk = await importPKCS8(jwtPrivateKeyPEM, 'RS256');
    // iat 60s geriyə yazılır: müştəri saatı serverdən bir neçə saniyə geri
    // qalanda köhnə wheel-lərin sıfır-leeway pyjwt verify-ı iat-ı "gələcəkdə"
    // görüb tokeni rədd edirdi (2026-06-12 insidenti). exp-ə təsiri yoxdur —
    // setExpirationTime cari vaxtdan hesablanır.
    return await new SignJWT(claims)
        .setProtectedHeader({ alg: 'RS256' })
        .setIssuedAt(nowSec() - 60)
        .setExpirationTime(`${ttlSeconds}s`)
        .setIssuer('mla-license-server')
        .sign(pk);
}

// Token abunənin bitməsindən o yana yaşamamalıdır — yoxsa trialing istifadəçi
// offline grace ilə trial sonunu 7 günə qədər uzada bilər.
function tokenTtlFor(periodEnd) {
    return Math.max(60, Math.min(JWT_TTL_SECONDS, periodEnd - nowSec()));
}

// ---- App ----
const app = express();
app.set('trust proxy', 1);
app.use((req, res, next) => {
    const t0 = Date.now();
    res.on('finish', () => {
        const ms = Date.now() - t0;
        console.log(`[${new Date().toISOString()}] ${req.method} ${req.path} ${res.statusCode} ${ms}ms ip=${req.ip}`);
    });
    next();
});
app.use(express.json({ limit: '64kb' }));
app.use(express.urlencoded({ extended: false, limit: '64kb' }));
app.use(
    session({
        name: 'tg.sid',
        secret: SESSION_SECRET,
        resave: false,
        saveUninitialized: false,
        cookie: {
            httpOnly: true,
            sameSite: 'lax',
            secure: false, // HTTPS qoşulduqda true et
            maxAge: 8 * 60 * 60 * 1000, // 8 saat
        },
    }),
);

function requireAdmin(req, res, next) {
    if (ADMIN_TOKEN && req.headers['x-admin-token'] === ADMIN_TOKEN) {
        req._tokenAuth = true;
        return next();
    }
    if (!req.session.adminEmail) {
        return res.status(401).json({ error: 'unauthorized' });
    }
    next();
}

function actorEmail(req) {
    return req._tokenAuth ? 'admin-token' : req.session.adminEmail;
}

function logAudit(adminEmail, action, target, details) {
    db.prepare(
        'INSERT INTO audit_log (admin_email, action, target, details, created_at) VALUES (?, ?, ?, ?, ?)',
    ).run(adminEmail, action, target || null, details ? JSON.stringify(details) : null, nowSec());
}

function nowSec() {
    return Math.floor(Date.now() / 1000);
}

function newId(prefix) {
    return prefix + crypto.randomBytes(8).toString('hex');
}

// ====================================================================
// Public endpoints (client extension/python istifadəsi)
// ====================================================================
app.get('/health', (_req, res) => res.json({ ok: true, ts: nowSec() }));

app.get('/pubkey', (_req, res) => {
    if (!jwtPublicKeyPEM) return res.status(500).send('JWT_PUBLIC_KEY not configured');
    res.type('application/x-pem-file').send(jwtPublicKeyPEM);
});

app.post('/check-key', (req, res) => {
    const key = String(req.body?.license_key || '').trim();
    if (!key) return res.status(400).json({ valid: false, reason: 'missing_key' });

    const row = db
        .prepare(
            `SELECT l.revoked, u.email, s.status, s.current_period_end
             FROM licenses l
             JOIN users u ON u.id = l.user_id
             LEFT JOIN subscriptions s
               ON s.user_id = l.user_id
              AND s.status IN ('active','trialing')
              AND s.current_period_end > ?
             WHERE l.key = ?
             ORDER BY s.current_period_end DESC LIMIT 1`,
        )
        .get(nowSec(), key);

    if (!row) return res.status(404).json({ valid: false, reason: 'not_found' });
    if (row.revoked) return res.status(401).json({ valid: false, reason: 'revoked' });
    if (!row.status) return res.status(402).json({ valid: false, reason: 'no_active_subscription' });

    res.json({ valid: true, email: row.email, status: row.status, expires_at: row.current_period_end });
});

app.post('/activate', async (req, res) => {
    const licenseKey = String(req.body?.license_key || '');
    const fp = String(req.body?.machine_fingerprint || '');
    if (!licenseKey || !fp) return res.status(400).json({ error: 'missing_fields' });

    const license = db
        .prepare('SELECT key, user_id, machine_fingerprint, revoked FROM licenses WHERE key = ?')
        .get(licenseKey);
    if (!license || license.revoked) return res.status(401).json({ error: 'invalid_license' });

    // current_period_end yoxlaması vacibdir: yoxsa bitmiş trialing/manual abunə
    // əbədi /activate edə bilir (Paddle webhook-u olmayan abunələrdə status
    // heç vaxt 'cancelled' olmur — vaxt yeganə qapıdır).
    const sub = db
        .prepare(
            `SELECT status, current_period_end FROM subscriptions
             WHERE user_id = ? AND status IN ('active','trialing')
               AND current_period_end > ?
             ORDER BY current_period_end DESC LIMIT 1`,
        )
        .get(license.user_id, nowSec());
    if (!sub) return res.status(402).json({ error: 'no_active_subscription' });

    if (license.machine_fingerprint && license.machine_fingerprint !== fp) {
        return res
            .status(403)
            .json({ error: 'machine_mismatch', hint: 'License is bound to another machine.' });
    }
    if (!license.machine_fingerprint) {
        db.prepare('UPDATE licenses SET machine_fingerprint = ?, activated_at = ? WHERE key = ?').run(
            fp,
            nowSec(),
            licenseKey,
        );
    }

    try {
        const ttl = tokenTtlFor(sub.current_period_end);
        const token = await issueToken({
            user_id: license.user_id,
            license_key: license.key,
            fingerprint: fp,
            subscription_status: sub.status,
            period_end: sub.current_period_end,
        }, ttl);
        res.json({ token, expires_at: nowSec() + ttl });
    } catch (e) {
        console.error('[activate] JWT sign error:', e);
        res.status(500).json({ error: 'jwt_sign_failed' });
    }
});

app.post('/validate', async (req, res) => {
    const auth = req.headers['authorization'] || '';
    if (!auth.startsWith('Bearer ')) return res.status(401).json({ error: 'missing_token' });
    const oldToken = auth.slice(7);
    let claims;
    try {
        const payload = oldToken.split('.')[1];
        claims = JSON.parse(Buffer.from(payload.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString());
    } catch {
        return res.status(400).json({ error: 'malformed_token' });
    }
    if (!claims.user_id || !claims.fingerprint || !claims.license_key) {
        return res.status(400).json({ error: 'malformed_claims' });
    }
    // Bitmiş abunə refresh ala bilməz (bax /activate-dəki şərh).
    const sub = db
        .prepare(
            `SELECT status, current_period_end FROM subscriptions
             WHERE user_id = ? AND status IN ('active','trialing')
               AND current_period_end > ?
             ORDER BY current_period_end DESC LIMIT 1`,
        )
        .get(claims.user_id, nowSec());
    if (!sub) return res.status(401).json({ error: 'subscription_inactive' });

    const lic = db
        .prepare('SELECT machine_fingerprint, revoked FROM licenses WHERE key = ?')
        .get(claims.license_key);
    if (!lic || lic.revoked || lic.machine_fingerprint !== claims.fingerprint) {
        return res.status(401).json({ error: 'license_revoked' });
    }
    try {
        const ttl = tokenTtlFor(sub.current_period_end);
        const token = await issueToken({
            user_id: claims.user_id,
            license_key: claims.license_key,
            fingerprint: claims.fingerprint,
            subscription_status: sub.status,
            period_end: sub.current_period_end,
        }, ttl);
        res.json({ token, expires_at: nowSec() + ttl });
    } catch (e) {
        console.error('[validate] JWT sign error:', e);
        res.status(500).json({ error: 'jwt_sign_failed' });
    }
});

// POST /trial — açarsız ilk işə düşmədə 30 günlük trial.
// Bir maşın = bir trial: qeyd `trials` cədvəlində fingerprint-ə bağlıdır,
// lokal faylların silinməsi reset vermir. Trial hələ aktivdirsə (reinstall
// halı) eyni açar üçün təzə token verilir; bitibsə 403 trial_expired.
app.post('/trial', async (req, res) => {
    const fp = String(req.body?.machine_fingerprint || '').trim();
    if (!fp || fp.length < 16 || fp.length > 128) {
        return res.status(400).json({ error: 'missing_fingerprint' });
    }
    const now = nowSec();

    const existing = db.prepare('SELECT user_id, license_key FROM trials WHERE fingerprint = ?').get(fp);
    if (existing) {
        const sub = db
            .prepare(
                `SELECT status, current_period_end FROM subscriptions
                 WHERE user_id = ? AND status = 'trialing' AND current_period_end > ?
                 ORDER BY current_period_end DESC LIMIT 1`,
            )
            .get(existing.user_id, now);
        if (!sub) return res.status(403).json({ error: 'trial_expired' });
        try {
            const ttl = tokenTtlFor(sub.current_period_end);
            const token = await issueToken({
                user_id: existing.user_id,
                license_key: existing.license_key,
                fingerprint: fp,
                subscription_status: 'trialing',
                period_end: sub.current_period_end,
            }, ttl);
            return res.json({
                token,
                expires_at: now + ttl,
                license_key: existing.license_key,
                trial_ends_at: sub.current_period_end,
            });
        } catch (e) {
            console.error('[trial] JWT sign error:', e);
            return res.status(500).json({ error: 'jwt_sign_failed' });
        }
    }

    const trialEnd = now + TRIAL_DAYS * 86400;
    const trx = db.transaction(() => {
        const userId = newId('usr_');
        const email = `trial-${fp.slice(0, 12)}@trial.tokengram.local`;
        db.prepare('INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)').run(userId, email, now);
        const licenseKey = newId('mla_trial_');
        db.prepare(
            'INSERT INTO licenses (key, user_id, machine_fingerprint, activated_at, note, created_at) VALUES (?, ?, ?, ?, ?, ?)',
        ).run(licenseKey, userId, fp, now, 'auto-trial', now);
        const subId = newId('sub_');
        db.prepare(
            `INSERT INTO subscriptions
               (id, user_id, polar_subscription_id, status, current_period_end, plan, created_at, updated_at)
             VALUES (?, ?, ?, 'trialing', ?, 'trial', ?, ?)`,
        ).run(subId, userId, 'trial_' + subId.slice(4), trialEnd, now, now);
        db.prepare('INSERT INTO trials (fingerprint, user_id, license_key, created_at) VALUES (?, ?, ?, ?)').run(
            fp,
            userId,
            licenseKey,
            now,
        );
        return { userId, licenseKey };
    });

    let created;
    try {
        created = trx();
    } catch (e) {
        // UNIQUE race (eyni fingerprint paralel iki sorğu) → retry oxu
        const row = db.prepare('SELECT user_id, license_key FROM trials WHERE fingerprint = ?').get(fp);
        if (!row) {
            console.error('[trial] create error:', e);
            return res.status(500).json({ error: 'trial_create_failed' });
        }
        created = { userId: row.user_id, licenseKey: row.license_key };
    }

    try {
        const ttl = tokenTtlFor(trialEnd);
        const token = await issueToken({
            user_id: created.userId,
            license_key: created.licenseKey,
            fingerprint: fp,
            subscription_status: 'trialing',
            period_end: trialEnd,
        }, ttl);
        logAudit('system-trial', 'create_trial', created.licenseKey, { fingerprint: fp.slice(0, 12), trialEnd });
        res.json({ token, expires_at: now + ttl, license_key: created.licenseKey, trial_ends_at: trialEnd });
    } catch (e) {
        console.error('[trial] JWT sign error:', e);
        res.status(500).json({ error: 'jwt_sign_failed' });
    }
});

// ====================================================================
// Admin endpoints
// ====================================================================
app.post('/admin/login', (req, res) => {
    const email = String(req.body?.email || '').trim().toLowerCase();
    const password = String(req.body?.password || '');
    if (!email || !password) return res.status(400).json({ error: 'missing_credentials' });

    const row = db.prepare('SELECT id, email, password_hash FROM admin_users WHERE email = ?').get(email);
    if (!row || !bcrypt.compareSync(password, row.password_hash)) {
        return res.status(401).json({ error: 'invalid_credentials' });
    }
    db.prepare('UPDATE admin_users SET last_login_at = ? WHERE id = ?').run(nowSec(), row.id);
    req.session.adminEmail = row.email;
    logAudit(row.email, 'login', null, null);
    res.json({ ok: true, email: row.email });
});

app.post('/admin/logout', (req, res) => {
    const email = req.session.adminEmail;
    req.session.destroy(() => {
        if (email) logAudit(email, 'logout', null, null);
        res.json({ ok: true });
    });
});

app.get('/admin/me', (req, res) => {
    if (!req.session.adminEmail) return res.status(401).json({ error: 'unauthorized' });
    res.json({ email: req.session.adminEmail });
});

app.get('/admin/keys', requireAdmin, (req, res) => {
    const q = String(req.query.q || '').trim();
    const params = [];
    let where = '';
    if (q) {
        where = 'WHERE u.email LIKE ? OR l.key LIKE ?';
        params.push(`%${q}%`, `%${q}%`);
    }
    const rows = db
        .prepare(
            `SELECT l.key, l.machine_fingerprint, l.activated_at, l.revoked, l.note, l.created_at,
                    u.id AS user_id, u.email,
                    (SELECT s.status FROM subscriptions s
                       WHERE s.user_id = u.id
                       ORDER BY s.current_period_end DESC LIMIT 1) AS status,
                    (SELECT s.current_period_end FROM subscriptions s
                       WHERE s.user_id = u.id
                       ORDER BY s.current_period_end DESC LIMIT 1) AS expires_at,
                    (SELECT s.plan FROM subscriptions s
                       WHERE s.user_id = u.id
                       ORDER BY s.current_period_end DESC LIMIT 1) AS plan
             FROM licenses l
             JOIN users u ON u.id = l.user_id
             ${where}
             ORDER BY l.created_at DESC
             LIMIT 500`,
        )
        .all(...params);
    const now = nowSec();
    const keys = rows.map((r) => ({
        license_key: r.key,
        email: r.email,
        plan: r.plan,
        sub_status: r.status,
        expired: !!r.expires_at && r.expires_at < now,
        revoked: !!r.revoked,
        machine_bound: !!r.machine_fingerprint,
        machine_fingerprint: r.machine_fingerprint,
        expires_at: r.expires_at,
        activated_at: r.activated_at,
        note: r.note,
        created_at: r.created_at,
    }));
    res.json({ rows, keys, count: keys.length });
});

app.post('/admin/keys', requireAdmin, (req, res) => {
    const email = String(req.body?.email || '').trim().toLowerCase();
    const plan = String(req.body?.plan || 'alpha').trim();
    const durationDays = parseInt(req.body?.duration_days || '365', 10);
    const note = String(req.body?.note || '').trim();

    if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
        return res.status(400).json({ error: 'invalid_email' });
    }
    if (!Number.isFinite(durationDays) || durationDays < 1 || durationDays > 36500) {
        return res.status(400).json({ error: 'invalid_duration' });
    }

    const now = nowSec();
    const trx = db.transaction(() => {
        let user = db.prepare('SELECT id FROM users WHERE email = ?').get(email);
        let userId;
        if (user) {
            userId = user.id;
        } else {
            userId = newId('usr_');
            db.prepare('INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)').run(userId, email, now);
        }
        const licenseKey = newId('mla_live_');
        db.prepare('INSERT INTO licenses (key, user_id, note, created_at) VALUES (?, ?, ?, ?)').run(
            licenseKey,
            userId,
            note || null,
            now,
        );
        const subId = newId('sub_');
        const polarFake = 'manual_' + subId.slice(4);
        db.prepare(
            `INSERT INTO subscriptions
               (id, user_id, polar_subscription_id, status, current_period_end, plan, created_at, updated_at)
             VALUES (?, ?, ?, 'active', ?, ?, ?, ?)`,
        ).run(subId, userId, polarFake, now + durationDays * 86400, plan, now, now);
        return { licenseKey, userId, expiresAt: now + durationDays * 86400 };
    });

    const result = trx();
    logAudit(actorEmail(req), 'create_key', result.licenseKey, { email, plan, durationDays });
    res.json({
        ok: true,
        key: result.licenseKey,
        license_key: result.licenseKey,
        user_id: result.userId,
        email,
        plan,
        expires_at: result.expiresAt,
    });
});

function revokeLicense(key) {
    const lic = db.prepare('SELECT key FROM licenses WHERE key = ?').get(key);
    if (!lic) return { status: 404, body: { error: 'not_found' } };
    db.prepare('UPDATE licenses SET revoked = 1 WHERE key = ?').run(key);
    return { status: 200, body: { ok: true } };
}

function restoreLicense(key) {
    const lic = db.prepare('SELECT key FROM licenses WHERE key = ?').get(key);
    if (!lic) return { status: 404, body: { error: 'not_found' } };
    db.prepare('UPDATE licenses SET revoked = 0 WHERE key = ?').run(key);
    return { status: 200, body: { ok: true } };
}

function resetFingerprint(key) {
    const lic = db.prepare('SELECT key FROM licenses WHERE key = ?').get(key);
    if (!lic) return { status: 404, body: { error: 'not_found' } };
    db.prepare('UPDATE licenses SET machine_fingerprint = NULL, activated_at = NULL WHERE key = ?').run(key);
    return { status: 200, body: { ok: true } };
}

function extendLicense(key, days) {
    if (!Number.isFinite(days) || days === 0) return { status: 400, body: { error: 'invalid_days' } };
    const row = db
        .prepare(
            `SELECT s.id, s.current_period_end
             FROM licenses l JOIN subscriptions s ON s.user_id = l.user_id
             WHERE l.key = ?
             ORDER BY s.current_period_end DESC LIMIT 1`,
        )
        .get(key);
    if (!row) return { status: 404, body: { error: 'not_found' } };
    const newEnd = Math.max(nowSec(), row.current_period_end) + days * 86400;
    db.prepare('UPDATE subscriptions SET current_period_end = ?, updated_at = ? WHERE id = ?').run(
        newEnd,
        nowSec(),
        row.id,
    );
    return { status: 200, body: { ok: true, expires_at: newEnd } };
}

app.post('/admin/keys/:key/revoke', requireAdmin, (req, res) => {
    const key = String(req.params.key);
    const out = revokeLicense(key);
    if (out.status === 200) logAudit(actorEmail(req), 'revoke_key', key, null);
    res.status(out.status).json(out.body);
});

app.post('/admin/keys/:key/restore', requireAdmin, (req, res) => {
    const key = String(req.params.key);
    const out = restoreLicense(key);
    if (out.status === 200) logAudit(actorEmail(req), 'restore_key', key, null);
    res.status(out.status).json(out.body);
});

app.post('/admin/keys/:key/reset-fingerprint', requireAdmin, (req, res) => {
    const key = String(req.params.key);
    const out = resetFingerprint(key);
    if (out.status === 200) logAudit(actorEmail(req), 'reset_fingerprint', key, null);
    res.status(out.status).json(out.body);
});

app.post('/admin/keys/:key/extend', requireAdmin, (req, res) => {
    const key = String(req.params.key);
    const days = parseInt(req.body?.days || '0', 10);
    const out = extendLicense(key, days);
    if (out.status === 200) logAudit(actorEmail(req), 'extend_key', key, { days, newEnd: out.body.expires_at });
    res.status(out.status).json(out.body);
});

// PATCH /admin/keys/:key  — admin_ui.py-nin sxemi: { action: deactivate|activate|extend|unbind, days? }
app.patch('/admin/keys/:key', requireAdmin, (req, res) => {
    const key = String(req.params.key);
    const action = String(req.body?.action || '').trim();
    let out;
    let auditAction;
    switch (action) {
        case 'deactivate':
            out = revokeLicense(key);
            auditAction = 'revoke_key';
            break;
        case 'activate':
            out = restoreLicense(key);
            auditAction = 'restore_key';
            break;
        case 'unbind':
            out = resetFingerprint(key);
            auditAction = 'reset_fingerprint';
            break;
        case 'extend':
            const days = parseInt(req.body?.days || '30', 10);
            out = extendLicense(key, days);
            auditAction = 'extend_key';
            break;
        default:
            return res.status(400).json({ error: 'unknown_action' });
    }
    if (out.status === 200) logAudit(actorEmail(req), auditAction, key, req.body);
    res.status(out.status).json(out.body);
});

// DELETE /admin/keys/:key — admin_ui.py-də nəzərdə tutulurdu (soft delete = revoke)
app.delete('/admin/keys/:key', requireAdmin, (req, res) => {
    const key = String(req.params.key);
    const out = revokeLicense(key);
    if (out.status === 200) logAudit(actorEmail(req), 'delete_key', key, null);
    res.status(out.status).json(out.body);
});

app.get('/admin/audit', requireAdmin, (_req, res) => {
    const rows = db
        .prepare('SELECT admin_email, action, target, details, created_at FROM audit_log ORDER BY id DESC LIMIT 200')
        .all();
    res.json({ rows });
});

// ====================================================================
// /buy — Paddle checkout hazır olana qədər stub.
// Landing-dəki bütün CTA düymələri bura gəlir (?plan=trial|monthly|yearly).
// Paddle inteqrasiyası bitəndə bu route Paddle checkout URL-inə 302 edəcək
// (bax: PAYMENT_PLAN.md, addım 4).
// ====================================================================
app.get('/buy', (req, res) => {
    const plan = ['trial', 'monthly', 'yearly'].includes(String(req.query.plan))
        ? String(req.query.plan)
        : 'monthly';
    const planLabel = { trial: '1-day Free Trial', monthly: 'Pro — $5/month', yearly: 'Pro — $29/year' }[plan];
    res.type('html').send(`<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tokengram — Checkout</title><link rel="icon" type="image/png" href="/icon.png">
<style>
  body { font-family: "Segoe UI", system-ui, sans-serif; background: #070b14; color: #e8edf7;
         display: grid; place-items: center; min-height: 100vh; margin: 0; text-align: center; }
  .card { max-width: 420px; padding: 40px 32px; border: 1px solid rgba(77,144,255,.3); border-radius: 16px;
          background: rgba(17,25,45,.6); box-shadow: 0 0 50px rgba(77,144,255,.12); }
  img { width: 72px; filter: drop-shadow(0 0 20px rgba(77,144,255,.35)); }
  h1 { font-size: 1.3rem; margin: 18px 0 6px; }
  .plan { color: #7fb4ff; font-weight: 600; }
  p { color: #93a0b8; font-size: .92rem; line-height: 1.55; }
  a.btn { display: inline-block; margin-top: 18px; padding: 10px 24px; border-radius: 10px;
          background: linear-gradient(135deg,#2f6fe0,#4d90ff); color: #fff; text-decoration: none; font-weight: 600; }
</style></head><body>
<div class="card">
  <img src="/icon.png" alt="Tokengram">
  <h1>Checkout opens very soon</h1>
  <p>You picked <span class="plan">${planLabel}</span>.<br>
     Payments go live shortly — drop us a line and we'll send your checkout link the moment it's ready.</p>
  <a class="btn" href="mailto:n.ilkin.humbatov@gmail.com?subject=Tokengram%20${encodeURIComponent(plan)}%20plan">Notify me</a>
</div>
</body></html>`);
});

// ---- Static UI ----
// Admin paneli /admin/ altına köçdü; kök (/) artıq tokengram.click landing-i verir.
app.use('/admin', express.static(path.join(__dirname, 'public')));
app.use('/', express.static(path.join(__dirname, 'site')));

app.listen(PORT, '0.0.0.0', () => {
    console.log(`[tokengram-admin] http://0.0.0.0:${PORT}`);
});

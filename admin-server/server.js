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
const { sendMail } = require('./mailer');

const PORT = parseInt(process.env.PORT || '3000', 10);
const DB_PATH = process.env.DB_PATH || path.join(__dirname, 'data', 'tokengram.db');
const JWT_PRIVATE_KEY_PATH = process.env.JWT_PRIVATE_KEY_PATH || path.join(__dirname, 'keys', 'jwt_private.pem');
const JWT_PUBLIC_KEY_PATH = process.env.JWT_PUBLIC_KEY_PATH || path.join(__dirname, 'keys', 'jwt_public.pem');
const SESSION_SECRET = process.env.SESSION_SECRET || crypto.randomBytes(32).toString('hex');
const ADMIN_TOKEN = (process.env.ADMIN_TOKEN || '').trim();
const JWT_TTL_SECONDS = 7 * 24 * 60 * 60;
const TRIAL_DAYS = parseInt(process.env.TRIAL_DAYS || '3', 10);

// ---- Lemon Squeezy ----
// Bütün dəyərlər Lemon panelindən gəlir (.env-ə yazılır); kod onları runtime-da oxuyur.
const LEMON_WEBHOOK_SECRET = (process.env.LEMON_WEBHOOK_SECRET || '').trim();
// Tam checkout URL-i: https://<store>.lemonsqueezy.com/checkout/buy/<variant-uuid>
const LEMON_CHECKOUT_URL = (process.env.LEMON_CHECKOUT_URL || '').trim();
const PRICE_LABEL = process.env.PRICE_LABEL || '$3/month';

// Mail linkləri + magic-link / dashboard üçün.
const PUBLIC_BASE_URL = (process.env.PUBLIC_BASE_URL || 'https://tokengram.click').replace(/\/+$/, '');
// Açar bir maşına bağlıdır; user başqa cihaza keçmək üçün "release" edə bilir,
// amma bu cooldown açarın çox nəfər arasında gəzməsinin qarşısını alır.
const REBIND_COOLDOWN_DAYS = parseInt(process.env.REBIND_COOLDOWN_DAYS || '7', 10);

// ---- DB ----
fs.mkdirSync(path.dirname(DB_PATH), { recursive: true });
const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

// Schema (idempotent)
const schemaSql = fs.readFileSync(path.join(__dirname, 'schema.sql'), 'utf8');
db.exec(schemaSql);

// Migrasiyalar — CREATE IF NOT EXISTS mövcud cədvələ sütun əlavə etmir,
// ona görə canlı DB-də çatışmayan sütunları ALTER ilə əlavə edirik (idempotent).
(function migrate() {
    const has = (table, col) =>
        db.prepare(`PRAGMA table_info(${table})`).all().some((c) => c.name === col);
    // users.contact_email — real email (qeyri-unikal). `email` daxili unikal id olaraq
    // qalır (trial-da saxta, admin-də real); real email-i ayrıca burada saxlayırıq ki,
    // UNIQUE(email) ilə toqquşma olmasın və eyni adam çox cihazda trial ala bilsin.
    if (!has('users', 'contact_email')) {
        db.exec('ALTER TABLE users ADD COLUMN contact_email TEXT');
        db.exec('CREATE INDEX IF NOT EXISTS idx_users_contact_email ON users(contact_email)');
    }
    // licenses.last_rebind_at — self-service re-bind cooldown üçün.
    if (!has('licenses', 'last_rebind_at')) {
        db.exec('ALTER TABLE licenses ADD COLUMN last_rebind_at INTEGER');
    }
    // subscriptions.portal_url — Lemon customer portal (kart dəyiş / ləğv et) linki.
    if (!has('subscriptions', 'portal_url')) {
        db.exec('ALTER TABLE subscriptions ADD COLUMN portal_url TEXT');
    }
    // trials.reminded_at — "trial sabah bitir" maili bir dəfə göndərilsin deyə.
    if (!has('trials', 'reminded_at')) {
        db.exec('ALTER TABLE trials ADD COLUMN reminded_at INTEGER');
    }
})();

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
// rawBody webhook HMAC üçün saxlanır (express.json parse-dən əvvəlki xam buffer).
app.use(express.json({ limit: '64kb', verify: (req, _res, buf) => { req.rawBody = buf; } }));
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

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ---- Email şablonları (sadə, inline-styled) ----
const MAIL_WRAP = (inner) =>
    `<div style="font-family:Segoe UI,system-ui,sans-serif;max-width:480px;margin:0 auto;color:#1a2230">${inner}
     <p style="color:#9aa6b8;font-size:12px;margin-top:28px">Tokengram · ${PUBLIC_BASE_URL}</p></div>`;
const KEY_BOX = (key) =>
    `<p style="font-family:monospace;background:#f1f4f9;border:1px solid #d8e0ec;border-radius:8px;padding:12px 14px;word-break:break-all">${escapeHtml(key)}</p>`;

function emailActiveHtml(key, portalUrl) {
    return MAIL_WRAP(
        `<h2>Abunəliyin aktivdir 🎉</h2>
         <p>Təşəkkürlər! Lisenziya açarın (cihazını dəyişsən bu açarı yenidən işlət):</p>
         ${KEY_BOX(key)}
         <p><a href="${PUBLIC_BASE_URL}/dashboard">Hesabını aç →</a></p>
         ${portalUrl ? `<p><a href="${escapeHtml(portalUrl)}">Abunəliyi idarə et (kart / ləğv)</a></p>` : ''}`,
    );
}

function emailTrialKeyHtml(key) {
    return MAIL_WRAP(
        `<h2>Tokengram trial-ın başladı</h2>
         <p>${TRIAL_DAYS} günlük pulsuz trial-ın aktivdir. Lisenziya açarın (saxla — cihaz bərpası üçün):</p>
         ${KEY_BOX(key)}
         <p>Hesabın: <a href="${PUBLIC_BASE_URL}/dashboard">${PUBLIC_BASE_URL}/dashboard</a></p>`,
    );
}

function emailTrialEndingHtml(key) {
    return MAIL_WRAP(
        `<h2>Trial-ın sabah bitir</h2>
         <p>Pulsuz trial müddətin bitmək üzrədir. Davam etmək üçün ${escapeHtml(PRICE_LABEL)} ilə abunə ol —
            <b>eyni açar avtomatik işləməyə davam edəcək</b>, heç nə dəyişmir.</p>
         <p><a href="${PUBLIC_BASE_URL}/buy?key=${encodeURIComponent(key)}">Abunə ol (${escapeHtml(PRICE_LABEL)}) →</a></p>`,
    );
}

function emailMagicLinkHtml(link) {
    return MAIL_WRAP(
        `<h2>Tokengram-a giriş</h2>
         <p>Hesabına daxil olmaq üçün linkə klik et (15 dəqiqə etibarlıdır):</p>
         <p><a href="${escapeHtml(link)}">${escapeHtml(link)}</a></p>
         <p style="color:#9aa6b8;font-size:12px">Bu linki sən istəməmisənsə, nəzərə alma.</p>`,
    );
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
    // Email könüllüdür və verify gözləmir — sadəcə əlaqə/conversion üçün saxlanır
    // (anti-abuse onsuz da fingerprint-dədir). Yanlış formatı sakitcə nəzərə almırıq.
    const email = String(req.body?.email || '').trim().toLowerCase();
    const validEmail = email && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) && email.length <= 200;
    const now = nowSec();

    const existing = db.prepare('SELECT user_id, license_key FROM trials WHERE fingerprint = ?').get(fp);
    if (existing) {
        // Reinstall halında user email-i indi verə bilər — boşdursa doldur.
        if (validEmail) {
            db.prepare('UPDATE users SET contact_email = ? WHERE id = ? AND contact_email IS NULL')
                .run(email, existing.user_id);
        }
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
        // `email` daxili unikal id-dir (saxta, fingerprint-ə bağlı). Real email
        // (varsa) contact_email-ə gedir — UNIQUE toqquşmasın deyə.
        const internalEmail = `trial-${fp.slice(0, 12)}@trial.tokengram.local`;
        db.prepare('INSERT INTO users (id, email, contact_email, created_at) VALUES (?, ?, ?, ?)')
            .run(userId, internalEmail, validEmail ? email : null, now);
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
        if (validEmail) {
            sendMail({
                to: email,
                subject: 'Tokengram — trial açarın',
                html: emailTrialKeyHtml(created.licenseKey),
                text: `Trial başladı. Açarın: ${created.licenseKey}\nHesab: ${PUBLIC_BASE_URL}/dashboard`,
            }).catch(() => {});
        }
        res.json({ token, expires_at: now + ttl, license_key: created.licenseKey, trial_ends_at: trialEnd });
    } catch (e) {
        console.error('[trial] JWT sign error:', e);
        res.status(500).json({ error: 'jwt_sign_failed' });
    }
});

// ====================================================================
// Lemon Squeezy webhook — abunə statusunun mənbəyi.
//  • İmza: X-Signature = HMAC-SHA256(raw body, LEMON_WEBHOOK_SECRET) hex.
//  • Event adı: X-Event-Name. Data JSON:API formatında body.data.attributes.
//  • Bizim license_key (checkout-da /buy ötürür) body.meta.custom_data-dadır.
// İdempotentdir: Lemon retry edə bilər, ona görə lemon subscription id ilə upsert.
// ====================================================================
function verifyLemonSignature(req) {
    if (!LEMON_WEBHOOK_SECRET || !req.rawBody) return false;
    const sig = String(req.headers['x-signature'] || '');
    if (!sig) return false;
    const digest = crypto.createHmac('sha256', LEMON_WEBHOOK_SECRET).update(req.rawBody).digest('hex');
    try {
        return crypto.timingSafeEqual(Buffer.from(digest, 'utf8'), Buffer.from(sig, 'utf8'));
    } catch {
        return false; // uzunluq fərqi timingSafeEqual-ı throw etdirir
    }
}

// Lemon abunə statusu → bizim sxem statusu.
// Lemon: on_trial, active, paused, past_due, unpaid, cancelled, expired.
// 'cancelled' = ləğv olunub AMMA period sonuna (ends_at) qədər hələ aktivdir →
// 'active' saxlayırıq; vaxt qapısı (current_period_end>now) /validate-də onsuz da kəsir.
// 'expired' = həqiqi bitmə → 'cancelled'.
function mapLemonStatus(s, endsAtInFuture) {
    switch (s) {
        case 'active': return 'active';
        case 'on_trial': return 'trialing';
        case 'cancelled': return endsAtInFuture ? 'active' : 'cancelled';
        case 'expired': return 'cancelled';
        case 'past_due':
        case 'unpaid':
        case 'paused': return 'past_due';
        default: return 'incomplete';
    }
}

app.post('/webhook/lemon', (req, res) => {
    if (!verifyLemonSignature(req)) {
        return res.status(401).json({ error: 'invalid_signature' });
    }
    const eventName = String(req.headers['x-event-name'] || '');
    const body = req.body || {};
    const data = body.data || {};
    const attr = data.attributes || {};
    const custom = (body.meta && body.meta.custom_data) || {};

    // Yalnız abunə OBYEKTİ daşıyan event-lər (subscription_*). payment_success/failed
    // data.type='subscription-invoices'-dir — onları nəzərə almırıq, çünki status
    // dəyişikliyi onsuz da müşayiət edən subscription_updated event-i ilə gəlir.
    if (data.type !== 'subscriptions') {
        return res.json({ ok: true, ignored: eventName, type: data.type || null });
    }

    const lemonSubId = String(data.id || '');
    if (!lemonSubId) return res.status(400).json({ error: 'missing_subscription_id' });
    const lemonStatus = String(attr.status || '');
    const toEpoch = (s) => (s ? Math.floor(new Date(s).getTime() / 1000) : 0);
    const renewsAt = toEpoch(attr.renews_at);
    const endsAt = toEpoch(attr.ends_at);
    const email = String(attr.user_email || '').trim().toLowerCase();
    const licenseKey = String(custom.license_key || '').trim();
    const portalUrl = attr.urls && attr.urls.customer_portal ? String(attr.urls.customer_portal) : null;
    const now = nowSec();

    // period_end: aktivdə renews_at; ləğv/bitmədə ends_at.
    let periodEnd = renewsAt || endsAt || now;
    if ((lemonStatus === 'cancelled' || lemonStatus === 'expired') && endsAt) periodEnd = endsAt;
    const status = mapLemonStatus(lemonStatus, endsAt > now);

    try {
        const trx = db.transaction(() => {
            // 1) İstifadəçi + lisenziyanı tap (prioritet sırası):
            //    (a) bu lemon abunəsi artıq var, (b) custom license_key (trial→paid),
            //    (c) email, (d) heç biri → trial-sız birbaşa alış: yeni hesab.
            let userId = null;
            let key = null;

            const existingSub = db
                .prepare('SELECT user_id FROM subscriptions WHERE polar_subscription_id = ?')
                .get(lemonSubId);
            if (existingSub) userId = existingSub.user_id;

            if (!userId && licenseKey) {
                const lic = db.prepare('SELECT key, user_id FROM licenses WHERE key = ?').get(licenseKey);
                if (lic) { userId = lic.user_id; key = lic.key; }
            }
            if (!userId && email) {
                const u = db
                    .prepare('SELECT id FROM users WHERE contact_email = ? OR email = ? LIMIT 1')
                    .get(email, email);
                if (u) userId = u.id;
            }
            if (!userId) {
                userId = newId('usr_');
                const internalEmail = email || `lemon-${lemonSubId}@buyer.tokengram.local`;
                db.prepare('INSERT INTO users (id, email, contact_email, created_at) VALUES (?, ?, ?, ?)')
                    .run(userId, internalEmail, email || null, now);
            } else if (email) {
                db.prepare('UPDATE users SET contact_email = ? WHERE id = ?').run(email, userId);
            }

            // 2) Lisenziya: trial açarı varsa onu paid-ə yüksəlt (eyni açar → extension
            //    avtomatik active olur, kopyala-yapışdır lazım deyil). Yoxsa yeni yarat.
            if (!key) {
                const lic = db.prepare('SELECT key FROM licenses WHERE user_id = ? ORDER BY created_at ASC LIMIT 1').get(userId);
                if (lic) {
                    key = lic.key;
                } else {
                    key = newId('mla_live_');
                    db.prepare('INSERT INTO licenses (key, user_id, note, created_at) VALUES (?, ?, ?, ?)')
                        .run(key, userId, 'lemon-paid', now);
                }
            }
            // Aktiv statusda revoke-u qaldır + paid kimi qeyd et + köhnə trial
            // abunə sətrini ləğv et. Yoxsa paid abunə bitəndə trialing sətri
            // (öz period_end-i ilə) hələ də müstəqil giriş verə bilər.
            if (status === 'active' || status === 'trialing') {
                db.prepare("UPDATE licenses SET revoked = 0, note = 'lemon-paid' WHERE key = ?").run(key);
                db.prepare(
                    "UPDATE subscriptions SET status = 'cancelled', updated_at = ? " +
                    "WHERE user_id = ? AND plan = 'trial' AND polar_subscription_id != ?",
                ).run(now, userId, lemonSubId);
            }

            // 3) Abunəni upsert et (lemon subscription id ilə açarlanır → idempotent).
            const row = db.prepare('SELECT id FROM subscriptions WHERE polar_subscription_id = ?').get(lemonSubId);
            if (row) {
                db.prepare('UPDATE subscriptions SET status = ?, current_period_end = ?, plan = ?, portal_url = COALESCE(?, portal_url), updated_at = ? WHERE id = ?')
                    .run(status, periodEnd, 'monthly', portalUrl, now, row.id);
            } else {
                db.prepare(
                    `INSERT INTO subscriptions
                       (id, user_id, polar_subscription_id, status, current_period_end, plan, portal_url, created_at, updated_at)
                     VALUES (?, ?, ?, ?, ?, 'monthly', ?, ?, ?)`,
                ).run(newId('sub_'), userId, lemonSubId, status, periodEnd, portalUrl, now, now);
            }
            return { userId, key, isNew: !row };
        });
        const out = trx();
        logAudit('system-lemon', `webhook_${eventName}`, out.key, {
            lemonSubId, lemonStatus, status, periodEnd, email: email.slice(0, 60),
        });
        // İlk dəfə aktivləşmədə user-ə açar + portal maili (best-effort, bloklamır).
        if (out.isNew && status === 'active' && email) {
            sendMail({
                to: email,
                subject: 'Tokengram — abunəliyin aktivdir 🎉',
                html: emailActiveHtml(out.key, portalUrl),
                text: `Abunəliyin aktivdir. Lisenziya açarın: ${out.key}\nHesab: ${PUBLIC_BASE_URL}/dashboard`,
            }).catch(() => {});
        }
        res.json({ ok: true });
    } catch (e) {
        console.error('[webhook/lemon] error:', e);
        res.status(500).json({ error: 'webhook_processing_failed' });
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
// Customer hesab — parolsuz magic-link sign-in + dashboard.
// Admin session-dan ayrıdır (req.session.userEmail vs adminEmail).
// ====================================================================
function requireUser(req, res, next) {
    if (!req.session.userEmail) return res.status(401).json({ error: 'unauthorized' });
    next();
}
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

// Giriş linki istə — mail göndərilir. Hesab tapılsa da tapılmasa da eyni cavab
// (email mövcudluğunu sızdırmırıq).
app.post('/auth/request-link', async (req, res) => {
    const email = String(req.body?.email || '').trim().toLowerCase();
    if (!email || !EMAIL_RE.test(email) || email.length > 200) {
        return res.status(400).json({ error: 'invalid_email' });
    }
    const user = db.prepare('SELECT id FROM users WHERE contact_email = ? OR email = ? LIMIT 1').get(email, email);
    if (user) {
        const token = crypto.randomBytes(32).toString('hex');
        const now = nowSec();
        db.prepare('INSERT INTO magic_links (token, email, expires_at, created_at) VALUES (?, ?, ?, ?)')
            .run(token, email, now + 15 * 60, now);
        const link = `${PUBLIC_BASE_URL}/auth/verify?token=${token}`;
        await sendMail({
            to: email,
            subject: 'Tokengram — giriş linki',
            html: emailMagicLinkHtml(link),
            text: `Giriş linki (15 dəq): ${link}`,
        }).catch(() => {});
    }
    res.json({ ok: true });
});

app.get('/auth/verify', (req, res) => {
    const token = String(req.query.token || '');
    const now = nowSec();
    const row = db.prepare('SELECT token, email, expires_at, used_at FROM magic_links WHERE token = ?').get(token);
    if (!row || row.used_at || row.expires_at < now) {
        return res.status(400).type('html').send(
            '<p style="font-family:sans-serif">Link etibarsız və ya vaxtı keçib. <a href="/dashboard">Yenidən cəhd et</a></p>',
        );
    }
    db.prepare('UPDATE magic_links SET used_at = ? WHERE token = ?').run(now, token);
    req.session.userEmail = row.email;
    res.redirect(302, '/dashboard');
});

app.post('/auth/logout', (req, res) => {
    delete req.session.userEmail;
    res.json({ ok: true });
});

// Hesab məlumatı (JSON) — dashboard JS bunu çəkir.
app.get('/account', requireUser, (req, res) => {
    const email = req.session.userEmail;
    const rows = db
        .prepare(
            `SELECT l.key, l.machine_fingerprint, l.revoked, l.last_rebind_at, l.note,
                    (SELECT s.status FROM subscriptions s WHERE s.user_id = l.user_id
                       ORDER BY s.current_period_end DESC LIMIT 1) AS status,
                    (SELECT s.current_period_end FROM subscriptions s WHERE s.user_id = l.user_id
                       ORDER BY s.current_period_end DESC LIMIT 1) AS expires_at,
                    (SELECT s.portal_url FROM subscriptions s WHERE s.user_id = l.user_id
                       ORDER BY s.current_period_end DESC LIMIT 1) AS portal_url
             FROM licenses l JOIN users u ON u.id = l.user_id
             WHERE (u.contact_email = ? OR u.email = ?) AND l.revoked = 0
             ORDER BY l.created_at DESC`,
        )
        .all(email, email);
    res.json({ email, price_label: PRICE_LABEL, rebind_cooldown_days: REBIND_COOLDOWN_DAYS, keys: rows });
});

// Cihazı boşalt (re-bind) — açarı cari maşından ayırır ki, yeni maşında
// activate olunsun. Cooldown açarın çox nəfər arasında gəzməsini dayandırır.
app.post('/account/release-device', requireUser, (req, res) => {
    const email = req.session.userEmail;
    const key = String(req.body?.license_key || '');
    const lic = db
        .prepare(
            `SELECT l.key, l.last_rebind_at FROM licenses l JOIN users u ON u.id = l.user_id
             WHERE l.key = ? AND (u.contact_email = ? OR u.email = ?)`,
        )
        .get(key, email, email);
    if (!lic) return res.status(404).json({ error: 'not_found' });
    const now = nowSec();
    const cooldown = REBIND_COOLDOWN_DAYS * 86400;
    if (lic.last_rebind_at && now - lic.last_rebind_at < cooldown) {
        const daysLeft = Math.ceil((cooldown - (now - lic.last_rebind_at)) / 86400);
        return res.status(429).json({ error: 'cooldown', days_left: daysLeft });
    }
    db.prepare('UPDATE licenses SET machine_fingerprint = NULL, activated_at = NULL, last_rebind_at = ? WHERE key = ?')
        .run(now, key);
    logAudit('user-' + email, 'release_device', key, null);
    res.json({ ok: true });
});

// Dashboard — tək səhifə. JS /account-u çəkir: 401 → giriş formu, 200 → açarlar.
app.get('/dashboard', (_req, res) => {
    res.type('html').send(`<!doctype html>
<html lang="az"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tokengram — Hesab</title><link rel="icon" type="image/png" href="/icon.png">
<style>
  :root{--bg:#070b14;--card:rgba(17,25,45,.6);--ln:rgba(77,144,255,.3);--fg:#e8edf7;--mut:#93a0b8;--acc:#4d90ff}
  *{box-sizing:border-box} body{font-family:"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0;min-height:100vh;display:grid;place-items:center;padding:20px}
  .card{width:100%;max-width:560px;padding:32px;border:1px solid var(--ln);border-radius:16px;background:var(--card)}
  h1{font-size:1.3rem;margin:0 0 4px} .mut{color:var(--mut);font-size:.9rem}
  input{width:100%;padding:11px 13px;border-radius:9px;border:1px solid var(--ln);background:#0c1322;color:var(--fg);font-size:1rem;margin:14px 0}
  button,a.btn{display:inline-block;padding:10px 18px;border:0;border-radius:9px;background:linear-gradient(135deg,#2f6fe0,#4d90ff);color:#fff;font-weight:600;font-size:.95rem;cursor:pointer;text-decoration:none}
  .ghost{background:none;border:1px solid var(--ln);color:var(--fg)}
  .key{font-family:monospace;background:#0c1322;border:1px solid var(--ln);border-radius:8px;padding:10px 12px;word-break:break-all;margin:8px 0}
  .row{border-top:1px solid var(--ln);padding:16px 0} .row:first-child{border-top:0}
  .tag{font-size:.75rem;padding:2px 8px;border-radius:20px;background:rgba(77,144,255,.15);color:#9cc2ff}
  .tag.warn{background:rgba(255,170,60,.15);color:#ffce8a} .tag.bad{background:rgba(255,90,90,.15);color:#ff9b9b}
  .hide{display:none} .msg{color:#9cc2ff;font-size:.9rem;margin-top:10px}
</style></head><body>
<div class="card">
  <div id="signin">
    <h1>Tokengram hesabı</h1>
    <p class="mut">Email-ini yaz — giriş linki göndərək (parol yoxdur).</p>
    <input id="email" type="email" placeholder="sən@example.com" autocomplete="email">
    <button id="send">Giriş linki göndər</button>
    <div id="m1" class="msg hide"></div>
  </div>
  <div id="account" class="hide">
    <h1>Hesabın</h1>
    <p class="mut"><span id="who"></span> · <a href="#" id="logout" class="mut">çıxış</a></p>
    <div id="keys"></div>
  </div>
</div>
<script>
const $=s=>document.querySelector(s);
function fmtDate(t){return t?new Date(t*1000).toLocaleDateString():'—'}
$('#send').onclick=async()=>{
  const email=$('#email').value.trim(); if(!email)return;
  await fetch('/auth/request-link',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({email})});
  const m=$('#m1');m.textContent='Linki '+email+' ünvanına göndərdik. Mailini yoxla.';m.classList.remove('hide');
};
$('#logout').onclick=async(e)=>{e.preventDefault();await fetch('/auth/logout',{method:'POST'});location.reload();};
async function release(key,btn){
  btn.disabled=true;
  const r=await fetch('/account/release-device',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({license_key:key})});
  if(r.status===429){const j=await r.json();alert('Cooldown: '+j.days_left+' gün sonra mümkün olacaq.');btn.disabled=false;return;}
  if(!r.ok){alert('Alınmadı.');btn.disabled=false;return;}
  alert('Cihaz boşaldıldı. İndi yeni maşında extension-da açarı işlət.');load();
}
async function load(){
  const r=await fetch('/account');
  if(r.status===401){$('#signin').classList.remove('hide');$('#account').classList.add('hide');return;}
  const d=await r.json();
  $('#signin').classList.add('hide');$('#account').classList.remove('hide');
  $('#who').textContent=d.email;
  $('#keys').innerHTML=d.keys.map(k=>{
    const active=(k.status==='active'||k.status==='trialing')&&k.expires_at&&k.expires_at>Date.now()/1000;
    const tag=active?'<span class="tag">'+(k.status==='trialing'?'trial':'aktiv')+'</span>':'<span class="tag bad">deaktiv</span>';
    const manage=k.portal_url?'<a class="btn ghost" href="'+k.portal_url+'">Abunəliyi idarə et</a>':
      '<a class="btn" href="/buy?key='+encodeURIComponent(k.key)+'&email='+encodeURIComponent(d.email)+'">Abunə ol ('+d.price_label+')</a>';
    return '<div class="row">'+tag+' <span class="mut">bitmə: '+fmtDate(k.expires_at)+'</span>'+
      '<div class="key">'+k.key+'</div>'+
      (k.machine_fingerprint?'<button class="ghost" data-k="'+k.key+'">Cihazı boşalt (yeni maşına keç)</button> ':'<span class="mut">heç bir cihaza bağlı deyil</span> ')+
      manage+'</div>';
  }).join('')||'<p class="mut">Açar yoxdur.</p>';
  document.querySelectorAll('[data-k]').forEach(b=>b.onclick=()=>release(b.dataset.k,b));
}
load();
</script>
</body></html>`);
});

// ====================================================================
// /buy — Lemon Squeezy checkout-a yönləndirir.
// license_key (varsa) custom data kimi ötürülür ki, ödəniş webhook-da mövcud
// trial açarına bağlansın (eyni açar paid-ə yüksəlir → extension-da kopyala yox).
// LEMON_CHECKOUT_URL .env-də yoxdursa nəzakətli "tezliklə" səhifəsi göstərilir.
// ====================================================================
app.get('/buy', (req, res) => {
    if (!LEMON_CHECKOUT_URL) {
        return res.status(503).type('html').send(`<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tokengram — Checkout</title><link rel="icon" type="image/png" href="/icon.png">
<style>body{font-family:"Segoe UI",system-ui,sans-serif;background:#070b14;color:#e8edf7;display:grid;place-items:center;min-height:100vh;margin:0;text-align:center}
.card{max-width:420px;padding:40px 32px;border:1px solid rgba(77,144,255,.3);border-radius:16px;background:rgba(17,25,45,.6)}
h1{font-size:1.3rem;margin:18px 0 6px}p{color:#93a0b8;font-size:.92rem;line-height:1.55}</style></head>
<body><div class="card"><h1>Checkout opens very soon</h1><p>Ödəniş (${PRICE_LABEL}) hazırlanır — tezliklə.</p></div></body></html>`);
    }
    const licenseKey = String(req.query.key || req.query.license_key || '').trim();
    const email = String(req.query.email || '').trim();
    let url;
    try {
        url = new URL(LEMON_CHECKOUT_URL);
    } catch {
        return res.status(500).type('text').send('LEMON_CHECKOUT_URL səhvdir');
    }
    if (email) url.searchParams.set('checkout[email]', email);
    if (licenseKey) url.searchParams.set('checkout[custom][license_key]', licenseKey);
    res.redirect(302, url.toString());
});

// ---- Static UI ----
// Admin paneli /admin/ altına köçdü; kök (/) artıq tokengram.click landing-i verir.
app.use('/admin', express.static(path.join(__dirname, 'public')));
app.use('/', express.static(path.join(__dirname, 'site')));

// ====================================================================
// "Trial sabah bitir" xatırlatması — conversion driver. 12 saatda bir:
// trialing + 24 saata bitir + email var + hələ xəbərdarlıq göndərilməyib.
// ====================================================================
function runTrialReminders() {
    try {
        const now = nowSec();
        const rows = db
            .prepare(
                `SELECT t.fingerprint, t.license_key, u.contact_email AS email, s.current_period_end
                 FROM trials t
                 JOIN users u ON u.id = t.user_id
                 JOIN subscriptions s ON s.user_id = t.user_id AND s.status = 'trialing'
                 WHERE t.reminded_at IS NULL AND u.contact_email IS NOT NULL
                   AND s.current_period_end > ? AND s.current_period_end < ?`,
            )
            .all(now, now + 86400);
        for (const r of rows) {
            sendMail({
                to: r.email,
                subject: 'Tokengram — trial-ın sabah bitir',
                html: emailTrialEndingHtml(r.license_key),
                text: `Trial-ın sabah bitir. Abunə ol: ${PUBLIC_BASE_URL}/buy?key=${encodeURIComponent(r.license_key)}`,
            }).catch(() => {});
            db.prepare('UPDATE trials SET reminded_at = ? WHERE fingerprint = ?').run(now, r.fingerprint);
        }
        if (rows.length) console.log(`[reminder] ${rows.length} trial-bitmə maili göndərildi`);
    } catch (e) {
        console.error('[reminder] xəta:', e.message);
    }
}
setInterval(runTrialReminders, 12 * 60 * 60 * 1000).unref();
setTimeout(runTrialReminders, 30 * 1000).unref(); // boot-dan 30s sonra bir dəfə

app.listen(PORT, '0.0.0.0', () => {
    console.log(`[tokengram-admin] http://0.0.0.0:${PORT}`);
});

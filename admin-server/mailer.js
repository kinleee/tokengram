'use strict';
// Generic SMTP mailer — SES SMTP / Mailgun / Gmail, fərq etmir (heç nəyə kilidlənmirik).
// SMTP konfiqi yoxdursa VƏ YA nodemailer quraşdırılmayıbsa: səssiz skip (link log-a düşür).
// Beləcə kod SMTP qurulmamış da işləyir; mail göndərmə sadəcə konfiq məsələsidir.

const SMTP_HOST = (process.env.SMTP_HOST || '').trim();
const SMTP_PORT = parseInt(process.env.SMTP_PORT || '587', 10);
const SMTP_SECURE = String(process.env.SMTP_SECURE || '').toLowerCase() === 'true' || SMTP_PORT === 465;
const SMTP_USER = (process.env.SMTP_USER || '').trim();
const SMTP_PASS = (process.env.SMTP_PASS || '').trim();
const MAIL_FROM = (process.env.MAIL_FROM || 'Tokengram <no-reply@tokengram.click>').trim();

let _transport = null;
let _tried = false;

function transport() {
    if (_tried) return _transport;
    _tried = true;
    if (!SMTP_HOST || !SMTP_USER || !SMTP_PASS) return null;
    try {
        const nodemailer = require('nodemailer');
        _transport = nodemailer.createTransport({
            host: SMTP_HOST,
            port: SMTP_PORT,
            secure: SMTP_SECURE,
            auth: { user: SMTP_USER, pass: SMTP_PASS },
        });
    } catch (e) {
        console.warn('[mailer] nodemailer yoxdur / SMTP konfiq xətası:', e.message);
        _transport = null;
    }
    return _transport;
}

async function sendMail({ to, subject, html, text }) {
    const t = transport();
    if (!t) {
        console.log(`[mailer] SKIP (SMTP konfiq yox) → ${to}: ${subject}`);
        return { skipped: true };
    }
    try {
        const info = await t.sendMail({ from: MAIL_FROM, to, subject, html, text: text || undefined });
        return { ok: true, id: info.messageId };
    } catch (e) {
        console.error('[mailer] göndərmə xətası:', e.message);
        return { error: e.message };
    }
}

module.exports = { sendMail, mailerConfigured: () => !!transport() };

// Tokengram admin UI — vanilla JS, single page.
(function () {
    const $ = (sel) => document.querySelector(sel);
    const topbar = $('#topbar');
    const loginView = $('#loginView');
    const adminView = $('#adminView');
    const who = $('#who');
    const msg = $('#msg');
    const keysBody = $('#keysBody');
    const searchBox = $('#searchBox');

    async function api(method, path, body) {
        const opts = { method, headers: {}, credentials: 'same-origin' };
        if (body !== undefined) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        const r = await fetch(path, opts);
        const ct = r.headers.get('content-type') || '';
        const data = ct.includes('application/json') ? await r.json() : await r.text();
        return { ok: r.ok, status: r.status, data };
    }

    function flash(text, isErr) {
        msg.textContent = text;
        msg.classList.toggle('err', !!isErr);
        msg.hidden = false;
        setTimeout(() => (msg.hidden = true), 4000);
    }

    function fmtTs(ts) {
        if (!ts) return '—';
        const d = new Date(ts * 1000);
        return d.toISOString().slice(0, 10);
    }

    function shortFp(fp) {
        if (!fp) return '—';
        return fp.length > 14 ? fp.slice(0, 10) + '…' : fp;
    }

    function statusPill(row) {
        const now = Math.floor(Date.now() / 1000);
        if (row.revoked) return '<span class="pill revoked">revoked</span>';
        if (!row.status) return '<span class="pill expired">no_sub</span>';
        if (row.expires_at && row.expires_at < now) return '<span class="pill expired">expired</span>';
        return `<span class="pill active">${row.status}</span>`;
    }

    function rowHtml(r) {
        const revoked = r.revoked === 1;
        const restoreBtn = revoked
            ? `<button data-action="restore" data-key="${r.key}">Aktiv et</button>`
            : `<button class="danger" data-action="revoke" data-key="${r.key}">Deaktiv et</button>`;
        return `
            <tr>
                <td>${escapeHtml(r.email)}</td>
                <td><code>${escapeHtml(r.key)}</code></td>
                <td>${escapeHtml(r.plan || '—')}</td>
                <td>${statusPill(r)}</td>
                <td>${fmtTs(r.expires_at)}</td>
                <td title="${escapeHtml(r.machine_fingerprint || '')}">${escapeHtml(shortFp(r.machine_fingerprint))}</td>
                <td class="muted">${escapeHtml(r.note || '')}</td>
                <td>
                    <div class="actions">
                        ${restoreBtn}
                        <button data-action="reset-fp" data-key="${r.key}">FP-i sıfırla</button>
                        <button data-action="extend" data-key="${r.key}">+30 gün</button>
                        <button data-action="copy" data-key="${r.key}">Kopyala</button>
                    </div>
                </td>
            </tr>`;
    }

    function escapeHtml(s) {
        return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    async function loadKeys() {
        const q = searchBox.value.trim();
        const { ok, data } = await api('GET', '/admin/keys' + (q ? `?q=${encodeURIComponent(q)}` : ''));
        if (!ok) {
            flash('Keys yüklənmədi: ' + (data?.error || ''), true);
            return;
        }
        keysBody.innerHTML = data.rows.map(rowHtml).join('') || '<tr><td colspan="8" class="muted" style="text-align:center;padding:24px">Hələ key yoxdur.</td></tr>';
    }

    async function checkSession() {
        const { ok, data } = await api('GET', '/admin/me');
        if (ok) {
            who.textContent = data.email;
            loginView.hidden = true;
            adminView.hidden = false;
            topbar.hidden = false;
            await loadKeys();
        } else {
            loginView.hidden = false;
            adminView.hidden = true;
            topbar.hidden = true;
        }
    }

    // ---- login ----
    $('#loginForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const { ok, data } = await api('POST', '/admin/login', {
            email: fd.get('email'),
            password: fd.get('password'),
        });
        const err = $('#loginErr');
        if (!ok) {
            err.textContent = data?.error === 'invalid_credentials' ? 'Email ya şifrə yanlışdır' : 'Xəta: ' + (data?.error || '');
            err.hidden = false;
            return;
        }
        err.hidden = true;
        await checkSession();
    });

    $('#logoutBtn').addEventListener('click', async () => {
        await api('POST', '/admin/logout');
        location.reload();
    });

    // ---- create ----
    const dlg = $('#createDialog');
    $('#createBtn').addEventListener('click', () => dlg.showModal());
    $('#cancelCreate').addEventListener('click', () => dlg.close());
    $('#createForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const body = {
            email: fd.get('email'),
            plan: fd.get('plan'),
            duration_days: parseInt(fd.get('duration_days'), 10),
            note: fd.get('note'),
        };
        const { ok, data } = await api('POST', '/admin/keys', body);
        if (!ok) {
            flash('Yaradılmadı: ' + (data?.error || ''), true);
            return;
        }
        dlg.close();
        $('#newKey').textContent = data.key;
        $('#resultExpiry').textContent = 'Bitmə tarixi: ' + fmtTs(data.expires_at);
        $('#resultDialog').showModal();
        await loadKeys();
    });

    $('#closeResult').addEventListener('click', () => $('#resultDialog').close());
    $('#copyKey').addEventListener('click', () => {
        navigator.clipboard.writeText($('#newKey').textContent).then(() => flash('Panoya köçürüldü.'));
    });

    // ---- search + refresh ----
    let searchTimer;
    searchBox.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(loadKeys, 200);
    });
    $('#refreshBtn').addEventListener('click', loadKeys);

    // ---- row actions ----
    keysBody.addEventListener('click', async (e) => {
        const btn = e.target.closest('button[data-action]');
        if (!btn) return;
        const key = btn.dataset.key;
        const action = btn.dataset.action;
        if (action === 'copy') {
            navigator.clipboard.writeText(key).then(() => flash('Key panoya köçürüldü.'));
            return;
        }
        if (action === 'revoke' && !confirm(`'${key}' deaktiv olunsun?`)) return;
        if (action === 'reset-fp' && !confirm(`'${key}' fingerprint sıfırlansın? (yenidən aktivasiya tələb olunacaq)`)) return;

        let url = null;
        let body = undefined;
        if (action === 'revoke') url = `/admin/keys/${encodeURIComponent(key)}/revoke`;
        else if (action === 'restore') url = `/admin/keys/${encodeURIComponent(key)}/restore`;
        else if (action === 'reset-fp') url = `/admin/keys/${encodeURIComponent(key)}/reset-fingerprint`;
        else if (action === 'extend') {
            url = `/admin/keys/${encodeURIComponent(key)}/extend`;
            body = { days: 30 };
        }
        if (!url) return;
        const { ok, data } = await api('POST', url, body);
        if (!ok) flash('Əməliyyat alınmadı: ' + (data?.error || ''), true);
        else {
            flash('Uğurla yerinə yetirildi.');
            await loadKeys();
        }
    });

    checkSession();
})();

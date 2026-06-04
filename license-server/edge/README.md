# Edge proxy: `https://tokengram.click` → EC2 license app (`:3000`)

The VS Code extension calls the license API over **`https://tokengram.click`** (port
443, TLS). The app currently serves only **`http://54.163.13.24:3000`** (plain HTTP,
no TLS, port 3000). So pointing DNS alone is **not** enough — we need HTTPS on :443
forwarding to :3000. Caddy does that with an auto-renewing Let's Encrypt cert.

```
browser/extension ──HTTPS:443──► Caddy (on EC2) ──HTTP:3000──► license app
        tokengram.click
```

## What needs YOUR account access (3 steps I can't do)

1. **Namecheap DNS** — remove the parking record, add:
   | Type | Host | Value          | TTL       |
   |------|------|----------------|-----------|
   | A    | `@`  | `54.163.13.24` | Automatic |

   (Currently `tokengram.click` → `162.255.119.28`, Namecheap parking. That's why
   `https://tokengram.click` hangs: nothing listens on its :443.)

2. **AWS security group** for the EC2 instance — add inbound rules:
   - TCP **443** from `0.0.0.0/0`
   - TCP **80** from `0.0.0.0/0`  ← required for the ACME HTTP-01 cert challenge

3. **On the EC2 box**, run the installer (one command):
   ```bash
   sudo bash setup-caddy.sh
   ```
   (Copy `setup-caddy.sh` to the box first, e.g. `scp` it, or paste it.)

## Verify

From any machine:
```bash
curl -sS https://tokengram.click/pubkey                       # expect the PEM
curl -sS -X POST https://tokengram.click/check-key \
     -H 'content-type: application/json' \
     -d '{"license_key":"mla_live_382c1d241d3dd984"}'         # expect valid=true
```

Once this works, the extension's existing default (`https://tokengram.click`) works
with **no code change** — and the tester-onboarding `AbortError` (fresh machine with
no `server_url.txt` → dead default) disappears.

## Notes
- The app already listens on `0.0.0.0:3000`, so Caddy's `localhost:3000` reaches it.
- Hardening (optional, later): once Caddy is in front, restrict inbound `:3000` in the
  security group so the app is only reachable via HTTPS.
- Cert auto-renews. Caddy stores it under `/var/lib/caddy`.

# Phase 4 — License Server Architecture

**Hədəf:** $0/ay infrastruktur ilə ödəniş + token validation + subscription idarəetməsi.
**Müddət:** 1 həftə (Cloudflare-də ilk dəfə işləyirsənsə, +2-3 gün öyrənmə).
**Risk səviyyəsi:** Aşağı — bütün komponentlər well-trodden, free tier-lər real istifadəyə yetir.

## Yüksək səviyyəli axış

```
┌──────────────┐  1. Stripe/Polar checkout    ┌──────────────┐
│   User       │ ──────────────────────────▶  │  Polar.sh    │
│  (browser)   │                              │  (MoR + VAT) │
└──────────────┘                              └──────┬───────┘
       │                                              │ 2. webhook: subscription.created
       │                                              ▼
       │                                       ┌──────────────┐
       │ 5. token validation                   │ Cloudflare   │
       │ (POST /validate)                      │ Worker       │
       │ ◀────────────────────────────────────▶│ + D1 (SQLite)│
       │                                       │ + KV (cache) │
       ▼                                       └──────────────┘
┌──────────────┐
│ Rust binary  │
│ (extension)  │  4. JWT verify (RSA public key local)
└──────────────┘
```

## Komponentlər və xərc

| Komponent | Servis | Free limit | Xərc 1k user-də |
|---|---|---|---|
| API | Cloudflare Workers | 100k req/gün | $0 |
| DB | Cloudflare D1 | 5GB, 5M read/gün, 100k write/gün | $0 |
| Cache | Cloudflare KV | 100k read/gün, 1k write/gün | $0 |
| Landing page | Cloudflare Pages | Limitsiz | $0 |
| Ödəniş | Polar.sh | — | 4% + $0.40 / tranzaksiya |
| Email | Resend | 3k mail/ay | $0 |
| Domain | (sənin seçimin) | — | ~$12/il |

**1000 user × $5/ay = $5000/ay gəlir**. Polar komissiyası ~$200. **Net: $4800/ay, infrastruktur xərci $0.**

## D1 sxema

```sql
CREATE TABLE users (
  id TEXT PRIMARY KEY,           -- uuid
  email TEXT UNIQUE NOT NULL,
  polar_customer_id TEXT UNIQUE,
  created_at INTEGER NOT NULL
);

CREATE TABLE subscriptions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  polar_subscription_id TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL,          -- active | cancelled | past_due
  current_period_end INTEGER NOT NULL,
  plan TEXT NOT NULL,            -- 'pro_monthly' | 'pro_yearly'
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE licenses (
  key TEXT PRIMARY KEY,          -- token user paste edir, məs. mla_live_xxx
  user_id TEXT NOT NULL REFERENCES users(id),
  machine_fingerprint TEXT,      -- ilk activation-da yazılır
  activated_at INTEGER,
  revoked INTEGER DEFAULT 0,
  created_at INTEGER NOT NULL
);

CREATE INDEX idx_subs_user ON subscriptions(user_id);
CREATE INDEX idx_lic_user ON licenses(user_id);
```

## API endpoints (Cloudflare Worker)

### `POST /activate`

User extension-da license key + machine fingerprint göndərir.

**Request:**
```json
{
  "license_key": "mla_live_abc123...",
  "machine_fingerprint": "sha256(cpu_id + hostname + mac)"
}
```

**Logic:**
1. `licenses` cədvəlində açarı tap
2. Subscription `active` olub-olmadığını yoxla
3. `machine_fingerprint` artıq varsa → fərqlidirsə 403
4. Boşdursa → bu fingerprint-i yaz, activated_at qeyd et
5. JWT yarad: `{user_id, license_key, fingerprint, exp: now+7days}` (RS256)
6. JWT-ni qaytar

**Response:**
```json
{
  "token": "eyJ...",
  "expires_at": 1715000000
}
```

### `POST /validate`

Extension hər başlanğıcda (və ya 7 gündən tez-tez) yenidən token alır.

**Request:** `Authorization: Bearer <old_jwt>`

**Logic:**
1. JWT-ni RS256 public key ilə verify et
2. Expired olubsa → DB-də subscription yenidən yoxla
3. Aktivdirsə → yeni JWT qaytar
4. Cancelled/past_due → 401

### `POST /webhook/polar`

Polar.sh webhook-ları:
- `subscription.created` → `subscriptions` cədvəlinə yaz + license_key yarad
- `subscription.updated` → status yenilə
- `subscription.cancelled` → status='cancelled', current_period_end-i hörmət et
- `subscription.past_due` → status='past_due', 7 gün sonra disable

**Webhook signature** verify et (Polar HMAC göndərir).

### `GET /me` (opsional, debug üçün)

User-ə öz subscription məlumatını qaytarır. Browser-də debug üçün.

## JWT açar çiftəliyi

```bash
# RSA 2048 generate et (bir dəfəlik)
openssl genrsa -out private.pem 2048
openssl rsa -in private.pem -pubout -out public.pem
```

- **Private key:** yalnız Cloudflare Worker secret olaraq saxlanır
  ```bash
  wrangler secret put JWT_PRIVATE_KEY
  ```
- **Public key:** Rust binary-də compile edilir (base64-encoded const). Çünki public-dir, kodda olması problem deyil.

Rust-da verify:
```rust
const PUBLIC_KEY_PEM: &[u8] = include_bytes!("../keys/jwt_public.pem");

fn verify_token(token: &str) -> Result<Claims> {
    let key = DecodingKey::from_rsa_pem(PUBLIC_KEY_PEM)?;
    let validation = Validation::new(Algorithm::RS256);
    let data = decode::<Claims>(token, &key, &validation)?;
    Ok(data.claims)
}
```

## Machine fingerprint strategiyası

```rust
fn machine_fingerprint() -> String {
    let cpu = machine_uid::get().unwrap_or_default();
    let host = hostname::get()
        .map(|h| h.to_string_lossy().to_string())
        .unwrap_or_default();
    let combined = format!("{cpu}|{host}");
    let hash = sha2::Sha256::digest(combined.as_bytes());
    hex::encode(hash)
}
```

**Faydası:**
- Eyni user iki PC-də istifadə etmək istəsə → 403, "license another machine-də aktiv"
- "Deactivate" endpoint-i lazımdır (user portal-da düymə): köhnə fingerprint sıfırla
- Hardware dəyişdirmə (yeni motherboard) → user support → manual reset

**Limitlər:**
- Disk image (VM clone) ilə paylaşıla bilər → bunu blocklemək üçün periodic re-validation şərtdir
- Çoxlu user paylaşan tək machine → fingerprint dəyişmir, problem yox

## Trial flow

- Polar.sh checkout-da "14-day free trial" seç (Polar dəstəkləyir)
- Webhook: `subscription.trialing` status-u göndərir
- Bizim DB-də eyni mantiq, status='trialing' qəbul edilir aktiv kimi
- Trial sonu: 24 saat əvvəlcədən email (Resend ilə)

## Refund policy

- 30 gün ərzində ilk ödəniş → tam refund (Polar dashboard-da bir click)
- 30 gün+ → no refund (subscription cancel only)
- Bu policy-ni Polar.sh-də konfiqurasiya et, manual webhook lazım deyil

## Build & deploy

```bash
# Wrangler CLI quraşdır
npm install -g wrangler

# Project init
mkdir mla-license-server && cd mla-license-server
wrangler init --type ts

# Secret-ləri əlavə et
wrangler secret put JWT_PRIVATE_KEY
wrangler secret put POLAR_WEBHOOK_SECRET

# D1 DB yarat
wrangler d1 create mla-licenses
# wrangler.toml-da binding əlavə et

# Sxemanı tətbiq et
wrangler d1 execute mla-licenses --file=schema.sql

# Deploy
wrangler deploy
```

Deploy həm staging həm production:
```bash
wrangler deploy --env staging
wrangler deploy --env production
```

## İnkişaf sırası (5–7 gün)

| Gün | Tapşırıq |
|---|---|
| 1 | Cloudflare Workers + D1 setup, sxema yazılır |
| 2 | `POST /activate` + `POST /validate` endpoints |
| 3 | JWT issue/verify, RSA açar quruluşu |
| 4 | Polar.sh hesab, webhook endpoint |
| 5 | Landing page (Cloudflare Pages, sadə HTML) |
| 6 | End-to-end test: kart ödə → license → activate → validate |
| 7 | Rust extension-da inteqrasiya |

## Tamamlanma kriterileri

- ☐ Test ödənişi Polar.sh-də işləyir (test mode)
- ☐ Webhook D1-də user və subscription yaradır
- ☐ `/activate` endpoint license_key alır, JWT qaytarır
- ☐ `/validate` endpoint JWT yeniləyir
- ☐ Etibarsız token / expired subscription 401 verir
- ☐ Rust binary token-i verify edib MCP tool-larını aktivləşdirir
- ☐ 1000 saxta request load test problemsiz keçir

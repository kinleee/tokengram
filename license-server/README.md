# Tokengram License Server

Cloudflare Workers + D1 üzərində qurulmuş, Polar.sh ödənişlərini qəbul edən və JWT lisenziya token-ləri buraxan minimal license server.

**Status:** Functional MVP. Bütün əsas endpoint-lər (`/activate`, `/validate`, `/deactivate`, `/webhook/polar`) implement olunub, Polar.sh field mapping və HMAC-SHA256 imza verify daxildir. Real deploy üçün D1 + KV id-lərini wrangler.toml-da əvəz et və secrets qoy.

## Arxitektura

Phase 4 plan-ında geniş izah olunub: [../launch-prep/04-license-server.md](../launch-prep/04-license-server.md)

## Quraşdırma

```bash
# 1. Dependencies
npm install

# 2. Cloudflare hesabına login
npx wrangler login

# 3. D1 DB yarat
npm run db:create
# → çıxan database_id-ni wrangler.toml-da REPLACE_WITH_REAL_DB_ID yerinə yaz

# 4. KV namespace yarat
npx wrangler kv:namespace create CACHE
# → çıxan id-ni wrangler.toml-da REPLACE_WITH_REAL_KV_ID yerinə yaz

# 5. Sxema tətbiq et
npm run db:migrate           # lokal
npm run db:migrate:remote    # production

# 6. Secrets əlavə et
npx wrangler secret put JWT_PRIVATE_KEY        # RSA private key (PEM)
npx wrangler secret put POLAR_WEBHOOK_SECRET   # Polar.sh HMAC secret
npx wrangler secret put POLAR_API_KEY          # Polar.sh API key
```

## JWT açar çiftəliyi yaratmaq

```bash
# RSA 2048
openssl genrsa -out keys/jwt_private.pem 2048
openssl rsa -in keys/jwt_private.pem -pubout -out keys/jwt_public.pem

# Private-i Cloudflare secret-ə qoy:
cat keys/jwt_private.pem | npx wrangler secret put JWT_PRIVATE_KEY

# Public-i Rust binary-də compile et (kodda const)
```

## Lokal inkişaf

```bash
npm run dev
# → http://localhost:8787

# Test request
curl -X POST http://localhost:8787/activate \
  -H "Content-Type: application/json" \
  -d '{"license_key":"mla_live_test","machine_fingerprint":"abc123"}'
```

## Deploy

```bash
npm run deploy:staging
# Smoke test: curl staging URL

npm run deploy:production
```

## Endpoints

| Method | Path | Açıklama |
|---|---|---|
| GET | `/` | Health check |
| POST | `/activate` | İlk activation: license_key + fingerprint → JWT |
| POST | `/validate` | Token refresh: köhnə JWT → yeni JWT |
| POST | `/deactivate` | Machine fingerprint sıfırla (PC dəyişəndə) |
| POST | `/webhook/polar` | Polar.sh webhook qəbulu (HMAC-SHA256 verify, anti-replay) |

## Implement olunmuş

- ✅ HMAC-SHA256 webhook signature verify (Standard Webhooks spec)
- ✅ 5-dəq anti-replay timestamp yoxlaması
- ✅ Polar.sh status mapping (`canceled` → `cancelled`, `unpaid` → `past_due` və s.)
- ✅ User upsert (email ilə)
- ✅ Subscription idempotent upsert (`ON CONFLICT(polar_subscription_id)`)
- ✅ License key generation (`mla_live_` + 32 char base36 random)
- ✅ Webhook event dədublikasiya (`webhook_events` cədvəli)
- ✅ JWT issue (RS256, 7 gün TTL)
- ✅ Machine fingerprint binding
- ✅ Subscription status real-time DB-də yoxlanır (token cache yox)

## Sonradan əlavə olunacaq

- [ ] Welcome email göndərmə (Resend integration) — `upsertSubscription`-da TODO işarələnib
- [ ] User self-serve portal (web UI: license görüntülə, deactivate düyməsi)
- [ ] Admin endpoint: subscription manual override (refund, comp account)
- [ ] Rate limiting per IP (Cloudflare default kifayət edə bilər başlanğıcda)
- [ ] Error tracking (Sentry və ya Cloudflare Workers Analytics)
- [ ] Tests — Vitest + Miniflare ilə endpoint-ləri lokal sınamaq

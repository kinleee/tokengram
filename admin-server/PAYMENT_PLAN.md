# Tokengram — Ödəniş və Qeydiyyat Planı

> Status: PLAN (2026-06-10). Landing page + `/buy` stub hazırdır; Paddle inteqrasiyası bu sənədə görə qurulacaq.

## 0. Əsas qərarlar

| Qərar | Seçim | Səbəb |
|---|---|---|
| Ödəniş provayderi | **Paddle** (Merchant of Record) | Azərbaycandan satıcı qəbul edir; vergi (EU VAT və s.) tam onun üzərində; 5% + $0.50 |
| Qiymətlər | Pro **$5/ay** və ya **$29/il** | $0.50 fiks komissiya kiçik qiyməti yeyir → illik plan əsas məhsuldur (~7% itki vs 30%) |
| Free trial | **1 günlük, kart mütləq, $0 bu gün** | Paddle subscription trial mexanizmi bunu hazır verir; kartsız checkout tamamlanmır |
| Trial bitəndə | Avtomatik seçilmiş plana keçir (ləğv etməsə) | Standart SaaS trial axını; landing-də açıq yazılıb |
| Qeydiyyat | Ayrıca signup səhifəsi YOXDUR | Paddle checkout email + kart alır = qeydiyyat elə budur. Server webhook-dan user yaradır |
| Pul çıxarma | Payoneer/Wise IBAN → Paddle payout | Ayda 1 dəfə, min $100 yığılanda |

## 1. Tam axın (user gözü ilə)

```
tokengram.click  →  "Start free trial" düyməsi
      │
      ▼
GET /buy?plan=trial|monthly|yearly        (server 302 → Paddle checkout)
      │
      ▼
Paddle Checkout (hosted səhifə)
  • email daxil edir          ← QEYDIYYAT BUDUR
  • kart daxil edir           ← KART YOXLANIŞI ($0 authorization, bu gün çəkilmir)
  • trial: "$0 due today, $5/mo starts tomorrow" göstərilir
      │
      ▼
Paddle webhook → POST /webhook/paddle (bizim EC2 server)
  • subscription.created (status=trialing)
  • server: user + subscription + license key yaradır (SQLite)
  • Resend ilə email: "Your Tokengram license key: mla_live_..."
      │
      ▼
Paddle success redirect → tokengram.click/welcome
  ("Key emailed — VS Code-da Tokengram: Enter License Key")
      │
      ▼
User VS Code-da key daxil edir → /activate → JWT → işləyir
      │
      ├─ 24 saat sonra ləğv etməyibsə: Paddle kartdan çəkir →
      │  webhook subscription.updated (status=active) → key işləməyə davam edir
      │
      └─ Ləğv edibsə: webhook subscription.canceled →
         status=cancelled → /validate uğursuz → hooks söndürülür (license_gate)
```

**Vacib:** mövcud server kodu (`/check-key`, `/activate`, `/validate`) `trialing` statusunu artıq dəstəkləyir — client tərəfdə HEÇ NƏ dəyişmir.

## 2. Paddle tərəfdə quraşdırma (manual addımlar)

1. **Hesab:** paddle.com → satıcı hesabı (Ilkin Humbatov, fərdi/sole trader). Domain: tokengram.click.
2. **Sayt tələbləri (approval üçün məcburi!):** Paddle domeni təsdiqləməzdən əvvəl saytda bunlar olmalıdır:
   - Terms of Service səhifəsi (`/terms`)
   - Privacy Policy səhifəsi (`/privacy`)
   - Refund Policy (`/refund` və ya terms daxilində)
   - Məhsulun nə olduğu aydın görünməlidir (landing bunu artıq verir)
   → 3 sadə statik səhifə `site/` qovluğuna əlavə olunacaq (şablon mətnlər kifayətdir).
3. **Məhsul + qiymətlər:** 1 product ("Tokengram Pro") + 2 price:
   - `price_monthly`: $5/month, **trial period = 1 day**
   - `price_yearly`: $29/year, **trial period = 1 day**
   - Hər ikisində "collect payment method on checkout" aktiv (default belədir).
4. **Webhook destination:** `https://tokengram.click/webhook/paddle`, events:
   `subscription.created`, `subscription.updated`, `subscription.canceled`, `transaction.completed`.
   Secret-i `.env`-ə yaz: `PADDLE_WEBHOOK_SECRET=...`
5. **Default payment link / success URL:** `https://tokengram.click/welcome`
6. **Payout:** Payoneer (və ya Wise) USD hesabının IBAN/SWIFT məlumatları → Paddle payout settings, threshold $100.
7. **Sandbox:** əvvəlcə sandbox.paddle.com-da eyni quruluş, test kartı ilə tam axın yoxlanır, sonra live.

## 3. Server dəyişiklikləri (`admin-server/`)

### 3.1 Sxem (migration)

```sql
-- webhook idempotency (CF worker-də var idi, Express-də yoxdur)
CREATE TABLE IF NOT EXISTS webhook_events (
  event_id TEXT PRIMARY KEY,
  processed_at INTEGER NOT NULL
);
```
`subscriptions.polar_subscription_id` sütunu **adını saxlayır**, Paddle subscription id-si yazılır (`sub_...`). Rename migration-a dəyməz — MVP.

### 3.2 Yeni endpoint: `POST /webhook/paddle`

- **Signature verify:** `Paddle-Signature` header (`ts=...;h1=...` formatı) → HMAC-SHA256(`ts:rawBody`, `PADDLE_WEBHOOK_SECRET`). Raw body lazımdır → bu route üçün `express.raw({type: 'application/json'})`.
- **Idempotency:** `event_id` `webhook_events`-də varsa → `{status:'duplicate'}`.
- **Status mapping:** `trialing→trialing`, `active→active`, `past_due→past_due`, `paused/canceled→cancelled`.
- **`subscription.created/updated`:** `ensureUser(email)` → subscription upsert (`current_period_end` = Paddle `next_billed_at`/`current_billing_period.ends_at`) → user-in aktiv license-i yoxdursa **yeni key yarat + email göndər**.
- **`subscription.canceled`:** status=cancelled.
- Email Paddle event-də `data.customer.email`-dən gəlir (lazımsa Paddle API-dən `GET /customers/{id}`).

### 3.3 `GET /buy` stub-ı real redirect-ə çevir

```js
const PADDLE_CHECKOUT = {
  trial:   process.env.PADDLE_LINK_MONTHLY,  // trial monthly price üzərindən gedir
  monthly: process.env.PADDLE_LINK_MONTHLY,
  yearly:  process.env.PADDLE_LINK_YEARLY,
};
app.get('/buy', (req, res) => res.redirect(302, PADDLE_CHECKOUT[plan] || PADDLE_CHECKOUT.monthly));
```

### 3.4 Email göndərmə (Resend)

- resend.com hesabı → tokengram.click domain verify (DNS: SPF + DKIM, Route53/registrar-da 2 TXT yazısı).
- `.env`: `RESEND_API_KEY=...`
- Webhook handler-də: `POST https://api.resend.com/emails` — from `Tokengram <key@tokengram.click>`, mövzu "Your Tokengram license key", body-də key + 3 addımlıq quraşdırma.
- Fallback: email göndərilməsə belə key DB-dədir → admin panel-dən görünür; `/welcome` səhifəsində "didn't get the email?" → mailto link.

### 3.5 `GET /welcome` statik səhifəsi

`site/welcome.html` — "Check your inbox" + VS Code-da key daxil etmə təlimatı (3 addım).

## 4. Trial abuse qarşısı (MVP səviyyəsi)

1. **Bir email = bir key:** webhook handler yalnız user-in aktiv license-i YOXDURSA key yaradır (mövcud məntiq). Köhnə cancelled user yenidən trial ala bilməz — yeni sub gəlsə də key köhnədir, status isə Paddle-ın trial qaydasına tabedir.
2. **Paddle tərəfi:** eyni kartla təkrar trial Paddle risk sistemində şübhəli sayılır; əlavə olaraq Paddle checkout-da kart real authorization keçir (oğurluq/virtual boş kartlar əksərən kəsilir).
3. **Machine fingerprint binding:** bir key = bir maşın (mövcud `/activate` məntiqi) — key paylaşmaq işləmir.
4. Kifayətdir — daha ağır tədbirlər (IP limit, device graph) indie mərhələdə artıqdır.

## 5. İş sırası və təxmini vaxt

| # | İş | Vaxt | Asılılıq |
|---|---|---|---|
| 1 | `/terms`, `/privacy`, `/refund` statik səhifələr | 1 saat | — |
| 2 | Landing + yeni server.js EC2-yə deploy (git pull + systemctl restart) | 30 dəq | — |
| 3 | Paddle hesabı + domain approval müraciəti | 30 dəq + **1-3 gün gözləmə** | 1, 2 |
| 4 | Resend domain verify | 30 dəq (DNS yayılması ilə) | — |
| 5 | `webhook_events` migration + `/webhook/paddle` + email | 3-4 saat | — |
| 6 | Sandbox-da tam axın testi (trial → key → activate → cancel) | 1-2 saat | 3, 5 |
| 7 | Live price-lar + `/buy` redirect + `.env` | 30 dəq | 6 |
| 8 | Real kartla 1 canlı test alışı + refund | 30 dəq | 7 |

**Cəmi:** ~1 iş günü kod + Paddle approval gözləməsi. Bloklayan tək şey: addım 3 (approval) — ona görə sayt + policy səhifələri birinci gedir.

## 6. Risklər

- **Paddle approval rədd edə bilər** (yeni domen, fərdi satıcı): sayt canlı, məhsul Marketplace-də real olduğundan şans yüksəkdir. Rədd gələrsə B planı: **Dodo Payments** (4%+40¢, Azərbaycanı açıq dəstəkləyir) — webhook strukturu oxşardır, eyni handler kiçik dəyişikliklə işləyir.
- **1 günlük trial qısadır** → konversiyaya mənfi təsir edə bilər; Paddle-da trial müddətini sonradan dəyişmək 1 kliklik işdir (3 gün/7 gün A-B testi mümkün).
- **Refund-lar:** Paddle MoR olduğu üçün chargeback-ləri özü idarə edir; refund policy-də 14 gün yazmaq tövsiyəlidir.

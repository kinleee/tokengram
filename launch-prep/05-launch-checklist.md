# Phase 5 — Launch Checklist

**Hədəf:** İlk paying user ilə real launch.
**Müddət:** 1 həftə hazırlıq + launch günü.
**Risk səviyyəsi:** Orta — bütün əvvəlki fazaların doğru bitməsindən asılıdır.

## Pre-launch (T-7 gün)

### Texniki hazırlıq

- ☐ Bütün Rust prototip step-ləri tamam (1-5)
- ☐ Cross-platform build pipeline işləyir (Windows/Mac/Linux artifact-ları)
- ☐ License server staging-də 100% endpoint test
- ☐ Polar.sh sandbox-da end-to-end ödəniş işləyir
- ☐ Webhook signature verification production-ready
- ☐ DB backup avtomatik (Cloudflare D1 daily export)
- ☐ Error tracking quraşdırılıb (Sentry pulsuz tier və ya Cloudflare Workers Analytics)
- ☐ Rate limiting per IP/user
- ☐ DDoS protection (Cloudflare default)

### Marketing materialları

- ☐ Landing page final versiya, mobile responsive
- ☐ Domain canlıdır, SSL aktivdir
- ☐ Demo video (60 san, screen recording)
- ☐ Animated GIF: Read vs search_code müqayisəsi
- ☐ Screenshot-lar VS Code-da işləyəndə
- ☐ Twitter/X thread draft (5-7 tweet)
- ☐ Hacker News "Show HN" başlığı və ilk şərh draft
- ☐ ProductHunt launch səhifəsi (planlaşdır, hələ submit etmə)
- ☐ Discord server qurulub, kanal strukturu

### Hüquqi və idarəetmə

- ☐ Phase 1 bütün maddələri ✅
- ☐ Privacy Policy + Terms of Service ictimai URL-də
- ☐ Refund policy aydındır (30 gün)
- ☐ Anthropic Partner Program müraciəti göndərilib (cavab gözləməyirik launch üçün)
- ☐ Yerli hüquqşünas yaşıl işıq verib (opsional amma tövsiyə)

### Sənədləşmə

- ☐ README — quickstart, install, configuration
- ☐ Docs site — Cloudflare Pages-də, Markdown-dan generate olunur
  - Installation
  - Configuration
  - MLA on/off, MlaSync, MlaReindex skills
  - FAQ
  - Troubleshooting
- ☐ Changelog v0.1.0 entry

## Launch günü (T-0)

### Səhər (saat 09:00 GMT)

- ☐ Final production deploy: Worker + landing page
- ☐ DB migration son yoxlama
- ☐ Smoke test: real kart ilə $5 ödəniş, refund (Polar dashboard-da)
- ☐ VS Code Marketplace publish (`vsce publish`)

### Günorta (saat 13:00 GMT, US sabahı)

- ☐ Twitter/X thread post
- ☐ Hacker News "Show HN" submit
- ☐ r/ClaudeAI paylaşım
- ☐ ProductHunt launch (əgər planlaşdırılıbsa)
- ☐ Discord-da @everyone elanı (varsa community)

### Axşam

- ☐ İlk feedback toplanır
- ☐ Critical bug-lar dərhal patch (hotfix release)
- ☐ Twitter cavabları, HN şərhləri (cavab dərhal, ilk 24 saat kritikdir)

## Post-launch (T+1 ilə T+7)

### Gündəlik

- ☐ Sentry error log-larını yoxla
- ☐ Polar dashboard — yeni subscription-ları izlə
- ☐ Discord/email support sorğularına cavab (max 4 saat reaksiya)
- ☐ Twitter mentions monitor
- ☐ Marketplace rating izlə (negative rating → user-a yazıb səbəbi soruş)

### Həftəlik

- ☐ Yeni feature və ya bugfix release
- ☐ Changelog yenilə
- ☐ Twitter "this week in MLA" post
- ☐ Metrics: yeni user / churn / MRR / DAU

## Müvəffəqiyyət metrikləri

### Həftə 1 (launch həftəsi)
- 🎯 100+ install (free + paid)
- 🎯 10+ paid subscription
- 🎯 5+ testimonial
- 🎯 1+ HN frontpage (250+ upvote)

### Ay 1
- 🎯 500+ install
- 🎯 50+ paid subscription = $250+ MRR
- 🎯 4.5+ VS Code Marketplace rating
- 🎯 1+ external blog post (kimsə bizdən yazıb)

### Ay 3
- 🎯 2000+ install
- 🎯 200+ paid = $1000+ MRR
- 🎯 Anthropic Partner Program qəbul (varsa)
- 🎯 Cursor + Antigravity rəsmi inteqrasiya təsdiqi

## Failure modes — və hazırlıq

| Risk | Necə tanıyırıq | Cavab |
|---|---|---|
| Hacker News down vote-ları | <50 vote 4 saatdan sonra | Submit-i sil, başqa gün yenidən cəhd |
| Negative VS Code reviews | <3.5 ulduz ilk həftədə | Hər review-a şəxsən cavab, fix list yarat |
| Server overload | 5xx error rate >1% | Cloudflare otomatik miqyaslanır, amma D1 quota yoxla |
| Polar webhook itkin gedir | DB-də subscription görünmür | Manual reconcile script, webhook event_id idempotent |
| Krak versiya çıxır | GitHub-da fork və ya forum-larda | İgnore et, brand+sürət yolu ilə gedirsən. Cease & desist yalnız trademark pozulsa |
| Anthropic-dan C&D məktubu | Email gələr | Hüquqşünas, dərhal cavabla, hörmətlə razılaş — adətən kiçik düzəlişlərlə həll olunur |

## Geri çəkilmə planı

Launch fəlakətə uğrayarsa:
1. Yeni subscription-ları dayandır (Polar-da pause)
2. Mövcud user-lərə email — refund təklif et
3. Marketplace-dən extension-ı `unpublish` et
4. Post-mortem yaz (özün üçün), 1-2 həftə fasilə
5. Yenidən başla — launch tək şans deyil

## Tamamlanma kriteriyaları

Phase 5 "tamam" sayılır əgər:
- ✅ İlk paying customer ödəyib və feedback verib
- ✅ Sistem 72 saat downtime olmadan işləyib
- ✅ Critical bug 24 saat ərzində patch olunub
- ✅ Marketing-də Anthropic ToS pozulması yoxdur
- ✅ MRR ölçülə bilən rəqəmə çatıb ($50+ olsa belə startdır)

## Phase 5 sonrası

Launch yalnız başlanğıcdır. Növbəti faza ola bilər:
- **Phase 6: Growth** — content marketing, blog posts, video tutorials
- **Phase 7: Enterprise** — team plan, SSO, audit log
- **Phase 8: Multi-IDE** — JetBrains, Sublime, Neovim
- **Phase 9: Multi-model** — GPT, Gemini, local LLM dəstəyi (MCP-da onsuz da işləyəcək)

Bunlar gəlirdən sonra düşünülür.

# MLA Agent — Production Launch Master Plan

Hazırlanma tarixi: 2026-05-12
Status: Phase 1 başlanır

## Strateji yekun (söhbətdən gələn qərarlar)

- **Qiymət:** $5–7/ay tək plan, 14 gün pulsuz trial
- **Müdafiə fəlsəfəsi:** Texnoloji DRM-ə minimum vaxt, brand+sürət+community-yə maksimum vaxt
- **Texnologiya:** Python → Rust köçürmə (asand kopyalama qarşısını alır)
- **Server:** Cloudflare Workers + D1 + Polar.sh (sıfır xərc, 10k user-ə qədər)
- **Marketing positioning:** "Smart context for Claude Code", ASLA "Anthropic-ə az ödə"
- **Distribution:** VS Code Marketplace (pulsuz extension) + license key flow

## 5 fazalı yol xəritəsi

### Phase 1 — Legal & Trademark (1 həftə)
**Məqsəd:** Hüquqi tərəfdən təmiz launch.
**Detal:** [01-legal-checklist.md](01-legal-checklist.md)

- Anthropic Brand Guidelines + Claude Code ToS oxu
- "MLA Agent" adını USPTO TESS-də yoxla
- README-da disclaimer əlavə et
- Anthropic Partner Program-a müraciət

### Phase 2 — Naming, Branding, Marketing (1 həftə)
**Məqsəd:** Trademark-safe ad + positioning.
**Detal:** [02-branding.md](02-branding.md)

- Final ad qərarı (MLA Agent qalsın yoxsa daha güclü ad?)
- Marketing dili: do/don't list
- Loqo + landing page mockup

### Phase 3 — Rust Prototype (2–3 həftə)
**Məqsəd:** Kritik məntiq Rust binary-də, copy-paste qorunması.
**Detal:** [03-rust-prototype.md](03-rust-prototype.md)
**Status:** Step 1 (embedding sanity check) kod yazıldı, build cərəyandadır.

- Kitabxanalar: `lancedb`, `fastembed-rs`, `mcp-rust-sdk`, `tokio`, `axum`
- Birinci hədəf: `search_code` Rust-da, Python versiyası ilə eyni nəticə
- Cross-platform build pipeline (Windows/Mac/Linux)

### Phase 4 — License Server (1 həftə)
**Məqsəd:** $0 xərclə token validation + ödəniş axını.
**Detal:** [04-license-server.md](04-license-server.md)

- Cloudflare Workers + D1 minimal API
- Polar.sh ödəniş inteqrasiyası (Merchant of Record, EU VAT işini həll edir)
- JWT token + machine fingerprint (7 gün offline işləmə)
- Online activation flow

### Phase 5 — Launch (1 həftə)
**Məqsəd:** Real istifadəçilərə çatdırma.
**Detal:** [05-launch-checklist.md](05-launch-checklist.md)

- VS Code Marketplace publish
- Twitter/X + ProductHunt + r/ClaudeAI launch
- Discord/community kanalı
- Analytics + error tracking
- İlk 100 user üçün feedback loop

## Tahmini total müddət

**Aktiv iş:** 6–8 həftə (paralel iş ilə daha tez)
**Calendar müddət:** 8–10 həftə (real həyat itkiləri ilə)

## Risk qeydlər

1. **Rust öyrənmə:** Mən kodu yazıram, sən product manager rolundasan. Bizim mövcud iş tempimizə uyğun olmalıdır.
2. **Anthropic API dəyişiklikləri:** Claude Code ekosistemi sürətlə dəyişir. Hər fazada current ToS-u yenidən yoxlayırıq.
3. **Trial dövründə kraker testi:** Launch öncəsi minimum 1 nəfər (dost/contractor) ilə krak cəhdi etmək faydalıdır — biz görmədiyimiz boşluqları tapa bilər.

## İndi başlanacaq

Phase 1 — Legal checklist. Aktiv sənəd: [01-legal-checklist.md](01-legal-checklist.md)

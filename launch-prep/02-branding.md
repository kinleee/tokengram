# Phase 2 — Naming, Branding, Marketing Positioning

**Hədəf:** Trademark-safe ad + güclü positioning + asand identitet.
**Müddət:** 3–5 gün.
**Risk səviyyəsi:** Aşağı — düşüncə işidir, kod yox.

## 1. Ad qərarı

### Yekun ad: **Tokengram** *(2026-05-15-də təsdiqləndi)*

"Tokengram" neyroelmində **beyində fiziki yaddaş izi** mənasını verir — söhbətlərin və kod kontekstinin yaddaş izini saxlayan bu məhsulun hərfi tərifidir.

**Pluslar:**
- Tək sözlü, dilə yatımlı, ingilis+Azərbaycan dilində eyni oxunur
- Tech-leaning developer auditoriyasına uyğun (neyroelm + AI kəsişməsi)
- Marketplace + GitHub-da rəqabətsizdir (yoxlanılmalıdır — Phase 1)
- Akronim deyil — özlüyündə brand, "what does X mean?" sualını izah etmək asandır
- SEO baxımından "tokengram code memory" terminləri rəqabətsiz

**Minuslar / risklər:**
- Scientology-də istifadə olunan termin var, amma developer market-də qarışmaz
- USPTO-da yoxlamaq lazımdır (Phase 1)

**Tarixçə:** Köhnə adı "MLA Agent" idi ("Memory Layer Agent" / "Mid-Layer Agent" çevik akronimi). 2026-05-15-də brand-vibe + telləfüz + SEO baxımından Tokengram-a keçildi. Köhnə texniki ID-lər (env: `MLA_LICENSE_*`, command: `mla.menu`, MCP: `mla-agent`, fayllar: `.mla_arch.md`, `.mla_savings_history.jsonl`) ayrı miqrasiya işidir — instaledilmiş istifadəçilərin config-i sınmasın deyə hələlik saxlanılır.

### Bir də nəzərdən keçirilmiş alternativlər

| Ad | Niyə seçilmədi |
|---|---|
| **Mneme** | Yunan ilahəsi adı; gözəl, amma telləfüz tutorial-ı lazım idi |
| **Ember** | Ember.js framework-u ilə qarışıq |
| **Crux** | Çox qısa, məna birbaşa deyildi |
| **Codex** | OpenAI Codex model adı ilə konflikt |
| **Recall** | Microsoft Recall (Windows 11 feature) ilə birbaşa konflikt |
| **Atlas** | Çox işlədilmiş ad, fərqlənmək çətindir |

### İcazə verilmir (Anthropic ilə qarışan adlar)

- ❌ "ClaudeMLA", "Claude Helper", "Claude+"
- ❌ "Anthropic-X" istənilən forma
- ❌ "Sonnet-X", "Opus-X", "Haiku-X" — model adları onlarındır

## 2. Positioning bayrağı

### Headline

**Tövsiyə (versiya A):**
> *Smart context for Claude Code — search instead of read, on any size codebase.*

**Versiya B (daha texniki):**
> *Vector-indexed context window for Claude Code. Your codebase, searchable.*

**Versiya C (problem-driven):**
> *Claude Code stops being useful at 100k LOC. We fix that.*

Mənim seçimim: **C** — problem birbaşa adlanır, "şarmlı" deyil amma yadda qalandır. Texniki auditoriya üçün doğru ton.

### One-liner (Twitter bio, Marketplace description)

> *MLA Agent gives Claude Code a vector-indexed memory of your entire codebase. Instead of reading 1000-line files, Claude searches them — saving tokens and unlocking massive repos.*

### Elevator pitch (15 saniyə)

> *Sənin codebase-in böyüdükdə Claude Code Read-lə hər faylı oxumalı olur — yavaşlaşır, kontekst dolur, cavab dağılır. MLA Agent ChromaDB ilə kodu indekslər, Claude `Read` əvəzinə `search_code` istifadə edir — yalnız lazımi parça gəlir. 50% az token, 5x böyük layihə.*

## 3. Marketing dili — do/don't

### ✅ İcazəli ifadələr

- "Extension for Claude Code"
- "Works with Claude Code"
- "Drop-in for Claude Code users"
- "Smart context manager"
- "MCP-powered tool"
- "Built on Model Context Protocol"
- "Use Claude Code on bigger codebases"

### ❌ Qadağan ifadələr

- "Anthropic-powered" / "Anthropic-built"
- "Official Claude tool" / "Endorsed by Anthropic"
- "Claude Pro Extension" (Pro Anthropic-in plan adıdır)
- "Replace Read with us" (negative framing)
- "Stop paying Anthropic so much" (siyasi səhv, hətta doğru olsa belə)
- Anthropic loqosu, Claude loqosu marketing-də

### ⚠️ Diqqətli ifadələr (mətnə görə dəyişən)

- "Save 50% tokens" — texniki düz, amma müştəri-yönlü qoy: *"5x larger projects in same context window"* daha güclüdür
- "AI agent" — 2026-da hər yerdə işlədilir, OK amma fərq yarat
- "ChromaDB-powered" — texniki auditoriya üçün OK, marketing-də gizlə

## 4. Loqo və brand identity

### Tövsiyə

- **Simvol:** Kvadrat ortasında "M" hərfi, ya da axtarış simvolu içində kod sətri (`</> + 🔍` mənası)
- **Rəng:** Anthropic narıncı/coraldan uzaq qal. Tövsiyə:
  - Primary: **#0EA5E9** (sky blue) və ya **#10B981** (emerald)
  - Accent: **#1F2937** (slate-800)
- **Şrift:** Sans-serif, kod kontekstinə uyğun — **Inter** və ya **IBM Plex Sans**
- **Tone:** Texniki, ciddi, yumor-suz. Developer auditoriyasına uyğun.

### Loqo qaynaqları

- Logoshi, Looka — AI generator, sadə loqo $20–50
- Fiverr — insan dizayner $50–150
- Sıfırdan: Figma-da 1 saat — kvadrat + hərf + 2 rəng

## 5. Landing page strukturu

Bu launch-da MVP üçün lazımdır. Cloudflare Pages-də host, pulsuz.

```
[ Header: logo | Docs | Pricing | Get Started ]

  Headline (large)
  "Claude Code stops being useful at 100k LOC. We fix that."

  Subheadline
  "MLA Agent gives Claude Code a vector-indexed memory of your entire codebase."

  [Animated demo GIF — Read vs search_code side by side]

  [ Install Extension ]  [ View on GitHub ]

  ─────────────────────────────────────

  How it works (3 columns)
  [ 1. Indexing ]  [ 2. Search ]  [ 3. Save tokens ]

  ─────────────────────────────────────

  Pricing
  [ Free (1 project) ]  [ Pro $7/mo (unlimited + priority) ]

  ─────────────────────────────────────

  FAQ
  • Is my code sent to your servers? No — everything indexes locally.
  • Does it work offline? Yes, after activation (7-day grace).
  • Which IDEs? VS Code, Cursor, Antigravity (any Claude Code host).
  • Is it affiliated with Anthropic? No — independent tool.

  Footer: © 2026 · Privacy · Terms · Not affiliated with Anthropic, PBC.
```

## 6. Social proof toplama strategiyası

Launch-dan sonra:
- İlk 100 user-dən testimonial istə (Discord-da soruş, email yoxsa)
- VS Code Marketplace rating yığ (5 ulduz hədəfi)
- ProductHunt launch — ilk 24 saat votes
- Hacker News "Show HN" — sadə, texniki paylaşım
- r/ClaudeAI, r/programming, r/vscode — paylaş, amma "promo spam" olma

## 7. Domain qeydiyyatı

- `mla-agent.com` — yoxla
- `mlaagent.com` — yoxla
- `mlagent.dev` — `.dev` developer brand-i üçün yaxşıdır
- `getmla.com` — qısa, asand
- `mla.ai` — bahalı olar (.ai $50–80/il), amma güclü

Tövsiyə: **mla-agent.dev** və ya **getmla.com** — qiymət $12–20/il.

## Tamamlanma kriterileri

- ☐ Ad final qərarı (MLA Agent qalır, yoxsa alternative seç)
- ☐ Headline + one-liner + elevator pitch hazırdır
- ☐ Loqo (MVP versiya, sonra dizayner yenilər)
- ☐ Brand rəngləri + şrift qərarı
- ☐ Landing page mockup (Figma və ya birbaşa HTML)
- ☐ Domain qeydiyyatı tamamdır
- ☐ README disclaimer və marketing copy do/don't siyahısına uyğundur

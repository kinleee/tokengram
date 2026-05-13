# Phase 1 — Legal & Trademark Checklist

**Hədəf:** Hüquqi olaraq təmiz launch — heç bir trademark/ToS pozulması yox.
**Müddət:** 3–7 gün (əsasən oxumaq və qeydiyyat işidir)
**Risk səviyyəsi:** Aşağı — bunlar hamısı dönüşməli/dönər addımlardır.

---

## 1. Anthropic sənədlərini oxu

- [ ] **Brand Guidelines** — https://www.anthropic.com/legal/brand
  - Hansı sözlər/loqolar olmaz, hansılar olar?
  - "Claude Code üçün/ilə" istifadə qaydaları
  - Qeyd al: əgər sənəddə dəyişiklik varsa, hansı qaydaları biz pozmuşuq?

- [ ] **Claude Code Terms of Service** — https://docs.anthropic.com/en/docs/claude-code (Terms axtar)
  - Üçüncü tərəf extension hüquqları
  - Reverse engineering bəndləri
  - Kommersiya istifadəsi məhdudiyyətləri (varsa)

- [ ] **MCP License** — https://modelcontextprotocol.io
  - MIT/Apache lisenziya əyri yoxdur, kommersiya istifadə açıqdır

- [ ] **Anthropic Usage Policies** — https://www.anthropic.com/legal/aup
  - "Anthropic API-ni necə işlədirsən" qaydaları

**Çıxarılacaq nəticə:** Hansı bəndlərə diqqət etməliyik? Notes faylına qeyd al.

---

## 2. Trademark yoxlamaları

### "MLA Agent" adı

- [ ] **USPTO TESS** (pulsuz) — https://tmsearch.uspto.gov
  - "MLA Agent" axtarışı et
  - "MLA" tək axtar (lərzə yaradan eyni sahədə qeydiyyat varsa)
  - Class 9 (software) və Class 42 (SaaS) prioritetdir

- [ ] **Azərbaycan patent ofisi** (azpatent.gov.az) — yerli trademark yoxla
- [ ] **Google search:** "MLA Agent" site:github.com → eyni adlı layihə var?
- [ ] **VS Code Marketplace search:** "MLA" → konflikt varsa, ad dəyişməlidir
- [ ] **npm + PyPI search** — eyni adda paket varsa, addan vaz keç

**Əgər konflikt çıxsa:** ad alternativləri (məs. "ClaudeMLA", "CodeMLA", "ContextSaver", "SmartContext")

### Loqo və brand

- [ ] Loqo Anthropic loqosuna bənzəməsin (Claude-un kvadrat narıncı simvolundan uzaq qal)
- [ ] Rəng palitrası fərqli olsun (Anthropic narıncı/coral istifadə edir — biz mavi/yaşıl seçə bilərik)

---

## 3. README & website disclaimer

- [ ] Layihə README.md-nin yuxarısına əlavə et:

```markdown
> **Disclaimer:** MLA Agent is an independent third-party tool.
> It is not affiliated with, endorsed by, or sponsored by Anthropic, PBC.
> "Claude" and "Claude Code" are trademarks of Anthropic, PBC.
```

- [ ] VS Code Marketplace publisher səhifəsinə eyni mətn
- [ ] Landing page footer-də eyni mətn

---

## 4. Marketing dili sınaq

İcazəli vs qadağan dil — bu siyahını marketing materiallarına baxarkən yoxla:

### ✅ İcazəlidir (nominative fair use)

- "Extension for Claude Code"
- "Works with Claude Code"
- "Smart context manager for Claude Code users"
- "Claude Code üçün ağıllı kontekst meneceri"

### ❌ Qadağandır

- "Claude Pro Tool"
- "Anthropic-powered MLA"
- "Official Claude extension"
- "Claude tərəfindən tövsiyə olunan"
- Anthropic/Claude loqosu marketing-də
- "Anthropic API faturanı azalt" (texniki düzgün, amma siyasi səhv)

---

## 5. Hüquqi qeydiyyatlar (Azərbaycan kontekstində)

- [ ] **Sahibkarlıq forması:** Fərdi sahibkar (FS) yoxsa MMC?
  - $5/ay × 100 user = $500/ay gəlir başlanğıcda → FS yetərlidir
  - 1000+ user-də MMC-yə keç (vergi optimizasiyası)

- [ ] **Vergi qeydiyyatı:**
  - FS-də: 4% sadələşdirilmiş vergi
  - VAT lazımdır? Polar.sh Merchant of Record olaraq EU VAT-ı özü ödəyir — sənin üzərinə düşmür
  - Yerli vergi: ARDNF qeydiyyatı + aylıq bəyannamə

- [ ] **Bank hesabı:**
  - USD qəbul edə bilən hesab (Kapital Bank, ABB Business)
  - Polar.sh-dən aylıq payout → manata çevrilmə xərclərini hesabla

**Yerli hüquqşünas məsləhəti:** 30–60 dəq konsultasiya. Soruş:
- Beynəlxalq SaaS satışında ARDNF-də necə qeyd alınır
- Geri qaytarmalar (refund) hüquqi olaraq necə işlənir
- Privacy policy/terms of service Azərbaycan dilində olmalıdır?

---

## 6. Anthropic Partner Program

- [ ] **Müraciət səhifəsi:** https://www.anthropic.com/partners (yoxsa builders.anthropic.com)
- [ ] Müraciət hazırla:
  - Layihə təsviri (1 paraqraf)
  - Hədəf auditoriya (Claude Code istifadəçiləri, böyük codebase olan developer-lər)
  - Texniki arxitektura (MCP server + hook-based, kompliant)
  - Tahmini user sayı + roadmap

**Faydası:** Qəbul olunsan rəsmi tərəfdaş nişanı + marketing visibility + hüquqi sığorta (rəsmi tərəfdaşa qarşı C&D göndərilmir).

**Real ehtimal:** Anthropic indie tərəfdaşları qəbul edir, amma proses 2–6 həftə çəkə bilər. Launch-ı bunun gözləməsi lazım deyil — paralel get.

---

## 7. Privacy Policy + Terms of Service

İki sənəd lazımdır, ikisi də ictimai URL-də:

- [ ] **Privacy Policy** — hansı user datası toplanır?
  - Email (license üçün)
  - Machine fingerprint hash (license üçün)
  - **Kod məzmunu serverə getmir** — bu vacib selling point
  - Cookies, analytics (varsa)

- [ ] **Terms of Service**
  - Subscription, refund policy (14 gün pulsuz trial içində refund şərti olmadan)
  - Lisenziya: "single user, single machine" yoxsa "single user, çoxlu machine"?
  - DMCA notices üçün əlaqə
  - Jurisdiction: Azərbaycan yoxsa neytral?

**Şablonlar:** termly.io, freeprivacypolicy.com (pulsuz, basic). İlk versiya üçün kifayətdir, sonra hüquqşünas yoxlasın.

---

## Phase 1 tamamlanma kriterileri

- ✅ Anthropic Brand Guidelines + Claude Code ToS oxunub, notes alınıb
- ✅ "MLA Agent" adı 4 mənbədə yoxlanılıb (USPTO, AZ patent, GitHub, VS Code Marketplace)
- ✅ README disclaimer əlavə olunub
- ✅ Marketing dili check-list-i bu fayldadır, referans kimi istifadə olunur
- ✅ Anthropic Partner Program müraciəti göndərilib (paralel, qəbul üçün gözləmirik)
- ✅ Yerli hüquqşünas ilə qısa məsləhət (opsional amma tövsiyə)
- ✅ Privacy Policy + ToS draft hazır (final versiya Phase 5-də)

**Bunlar bitəndə Phase 2-yə keç.**

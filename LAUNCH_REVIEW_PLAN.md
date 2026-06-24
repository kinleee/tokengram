# Launch Review Plan — 2026-06-11 (Rev 3 — FINAL, icra başlayır)

10 xarici iradın CEO qiymətləndirməsi + icra planı. Faktlar kodda yoxlanılıb.
**Rev 2:** auditin 7 iradı qəbul edildi — A1 genişləndi (build-flag dev strip, server-side trial binding, bar state-ləri), trial 14→30 gün, Paddle Faza B-yə, A2-yə retroaktiv purge + kod chunk redaction, A3-də Edit/Bash uçotu açıq, hüquqi minimum + onboarding fallback.
**Rev 3 (FINAL):** 5 qalıq məqam qəbul edildi — release smoke test, tester miqrasiyası (deploy-dan ƏVVƏL), bar "regressiya" izahı + mütləq rəqəm önə, Paddle müraciəti BU GÜN, köhnə client compat testi, 48s fallback şüurlu risk kimi qeyd, uğur metrikləri bölməsi. **Audit bağlandı — bundan sonra icra (A1).**

## Verdiktlər (orijinal 10 irad)

| # | İrad | Verdikt | Sübut |
|---|------|---------|-------|
| 1 | Lisenziya özünü inkar edir | **HAQLIDIR — ən ciddi** | `mcp_server.py:848` — açar yoxdursa "dev mode", tool işləyir; `license_gate.py` — açarsız hooks silent allow |
| 2 | API vs abunəçi seqmenti qarışıb | **HAQLIDIR** | Pro/Max user üçün qənaət = rate-limit nəfəsi, dollar deyil |
| 3 | $2/ay riyaziyyatı işləmir | **HAQLIDIR** | Paddle $0.50 + 5% → $2-dən ~30% fee-yə gedir |
| 4 | Sayğac kontrfaktualdır | **HAQLIDIR** | Baseline yoxlanıla bilməz; "fakt" kimi göstərmək olmaz |
| 5 | "~50%" n=1-dir | **HAQLIDIR** | Bir günlük müqayisə ilə launch riskli |
| 6 | Warn-only → agent xasiyyətindən asılı | **QİSMƏN** | Fakt doğru, amma `warn_allow` loglanır → əməl faizi metrikası ucuzdur |
| 7 | Platforma riski | **HAQLIDIR — roadmap** | MCP universal; UX qatı Claude Code + VS Code-a bağlı |
| 8 | Closed-source etibar | **QİSMƏN** | Real, amma open-core indi = launch dayanır; şəffaflıq səhifəsi ucuz cavabdır |
| 9 | Pul komandadadır | **HAQLIDIR — roadmap** | "Team — contact" tier kod yazmadan |
| 10a | .click domeni | **HAQLIDIR** | .com/.dev al, redirect |
| 10b | Tək EC2 SPOF | **OK launch üçün** | 7 günlük grace + B5/B7 |
| 10c | Offline grace yoxdur | **FAKTİKİ SƏHV** | `license.py:35` — 7 gün var, explicit rədd-də yox |
| 10d | Conversation secrets filtri yoxdur | **HAQLIDIR — təsdiqləndi** | `conversation_indexer.py`-də redaction yoxdur |

## Audit Rev-2 verdiktləri (7 irad — hamısı qəbul)

| # | İrad | Qərar |
|---|------|-------|
| R1 | TOKENGRAM_DEV env boşluğu + trial faylı reset | Build flag ilə dev branch public build-dən kəsilir; trial serverdə fingerprint-ə bağlanır (1 maşın = 1 trial) |
| R2 | Paddle gizli launch blocker | Trial 14→30 gün + Paddle Faza B, hədəf launch+2 həftə |
| R3 | Redaction yalnız irəliyə baxır | redaction_version marker + bir dəfəlik purge/reindex; regex kod chunk-larına da |
| R4 | Edit/Bash uçotu açıq deyildi | Açıq yazıldı: real_spent-ə daxildir, faiz real məxrəcdən |
| R5 | Bar-a trialing/trial_expired lazım | A1-ə daxil; A1 = 2-3 gün |
| R6 | Terms + Privacy | B4-ə daxil + "maşından nə çıxır" cədvəli |
| R7 | Server = onboarding SPOF | Uptime monitor + bir-dəfəlik 48s lokal müvəqqəti icazə |
| R+ | "Dayansa heç nə sınmır" mesajı | A4 + trial_expired mesajına daxil |

## Audit Rev-3 verdiktləri (5 qalıq + 2 qeyd — hamısı qəbul)

| # | Məqam | Qərar |
|---|-------|-------|
| S1 | Build-flag-ə proses qoruması | Release audit qaydası genişlənir: hazır wheel üzərində smoke test — təmiz env-də quraşdır, `TOKENGRAM_DEV=1` set et, açarsız tool-ların RƏDD etdiyini assert et. Regressiya sinif olaraq bağlanır |
| S2 | Mövcud testerlərin miqrasiyası | A1 deploy-undan ƏVVƏL bütün aktiv testerlərə admin endpoint-dən uzunmüddətli açar (plan=alpha, 6-12 ay). Testerlər heç vaxt trial_expired görməməlidir |
| S3 | Dürüst bar = görünən "regressiya" | Changelog + bar menyusunda bir sətir: "Ölçmə metodologiyası düzəldildi — indi bütün xərclər sayılır". Marketinqdə faiz yox, mütləq rəqəm önə: "bu ay 1.8M token / ~$X" |
| S4 | Paddle müraciəti vs inteqrasiya | Merchant application BU GÜN açılır (kod yazılmamış) — approval bizim nəzarətimizdə deyil. Nəticə: qiymət qərarı ($29/il + $4/ay) bu həftəlikdir, çünki Paddle konfiq + landing eyni rəqəmi istəyir |
| S5 | Köhnə client + yeni server statusu | Dizayn qaydası: server dəyişiklikləri deployed wheel-lərlə geriyə uyğun olmalıdır; tanınmayan status → mövcud stale/grace davranışı (fail-open YOX, exception YOX). Bir compat test: köhnə client davranışı yeni server cavabları ilə |
| S6 | 48s fallback = mini dev-mode | **Şüurlu qəbul edilmiş risk:** lokal marker silinib təkrar 48s almaq mümkündür; $4-luq məhsulda fingerprint reconcile-dan artıq mübarizəyə dəyməz. Sonradan "boşluq tapıldı" kimi qayıtmasın deyə burada qeyd olunur |
| S7 | Uğur metrikləri əvvəlcədən yox idi | Aşağıda "Uğur metrikləri" bölməsi əlavə olundu — rəqəmlər və qərar tetikləyiciləri launch-dan ƏVVƏL təyin edilir |

## Faza A — Launch blockers (~4-5 gün)

### A1. Dev-mode boşluğunu bağla + trial axını — 2-3 gün
- `ensure_license_cached()`: açar yoxdursa → serverdən **30 günlük** trial token (`/trial` endpoint, EC2 Express-ə əlavə olunur).
- **Trial binding:** server fingerprint-i qeyd edir; 1 fingerprint = 1 trial. Lokal faylı silmək reset vermir.
- **Dev bypass:** `build_pypi.py` release-də `RELEASE_BUILD=True` inject edir → dev branch .pyd-də ölü kod. Env var yalnız source layout-da işləyir.
- **(S1) Release smoke test:** hazır wheel təmiz env-də + `TOKENGRAM_DEV=1` → açarsız tool RƏDD etməlidir. Release checklist-ə daimi maddə (mövcud "yalnız run_mcp_server.py + hooks .py" auditi ilə yanaşı).
- **(S2) Tester miqrasiyası — deploy-dan ƏVVƏL:** bütün aktiv testerlərə admin endpoint-dən 6-12 aylıq alpha açarı. Yalnız açarlar paylanandan sonra A1 deploy olunur.
- **(S5) Geriyə uyğunluq:** köhhnə wheel-lər yeni server statuslarında mövcud stale/grace davranışına düşməlidir; bir compat test yazılır.
- Trial bitdi + açar yoxdur → `LicenseError` ("Get a license at tokengram.click — heç nə sınmır, sadəcə qənaət dayanır").
- **Extension:** bar-a `trialing` ("Trial: N gün qaldı · bu ay ~X token qənaət") və `trial_expired` state-ləri; wizard trial axını.

### A2. Secrets redaction — irəli + geri — yarım gün
- Conversation VƏ kod chunk pipeline-ında chunk-dan ƏVVƏL regex scrub: `sk-`, `ghp_`, `github_pat_`, `AKIA`, `AIza`, `xoxb-`, JWT (`eyJ`), PEM, `password=`/`token=` → `[REDACTED]`.
- Retroaktiv: `redaction_version` marker → köhnə versiyada conversation purge + avtomatik reindex.

### A3. Sayğac dürüstlüyü — uçot + format + izah — ~1 gün
- **Uçot (kök):** Edit/Bash/chunked-Read xərci `real_spent`-ə daxil; faiz real məxrəcdən (90% → real 20-40%).
- **Format:** «Təxmini baseline: X · Faktiki xərc: Y» + "estimated".
- **(S3) Regressiya izahı:** changelog + bar menyusunda "Ölçmə metodologiyası düzəldildi — indi bütün xərclər sayılır" sətri.
- **(S3) Mütləq rəqəm önə:** bar/landing-də əsas rəqəm faiz yox, "bu ay N token / ~$X" — metodologiya dəyişikliyinə davamlıdır.
- Missed-savings tracker (deferred fixes siyahısından).

### A4. Landing copy — 2-3 saat
- İki seqment: API user → dollar; Pro/Max → rate-limit nəfəsi + təmiz kontekst.
- "Tokengram dayansa heç nə sınmır — sadəcə qənaət dayanır" bloku.
- "50%" iddiası çıxır → "öz sayğacın göstərəcək".

## Faza B — Launch-dan əvvəl / launch+2 həftə (~2-3 gün)

- **B1. Compliance metrikası:** warn_allow → "əməl faizi", bar menyusu. 1-2 saat.
- **B2. Qiymət + Paddle:** $29/il + $4/ay — **qərar bu həftə** (S4: Paddle konfiq + landing eyni rəqəmi istəyir). **Paddle merchant application BU GÜN açılır**; inteqrasiya hədəfi launch+2 həftə; 30 günlük trial bufer verir.
- **B3. Domen:** tokengram.com/.dev al → redirect.
- **B4. Hüquq + şəffaflıq:** Terms + Privacy + "maşından nə çıxır" cədvəli (yalnız açar + fingerprint + son yoxlama tarixi; kod/indeks/qənaət lokaldır) + grace=7gün sənədi.
- **B5. EC2 runbook:** gündəlik backup cron + bərpa addımları.
- **B7. Onboarding resilience:** uptime monitor + bir-dəfəlik 48s lokal icazə (S6: marker-silmə residual riski şüurlu qəbul edilir).

## Uğur metrikləri və qərar tetikləyiciləri (S7 — launch-dan ƏVVƏL yazıldı)

| Metrik | Hədəf | Tetikləyici |
|--------|-------|-------------|
| Trial → paid konversiya | 3-5% (utility kateqoriyası üçün realistik) | **<2% (60 gün sonra)** → qiymət/trial modelinə qayıt (qiymət aşağı/trial uzat/dəyər təklifi yenidən) |
| Warn-compliance faizi | ≥60% (agent xəbərdarlığa əməl edir) | **<40%** → hook mesajı + CLAUDE.md təlimatı gücləndirilir; hələ də aşağıdırsa → enforcement dizaynı yenidən baxılır (məhsulun işləməsi bundan asılıdır) |
| D7 retention (MCP istifadəsi 7-ci gündə davam edir) | ≥40% | **<25%** → onboarding/dəyər problemi — konversiyadan əvvəl bunu düzəlt, marketinqə pul tökmə |

Qayda: data yığılır (lokal odometr + server-side trial/aktivasiya qeydləri), 2-4 həftə sonra bu cədvəllə müqayisə olunur. Cədvəldə olmayan qərar səbəbi = post-hoc rasionalizasiya, qəbul edilmir.

## Faza C — Launch-dan sonra (roadmap)

- **C1.** Cline / Codex CLI üçün MCP quraşdırma sənədi; adapter yalnız real tələbdə.
- **C2.** Team tier: "Team — contact us" → design partner.
- **C3.** 2-4 həftəlik real data → marketing rəqəmi (yuxarıdakı metrik cədvəlinə görə).
- **C4.** Open-core: yalnız real satış etirazlarında yenidən bax.

## Qəbul edilməyən / düzəldilən iddialar
- "Offline grace yoxdur" — səhv: 7 gün var, explicit rədd-də yox.
- "Hard-block lazımdır" — yox: Edit-i sındırır; cavab ölçmək + prompt.
- İmzalanmış dev açarı — over-engineering; build-flag + smoke test (S1) kifayətdir.
- Multi-instance server — over-engineering; monitor + 48s fallback kifayətdir.

## Ümumi effort və status
Faza A ≈ 4-5 gün, Faza B ≈ 2-3 gün → **6-8 iş günü** (S1/S2/S5 əlavələri ≈ +yarım gün, daxil edilib).
**Status: audit bağlandı (3 reviziya, konvergensiya). Növbəti addım = A1 icrası + Paddle application (bu gün) + qiymət qərarı (bu həftə).**

# MLA Agent — Hərtərəfli Test Planı

Tarix: 2026-05-12.

Bu plan MLA Agent sisteminin son commit-də (`496d77c`) olan halını
hərtərəfli yoxlayır. Test sahələri ən çox dəyişən komponentlərə yönəldirib:
mərkəzləşdirilmiş `mla_constants`, genişlənmiş extension siyahısı,
fayl-səviyyəli filtrlər, hooks zənciri, Stop hook zənciri və MCP serveri.

## Test prinsipləri

1. **Hər mərhələdən əvvəl** lokal git-ə snapshot commit edilir
   (`test: phase N pre-test snapshot`).
2. Qarşılaşılan problem layihənin mövcud kod üslubu və yanaşmaları
   çərçivəsində həll edilir, sonra eyni test təkrar edilir.
3. Problem + həll TEST_REPORT.md-yə yazılır.
4. Heç bir push edilmir — yalnız local commit-lər (`origin/main`-ə son
   yekun push-u istifadəçi qərarına saxlanır).

## Mərhələ 1 — Unit: mla_constants və find_code_files filtrləri

| # | Test | Gözlənilən |
|---|---|---|
| 1.1 | `mla_constants.SUPPORTED_EXTENSIONS` 36 element, hamısı `.` ilə başlayır | ✓ |
| 1.2 | `EXCLUDED_DIRS` / `EXCLUDED_FILE_PATTERNS` / `EXCLUDED_FILE_SUFFIXES` boş deyil və konflikt etmir | ✓ |
| 1.3 | `MAX_FILE_SIZE_BYTES = 1_000_000` (sənədli sabit) | ✓ |
| 1.4 | `config.py` `mla_constants`-dan import edir, eyni adlar mövcuddur | ✓ |
| 1.5 | `find_code_files('.')` 37 fayl tapır, `.json/.ts/.js/.ps1/.sh` daxil | ✓ |
| 1.6 | Tmp `package-lock.json` (lock pattern) skip olunur | ✓ |
| 1.7 | Tmp `foo.min.js` (suffix) skip olunur | ✓ |
| 1.8 | Tmp 1.5 MB-lıq `huge.py` (size cap) skip olunur | ✓ |
| 1.9 | Tmp boş fayl skip OLUNMUR (size = 0 ≤ MAX) — chunker tərəfində handle olunur | ✓ |

## Mərhələ 2 — Enforcement hooks (3 hook × extension matrisi)

### 2.A — `pre_read_check.py` (PreToolUse Read)

| # | Fayl | Sətir | Flag | Gözlənilən |
|---|---|---|---|---|
| 2.1 | `.ts` fayl 100 sətir | ON | exit 2, message-də `/MlaReindex` qeydi |
| 2.2 | `.go` fayl 60 sətir | ON | exit 2 |
| 2.3 | `.py` fayl 40 sətir | ON | exit 0 + tip stderr |
| 2.4 | `.py` fayl 20 sətir | ON | exit 0 silent |
| 2.5 | `.json` fayl 100 sətir | ON | exit 2 |
| 2.6 | `.ts` fayl 100 sətir | **OFF** | exit 0 silent (self-exit) |
| 2.7 | `.txt` fayl 200 sətir | ON | exit 0 (not in INDEXED_EXTS) |
| 2.8 | Project-xarici `.py` | ON | exit 0 (relative_to fail) |

### 2.B — `post_grep_check.py` (PostToolUse Grep)

| # | Path | Lines | Flag | Gözlənilən |
|---|---|---|---|---|
| 2.9 | `.ts` 50 sətir | ON | log entry `grep_search` |
| 2.10 | `.py` 20 sətir | ON | no log (threshold altı) |
| 2.11 | `.txt` 100 sətir | ON | no log (non-indexed) |
| 2.12 | `.py` 50 sətir | **OFF** | no log |

### 2.C — `post_bash_check.py` (PostToolUse Bash)

Komanda matrisi (hamısı indeksli `≥50 sətir` fayl üzərində):

| # | Komanda forması | Gözlənilən |
|---|---|---|
| 2.13 | `cat hooks/post_bash_check.py` | log |
| 2.14 | `head -n 5 file.py` | log |
| 2.15 | `Select-String "x" file.py` | log |
| 2.16 | `findstr "x" file.py` | log |
| 2.17 | `gc file.py` | log |
| 2.18 | `Get-Content file.py` | log |
| 2.19 | `type file.py` | log |
| 2.20 | `awk '/x/{print}' file.py` | log |
| 2.21 | `sed -n 1,10p file.py` | log |
| 2.22 | `git show HEAD:file.py` | log |
| 2.23 | `head -n 5 file.py \| grep x` | log (head seqmenti) |
| 2.24 | `git status` (inspect deyil) | no log |
| 2.25 | `cat file.py` | flag OFF → no log |

## Mərhələ 3 — Stop hook zənciri

`arch_doc.py` (1-ci) və `savings_report.py` (2-ci) bir-birinə bağlıdır.

| # | Test | Gözlənilən |
|---|---|---|
| 3.1 | Boş `.mla_session_log.jsonl` ilə `savings_report` çağırılır | history-yə **yazmır**, exit 0 |
| 3.2 | 3 mixed entry (search/grep/bash) ilə çağırılır | 1 history record + session_log silinir |
| 3.3 | `arch_doc.py` çağırılır, `.mla_arch_state.json` yenilənir | ✓ |
| 3.4 | `arch_doc.py` mövcud session_log-u **silmir** (savings_report etməlidir) | ✓ |
| 3.5 | Stop hook 2 hook-dan ibarət olduğu üçün hər ikisi sıra ilə işləyir (`settings.json`) | ✓ |

## Mərhələ 4 — MCP serveri və `RustBindingsAPI` araşdırması

| # | Test | Gözlənilən |
|---|---|---|
| 4.1 | `mcp_server` direct import → `search_code` workflow (CLI ilə) | Cavab gəlir, xəta yox |
| 4.2 | `--fresh` re-index-dən dərhal sonra search | Cold-init xətası varsa reproduce et |
| 4.3 | Səbəb müəyyənləşsə, layihə kod stilinə uyğun fix tətbiq olunur | ✓ |
| 4.4 | Fix-dən sonra 4.1 təkrar | ✓ |

## Mərhələ 5 — İnteqrasiya & regression

| # | Test | Gözlənilən |
|---|---|---|
| 5.1 | `/MlaOn` → flag dəyişir → `pre_read_check` block-a başlayır | ✓ |
| 5.2 | `/MlaOff` → bütün hooks self-exit | ✓ |
| 5.3 | `/MlaResetBar` → history backup-a köçür, sıfırlanır | ✓ |
| 5.4 | `/MlaSync` → session_log-u history-yə köçürür | ✓ |
| 5.5 | `/MlaReindex` skript `main.py index . --fresh` çağırır | ✓ |
| 5.6 | `savingsReader.ts` tipik history fayldan düzgün cəm hesablayır | unit test JS |
| 5.7 | Status bar boş history-də "no data" / "starting..." göstərir | manual yox, kod review |

## Mərhələ 6 — Sənədləşdirmə

TEST_REPORT.md yaradılır:
- Hər mərhələdə icra olunan testlər
- Tapılan problemlər (Mövcud halı + Səbəb + Həll + Validation)
- Yekun statistika (PASS/FAIL/SKIP)
- Açıq qalmış məsələlər (gələcək work)

## Coverage out-of-scope

Bu plana **daxil edilməyən** sahələr (qərarla):
- VS Code extension JS unit test-ləri (esbuild bundle, manual UI test daha səmərəli)
- Watchdog real-time event handling (watchdog/inotify spesifik, separate suite lazımdır)
- ChromaDB embedding model semantic accuracy (data-quality, ML-tier)
- Konkurrent multi-Edit hook race condition (ehtimal aşağı, observed deyil)

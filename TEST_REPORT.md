# MLA Agent — Test Hesabatı

**Tarix:** 2026-05-12  
**Test edilən commit-lər:** `21060ad..a2c9972` (TEST_PLAN-dan Phase 5 fix-ə qədər)  
**Yekun:** **66 / 66 PASS** · 2 production bug aşkar olundu və düzəldildi · 1 transient məsələ sənədləşdirildi

## Yekun cədvəl

| Mərhələ | Test sayı | Status | Tapılan problem | Müddət |
|---|---:|---|---|---:|
| 1 — Constants & file filters | 13 | ✓ | — | 0.05s |
| 2 — Enforcement hooks (pre_read/post_grep/post_bash) | 25 | ✓ | — | 3.1s |
| 3 — Stop hook zənciri | 9 | ✓ (fix sonra) | **Bug #1**: stderr cp1252 Azərbaycan hərflərini escape edirdi | 1.1s |
| 4 — MCP search_code | 5 | ✓ | `RustBindingsAPI` transient (sənədləşdirildi) | 23.8s |
| 5 — İnteqrasiya regression | 14 | ✓ (fix sonra) | **Bug #2**: show_arch.py stdout cp1252 → exit 1 | 1.4s |
| **CƏMİ** | **66** | **✓** | 2 fix + 1 dok | **~30s** |

---

## Tapılan problemlər və həllər

### Bug #1 — Windows stderr cp1252 escape (savings_report.py)

**Aşkar olunan mərhələ:** Phase 3, `test_savings_with_mixed_entries_writes_one_record`

**Simptom:** Stop hook bitəndə istifadəçi `[mla-agent] Bu task: 1 axtarış, ...` yerinə `[mla-agent] Bu task: 1 axtarış, ...` görürdü. Stderr-də Azərbaycan hərfləri (`ş`, `ı`, `ə`, `→`) literal Unicode-escape kimi çıxırdı.

**Niyə:** Python `sys.stderr` Windows-da default olaraq `locale.getpreferredencoding()` = **cp1252** istifadə edir. Bu encoding-də Azərbaycan-spesifik kod nöqtələri yoxdur (U+0131, U+015F, U+0259). Default `errors='backslashreplace'` handler çağırılır və `\uXXXX` escape format-a düşür.

**Həll** ([hooks/savings_report.py:18-26](hooks/savings_report.py#L18-L26)):
```python
if sys.platform == "win32":
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
```

Symmetri üçün eyni patch [hooks/arch_doc.py:13-19](hooks/arch_doc.py#L13-L19)-də də tətbiq olundu (gələcəkdə stderr-ə yazsa eyni problemi olmasın).

**Niyə layihə üslubuna uyğundur:** `main.py` artıq bu pattern-i `sys.stdout.reconfigure` üçün istifadə edir (Windows konsolu UTF-8 problemi həll yolu).

**Validation:** Phase 3 `test_savings_with_mixed_entries_writes_one_record` indi `axtarış` literal-i stderr-də tapır.

**Test infra collateral fix:** [tests/test_phase2_hooks.py](tests/test_phase2_hooks.py) və [tests/test_phase3_stop_chain.py](tests/test_phase3_stop_chain.py)-də `subprocess.run` çağırışlarına `encoding="utf-8"` parametri əlavə olundu. Bu olmadan parent prosesi child-ın UTF-8 output-unu cp1252 kimi decode edirdi → mojibake (`ı` → `Ä±` kimi). Test fail-i bu mojibake idi, prod fix-i deyildi — amma onsuz prod fix-i validate edə bilməzdik.

---

### Bug #2 — Windows stdout cp1252 → show_arch.py exit 1

**Aşkar olunan mərhələ:** Phase 5, `test_show_arch_missing_file_friendly_message`

**Simptom:** `/MlaArch` slash command-da arch doc hələ yaradılmadıqda istifadəçi-dostu mesaj göstərilməli idi — amma skript exit 1 ilə crash edirdi. Print mesajı `"Arch doc hələ yaradılmayıb. ..."` Azərbaycan-spesifik hərflər saxlayırdı; Windows stdout cp1252-də encode edə bilmir → `UnicodeEncodeError` → process exit 1.

**Niyə:** Bug #1-in eyni kökü, amma stdout tərəfində. Print() default `errors='strict'` ilə UnicodeEncodeError throw edir (stderr fərqlidir, oradakı default `backslashreplace` olur).

**Həll** ([hooks/show_arch.py:8-14](hooks/show_arch.py#L8-L14)):
```python
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
```

**Validation:** Phase 5 `test_show_arch_missing_file_friendly_message` indi exit 0 + dostluq mesajı qaytarır.

**Niyə digər skriptlərə də tətbiq olunmadı:** Audit edildi — `toggle_mla.py`, `reset_savings.py`, `refresh_bar.py` stdout-a yalnız ASCII print edir; `queue_change.py`, `post_grep_check.py`, `post_bash_check.py` print etmir. Tək hədəf show_arch.py idi.

---

### Transient #3 — `'RustBindingsAPI' object has no attribute 'bindings'`

**Aşkar olunan an:** İlk MCP `search_code` çağırışı `--fresh` re-index sonrası (yalnız bir dəfə görüldü).

**Reproduksiya:** **Mümkün olmadı.** Phase 4-də 5 ardıcıl direct call (fast/semantic/file-type-filter/empty-result) hamısı uğurla bitdi. Sənin əvvəl gördüyün xəta:

```
Error executing tool search_code: 'RustBindingsAPI' object has no attribute 'bindings'
```

bir-dəfəlik idi və özbaşına həll oldu.

**Hipotez:** `--fresh` re-index başqa Python prosesi (`main.py index . --fresh`) ChromaDB faylarını silib yenidən yazdığı anda eyni vaxtda Claude Code-un MCP stdio child-ı `chromadb` singleton-ı stale handle-larla saxlayırdı. ChromaDB-nin Rust-əsaslı vektor index layeri (`chroma-rs`) bu yarış halı vəziyyətdə `RustBindingsAPI.bindings` attribute-unun olmadığını rapor etdi — sonra growth/heal etdi.

**Sənədli mitigasiya:** Növbəti dəfə görsən, sadəcə search_code-u 1-2 saniyə sonra təkrarla. Davamlı təkrar görsən:
1. `Get-Process python | Stop-Process -Force` ilə MCP server-i öldür
2. Növbəti search_code çağırışında Claude Code stdio child-ı təmiz halda respawn edəcək

**Kod fix-i etmədik niyə:** Yalnız bir dəfə müşahidə olundu, defensive retry/lock əlavə etmək vəziyyəti mürəkkəbləşdirir, və əsl səbəb (third-party `chromadb` daxilində) bizim koddan kənardır. Davamlı problem olarsa ayrıca task açılmalıdır.

---

## Test infrastrukturu

`tests/` qovluğu yaradıldı:

| Fayl | Test sayı | Mövzu |
|---|---:|---|
| [tests/test_phase1.py](tests/test_phase1.py) | 13 | `mla_constants`, `find_code_files` (lock filter, suffix filter, size cap) |
| [tests/test_phase2_hooks.py](tests/test_phase2_hooks.py) | 25 | `pre_read_check`, `post_grep_check`, `post_bash_check` subprocess matrix |
| [tests/test_phase3_stop_chain.py](tests/test_phase3_stop_chain.py) | 9 | `arch_doc.py`, `savings_report.py` end-to-end + settings.json hook order |
| [tests/test_phase4_mcp.py](tests/test_phase4_mcp.py) | 5 | `mcp_server.search_code` direct API |
| [tests/test_phase5_integration.py](tests/test_phase5_integration.py) | 14 | Slash command back-end-ləri + savingsReader.ts math port |

**Hamısını işlət:**
```bash
for f in tests/test_phase*.py; do python "$f"; done
```

**İstifadə tövsiyəsi:** Hər `hooks/` və ya `mla_constants.py` dəyişikliyindən sonra ilk olaraq Phase 1 + 2 + 3 + 5 (cəmi ~6 saniyə) işlət. Phase 4 (cold start 20s+ embedding model) yalnız MCP server koduna toxunduğun zaman.

---

## Coverage və açıq sahələr

**Bu test suite-i əhatə edir:**
- ✓ Mərkəzləşdirilmiş `mla_constants` import zənciri (config + 4 hook)
- ✓ Genişlənmiş 36 extension siyahısı
- ✓ Lock/min/bundle/generated fayl filtrləri
- ✓ 1 MB MAX_FILE_SIZE limit
- ✓ 3 enforcement hook (block/warn/silent + 14 Bash komanda forması)
- ✓ Stop hook zənciri (arch_doc → savings_report sıralaması + session_log idarəsi)
- ✓ Stop hook OFF state davranışı (data clean-up vs no-op)
- ✓ 5 slash command back-end skripti
- ✓ Status bar 24h savings hesablama formulu (JS↔Python sinxron)
- ✓ Cross-platform encoding (UTF-8 reconfigure)

**Bu test suite-i əhatə etmir (out-of-scope):**
- ✗ VS Code extension TypeScript unit-test (esbuild bundle test infra-sı yoxdur; manual UI verification daha səmərəlidir)
- ✗ Watchdog filesystem event handler (real-time, race condition spesifik — separate harness lazımdır)
- ✗ ChromaDB embedding semantic doğruluğu (data-quality test, ML domain)
- ✗ Konkurrent multi-Edit yarış halı
- ✗ Real Claude Code MCP stdio integration (test stdio handshake-i mock edə bilməz)
- ✗ `/MlaReindex` tam end-to-end (60+ san real reindex)

---

## Tövsiyə olunan növbəti addımlar

1. **Davamlı CI**: GitHub Actions-da Phase 1/2/3/5 işlədilsə (Phase 4 LFS embedding model ilə həm bahalı, həm slow), bütün PR-larda regression görünə bilər.
2. **Phase 4 reranker mode-u**: hazırda yalnız fast + semantic test olunur. `mode="rerank"` ayrıca yoxlanmalıdır (reranker model yüklənməsi əlavə cold-start budget tələb edir).
3. **VS Code extension JS test-i**: əgər extension daha mürəkkəbləşsə, vitest/jest qurmaq lazım gələcək. Hazırda 105 sətir TS kodu və 2 fayl — overkill.
4. **`RustBindingsAPI` reqressiya**: əgər istifadəçi bu xətanı yenidən görsə, mcp_server.py-də `try/except` ilə bir-dəfəlik retry əlavə oluna bilər.

---

## Git tarixçəsi (bu sessiyada)

```
a2c9972 test(phase5)+fix: force UTF-8 stdout in show_arch.py
ddd9429 test(phase4): MCP search_code direct-invocation smoke suite
8b589b9 test(phase3)+fix: force UTF-8 stderr on Windows for Stop-hook scripts
86d8a1c test(phase2): 25-case enforcement-hook subprocess suite
583531e test(phase1): mla_constants + find_code_files unit suite (13 cases)
21060ad docs: add comprehensive test plan covering hooks, filters, Stop chain, MCP
496d77c feat: broaden indexed languages + harden file-level filters
3effe99 feat: broaden bash-inspect detector + /MlaSync recovery command
0c589e4 feat: arch doc + grep/bash post-checks + extended savings analytics
```

Bütün commit-lər **local-də** qalıb (push edilməyib) — yekun push istifadəçi qərarındadır.

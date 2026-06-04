# Tokengram Layihə Healthcheck-i

> **Məqsəd:** "Yoxla görək hər şey qaydasındadır?" sualı veriləndə bu siyahıya görə layihəni sistemli yoxlamaq. Hər yeni problemli sahə kəşf ediləndə dərhal buraya əlavə olunur — bu sənəd canlı yaşayan kontrakt-dır.
>
> **İstifadə qaydası:**
> 1. Aşağıdakı bütün bölmələri (A–L) növbə ilə yoxla.
> 2. Hər bənd üçün status göstər: ✅ OK · ⚠️ Diqqət · ❌ Xəta · ❓ Qərar lazımdır.
> 3. "Son tapılan problemlər" bölməsinə yeni discoveryləri tarixlə əlavə et.
> 4. Tamamlanmış problem üçün satırı ✅ kimi işarələ amma silmə (tarixçə qalmalıdır).
>
> **PROBLEMS.md-dən fərq:** PROBLEMS.md ilkin setup-da olan tarixi log-dur (snapshot). HEALTHCHECK.md təkrarlanan diaqnostikadır (loop).

---

## A. Hooks layer (Claude Code hooks/)

| # | Yoxlama | Necə | Bayraq |
|---|---------|------|--------|
| A1 | `.claude/settings.json` bütün lazımi hook-ları qeydiyyatdadır | grep matcher: `Stop`, `PreToolUse:Read`, `PostToolUse:Grep`, `PostToolUse:Bash` | – |
| A2 | `license_gate` Stop hook chain-nə əlavə olunub | settings.json-da `license_gate.py` referansı | – |
| A3 | Hər hook faylı `hooks/` qovluğunda mövcuddur | Glob `hooks/*.py` | – |
| A4 | Hook-lar import xətasız işləyir | `python hooks/<name>.py < /dev/null` test | – |
| A5 | PROJECT_ROOT subfolder workspace-də düzgün tapılır | `hooks/project_root.py` walk-up logic test | – |
| A6 | Hook stderr UTF-8-dir (cp1252 buglarını qaytarmamaq) | Bütün hook-larda `sys.stderr.reconfigure(encoding="utf-8")` | – |

## B. MCP server + re-index növbəsi

| # | Yoxlama | Necə | Bayraq |
|---|---------|------|--------|
| B1 | Yalnız BİR MCP server prosesi işləyir | `Get-Process python` — birdən çox PID race riskidir | – |
| B2 | Proses canlıdır və idle deyil | CPU > 0, son stderr log < 5 dəq | – |
| B3 | `.mla_pending.txt` boşdur və ya kiçikdir (<50 fayl) | `Get-Content .mla_pending.txt -Tail 5` | – |
| B4 | `.mla_pending.processing` yoxdur və ya <5 dəq köhnədir | mtime test; köhnədirsə → stuck | – |
| B5 | Background worker drain edir | `chroma_db/` mtime son dövr içində yenilənir | – |
| B6 | `mcp__mla-agent__get_stats` cavab qaytarır | MCP tool call | – |
| B7 | `mcp__mla-agent__search_code` mode="fast" işləyir | smoke test | – |

## C. ChromaDB

| # | Yoxlama | Necə | Bayraq |
|---|---------|------|--------|
| C1 | `chroma_db/` mövcuddur və >10MB | `Get-ChildItem chroma_db -Recurse \| Measure Length -Sum` | – |
| C2 | `chroma_db/chroma.sqlite3` corruption yoxdur | `sqlite3 chroma_db/chroma.sqlite3 "PRAGMA integrity_check"` | – |
| C3 | chromadb versiyası `==1.5.8` pinləndi | requirements.txt | – |
| C4 | Köhnə `chroma_db.broken-*` arxivləri 7 gündən artıqdırsa təmizlənə bilər | Manual review | – |
| C5 | `chroma_db/` mtime yazma siklində yenilənir | Hər drain-dən sonra mtime artmalıdır | – |

## D. State faylları (.mla_*)

| # | Yoxlama | Necə | Bayraq |
|---|---------|------|--------|
| D1 | `.mla_savings_history.jsonl` >0 bayt (data_reset state-i yox) | `(Get-Item .mla_savings_history.jsonl).Length` | – |
| D2 | `.mla_session_log.jsonl` ölçü makuldur (<100KB), Stop hook-da flush olur | – | – |
| D3 | `.mla_enforcement.flag` "on" / "off" yazılıb (digər dəyər yoxdur) | – | – |
| D4 | `.bak.*` saxlamaları 10-dan çox deyil (rotation lazımdır) | `Get-ChildItem .mla_savings_history.jsonl.bak.* \| Measure` | – |
| D5 | `.mla_arch.md` + `.mla_arch_state.json` syncde-dir | mtime fərqi <1 saat | – |
| D6 | Bütün `.mla_*` faylları .gitignore-dadır | grep .gitignore | – |

## E. Status bar / Savings widget (VS Code)

| # | Yoxlama | Necə | Bayraq |
|---|---------|------|--------|
| E1 | Status bar 7 state-i düzgün yansıdır (active/idle/queue_stuck/data_reset/...) | Manual VS Code reload | – |
| E2 | Real qənaət hesablanır (Edit/Bash/chunked-Read sayılır) | Memory: `feedback_savings_bar_misleading` (launch blocker) | – |
| E3 | Missed-savings tracker MVP üçün hazırdır | `feedback_savings_bar_misleading` 1-2 saatlıq fix | – |
| E4 | Per-extension breakdown menusunda görünür | Memory: `savings_widget_deferred_fixes` | – |
| E5 | Reset history button real işləyir (köhnəni .bak alır) | `MlaResetBar` skill | – |
| E6 | Re-index button hard-coded `python main.py` deyil | Memory: `reindex_skill_and_button` (launch blocker) | – |

## F. VS Code extension (vscode-extension/)

| # | Yoxlama | Necə | Bayraq |
|---|---------|------|--------|
| F1 | `package.json`: name=tokengram, publisher=kinleee, version monoton artır | – | – |
| F2 | `dist/extension.js` build edilib və src/-dən yenidir | mtime müqayisəsi | – |
| F3 | Bütün command-lar `package.json` + `extension.ts` arasında uyğundur | grep contributes.commands → registerCommand | – |
| F4 | `icon.png` mövcuddur, ölçü <100KB | – | – |
| F5 | `CHANGELOG.md` son versiya üçün entry var | – | – |
| F6 | `vsce package` xətasız işləyir | dry-run | – |
| F7 | License status TS file (`licenseStatus.ts`) live polling edir | – | – |

## G. License layer

| # | Yoxlama | Necə | Bayraq |
|---|---------|------|--------|
| G1 | `hooks/license_gate.py` mövcuddur və enforcement_active() istifadə olunur | grep | – |
| G2 | Açar yoxdursa hooks silent allow (no traceback) | `python hooks/pre_read_check.py` boş key ilə | – |
| G3 | License server URL aktiv: `https://tokengram.click` (Caddy→EC2:3000; köhnə workers.dev RETIRED) | `curl https://tokengram.click/pubkey` | – |
| G4 | License DB mövcuddur (EC2 `admin-server`, better-sqlite3: `data/tokengram.db`) | – | – |
| G5 | Açar formatı: `tk_` prefiksli (memory: engram_rename Tier 3 — hələ MLA prefiksi qala bilər) | – | – |
| G6 | Toggle MLA "ON" yalnız valid key varsa qoşula bilir | Memory: `feedback_license_gates_on` | – |

## H. Distribution / build

| # | Yoxlama | Necə | Bayraq |
|---|---------|------|--------|
| H1 | `tokengram/*.pyd` bütün business modullar üçün mövcuddur | Glob | – |
| H2 | Yalnız `run_mcp_server.py` + `hooks/*.py` source `.py` distribusiyaya çıxır | Source protection audit (memory) | – |
| H3 | `pyproject.toml` versiya `package.json` ilə uyğundur | – | – |
| H4 | `requirements.txt` versiyalar pinləndi | – | – |
| H5 | `install.ps1` test edilir: copies hooks/, writes .claude/settings.json | Memory: `installer_requirements` | – |
| H6 | `make_distribution.py` zip build-i təmiz çıxır | – | – |

## I. Identity / Branding (tokengram migration Tier 3)

| # | Yoxlama | Necə | Bayraq |
|---|---------|------|--------|
| I1 | README.md/.az.md brand "Tokengram" | – | – |
| I2 | Environment variable-lar (CLAUDE_PROJECT_DIR-dən kənar) tokengram prefiksindədir | grep `MLA_`, `ENGRAM_` | – |
| I3 | MCP server adı tokengram-a uyğundur (.mcp.json) | – | – |
| I4 | License prefiksi `tk_` (hələ defer-də) | – | – |
| I5 | Hook adları tokengram brand-i daşıyır (deferred, Tier 3) | – | – |
| I6 | Skill adları (`/Mla*`) tokengram-a rename ediləcək — hələ defer | Memory: `engram_rename` | – |

## J. Tests

| # | Yoxlama | Necə | Bayraq |
|---|---------|------|--------|
| J1 | `tests/test_phase1.py` ... `test_phase6_i18n.py` keçir | `python -m unittest discover tests` | – |
| J2 | Smoke test: MCP `search_code` direct invocation | `tests/test_phase4_mcp.py` | – |
| J3 | Stop-chain hook test cp1252 regression yoxdur | `tests/test_phase3_stop_chain.py` | – |

## K. Git hygiene

| # | Yoxlama | Necə | Bayraq |
|---|---------|------|--------|
| K1 | `.gitignore` bütün `.mla_*` runtime faylları exclude edir | – | – |
| K2 | `chroma_db.broken-*` commit olunmayıb | git status | – |
| K3 | `vscode-extension/node_modules/` ignore-dadır | – | – |
| K4 | Kritik dəyişikliklər (license_gate.py, mcp_server.py worker) commit olunub | – | – |
| K5 | Branch state təmizdir, force-push tarixçəsi yoxdur | – | – |

## L. Rust prototip

| # | Yoxlama | Necə | Bayraq |
|---|---------|------|--------|
| L1 | `cargo check` xətasız | rust-prototype/mla-search-rs | – |
| L2 | LanceDB runtime state `.gitignored` | – | – |
| L3 | Build log-ları gitignore-dadır | Memory: untrack runtime LanceDB + build logs | – |

---

## 2026-05-19 — `yoxla` pass nəticələri

### Bayraq icmal
| Bölmə | ✅ | ⚠️ | ❌ | ❓ |
|-------|----|----|----|----|
| A. Hooks | A1,A3,A4,A5 | A6 | **A2** | – |
| B. MCP/queue | B2,B3,B4,B5,B6,B7 | B1 | – | – |
| C. ChromaDB | C1,C2,C3 | C4,C5 | – | – |
| D. State files | D3,D5,D6 | D2 | **D1,D4** | – |
| E. Status bar | – | – | – | E1–E6 (VS Code reload lazımdır) |
| F. Ext | F1,F2,F3,F4 | – | **F5** | F6,F7 |
| G. License | G1,G2,G3,G4,G6 | G5,**G7** | – | – |
| H. Dist | H1,H4 | H2,H3 | – | H5,H6 |
| I. Brand | I1 | I2,I4,I5,I6 | **I3** | – |
| J. Tests | **J1,J2,J3** ✅ 78/78 | – | – | – |
| K. Git | K1,K3,K5 | K2,K4 | – | – |
| L. Rust | L1,L2,L3 | – | – | – |

### Aşkar problemlər (prioritet sırası)

**1. ❌ A2 — `license_gate` hook qeydiyyatsız**
- `.claude/settings.json`-da heç bir hook chain-ə əlavə olunmayıb.
- license_gate.py mövcuddur və modul kimi pre_read_check/savings_report-də import olunur — yəni runtime gate işləyir.
- Lakin Stop chain-də müstəqil hook kimi qeydiyyat lazımdır (memory: license_runtime_enforcement).
- **Fix:** Stop chain-ə `license_gate.py` əlavə et VƏ YA bu memory entry-ni düzəlt (gate artıq module-level çağırılır).

**2. ⚠️ G7 — License 6 gün sonra bitir** (expires_at 1779789206 ≈ 2026-05-25)
- `mcp__mla-agent__license_status` cavabı: `{"status": "active", "days_left": 6}`.
- **Fix:** Yeni key issue et və ya subscription rolloveri.

**3. ❌ F5 — CHANGELOG.md köhnə**
- package.json v0.1.12, CHANGELOG.md son entry v0.1.0 (2026-05-15).
- 0.1.1-0.1.12 üçün heç bir release notes yoxdur. Marketplace üçün vacibdir.

**4. ❌ I3 — .mcp.json brand uyğunsuzluğu**
- `mcpServers: {"mla-agent": ...}` — Tokengram brand-i ilə uyğun deyil.
- Bu MCP tool adlarına da təsir edir (`mcp__mla-agent__search_code` instead of `mcp__tokengram__search_code`).
- Bu Tier 3 işidir — break risk var (skill-lər, sənədlər, .claude/commands).

**5. ❌ D1/D4 — Savings widget data zədəli**
- `.mla_savings_history.jsonl` = 0 bayt (bugün 11:12-də sıfırlanıb).
- 18 `.bak.*` faylı yığılıb — rotation policy yoxdur.
- Status bar "data_reset" state göstərməlidir (memory: bar_health_states v0.1.12).
- Bu, memory-də deyilən `feedback_savings_bar_misleading` launch blocker-ı ilə birlikdə düşünülməlidir.

**6. ⚠️ A6 — stderr UTF-8 reconfigure 10/13 hook-da yoxdur**
- Yalnız `arch_doc.py`, `pre_read_check.py`, `savings_report.py` UTF-8 force edir.
- `post_grep_check.py`, `post_bash_check.py` (qeydiyyatlı!) AZ mətn yazsa cp1252 regression baş verə bilər.
- Memory: phase3 test bu bug-u qaytarmaq üçün əlavə edilib.

**7. ⚠️ B1 — 2 MCP server prosesi**
- 2 `python.exe` (PID 6292, 13316) → ehtimal: extension auto-start + manual `.mcp.json` start.
- **Drain status:** İlk yoxlamada stuck görsənirdi, lakin 14:22-də chroma_db mtime yeniləndi və pending növbə təmizlənir. Worker canlıdır.
- **Risk:** Bir prosesi öldürmək cari MCP session-ı sındıra bilər. Adi şərtlərdə vahid proses olmalıdır.

**8. ⚠️ C4/K2 — chroma_db.broken-* arxivi**
- 108MB arxiv (5/18-dən), git-də untracked (?? prefix), .gitignore-də exclude yoxdur.
- **Fix:** .gitignore-yə `chroma_db.broken-*/` əlavə et.

**9. ❌ queue_change.py wired deyil**
- PostToolUse:Edit / PostToolUse:Write hook-u yoxdur.
- Edit-lər avtomatik queue-a düşmür — yalnız file_watcher (varsa) və ya manual flush.

**10. ⚠️ H3 — pyproject.toml v0.1.1 vs ext v0.1.12**
- İki ayrı stream (Python wheel + VS Code ext), bilərəkdən fərqlidir. Sənədləşdirmək lazımdır.

---

## 2026-05-19 — Fix işləri

| # | Status | Fix |
|---|--------|-----|
| K2 | ✅ | `.gitignore`-yə `chroma_db.broken-*/` əlavə olundu. |
| F5 | ✅ | `vscode-extension/CHANGELOG.md` 0.1.1 → 0.1.12 entry-ləri əlavə olundu (memory + commit subjects əsasında). |
| B4 | ✅ | Worker öz-özünə drain etdi (14:22 chroma_db update). Manual müdaxilə lazım olmadı. |
| A2 | ❓ | `license_gate.py` enforcement_active() module-level istifadə olunur (pre_read_check, savings_report). Stop chain-də ayrıca hook qeydiyyatına ehtiyac yoxdur — memory yanıltıcı idi. **Memory düzəliş tələb edir.** |
| G7 | ⚠️ | License 6 gün sonra bitir. User özü `license-server/new_tester_key.ps1` işlədə bilər. |
| D4 | ⚠️ | 18 .bak — kod fix-i `savings_report.py`-də rotation əlavə etmək lazımdır (deferred, 1-2 saat). |
| A6 | ⚠️ | 10 hook-da stderr UTF-8 yoxdur — passive risk, hələ regression yoxdur. |
| I3 | ⚠️ | `.mcp.json` "mla-agent" — Tier 3 brand rename ilə birlikdə edilməlidir (break risk). |
| D1 | ✅/❓ | Savings history boş — bar `data_reset` state göstərməlidir; VS Code-da manual yoxla. |
| – | (queue_change.py) | Hook chain-də qeydiyyatsız, lakin MCP-də file_watcher pickup edir → işlək. Dead code kimi yox, fallback kimi qalsın. |

---

## 2026-05-19 — Launch blocker düzəliş sessiyası

| Blocker | Status | Detal |
|---------|--------|-------|
| #1 Re-index button | ✅ DONE (lk. 0.1.7) | Yanılma idi — MEMORY.md index köhnə idi. Memory düzəldildi. |
| #2 Subfolder workspace hooks | ✅ FIX (ext 0.1.13) | `extension.ts:activate()`-də `mirrorParentWorkspaceHooks()` əlavə olundu — workspace açılanda parent-də `.claude/settings.json` taparsa cari sub-folder-ə kopyalayır. |
| #3 Savings bar misleading | ✅ Partial (ext 0.1.13) | Bar headline-də artıq % yoxdur (lk. 0.1.5-də edilmişdi). Tooltip və package.json description-də "izlənən əməliyyatlar üzrə" şərt əlavə olundu. Edit/Bash output tracker-lər hələ defer. |

**Buraxılış:** `vscode-extension/tokengram-0.1.13.vsix` (98.57 KB). VS Code-a install edildi — user reload etməlidir.

**Hələ açıq launch riski:**
- License key 6 gün sonra bitir (user `license-server/new_tester_key.ps1` işlədə bilər)
- `.mcp.json` server adı "mla-agent" (Tier 3 brand rebrand)
- 10 hook-da stderr UTF-8 yoxdur (passive risk)
- macOS/Linux experimental status (Marketplace mətnində qalır)

---

## 2026-05-19 — Kritik risk auditi

**Soruşulan: "Kritik risk var?"**

| # | Risk | Status | Detal |
|---|------|--------|-------|
| 1 | **Privacy: secrets faylları chromadb-yə düşür** | ✅ FIX (wheel 0.1.2) | `mla_constants.EXCLUDED_FILE_PATTERNS`-ə `.env`, `secrets.`, `credentials.`, `service-account`, `firebase-adminsdk`, `google-services.json` əlavə olundu. Compile + wheel rebuild + runtime test ilə təsdiqləndi. |
| 2 | **Source protection: .py business logic leak?** | ✅ Yanlış xəbərdarlıq | Wheel auditi: yalnız `__init__.py`, `__main__.py`, `server.py` (shim) və `hooks/*.py` source-dur. Bütün business logic 13 `.pyd`-də. |
| 3 | **Developer license 6 gündə bitir** | ⚠️ User fix | `license-server/new_tester_key.ps1` ilə özün üçün yeni key issue et. |

**Buraxılış:** `dist/tokengram-0.1.2-py3-none-any.whl` — privacy fix-li yeni wheel. PyPI-ya upload üçün hazırdır.

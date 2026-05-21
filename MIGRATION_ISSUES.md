# Migration Issues Log

Bu fayl Python-side license integration + Nuitka migration boyunca qarşılaşılan problemləri qeyd edir.

**Format:**
- ✅ HƏLL OLUNDU — problem və qoyulan həll
- ⏸ TƏXİRƏ SALINDI — problem və niyə təxirə salındı + nə zaman bağlanmalıdır
- 🔴 BLOCKER — aktiv blocker, indi həll lazım

Tarix: 2026-05-13

---

## Faza A — License client (Python port)

### ✅ HƏLL OLUNDU: Test env clear Windows-da Path.home() qırır
- **Problem**: `patch.dict(os.environ, {}, clear=True)` Windows-da USERPROFILE/HOME env-lərini silir, `Path.home()` xəta atır.
- **Həll**: `_scrub_mla_env` helper yazıldı — yalnız `MLA_LICENSE_*` env-ləri sil, system env-lərə toxunma.
- **Fayl**: `test_license.py:18-46`

### ⏸ TƏXİRƏ SALINDI: Real server-ə qarşı end-to-end smoke test
- **Problem**: Local-da deploy olunmuş Cloudflare Worker yoxdur, real `/activate` `/validate` axınını sınamaq mümkün deyil. Unit testlərdə HTTP mock-lanır.
- **Niyə təxirə**: Worker `wrangler dev` ilə local-da çalışdırılmalıdır, D1 + KV + Polar.sh secrets quraşdırılmalıdır — 1-2 saatlıq əlavə setup. MVP üçün unit testlər kifayətdir.
- **Nə vaxt bağlanmalı**: Faza D1-də (alpha paylaşmadan əvvəl) — iş yoldaşına .vsix verməzdən qabaq mütləq real Worker-ə qarşı 1 manual smoke test edilməlidir.

### 📋 İz: machineid package istifadə olunur, fallback hazırdır
- `py-machineid` quruldu və işləyir (test maşınında ID: bd1a0a29-459b-49...).
- Fallback (Windows registry, /etc/machine-id, macOS ioreg) yazıldı amma test edilməyib — machineid uğursuz olarsa fallback işə düşür.
- **Risk**: Fallback platformdan-platforma fərqli ID verə bilər (məs. machineid `winreg` istifadə edirsə eyni şey, yoxsa fərq olar). Production-da bir-birinə uyğun olduğundan əmin olmaq lazımdır.

### ✅ HƏLL OLUNDU (2026-05-14): Offline graceful degradation
- **Həll**: `ensure_license()` içində /validate və /activate ikisi də network xətası verərsə, cache-dəki token `exp > now` (cryptographically valid) ikən log warning + cached LicenseGuard qaytarır.
- **Test**: 3 yeni unit test (offline_grace_period_uses_cache_when_server_down, fails_when_cache_expired, fails_when_no_cache) — 27/27 keçir.
- **Behavioral verify**: license.pyd-də runtime test uğurlu (server unreachable + valid cache → graceful).

## Sessiya 2 bug fix-ləri (2026-05-14)

### ✅ HƏLL OLUNDU: Status bar "yenilənmir" hissi
- **Root cause**: Bar yalnız 24h aggregate göstərirdi. Bir böyük entry (450k saved) toplamı dominate edirdi → hər turn-də 5-10k əlavə olunsa belə vizuаl olaraq görünmürdü (504.5k → 509.6k = eyni görsənir).
- **Texniki real durum**: Stop hook fire edirdi, session_log yazılırdı, savings_history yenilənirdi, file watcher fire edirdi, 5s polling işləyirdi. Bar **kifayət qədər canlı idi**, sadəcə **kiçik fərq görünə bilmirdi**.
- **Həll** (statusBar.ts + savingsReader.ts):
  - **Live badge**: `⚡+5k indi` — bu turn-də session_log-da olan pending qənaət. Hər tool call-da görsənir, Stop hook-da history-ə drain olunduqda yox olur. **İmmediate feedback**.
  - **Indexing badge**: `🔄52` — `.mla_pending.txt`-dəki fayl sayı. Background worker faylları drain etdikcə azalır. **User görür ki, "X fayl re-index olunur"**.
  - **Yeni file watcher**: `.mla_pending.txt` dəyişdikdə də refresh tetiklənir.
- **Test**: `npm run compile-check` + `build:prod` keçdi, `.vsix` 7.18 KB (sourcemap-sız).

### ✅ HƏLL OLUNDU: "Hər toggle ON-da re-index olur" misconception
- **Root cause**: Yanlış model. ChromaDB **persistentdir** — 84 MB diskdə, sessiya arası qalır.
- **Diaqnostika sübutu** (2026-05-14 10:37):
  - `chroma_db/chroma.sqlite3`: **68 MB** sqlite
  - **7,588 chunk** indekslidir (87 fayl)
  - chunk növləri: 7165 text_split, 147 markdown_section, 112 function, 64 class_part, etc.
  - file types: 268 .py, 722 .json, 147 .md, 46 .ts, 40 .rs, etc.
- **Toggle davranışı**: `toggle_mla.py` YALNIZ `.mla_enforcement.flag` yazır — ChromaDB-yə toxunmur.
- **Re-index nə vaxt baş verir**:
  - `MlaReindex` skill açıq çağrılır (explicit user action)
  - `index_directory(fresh=True)` parametri verilir (explicit)
  - **`.mla_pending.txt` faylları** — bunlar edit olunmuş fayllardır, **incremental** re-embed. MCP server-in daxili `watchdog` izləyicisi əlavə edir.
- **52 fayl pending-də olması**: Bu sessiyada mən çoxlu edit etdim (mcp_server.py, license.py, esbuild.config.js, README-lər, etc.). Watchdog onları queue-ya qoydu. Background worker drain edir (drain 20 fayl/dövr).
- **Claude API quota istifadəsi**: Re-index local sentence-transformers modeli ilə embed edir. **Heç bir Claude API çağırışı YOXDUR**. CPU + RAM istifadəsi var, lakin API token-i sərf olunmur.
- **Yeni indexing badge** (yuxarıdakı bug fix): user indi `🔄52` görür, başa düşür ki, 52 fayl background-da re-embed olunur.

### ✅ Faza A xülasəsi
- 24/24 unit test keçir.
- `mcp_server.py` import smoke test keçdi: license modulu wire olunub, `_check_license()` dev mode-da None qaytarır.
- 5 mövcud MCP tool (`search_code`, `index_directory`, `index_file`, `get_stats`, `route_project`) hamısında `_check_license()` gate var.
- Yeni `license_status` MCP tool əlavə olundu — extension status bar üçün.
- `requirements.txt` 4 yeni dependency əlavə olundu (pyjwt[crypto], cryptography, requests, py-machineid).
- `LicenseConfig.from_env()` artıq fayl fallback dəstəkləyir: env → ~/.mla/license_key.txt → None. VSCode extension license_key-i bu fayla yazır, MCP server (Claude Code tərəfindən spawn olunduğu üçün) faylı oxuyur.

---

## Faza B — Nuitka build (LƏĞV EDİLDİ)

### ❌ LƏĞV EDİLDİ: Standalone build heavy deps üzündən praktiki deyildi
- Build başladı: 22:34, 20+ dəq analiz fazasında qaldı.
- chromadb → sentence-transformers → torch → transformers → huggingface_hub → PIL transitively kəşf olunan modul sayı 10,000+ keçdi.
- 2 GB RAM Nuitka analyzer-də, hələ kod generation-a çatmamışdı.
- Yekun build vaxt proqnozu: 1-3 saat; binary ölçüsü: 1-2 GB.
- **Qərar**: Nuitka standalone bütün dependency tree-ni kompil edir, halbuki public Python paketləri (chromadb, torch, etc.) onsuz da GitHub-da açıqdır. Yalnız bizim biznes logic qorunmalıdır.

## Faza E — Cython hybrid (NUITKA YERİNƏ)

### ✅ HƏLL OLUNDU: 6 biznes modulu Cython ilə .pyd-ə kompil olundu
- Build vaxt: ~3 dəq (Nuitka 1-3 saat ilə müqayisədə)
- Binary ölçüsü: 896 KB cəmi (Nuitka 1-2 GB ilə müqayisədə)
- `setup_cython.py` Windows multiprocessing fork-safe (`if __name__ == "__main__"` guard + nthreads=0)
- Cython directives: `language_level=3`, `embedsignature=True` (FastMCP inspect.signature() üçün), `binding=True`

### ✅ HƏLL OLUNDU: .pyd-yə qarşı 24/24 test keçdi
- .py mənbə faylları müvəqqəti silindi → yalnız .pyd ilə testlər keçdi → .py geri qaytarıldı
- mcp_server.pyd uyğur import olunur, `_check_license()` gate işləyir
- license.pyd Claims, LicenseConfig, ensure_license — hamısı .py kimi davranır

### ✅ HƏLL OLUNDU: Distribution paketi (0.42 MB zip)
- `make_distribution.py` skripti yazıldı: Cython build → dist qovluğu → zip
- `dist/mla-agent-0.1.0-alpha/`:
  - 6 .pyd (compiled biznes logic)
  - config.py, main.py, hooks/ — sensitive olmayan yardımçılar
  - requirements.txt — açıq Python paketləri
  - .mcp.json — `python -m mcp_server` çağırır
- Sensitive .py mənbə (license.py, mcp_server.py, və s.) paketdə YOXDUR

### ✅ HƏLL OLUNDU: .gitignore yeniləndi
- `*.pyd`, `*.c`, `*.so`, `dist_compiled/`, `nuitka_build/` ignore olunur

### ✅ HƏLL OLUNDU (2026-05-14): VSCode extension sourcemap + minify
- `esbuild.config.js`-də `--prod` flag dəstəyi: sourcemap off, minify on, drop console/debugger, legalComments none, keepNames false.
- `package.json` `vscode:prepublish` `build:prod`-a yönəlir.
- `.vsix` indi 6.95 KB (əvvəl 18 KB sourcemap-li); extension.js 15.07 KB minified.
- Casual inspector .vsix unzip etsə minified single-line JS görür, TypeScript bərpa oluna bilməz.

### ⏸ TƏXİRƏ SALINDI (BY DESIGN): Cross-platform .pyd builds
- Hazırda yalnız Windows x86_64 / Python 3.12. Linux və macOS üçün ayrıca build lazımdır.
- **Niyə təxirə**: İş yoldaşları Windows-da. Mac/Linux user gəldikdə həll edilər.
- **Həll**: Hər platformda `python setup_cython.py build_ext --inplace` icra et, .pyd-ləri ayrı arch artifact-da paketlə. CI matrix-i GitHub Actions ilə sonra avtomatlaşdırılır.

### ⏸ TƏXİRƏ SALINDI (BY DESIGN): machineid fallback test edilməyib
- `py-machineid` Windows-da işləyir (test maşınında: bd1a0a29-459b-49...).
- Manual fallback (winreg, /etc/machine-id, macOS ioreg) yazılıb amma test edilməyib.
- **Niyə təxirə**: machineid uğursuz olarsa fallback işə düşür — sınanmaq üçün machineid-i siləməliyik, alpha-da bu hal olmayacaq.
- **Risk**: Aşağı. machineid widely-used, stable package.

### ⏸ TƏXİRƏ SALINDI (BY DESIGN): Top-level "Set License Key" command
- "Set license key" hazırda `mla.menu` QuickPick içindədir. Ayrıca top-level command `Ctrl+Shift+P` axtarışında görünmür.
- **Niyə təxirə**: Menu içində yetərli — kolleq onsuz da menu-dən keçəcək. UX-də önəmli fərq yoxdur.
- **Həll** (lazım olsa): `vscode-extension/package.json` `contributes.commands`-a yeni entry: `{ "command": "mla.setLicenseKey", "title": "MLA: Set License Key" }` + `extension.ts`-də registerCommand.

### ⏸ TƏXİRƏ SALINDI: Real Worker-ə qarşı E2E smoke test
- Local-da deploy olunmuş Cloudflare Worker yoxdur, real /activate /validate axını sınanmayıb.
- **Niyə təxirə**: Worker setup user tərəfində (DEPLOYMENT_GUIDE.md). User Worker-i deploy etdikdə alpha-dan əvvəl mütləq edilməlidir.
- **Sənədləşmə**: DEPLOYMENT_GUIDE.md §5 — smoke test checklist.

### ⏸ TƏXİRƏ SALINDI: Dev key generate prosesi
- Polar.sh sandbox quraşdırması mürəkkəbdir, manual D1 INSERT skripti DEPLOYMENT_GUIDE.md-də verildi.
- **Niyə təxirə**: User tərəfində — D1 deploy olunduqdan sonra hər kolleq üçün ayrıca generate.
- **Komanda**: DEPLOYMENT_GUIDE.md §3 (PowerShell snippet).

## Faza C — Extension dəyişiklikləri

### ✅ HƏLL OLUNDU: Extension license_key UI
- `menu.ts`-də yeni "Set license key" QuickPick item əlavə olundu.
- `setLicenseKey()` funksiyası `~/.mla/license_key.txt` faylına yazır (mode 0o600).
- Format yoxlama: `mla_live_` və ya `mla_test_` ilə başlamalıdır.
- i18n strings EN + AZ əlavə olundu.
- TypeScript compile keçdi, esbuild bundle keçdi.

### ✅ HƏLL OLUNDU: .mcp.json.binary template
- `.mcp.json.binary` yaradıldı — Nuitka binary-yə yönəlir.
- Production-da bu fayl `.mcp.json` olaraq deploy ediləcək.
- Dev environment-də mövcud `.mcp.json` (python mcp_server.py) saxlanır.
- `vscode-extension/bin/` qovluğu yaradıldı, binary buraya köçürüləcək.

### ⏸ TƏXİRƏ SALINDI: Extension command package.json contributes
- Yeni "License" action mövcud `mla.menu` QuickPick-ə əlavə olundu — yeni top-level command lazım deyil.
- `package.json` `contributes.commands` dəyişdirilmədi (cari sadəcə `mla.menu` var, kifayət edir).
- **Niyə təxirə**: Əgər user "Set License Key"-ə top-level command istəsə (Ctrl+Shift+P-də ayrıca tap olmaq üçün), sonra əlavə edə bilərik.

## Faza D — Distribution

### ⏸ TƏXİRƏ SALINDI: Dev key generate prosesi
- Polar.sh sandbox test subscription / D1 direct INSERT — hələ icra edilməyib.
- **Niyə təxirə**: Worker deploy olunmalıdır + Polar.sh hesabı + D1 + KV credentials. Setup ayrıca tasking-dir.
- **Nə vaxt bağlanmalı**: İş yoldaşlarına .vsix verməzdən qabaq mütləq bir test key generate olunmalı və end-to-end yoxlanmalıdır.
- **Komanda nümunəsi (Polar.sh-dən sonra)**:
  ```bash
  # Production Worker D1-də manual INSERT
  npx wrangler d1 execute mla-licenses --remote --command \
    "INSERT INTO licenses (key, user_id, status, created_at) \
     VALUES ('mla_live_dev_colleague001', 'colleague@example.com', 'active', strftime('%s','now'));"
  ```

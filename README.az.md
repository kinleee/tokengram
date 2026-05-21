# Tokengram — Hybrid RAG Yaddaş Qatı

Claude Code üçün lokal kod axtarış MCP server-i.
**Token qənaəti:** Axtarış/Read-heavy iş axınlarında **~70%-ə qədər** input
token azalır; Edit-heavy refactor-larda qənaət daha azdır (Edit, xam `Bash`
output, sistem-prompt overhead Tokengram-dan keçmir).
**Progressive RAM:** 93 MB (BM25-only) → 700 MB (semantic) → 900 MB (+ reranker).

## Nədir bu?

İş yoldaşına Claude Code-da kod haqqında sual verəndə Claude faylları `Read` ilə tam oxuyur — hər sorğuda 5-10K input token gedir. Tokengram layihəni əvvəlcədən vektorlaşdırır və Claude soruşduqda yalnız **uyğun ~3-5 chunk** qaytarır. Yəni:

- ⚡ **Axtarış-heavy işlərdə 70%-ə qədər az input token** → daha ucuz API çağırışları
- 🔒 **Lokal-only** — kodun heç bir yerə getmir (lokal embedding + lokal axtarış)
- ♻️ **Avtomatik re-index** — sən fayl save edəndə MCP avtomatik yeniləyir
- 🎯 **Hybrid search** — semantic (meaning) + BM25 (keyword) + cross-encoder reranker

## Nə vaxt İŞƏ YARAYIR?
- ✅ Orta-böyük Python/JS/Go layihələri (50+ fayl)
- ✅ "Bu funksiya hara çağırılır?" tipli kontekstual suallar
- ✅ Refactoring üçün kontekst yığma

## Nə vaxt İŞƏ YARAMIR (hələlik)?
- ❌ <20 fayllı layihələr — Claude onsuz da hər şeyi oxuya bilir
- ❌ 4 GB RAM-dan az olan maşınlar (embedding + reranker üçün lazımdır)
- ❌ Python qurulmamış sistemlər

---

## Quraşdırma (~3 dəqiqə)

### Tələblər
- Python 3.10+
- VS Code + Claude Code extension
- 4 GB RAM (8 GB tövsiyə)
- ~500 MB disk (model cache üçün)

### Windows
```powershell
git clone <repo-url> mla-agent
cd mla-agent
./setup.ps1
```

### macOS / Linux
```bash
git clone <repo-url> mla-agent
cd mla-agent
./setup.sh
```

### Sonra
1. **VS Code-u tam bağla və yenidən aç** (MCP server-i pickup üçün)
2. Claude Code-da `/mcp` — `mla-agent` `connected` olmalıdır
3. Sual ver:
   > "mla-agent.search_code istifadə et — autentifikasiya harada həyata keçirilib?"

Claude avtomatik MCP tool-u çağırır, top-4 ən uyğun chunk-ı kontekst kimi alır, və sənə cavab verir.

---

## Başqa layihəni indeksləşdirmək

Hər layihə üçün ayrı indeksləmə lazımdır.

### Variant 1 — yeni layihə üçün setup-ı yenidən qaç
```powershell
./setup.ps1 -ProjectDir "C:\path\to\my-project"
```

### Variant 2 — manual əmr
```bash
python main.py index /path/to/my-project --fresh
```

> **Diqqət:** Hal-hazırda `chroma_db/` Tokengram qovluğunda saxlanılır. Yəni eyni anda yalnız bir layihə indekslənmiş ola bilər. Multi-project dəstəyi gələn versiyadadır.

---

## CLI Əmrləri

```bash
python main.py index <dir> [--fresh]    # İndeksləşdir
python main.py stats                     # Baza statistikası
python main.py route <dir>               # Smart router məsləhəti
python main.py reset --yes               # Bazanı sıfırla
python main.py watch <dir>               # Avtomatik re-index (Ctrl+C ilə dayan)
python main.py ask "sual"                # CLI üzərindən sual (API açarı lazım)
```

---

## MCP Alətləri

Claude Code avtomatik bunları görür və lazım olduqda çağırır:

| Alət | Nə edir |
|------|---------|
| `search_code(query, top_k, mode, file_type)` | 3-tier axtarış (aşağıda) |
| `index_directory(path, fresh)` | Layihəni indeksləşdir |
| `index_file(path)` | Tək faylı re-index |
| `get_stats()` | Baza statistikası |
| `route_project(path)` | Layihə ölçüsünə əsaslanan tövsiyə |

### search_code rejimləri (progressive RAM)

| `mode` | RAM artımı | İlk çağırış | Hansı sorğular |
|--------|-----------|-------------|----------------|
| `"fast"` (default) | **0 MB** | ~50ms | Funksiya/sinif/fayl adı, sintaktik axtarış |
| `"semantic"` | +400-700 MB | 30-60s | "Auth necə işləyir" tipli konseptual sorğular |
| `"rerank"` | +200 MB | +30s ilk | Maksimum sıralanma keyfiyyəti |

**İdealca:** Claude default `"fast"` istifadə edir. Sintaktik nəticə kifayətdirsə, dayanır. Konseptual cavab lazımdırsa, `"semantic"`-ə keçir. Reranker yalnız çox vacib seçimlər üçün.

---

## Auto Re-Index

İki paralel mexanizm — hər ikisi eyni növbəyə (`.mla_pending.txt`) yazır, MCP-nin fon işçisi dren edir:

### 1. Daxili watcher (default, **bütün IDE-lərdə işləyir**)
MCP server startup-da watchdog ilə proyekt qovluğunu izləyir. VS Code, Antigravity, Cursor — fərq etməz. Hooks lazım deyil.
- İzləniləcək qovluq: MCP serverin `cwd`-si (default), və ya `MLA_WATCH_DIR` env override
- Söndürmək: `MLA_DISABLE_WATCHER=1`
- Debounce: 2s (çoxsaylı save-lər birləşir)

### 2. Claude Code hooks (yalnız Claude Code-da)
- `PostToolUse` (~50ms) — Edit/Write/MultiEdit-dən sonra fayl yolu növbəyə yazılır
- `Stop` — Claude cavabı bitəndə (artıq pasif: əsas iş MCP fon işçisi tərəfindən görülür)

İki mexanizm birgə işləyir — drainer hash check + dedup edir, ikiqat re-index olmur.

---

## Tez-tez sorulan suallar

### API açarı lazımdır?
**Yox.** Claude Code-da MCP üzərindən istifadə edirsənsə, bütün düşünmə Claude tərəfindən edilir. API açarı yalnız standalone CLI `python main.py ask` üçün lazımdır.

### İlk axtarış niyə yavaşdır?
İlk MCP `search_code` çağırışı ~10-30s — embedding modeli RAM-a yüklənir. Sonrakı çağırışlar ~100ms.

### Hansı dilləri dəstəkləyir?
- Python (.py) — AST-based chunking
- Solidity (.sol) — Regex-based
- SQL (.sql) — Statement-based
- Markdown (.md) — Heading-based

JavaScript/TypeScript hələ fallback splitter istifadə edir (gələn versiyada AST əlavə olunacaq).

### Ne qədər disk yer tutur?
- Embedding model: ~130 MB (bge-small)
- Reranker model: ~90 MB (ms-marco-MiniLM)
- ChromaDB indeks: ~5-10 KB / fayl (təxmini)

100 fayllı layihə üçün cəmi: ~220 MB.

### Problem var?
Bax: [PROBLEMS.md](PROBLEMS.md) — quraşdırma zamanı qarşılaşdığımız 14 problem və hər birinin həlli.

---

## Layihə Quruluşu

```
mla-agent/
├── config.py              # Bütün parametrlər
├── document_loader.py     # AST + regex chunking
├── vector_store.py        # ChromaDB wrapper
├── search_engine.py       # Hybrid (semantic + BM25 + reranker)
├── llm_agent.py           # Standalone CLI agent (opsional)
├── smart_router.py        # Layihə ölçüsünə əsaslanan rejim
├── file_watcher.py        # Standalone watchdog (opsional)
├── main.py                # CLI giriş nöqtəsi
├── mcp_server.py          # Claude Code MCP server
├── hooks/
│   ├── queue_change.py    # PostToolUse hook
│   └── flush_queue.py     # Stop hook
├── .mcp.json              # Claude Code MCP qeydi
├── .claude/settings.json  # Hook konfiqurasiyası
├── setup.ps1, setup.sh    # Quraşdırma skriptləri
├── PROGRESS.md            # Inkişaf jurnalı
└── PROBLEMS.md            # Tapılan/həll edilən problemlər
```

---

## Lisenziya

Kommersiya. Bax: [vscode-extension/LICENSE.txt](vscode-extension/LICENSE.txt). Feedback: n.ilkin.humbatov@gmail.com

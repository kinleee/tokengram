# MLA Agent — İrəliləmə Hesabatı

> **Sonuncu yenilənmə:** 2026-04-30
> **Layihə:** Hybrid RAG əsaslı kod axtarış və sual-cavab agenti

---

## 📊 Mərhələlərin Vəziyyəti

| Mərhələ | Modul | Status | Təsvir |
|---------|-------|--------|--------|
| 1 | `document_loader.py` | ✅ Tamam | AST + regex əsaslı chunking (Python/Solidity/SQL/Markdown) |
| 2 | `vector_store.py` | ✅ Tamam | ChromaDB + nomic-embed-code + hash-əsaslı incremental |
| 3 | `search_engine.py` | ✅ Tamam | Hybrid (Dense + BM25) + RRF fusion + Reranker |
| 4 | `llm_agent.py` | ✅ **Yeni** | Claude + GPT provider, prompt caching, decomposition |
| 5 | `smart_router.py` | ✅ **Yeni** | Layihə ölçüsünə görə DIRECT / RAG_LIGHT / RAG_FULL |
| 6 | `file_watcher.py` | ✅ **Yeni** | watchdog + debounce ilə avto re-index |
| 7 | `main.py` | ✅ **Yeni** | CLI: `index`, `ask`, `watch`, `stats`, `reset`, `route` |
| 8a | `mcp_server.py` | ✅ **Yeni** | Claude Code üçün MCP server (FastMCP, 6 alət) |
| 8b | `hooks/queue_change.py` | ✅ **Yeni** | PostToolUse hook — sürətli növbə (~50ms) |
| 8c | `hooks/flush_queue.py` | ✅ **Yeni** | Stop hook — növbəni axirə endirir |
| 8d | `.mcp.json`, `.claude/settings.json` | ✅ **Yeni** | Claude Code konfiqurasiyası |

---

## ✅ Bu Sessiyada Tamamlananlar

### 1. `llm_agent.py` — LLM Agent
- **`BaseLLMProvider`** abstraksiyası → `AnthropicProvider` və `OpenAIProvider`
- **Anthropic prompt caching** (`cache_control: ephemeral`) — eyni system prompt-da təkrar sorğular üçün xərc azalır
- **Streaming dəstəyi** — uzun cavablarda token-bə-token çıxış
- **`format_context()`** — axtarış nəticələrini strukturlu LLM kontekstinə çevirir (mənbə nömrələri, fayl, simvol)
- **`RAGAgent.ask()`** — birləşdirilmiş hybrid axtarış + LLM cavabı
- **`ask_with_decomposition()`** — mürəkkəb sualları 2-3 alt-suala bölür, hər biri üçün ayrıca axtarır, nəticələri deduplicate edir

### 2. `smart_router.py` — Smart Router
- `tiktoken` ilə token sayma (yoxdursa fallback: `len/4`)
- 3 rejim: **DIRECT** (<4K token), **RAG_LIGHT** (<50K), **RAG_FULL** (≥50K)
- `SmartRouter` sinfi avtomatik rejim seçimi + axtarış parametrləri

### 3. `file_watcher.py` — File Watcher
- `watchdog.Observer` ilə qovluq izləmə (rekursiv)
- **Debounce məntiq** (`config.WATCHER_DEBOUNCE_SEC = 2.0s`) — bir saniyəlik IDE save partlayışları bir hadisəyə birləşir
- Yalnız dəstəklənən uzantılar (`.py`, `.sol`, `.sql`, `.md`)
- `EXCLUDED_DIRS`-dakı qovluqlar avtomatik atlanır
- Silinmə hadisəsi → `vector_store.delete_file()`
- Dəyişmə → `vector_store.index_file()` (hash yoxlaması ilə)

### 4. `main.py` — CLI
- 6 alt-əmr: `index`, `ask`, `watch`, `stats`, `reset`, `route`
- `ask` üçün flaqlar: `--stream`, `--decompose`, `--show-sources`, `--top-k`, `--provider`
- `index` üçün `--fresh` (köhnə bazanı silmək)
- `--verbose` ilə debug logging

### 5. `config.py` — Yeniləmə
- `ANTHROPIC_MODEL` köhnə `claude-sonnet-4-20250514` → aktual `claude-sonnet-4-6` (2026-cı il aprel)

---

## 🐛 Üzləşilən Problemlər və Həllər

### 1. Anthropic prompt caching strukturu
**Problem:** Anthropic SDK-da system mesajı string ola bilər, amma caching üçün `[{type: "text", text: ..., cache_control: ...}]` formatı tələb olunur.
**Həll:** `AnthropicProvider.complete()` daxilində system mesajını həmişə cache-lənmiş formatda göndəririk. Eyni kontekst üçün təkrar sorğular əhəmiyyətli dərəcədə ucuz olur (~90% input token endirimi).

### 2. Watchdog debounce → çox sayda eyni-fayl save hadisəsi
**Problem:** VS Code/PyCharm bir fayl save edəndə 3-5 hadisə yarada bilir (`modified` × 3). Hər biri üçün ayrıca re-index = lazımsız hesablama.
**Həll:** `_DebouncedHandler._schedule()` daxilində bir `threading.Timer` saxlanılır. Yeni hadisə gələndə timer reset olunur. Yalnız son 2 saniyədə sakitlik olduqdan sonra `_flush()` işə düşür və yığılmış pending dict işlənir.

### 3. Fayl köçürülməsi (`on_moved`) — köhnə yol bazada qalmaq problemi
**Problem:** `mv old.py new.py` zamanı yalnız `on_moved` çağırılır, `on_deleted` yox. Köhnə chunk-lar bazada qalır.
**Həll:** `on_moved` handler-də həm `src_path` üçün `delete`, həm də `dest_path` üçün `modified` planlaşdırılır.

### 4. Smart router üçün tiktoken yoxluğu
**Problem:** İstifadəçidə `tiktoken` quraşdırılmaya bilər (böyük asılılıq).
**Həll:** `count_tokens()` daxilində try/except — uğursuz olarsa `len(text) // 4` təxmini istifadə olunur (≈ ortalama BPE nisbəti).

### 5. Query decomposition — model JSON deyil mətn qaytara bilir
**Problem:** Claude/GPT bəzən "Bu suallar ola bilər: ..." şəklində izahla cavablayır, JSON parse uğursuz olur.
**Həll:** `decompose_query()` `re.search(r'\[.*\]', answer, re.DOTALL)` ilə cavabdan JSON list-i çıxarır. Tapılmazsa, orijinal sual yeganə "alt-sual" kimi qaytarılır (graceful fallback).

### 6. Boş kolleksiya üzərində ChromaDB query xətası
**Problem:** `collection.count() == 0` halında `.query()` exception atırdı.
**Həll:** `_semantic_search()` əvvəlcə `count()` yoxlayır, sıfırdırsa boş list qaytarır.

### 7. Çox-prosesli BM25 staleness (MCP server vs hook)
**Problem:** `flush_queue.py` hook-u Claude turn-i bitəndə fayl indeksləyir, amma MCP server prosesi ayrıdır — onun in-memory BM25 indeksi köhnə qalır. Növbəti `search_code` çağırışı yeni faylları BM25 nəticələrində görmür.
**Həll:** `.file_hashes.json` faylının `mtime`-ı paylaşılan signal kimi istifadə olunur. `HybridSearchEngine.__init__` zamanı bu mtime "imza" kimi saxlanılır; hər `search()` əvvəlində `os.path.getmtime` ilə yoxlanır (~mikrosaniyə). İmza dəyişibsə → BM25 avtomatik yenidən qurulur. Beləcə hook və MCP server arasında əl ilə sinxronizasiya lazım deyil.

---

## 🔌 Claude Code İnteqrasiyası (MƏRHƏLƏ 8 — Hibrid)

İki yolla işləyir, paralel olaraq:

### A) MCP Server (`mcp_server.py`)
Claude Code başlayanda `.mcp.json`-u oxuyur və `mla-agent` adlı serveri stdio rejimində fork edir. Server `FastMCP` üzərində qurulub və **5 retrieval-only alət** açır (heç bir LLM çağırışı yoxdur — düşünmə Claude Code-un öz Claude-u tərəfindən edilir, ona görə **API açarı lazım deyil**):

| Alət | Nə edir |
|------|---------|
| `search_code(query, top_k, file_type)` | Hybrid axtarış nəticələri |
| `index_directory(path, fresh)` | Bütün qovluğu indeksləşdir |
| `index_file(path)` | Tək fayl üçün incremental |
| `get_stats()` | Baza statistikası |
| `route_project(path)` | Smart router məsləhəti |

Lazy-load strategiyası: `_store` və `_engine` ilk istifadədə qurulur və MCP server prosesinin ömrü boyu yaşayır. Yəni embedding modeli 1 dəfə yüklənir.

> **Qeyd:** Əvvəl `ask_codebase` aləti də vardı (RAG ilə öz LLM cavabı yaradan). Claude Code kontekstində dublikat olduğuna görə MCP-dən çıxarılıb. Standalone CLI üçün `python main.py ask` qalır — orada API açarı lazımdır.

### B) Avto-İndeksləşdirmə Hook-ları
**Problem:** Hər `Edit`-də ChromaDB import etmək = 3-5 saniyə gecikmə = pis UX.

**Həll — növbə strategiyası:**

```
Edit/Write/MultiEdit
        ↓
  PostToolUse hook
   (queue_change.py)
        ↓
.mla_pending.txt-ə yol əlavə
        ↓
   ... çoxlu redaktə ...
        ↓
  Claude cavabı bitirdi
        ↓
     Stop hook
   (flush_queue.py)
        ↓
Növbəni oxu, dedup et,
incremental re-index
```

- `queue_change.py` heç bir ağır import etmir → ~50ms
- `flush_queue.py` Claude turn-də bir dəfə işləyir, hash-əsaslı incremental sayəsində yalnız həqiqətən dəyişmiş fayllar yenidən indekslənir
- Əgər fayl Claude tərəfindən silindiyse (`p.exists() == False`), `delete_file()` çağırılır

### Aktivləşdirmək üçün
1. `pip install -r requirements.txt` (`mcp` paketi əlavə olundu)
2. `.env`-də real API açarı qoy
3. `python main.py index . --fresh` (ilk indeks)
4. **Claude Code-u yenidən başlat** (MCP server-i pick up etmək üçün)
5. `/mcp` əmri ilə `mla-agent` serverin qoşulduğunu yoxla

---

## ⚠️ Hələ Açıq Olan Məsələlər

1. ~~**BM25 indeksi watcher/hook tərəfindən yenilənmir.**~~ ✅ **HƏLL OLUNDU.** `HybridSearchEngine` artıq `.file_hashes.json` faylının `mtime`-ını "imza" kimi saxlayır. Hər `search()` çağırışında ucuz `os.path.getmtime` yoxlanır — başqa proses (məs. `flush_queue.py` hook-u) hash faylına yazıbsa, BM25 avtomatik yenidən qurulur. ChromaDB SQLite üzərindən onsuz da paylaşıldığı üçün dense indeks həmişə təzədir. (Bax: `_ensure_fresh_bm25()` — search_engine.py)
2. **DIRECT rejim hələ `RAGAgent`-ə inteqrasiya olunmayıb.** `SmartRouter` rejim qaytarır, amma `RAGAgent.ask()` həmişə RAG istifadə edir. Növbəti addım: agent-ə router ötürmək və DIRECT halında `load_all_files_as_context()`-i birbaşa LLM-ə göndərmək.
3. **`config.GRAPH_EXPANSION_COUNT` istifadə olunmur.** Graph expansion (eyni faylın qonşu chunk-larını gətirmək) hələ tətbiq edilməyib — opsional 8-ci mərhələ ola bilər.
4. **Cost tracking yoxdur.** `tokens_used` qaytarılır, amma birikmiş xərc dollarla göstərilmir.
5. **API açarları `.env`-də placeholder qalıb** (`your_anthropic_api_key_here`). İstifadəyə qədər real açarla əvəz olunmalıdır.

---

## 🚀 Sürətli Başlanğıc

```bash
# 1. Asılılıqları quraşdır
pip install -r requirements.txt

# 2. .env-də API açarını qoy
# ANTHROPIC_API_KEY=sk-ant-...

# 3. Layihəni indeksləşdir
python main.py index ./my_project --fresh

# 4. Sual ver
python main.py ask "İstifadəçi autentifikasiyası harada həyata keçirilir?" --show-sources --stream

# 5. Avtomatik re-index üçün izlə
python main.py watch ./my_project

# 6. Statistika
python main.py stats

# 7. Layihə üçün uyğun rejim
python main.py route ./my_project
```

---

## 🧪 Test Tövsiyəsi

Hələ test faylları yazılmayıb. Növbəti sessiya üçün təklif:

- `tests/test_chunking.py` — Python AST-in böyük sinfi metodlarına böldüyünü yoxla
- `tests/test_search.py` — RRF fusion düzgün rank verdiyini yoxla (mock ChromaDB ilə)
- `tests/test_router.py` — token threshold-larında düzgün rejim seçildiyini yoxla
- `tests/test_watcher.py` — debounce-un 5 ardıcıl save-i 1 hadisəyə birləşdirdiyini yoxla

---

## 📁 Layihə Quruluşu

```
MLA_AGENT/
├── config.py              # Bütün parametrlər
├── document_loader.py     # MƏRHƏLƏ 1 — chunking
├── vector_store.py        # MƏRHƏLƏ 2 — ChromaDB
├── search_engine.py       # MƏRHƏLƏ 3 — hybrid axtarış
├── llm_agent.py           # MƏRHƏLƏ 4 — LLM agent
├── smart_router.py        # MƏRHƏLƏ 5 — router
├── file_watcher.py        # MƏRHƏLƏ 6 — auto re-index
├── main.py                # MƏRHƏLƏ 7 — CLI
├── mcp_server.py          # MƏRHƏLƏ 8a — MCP server     ← YENİ
├── hooks/
│   ├── queue_change.py    # MƏRHƏLƏ 8b — sürətli queue   ← YENİ
│   └── flush_queue.py     # MƏRHƏLƏ 8c — bulk re-index   ← YENİ
├── .mcp.json              # MCP server qeydi             ← YENİ
├── .claude/
│   └── settings.json      # Hook konfiqurasiyası          ← YENİ
├── PROGRESS.md            # Bu sənəd
├── requirements.txt
├── .env
├── .gitignore
├── .mla_pending.txt       # Hook növbəsi (avto-yaradılır)
└── chroma_db/             # Avto-yaradılır
```

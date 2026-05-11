# Aşkar Edilmiş Problemlər

> **Tarix:** 2026-05-05
> **Kontekst:** İlk dəfə MCP server-i Claude Code daxilindən sınamağa cəhd edildi. `get_stats` aləti çağırıldı və 30+ dəqiqə cavab gəlmədi.
>
> **Status (sonuncu yenilənmə 2026-05-05 22:58):** ✅ Layihə uğurla indekslənir, sınağa hazırdır.

---

## 📈 Həll Cədvəli

| # | Problem | Status | Qeyd |
|---|---------|--------|------|
| P1 | `nomic-embed-code` 14GB | ✅ Həll olundu | `BAAI/bge-small-en-v1.5` (130MB) |
| P2 | Heç bir progress feedback | 🟡 Qismən | İlk yükləmə hələ də gözləməsizdir, amma 30s yox 1-3 dəq |
| P3 | Boş chroma_db artefakt | 🟢 Qəbul olundu | Əhəmiyyətsiz |
| P4 | Yanıltıcı şərh | ✅ Həll olundu | config.py-də yenilənib |
| P5 | tiktoken məcburi | 🟢 Qəbul olundu | Az prioritet |
| P6 | MCP timeout riski | ✅ Həll olundu | Yeni model yükləməsi 30s — timeout-dan az |
| **P7 (YENİ)** | Encoding xətası — Windows cp1252 | ✅ Həll olundu | main.py-də utf-8 reconfigure |
| **P8 (YENİ)** | `einops` paketi yox idi | ✅ Həll olundu | requirements.txt-ə əlavə (artıq lazım deyil) |
| **P9 (YENİ)** | ChromaDB ≥ 0.6 `name()` tələb edir | ✅ Həll olundu | `CodeEmbeddingFunction.name()` əlavə |
| **P10 (YENİ, KRİTİK)** | nomic-text-v1.5 Windows-da segfault | ✅ Həll olundu | Modeli bge-small-ə dəyişdirdim |
| **P11 (YENİ, KRİTİK)** | langchain top-level import 24 saniyə | ✅ Həll olundu | Lazy import-a keçirildi |
| **P12 (YENİ)** | Embedding modeli `__init__`-də yüklənirdi | ✅ Həll olundu | Lazy-of-lazy refactor |
| **P13 (YENİ, KRİTİK)** | FastMCP worker thread-də Python import deadlock | ✅ Həll olundu | Heavy import-lar module-level-ə qaldırıldı |
| **P14 (YENİ)** | bge-reranker-v2-m3 8GB RAM sistemdə yüklənmir | ✅ Həll olundu | ms-marco-MiniLM-L-6-v2 (25x kiçik) seçildi |

---

## 🆕 Sessiya Boyu Aşkarlanan Yeni Problemlər (qısa)

### P7 — Windows konsol cp1252 encoding-i emoji yaza bilmir
**Simptom:** `python main.py index .` dərhal `UnicodeEncodeError` ilə crash etdi (`📂` yaza bilmir).
**Həll:** `main.py`-in başında `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`.

### P8 — `nomic-embed-text-v1.5` `einops` paketini tələb edir
**Simptom:** `trust_remote_code=True` → custom modul → `einops` import → `ModuleNotFoundError`.
**Həll:** `pip install einops` + requirements.txt-ə əlavə. (Sonradan modeli dəyişdik, artıq lazım deyil — amma requirements-də qalır).

### P9 — ChromaDB ≥ 0.6 EmbeddingFunction-da `name()` metodu tələb edir
**Simptom:** `AttributeError: 'CodeEmbeddingFunction' object has no attribute 'name'`.
**Səbəb:** ChromaDB API-si dəyişib — embedding function-ları unikal ad ilə qeyd olunmalıdır (telemetrik və caching üçün).
**Həll:** `CodeEmbeddingFunction.name()` static metodu əlavə olundu.

### P10 — nomic-text-v1.5 Windows-da segfault (kritik)
**Simptom:** Model yükləndikdən sonra `collection.upsert()` zamanı **exit code 139 (segmentation fault)**, Python traceback yox — C-level crash.
**Səbəb:** `trust_remote_code=True` ilə yüklənən nomic-bert custom kodu Windows-da PyTorch ilə uyğunsuz. Linux-da işləyir, Windows-da yox.
**Həll:** `BAAI/bge-small-en-v1.5`-ə keçdik — standard SentenceTransformer arxitekturası, custom kod yoxdur, Windows-da stabil.

### P11 — `langchain_text_splitters` top-level import 24 saniyə çəkir (kritik UX)
**Simptom:** MCP `get_stats` çağırışı 10-30 dəqiqə hang oldu — istifadəçi neçə dəfə təslim oldu və reject etdi.
**Diaqnoz:** Manual `python -c "from langchain_text_splitters import RecursiveCharacterTextSplitter"` 24.06 saniyə çəkir. langchain-in çoxlu opsional asılılığı top-level-də yüklənir.
**Niyə həssas:** `mcp_server.py` → `from vector_store import ChromaVectorStore` → `from document_loader import CodeChunk` → top-level langchain import. Yəni hər tool çağırışı (səssizcə) 24 saniyə əlavə edirdi.
**Həll:** `document_loader.py`-də langchain import-u top-level-dən çıxarıldı, yalnız `_fallback_chunk()` və `chunk_markdown()` daxilində çağırılır. Sınaq: `vector_store` import-u 28s → **4s**.

### P12 — Embedding modeli `ChromaVectorStore.__init__`-də yüklənirdi
**Simptom:** Sadə `get_stats` (yalnız metadata count) çağırışı belə ~10-30s vaxt aparırdı.
**Səbəb:** `CodeEmbeddingFunction.__init__` daxilində `SentenceTransformer(...)` çağırılırdı — model RAM-a alınırdı, halbuki `count()` üçün lazım deyil.
**Həll:** Lazy-of-lazy — `__init__` yalnız `self._model = None` saxlayır, real yükləmə yalnız `__call__` zamanı baş verir. `get_stats` artıq instant.

**Nəticə (sonuncu yoxlama):** Manual `from vector_store import ChromaVectorStore; store = ChromaVectorStore(); store.get_stats()` indi 5 saniyəyə bitir (ondan da 4 saniyəsi chromadb library import-udur). Sonrakı çağırışlar < 100ms.

### P13 — FastMCP worker thread-də Python import lock deadlock (kritik)
**Simptom:** Manual test 5 saniyəyə bitirdi, amma MCP server üzərindən `get_stats` **sonsuz hang** olurdu. Stderr log-da `get_stats: çağırıldı` görünürdü, sonra heç nə.
**Diaqnoz:** FastMCP sync tool-ları `anyio.to_thread.run_sync` ilə worker thread-də çağırır. `_get_store()` daxilində lazy `from vector_store import ChromaVectorStore` çağırılır. Python-un import lock-u digər thread-lərdəki lazy import-ları blokladığında deadlock yaranır.
**Səbəb:** Bu klassik Python multi-threading + lazy import problemidir. Module-level import-lar main thread-də işə salınır və lock heç vaxt thread-lər arasında saxlanmır.
**Həll:** `mcp_server.py`-də `from vector_store import ChromaVectorStore`, `from search_engine import HybridSearchEngine`, `from document_loader import _CHUNKER_MAP, _fallback_chunk, load_directory`, `from smart_router import SmartRouter` — hamısı module-level-ə qaldırıldı. Lazy import-lar tool funksiyalarından silindi.

**JSON-RPC end-to-end test nəticəsi (FİNAL):**
```
init:                   3.14s   (subprocess + chromadb import)
get_stats (ilk):        0.32s   (DB açılır)
get_stats (cached):     0.01s   ← 10ms
route_project:          0.48s   (file walk + token count)
```

### P14 — bge-reranker-v2-m3 8GB sistemdə RAM-a sığmır
**Simptom:** `OSError: The paging file is too small` — Windows page file mövcud olsa belə, sentence_transformers reranker yükləməsi uğursuz.
**Diaqnoz:** Sistemdə cəmi 8GB RAM, sınaq zamanı 890MB boş. bge-reranker-v2-m3 568M parametrli, ~1.5GB RAM tələb edir → sığmır.
**Həll:** `cross-encoder/ms-marco-MiniLM-L-6-v2` — 22M parametr (25x kiçik), ~90MB disk, ~200MB RAM. 33 saniyəyə tam yükləndi (download + load + test).
**Trade-off:** Model bir az daha az dəqiqdir (multilingual deyil, ingilis dilinə yönəlmiş), amma kod axtarışı üçün kifayət qədər keyfiyyətli olduğu sübut olunmuşdur (MTEB benchmark-ında bge-reranker-base-ə yaxın).

---

## 🔴 P1 — Kritik: `nomic-embed-code` modeli 14GB-dır, MCP tool çağırışını bloklayır

### Simptom
Claude Code-dan `mcp__mla-agent__get_stats` çağırılanda heç bir cavab gəlmədi (30+ dəqiqə). MCP tool çağırışları stdio-blocking olduğu üçün Claude Code "pending" vəziyyətdə qalır.

### Səbəb
`config.py`-də:
```python
EMBEDDING_MODEL_NAME = "nomic-ai/nomic-embed-code"
```

Bu model **7B parametrlidir, ~14 GB**. Mənim əvvəlki şərhimdə "~500MB" yazılması yanlış idi.

`vector_store.py`-də `ChromaVectorStore.__init__()` daxilində `CodeEmbeddingFunction()` qurulur, o da `SentenceTransformer(...)` çağırır → ilk dəfədə model HuggingFace-dən endirilməyə başlayır. Endirmə bitənə qədər `__init__` qaytarmır → MCP tool çağırışı bütövlükdə bloklanır.

**Sübut:** `chroma_db/chroma.sqlite3` yaradılıb (Chroma client başlayıb), amma `~/.cache/huggingface` cəmi 389 KB-dır — model heç vaxt tam yüklənməyib.

### Təsir
- MCP server praktiki olaraq **istifadə oluna bilməz** — hər ilk tool çağırışı saatlarla blok olacaq
- Hətta model yüklənsə də, CPU-da 14GB modeli RAM-a yükləmək çox bahalıdır

### Həll variantları
1. **Daha kiçik model** (tövsiyə olunan):
   - `nomic-ai/nomic-embed-text-v1.5` — 137M parametr, ~250MB, yenə də güclü, kod üçün də kifayətdir
   - `BAAI/bge-base-en-v1.5` — 110M parametr, ~440MB, çox geniş istifadə olunur
   - `BAAI/bge-small-en-v1.5` — 33M parametr, ~130MB, ən sürətli
2. **Ollama / lokal API server**: `nomic-embed-text` Ollama-da əlçatandır, embedding-i HTTP üzərindən çağırmaq olar — lakin Ollama quraşdırma tələb edir
3. **OpenAI embedding API**: `text-embedding-3-small` ($0.02 / 1M token), amma API açarı və xərc var

---

## 🟠 P2 — MCP server initialization heç bir progress feedback vermir

### Simptom
İlk `get_stats` çağırılanda istifadəçi bilmir nə baş verir — tool sadəcə hang edir.

### Səbəb
- `mcp_server.py`-də `_get_store()` lazy-load edir, amma model yüklənməsi `SentenceTransformer.__init__` daxilində baş verir və progress bar `show_progress_bar=False` ilə söndürülmür (`vector_store.py`-də `model.encode(... show_progress_bar=False)`, amma model **yüklənməsi** ayrı şeydir)
- Bütün loglar stderr-ə gedir, MCP protocol stderr-i istifadəçiyə göstərmir
- Tool çağırışı yalnız tam bitəndən sonra cavab qaytarır

### Həll variantları
1. **Eager init at startup**: `mcp_server.py`-in `if __name__ == "__main__"` bloku `_get_store()` çağırsın, beləcə model yüklənməsi MCP server prosesinin başlanğıcında baş versin (Claude Code-da progress görünməyəcək, amma sonrakı tool çağırışları sürətli olacaq)
2. **Hazırlıq skripti**: `python -c "from vector_store import ChromaVectorStore; ChromaVectorStore()"` istifadəçi əl ilə çağırsın — model bir dəfə yüklənsin, sonra MCP server cache-dən oxusun

---

## 🟠 P3 — `chroma_db` `.gitignore`-dadır amma boş halda yaradılır

### Simptom
`chroma_db/chroma.sqlite3` boş halda diskdə qalır. Layihəni yenidən qurarkən təmizləmək lazım gələ bilər.

### Səbəb
Boş Chroma client başladılması da SQLite faylı yaradır.

### Həll
İcazə var — `git status` təsir etmir (`.gitignore`-da). Sadəcə qeyd üçün.

---

## 🟡 P4 — `Comment` problemi: `EMBEDDING_MODEL_NAME` üçün şərh yanıltıcıdır

### Simptom
`config.py:67`:
```python
# Embedding modeli: nomic-embed-code (kod üçün xüsusi, ~500MB)
EMBEDDING_MODEL_NAME = "nomic-ai/nomic-embed-code"
```

"~500MB" yazılıb, əslində ~14GB. Bu mənim əvvəlki səhvimdir.

### Həll
Modeli dəyişəndə şərhi də düzəlt.

---

## 🟡 P5 — `requirements.txt`-də `tiktoken` opsionaldır, amma quraşdırılması məcburi göstərilib

### Simptom
`smart_router.py` `tiktoken` yoxdursa fallback istifadə edir, amma `requirements.txt`-də məcburi siyahıdadır.

### Səbəb
Mənim əvvəlki versiyamda. Məcburi quraşdırılır → əgər istifadəçidə ölçü problemi varsa, opsional işarələnməlidir.

### Həll
Az prioritet. Olduğu kimi qoymaq olar.

---

## 🟡 P6 — MCP server-in startup latency-i üçün TIMEOUT dəyəri

### Simptom
Claude Code MCP server-in cavabını gözləyir. Default timeout-u keçərsə, server "failed" olaraq işarələnir.

### Səbəb
İlk model yüklənməsi 5-10+ dəqiqə çəkə bilər. Default MCP timeout-u (adətən 30-60 saniyə) üçün çox çoxdur.

### Həll
- P1 və P2 həll olunduqdan sonra bu öz-özünə çözülür (model yüklənməsi sürətli olar)
- Yaxud `.mcp.json`-a `"timeout": 600000` (10 dəqiqə) əlavə etmək olar — amma bu UX baxımından yaxşı deyil

---

## 🟢 İndiyə qədər həll edilmiş problemlər (PROGRESS.md-dən)

Bunlar artıq həll olunub və burada xatırlatma kimi:

- ✅ BM25 staleness multi-process (mtime imzası ilə)
- ✅ Boş kolleksiyada query xətası
- ✅ Watchdog debounce (eyni faylın çoxsaylı save-ləri)
- ✅ `on_moved` köhnə yolun bazada qalması
- ✅ Query decomposition non-JSON cavab
- ✅ `tiktoken` yoxluğunda fallback
- ✅ Anthropic prompt caching strukturu

---

## 🎯 Növbəti Addımlar — Tövsiyə Edilən Sıra

1. **P1-i həll et** → `EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"` (və ya `nomic-embed-text-v1.5`)
2. `chroma_db/` qovluğunu sil (köhnə embedding ölçüsü ilə uyğunsuz olar)
3. Modeli əl ilə pre-load et: `python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"` — gözləməyəcəksən, amma proqresi görəcəksən
4. `python main.py index . --fresh` — indi sürətli olmalıdır (~30 saniyə)
5. Claude Code-u restart et və `mcp__mla-agent__get_stats` çağır → dərhal cavab gəlməlidir

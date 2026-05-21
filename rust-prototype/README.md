# Tokengram — Rust Prototype (DEFERRED)

> **⚠️ Status: DONDURULMUŞDUR (2026-05-13)**
>
> Bu prototip launch öncəsi anti-tamper hədəfi üçün başlandı, lakin Python implementasiyası ilə feature parity üçün **40-80 saat əlavə iş** lazımdır (24 məsələ: constants drift, BM25/reranker/SmartRouter yoxluğu, session_log gap, schema migration ağrısı).
>
> **Cari path: Nuitka ilə Python → native binary kompilyasiyası.** Eyni anti-tamper effektini sıfır feature regression ilə verir.
>
> Sun-cost qorumaq və gələcəkdə (məs. müəyyən hot path-i Rust-da yenidən yazmaq) revisit etmək üçün kod silinmir. Aktiv development bu qovluqda dayandırılmışdır.
>
> Tarix: [söhbət konteksindən](../) — 2026-05-13.

---

Bu qovluq Python implementasiyasının Rust-a köçürmə prototipidir. Məqsəd: launch öncəsi kritik məntiqi opaque native binary-yə çevirmək.

## Niyə Rust?

Söhbətdən gələn qərar (launch-prep/PLAN.md-də):
- Reverse engineering-ə qarşı ən güclü mainstream dil
- Native binary, decompile geri Rust kodu vermir
- Generic monomorphization + iterator chain-ləri RE üçün ağrılıdır
- Bonus: Python-dan 3–5x sürətli, 2–3x az RAM

## Sistem tələbləri

**Rust toolchain:** 1.85+ (edition 2024 üçün). `winget install Rustlang.Rustup` ilə qoş.

**Protobuf compiler (LanceDB üçün, Step 2+):**
```powershell
winget install Google.Protobuf
# Yeni shell sessiyasında protoc PATH-də olacaq.
# Mövcud sessiyada PROTOC env qoy:
$env:PROTOC = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Google.Protobuf_Microsoft.Winget.Source_8wekyb3d8bbwe\bin\protoc.exe"
```

Bu lazımdır çünki `lance-encoding` build script-i `.proto` fayllarını compile edir. Windows-da protoc default gəlmir.

**Linux/macOS:**
```bash
# Debian/Ubuntu:  apt install protobuf-compiler
# macOS:          brew install protobuf
```

## Mərhələli quraşdırma

### Step 1 — Embedding sanity check ✅ (cari)

Yalnız `fastembed` ilə `BAAI/bge-small-en-v1.5` modelini yükləyib bir sorğu və bir neçə sənəd embedding-ini hesablayır, cosine similarity çap edir. Bu sübut edir:

- Rust + ONNX Runtime Windows-da işləyir
- Eyni embedding modeli Python ilə uyğundur
- 384-dim vektor çıxır
- Auth-mövzulu sənəd UI-mövzulu sənəddən yüksək sim verir

```powershell
cd mla-search-rs
cargo run --release
```

İlk run model yükləyəcək (~130MB, `.fastembed_cache/` qovluğuna).

### Step 2 — LanceDB inteqrasiyası (növbəti)

- LanceDB embedded mode
- Index/store/search API
- Python ChromaDB ilə eyni metadata sxemi (file_path, chunk_type, content)

### Step 3 — Chunking + indexer (sonra)

- AST parser (`tree-sitter` Rust binding)
- Fallback text splitter (1200 char, 200 overlap — Python ilə eyni)
- File walker (`ignore` crate, `.gitignore` hörmət edir)

### Step 4 — MCP server (sonra)

- `mcp-rust-sdk` (rəsmi Anthropic SDK)
- `search_code` tool — Python `mcp_server.py`-dakı kimi
- `get_stats`, `index_directory` və s.

### Step 5 — License client (sonra)

- JWT verify
- Machine fingerprint (CPU id + hostname hash)
- Online activation (Cloudflare Workers backend)

## Python ilə paritet hədəfləri

| Komponent | Python | Rust (hədəf) |
|---|---|---|
| Embedding model | `sentence-transformers` + BAAI/bge-small-en-v1.5 | `fastembed-rs` + eyni model |
| Query prefix | `"Represent this sentence for searching relevant passages: "` | Eyni |
| Vector DB | ChromaDB (`code_vectors` collection) | LanceDB (eyni sxema) |
| Chunk size (fallback) | 1200 char, 200 overlap | Eyni |
| AST chunk max | 3000 char | Eyni |
| Top K default | 4 | Eyni |
| Hybrid alpha | 0.6 | Eyni |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Eyni (fastembed-rs reranker dəstəkləyir) |

## Build artifacts

```powershell
cargo build --release
# → target/release/mla-search-rs.exe (~10–15 MB, strip ilə)
```

Release profil-də `lto = true` + `codegen-units = 1` + `strip = true` — kiçik və sürətli binary, debug symbol-lar yox.

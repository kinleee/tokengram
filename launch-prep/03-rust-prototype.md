# Phase 3 — Rust Prototype Plan

**Hədəf:** Python kritik məntiqini Rust-a köçürüb native binary kimi paketləmək.
**Müddət:** 2–3 həftə (5 step, hər biri 2–4 gün).
**Risk səviyyəsi:** Orta — texniki iş çoxdur, amma stack yetkindir.

## Strategiya: mərhələli, hər step öz başına işləyəndir

Sıfırdan tam köçürmə risklidir. Bunun yerinə **incremental** gedirik — hər step öz başına test olunur və əvvəlkinə əsaslanır. Step bitəndə Python ilə paritet yoxlanılır.

---

## Step 1 — Embedding sanity check ✅ (cari iş)

**Status:** Cargo project quruldu, kod yazıldı, build edilir (background).

**Faylllar:**
- [../rust-prototype/mla-search-rs/Cargo.toml](../rust-prototype/mla-search-rs/Cargo.toml)
- [../rust-prototype/mla-search-rs/src/main.rs](../rust-prototype/mla-search-rs/src/main.rs)
- [../rust-prototype/README.md](../rust-prototype/README.md)

**Sübut edir:**
- Rust + ONNX Runtime Windows-da işləyir
- `BAAI/bge-small-en-v1.5` modeli yüklənir
- 384-dim vektor alınır
- Cosine similarity məntiqlidir (auth query → auth doc daha yüksək)

**Tamamlanma kriterileri:**
- ☐ `cargo build` xətasız bitir
- ☐ `cargo run --release` model yükləyir
- ☐ Cosine sim çıxışı məntiqlidir (auth doc UI doc-dan yuxarı)

---

## Step 2 — LanceDB inteqrasiyası

**Hədəf:** ChromaDB-ni LanceDB ilə əvəz et — store, query, metadata.

**Yeni dependencies:**
```toml
lancedb = "0.10"
arrow = "53"
arrow-array = "53"
arrow-schema = "53"
futures = "0.3"
tokio = { version = "1", features = ["full"] }
```

**Sxema (Python ChromaDB metadata ilə eyni):**
```rust
struct CodeChunk {
    id: String,          // uuid
    content: String,     // chunk text
    embedding: Vec<f32>, // 384-dim
    file_path: String,
    chunk_type: String,  // text_split / markdown_section / function / class / ...
    start_line: i32,
    end_line: i32,
    file_hash: String,
}
```

**Tamamlanma kriterileri:**
- ☐ 10 sənədi index et, search et, top-3 qaytar
- ☐ Python ChromaDB ilə eyni sıralanma çıxsın (eyni embeddings → eyni nəticələr)

---

## Step 3 — Chunking + file walker

**Hədəf:** Repo gəz, faylları parçala, indekslə.

**Yeni dependencies:**
```toml
ignore = "0.4"          # .gitignore hörmət edən walker
tree-sitter = "0.22"
tree-sitter-rust = "0.21"
tree-sitter-python = "0.21"
tree-sitter-typescript = "0.21"
```

**Yanaşma:**
1. Python `document_loader.py`-dakı kimi: tree-sitter ilə AST chunking, fallback text splitter
2. `ignore` crate `.gitignore`, `.mla_ignore` hörmət edir
3. `mla_constants` sabitləri Rust `consts.rs`-yə köçür

**Tamamlanma kriterileri:**
- ☐ MLA_AGENT repo-sunu indekslə, Python ilə eyni sayda chunk
- ☐ chunk_types paylanması Python ilə ~10% daxilində uyğun

---

## Step 4 — MCP server

**Hədəf:** Claude Code MCP server kimi qoş.

**Yeni dependencies:**
```toml
# Rəsmi MCP Rust SDK
modelcontextprotocol-sdk = "0.5"
```

**Tool-lar (Python `mcp_server.py`-dakı kimi):**
- `search_code(query, mode, top_k, file_type)`
- `index_directory(path)`
- `index_file(path)`
- `get_stats()`
- `route_project()`

**Tamamlanma kriterileri:**
- ☐ Claude Code-da Rust binary MCP server kimi register olunur
- ☐ Bütün 5 tool Python versiyası ilə eyni JSON şəklində cavab verir
- ☐ Stdio transport stable işləyir

---

## Step 5 — License client

**Hədəf:** Online activation + offline işləmə.

**Yeni dependencies:**
```toml
jsonwebtoken = "9"
sha2 = "0.10"
hostname = "0.4"
machine-uid = "0.5"
reqwest = { version = "0.12", features = ["json", "rustls-tls"] }
```

**Akış:**
1. İlk başlanğıcda user token-i daxil edir (env var və ya config faylı)
2. Extension Cloudflare Workers endpoint-ə `POST /validate` göndərir
3. Server JWT qaytarır (machine_fingerprint + expires_at + signature)
4. Bütün MCP tool-lar əvvəlcə JWT verify edir, sonra cavab verir
5. JWT 7 gün etibarlıdır, sonra refresh

**Tamamlanma kriterileri:**
- ☐ Etibarsız token ilə tool-lar imtina edir
- ☐ Etibarlı token ilə hər şey işləyir
- ☐ 7 gündən sonra avtomatik refresh
- ☐ Internet yoxdursa, etibarlı JWT cache-də varsa işləyir

---

## Cross-platform build

**Hədəf platformalar:**
- Windows x64 (sənin əsas user-lərin)
- macOS arm64 (Apple Silicon, populyar)
- macOS x64 (köhnə Mac)
- Linux x64

**GitHub Actions matrix build:**
```yaml
matrix:
  include:
    - os: windows-latest
      target: x86_64-pc-windows-msvc
    - os: macos-latest
      target: aarch64-apple-darwin
    - os: macos-latest
      target: x86_64-apple-darwin
    - os: ubuntu-latest
      target: x86_64-unknown-linux-gnu
```

Hər platforma üçün `mla-search-rs-{platform}.exe` artifact-ı.

---

## Risk və mitigasiyalar

| Risk | Mitigasiya |
|---|---|
| `ort` (ONNX) Windows-da segfault | Step 1-də erkən aşkar olunur. Fallback: `candle` |
| LanceDB metadata sxema dəyişikliyi | Versiya pin et (`= "0.10.5"`) |
| Tree-sitter dil dəstəyi yoxdur | Fallback text splitter onsuz da var |
| MCP SDK qeyri-stabil API | Mayor versiya pin + öz transport wrapper |
| Build time çox uzun | LTO yalnız release-də, sccache CI-də |

---

## Step 1 sonrası növbəti addım

Build keçəndə və sanity test uğurlu olanda, Step 2-yə (LanceDB) keç. Hər step sonu git commit + tag (`prototype-step1`, `prototype-step2`, ...) — geri qayıtma asand olsun.

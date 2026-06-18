"""Mərkəzi extension/qovluq/fayl filtrləri.

`config.py`, `document_loader.py` və bütün `hooks/*.py` skriptləri bu fayldan
import edir — siyahıların 5 yerdə drift olmaması üçün tək mənbə.

Heç bir 3rd-party asılılığı yoxdur (dotenv, chromadb yoxdur), hooks bunu sürətlə
yükləyə bilir (~5ms cold import).
"""

# İndekslənən fayl uzantıları. Hooks (pre_read_check, post_grep_check,
# post_bash_check) bu siyahıya əsasən block/log qərarı verir.
SUPPORTED_EXTENSIONS = {
    # Python ekosistemi (orijinal)
    ".py", ".sol", ".sql", ".md",
    # TypeScript / JavaScript
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    # Sistem dillər
    ".go", ".rs", ".java", ".kt", ".cs",
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp",
    # Dinamik dillər
    ".rb", ".php", ".swift", ".dart",
    # Markup / config
    ".html", ".css", ".scss",
    ".json", ".yaml", ".yml", ".toml",
    # Skript / infra
    ".sh", ".bash", ".ps1", ".tf",
}

# İndeksləmə zamanı tam istisna olunan qovluqlar.
EXCLUDED_DIRS = {
    # Baza & cache
    "chroma_db", "__pycache__", ".git", ".svn", ".hg",
    "models_cache", ".fastembed_cache",  # HF/fastembed model cache (tokenizer.json = 700+ chunk noise)
    # Package manager / vendor (asılılıq qovluqları — semantik dəyər yox,
    # layihəni nəhəng göstərir: Laravel vendor/ = 12k+ fayl)
    "node_modules", "venv", ".venv", "env", ".env",
    "site-packages", "vendor", "bower_components",
    ".gradle", ".m2", "Pods", ".dart_tool", ".pub-cache", ".terraform",
    # Build output
    "dist", "build", "out", "target",
    # Tokengram-ın öz build/staging artefaktları: build_pypi.py `build_tmp/`
    # yaradır və mənbəni `tokengram/` paketinə kopyalayır, `dist_compiled/`-də
    # .pyd saxlanır. İstisna olunmasa, build zamanı canlı serverin builtin
    # watcher-i onlarla fayl-yazısını növbəyə atır (2026-06-17: bir redaktəyə
    # ⟳ 34 — hamısı build noise). tokengram/ həm də root mənbənin dublikatıdır.
    "build_tmp", "dist_compiled", "tokengram",
    ".next", ".nuxt", ".eggs",
    # Cache / coverage
    ".cache", ".parcel-cache", ".turbo",
    "coverage", "htmlcov", ".nyc_output",
    # Laravel runtime (storage/framework/views compiled blade və s.)
    "storage",
    # IDE / agent state
    ".idea", ".vscode",
    ".claude", ".aider", ".cursor", ".antigravity", ".mla",
    # Test cache
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
}

# Fayl-səviyyəli ad uyğunluqları — `name.startswith(pattern)` ilə yoxlanır.
# Həm MLA internal state-i, həm package manager lock faylları (10K+ sətir, sıfır
# semantik dəyər) buradadır.
EXCLUDED_FILE_PATTERNS = (
    # MLA internal state
    ".mla_pending", ".mla_session_log", ".file_hashes",
    # Test prompt / fixture noise — keyword spam BM25-i aldadır,
    # konseptual sorğularda real koddan üstün gəlir.
    "TEST_PROMPT", "test_prompt",
    "PROMPT_", "prompts.",
    "FIXTURE_", "fixture_",
    # Package manager lock faylları
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Cargo.lock", "go.sum", "composer.lock", "Gemfile.lock",
    "poetry.lock", "uv.lock", "bun.lockb",
    # Secret / credential fayllar — chromadb-yə düşməməlidir.
    # Tokengram "local · private" iddia edir, lakin chroma_db-yə əli çatan
    # hər kəs (backup, paylaşılan disk) secret-ləri görə bilər.
    # `name.startswith(pattern)` ilə yoxlanır.
    ".env",                 # .env, .env.local, .env.production, ...
    "secrets.",             # secrets.json, secrets.yaml
    "credentials.",         # credentials.json, credentials.yaml
    "credential.",
    "service-account",      # service-account.json, service-account-*.json
    "firebase-adminsdk",    # firebase-adminsdk-*.json
    "google-services.json",
)

# Fayl adının suffix-i bunlardan biri ilə bitirsə skip — minified bundle-lar,
# generated kod, source map-lar.
EXCLUDED_FILE_SUFFIXES = (
    ".min.js", ".min.css",
    ".bundle.js", ".bundle.css",
    ".map",                          # source map (foo.js.map)
    ".pb.go", ".pb.ts",              # protobuf generated
    "_pb2.py", "_pb2_grpc.py",       # protobuf python
    ".gen.go", ".gen.ts",            # generated marker
    ".generated.ts", ".generated.go",
)

# Tək fayl ölçü tavanı (bayt). 1 MB ~ 30K sətir — normal kod fayllarından çox
# böyükdür. Bundan iri fayllar (data dump, vendor bundle) indeksdən kənar.
MAX_FILE_SIZE_BYTES = 1_000_000

# Token estimation helper — bütün hook-larda baseline hesablamaq üçün.
# `lines × 10` heuristikasını əvəz edir (kobud, JSON/MD-də 2-3x səhvə düşür).
#
# `len(text) // CHARS_PER_TOKEN` daha dəqiqdir, çünki:
#   - Düz mətn/markdown:  ~4 chars/token
#   - Kod (Python/JS):     ~3-4 chars/token
#   - Minified JSON:       ~2-3 chars/token (səhv tərəfdə qoyuruq, konservativ)
# Real tiktoken-dən ~10-15% səhvlik, lakin tiktoken hər hook-da load etmək
# 100-200ms cold start əlavə edərdi — hook tələbat-əleyhinə olar.
CHARS_PER_TOKEN = 4


def estimate_tokens(text) -> int:
    """Mətn/bayt → təxmini token sayı. Heç vaxt 0 qaytarmır (≥1)."""
    if text is None:
        return 1
    if isinstance(text, (bytes, bytearray)):
        n = len(text)
    elif isinstance(text, str):
        n = len(text)
    else:
        n = len(str(text))
    return max(1, n // CHARS_PER_TOKEN)

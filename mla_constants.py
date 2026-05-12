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
    "chroma_db", "__pycache__", ".git",
    "models_cache",
    # Package manager
    "node_modules", "venv", ".venv", "env", ".env",
    "site-packages",
    # Build output
    "dist", "build", "out", "target",
    ".next", ".nuxt", ".eggs",
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
    # Package manager lock faylları
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Cargo.lock", "go.sum", "composer.lock", "Gemfile.lock",
    "poetry.lock", "uv.lock", "bun.lockb",
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

"""Central extension/directory/file filters.

`config.py`, `document_loader.py` and all `hooks/*.py` scripts import from this
file — a single source so the lists don't drift across 5 places.

No 3rd-party dependencies (no dotenv, no chromadb), so hooks can load it quickly
(~5ms cold import).
"""

# Indexed file extensions. Hooks (pre_read_check, post_grep_check,
# post_bash_check) make block/log decisions based on this list.
SUPPORTED_EXTENSIONS = {
    # Python ecosystem (original)
    ".py", ".sol", ".sql", ".md",
    # TypeScript / JavaScript
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    # System languages
    ".go", ".rs", ".java", ".kt", ".cs",
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp",
    # Dynamic languages
    ".rb", ".php", ".swift", ".dart",
    # Markup / config
    ".html", ".css", ".scss",
    ".json", ".yaml", ".yml", ".toml",
    # Script / infra
    ".sh", ".bash", ".ps1", ".tf",
}

# Directories fully excluded during indexing.
EXCLUDED_DIRS = {
    # Database & cache
    "chroma_db", "__pycache__", ".git", ".svn", ".hg",
    "models_cache", ".fastembed_cache",  # HF/fastembed model cache (tokenizer.json = 700+ chunk noise)
    # Package manager / vendor (dependency directories — no semantic value,
    # make the project look huge: Laravel vendor/ = 12k+ files)
    "node_modules", "venv", ".venv", "env", ".env",
    "site-packages", "vendor", "bower_components",
    ".gradle", ".m2", "Pods", ".dart_tool", ".pub-cache", ".terraform",
    # Build output
    "dist", "build", "out", "target",
    ".next", ".nuxt", ".eggs",
    # Cache / coverage
    ".cache", ".parcel-cache", ".turbo",
    "coverage", "htmlcov", ".nyc_output",
    # Laravel runtime (storage/framework/views compiled blade etc.)
    "storage",
    # IDE / agent state
    ".idea", ".vscode",
    ".claude", ".aider", ".cursor", ".antigravity", ".mla",
    # Test cache
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
}

# File-level name matches — checked with `name.startswith(pattern)`.
# Both MLA internal state and package manager lock files (10K+ lines, zero
# semantic value) are here.
EXCLUDED_FILE_PATTERNS = (
    # MLA internal state
    ".mla_pending", ".mla_session_log", ".file_hashes",
    # Test prompt / fixture noise — keyword spam fools BM25,
    # outranks real code in conceptual queries.
    "TEST_PROMPT", "test_prompt",
    "PROMPT_", "prompts.",
    "FIXTURE_", "fixture_",
    # Package manager lock files
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Cargo.lock", "go.sum", "composer.lock", "Gemfile.lock",
    "poetry.lock", "uv.lock", "bun.lockb",
    # Secret / credential files — must not end up in chromadb.
    # Tokengram claims "local · private", but anyone with access to chroma_db
    # (backup, shared disk) could see the secrets.
    # Checked with `name.startswith(pattern)`.
    ".env",                 # .env, .env.local, .env.production, ...
    "secrets.",             # secrets.json, secrets.yaml
    "credentials.",         # credentials.json, credentials.yaml
    "credential.",
    "service-account",      # service-account.json, service-account-*.json
    "firebase-adminsdk",    # firebase-adminsdk-*.json
    "google-services.json",
)

# Skip if the file name ends with one of these suffixes — minified bundles,
# generated code, source maps.
EXCLUDED_FILE_SUFFIXES = (
    ".min.js", ".min.css",
    ".bundle.js", ".bundle.css",
    ".map",                          # source map (foo.js.map)
    ".pb.go", ".pb.ts",              # protobuf generated
    "_pb2.py", "_pb2_grpc.py",       # protobuf python
    ".gen.go", ".gen.ts",            # generated marker
    ".generated.ts", ".generated.go",
)

# Single file size ceiling (bytes). 1 MB ~ 30K lines — much larger than normal
# code files. Files bigger than this (data dumps, vendor bundles) stay out of the index.
MAX_FILE_SIZE_BYTES = 1_000_000

# Token estimation helper — used to compute a baseline in all hooks.
# Replaces the `lines × 10` heuristic (crude, off by 2-3x for JSON/MD).
#
# `len(text) // CHARS_PER_TOKEN` is more accurate, because:
#   - Plain text/markdown:  ~4 chars/token
#   - Code (Python/JS):     ~3-4 chars/token
#   - Minified JSON:        ~2-3 chars/token (we err on the conservative side)
# About ~10-15% error vs real tiktoken, but loading tiktoken in every hook
# would add 100-200ms of cold start — that would defeat the purpose of a hook.
CHARS_PER_TOKEN = 4


def estimate_tokens(text) -> int:
    """Text/bytes → approximate token count. Never returns 0 (≥1)."""
    if text is None:
        return 1
    if isinstance(text, (bytes, bytearray)):
        n = len(text)
    elif isinstance(text, str):
        n = len(text)
    else:
        n = len(str(text))
    return max(1, n // CHARS_PER_TOKEN)

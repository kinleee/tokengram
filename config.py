"""
============================================
config.py — Layihə Konfiqurasiyası
============================================
Bütün sabitlər və parametrlər burada saxlanılır.
Dəyişiklik etmək üçün yalnız bu faylı redaktə edin.
"""

import os
from dotenv import load_dotenv

# .env faylından mühit dəyişənlərini yüklə
load_dotenv()

# ============================================
# FAYL SİSTEMİ KONFİQURASİYASI
# ============================================
# Tək mənbə: `mla_constants.py`. Bütün hooks da oradan import edir,
# beləliklə 5 yerdə drift olmur.

from mla_constants import (
    SUPPORTED_EXTENSIONS,
    EXCLUDED_DIRS,
    EXCLUDED_FILE_PATTERNS,
    EXCLUDED_FILE_SUFFIXES,
    MAX_FILE_SIZE_BYTES,
)

# ============================================
# CHUNKİNG KONFİQURASİYASI
# ============================================

# AST chunking üçün maksimum chunk ölçüsü (simvol)
AST_MAX_CHUNK_SIZE = 3000

# Fallback text splitter üçün parametrlər
FALLBACK_CHUNK_SIZE = 1200
FALLBACK_CHUNK_OVERLAP = 200

# ============================================
# CHROMADB KONFİQURASİYASI
# ============================================

# ChromaDB verilənlər bazasının yolu
CHROMA_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_db")

# ChromaDB collection adı
COLLECTION_NAME = "code_vectors"

# ============================================
# EMBEDDİNG MODELİ KONFİQURASİYASI
# ============================================

# Embedding modeli: BAAI/bge-small-en-v1.5
# 33M parametr, ~130MB — standard SentenceTransformer arxitekturası,
# Windows-da stabil. Custom (trust_remote_code) kod yoxdur.
# (Nomic versiyası Windows + PyTorch-da segfault verirdi.)
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"

# bge-en-v1.5: query üçün instruction prefix tövsiyə olunur,
# sənəd üçün prefix yoxdur.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
DOCUMENT_PREFIX = ""

# ============================================
# RERANKER KONFİQURASİYASI
# ============================================

# Cross-encoder reranker modeli
# ms-marco-MiniLM-L-6-v2: 22M parametr, ~90MB disk, ~200MB RAM
# (BAAI/bge-reranker-v2-m3 568M parametr idi, RAM-a sığmadı 8GB sistemdə)
RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Reranker üçün maksimum token uzunluğu
RERANKER_MAX_LENGTH = 512

# ============================================
# AXTARIŞ KONFİQURASİYASI
# ============================================

# Default top-k nəticə sayı
TOP_K_RESULTS = 4

# Hybrid search üçün alpha (0.0=yalnız BM25, 1.0=yalnız semantic)
HYBRID_ALPHA = 0.6

# İlkin axtarışda gətiriləcək namizəd sayı (reranker üçün)
CANDIDATE_COUNT = 20

# Confidence threshold — bu dəyərdən aşağı skor "aşağı etibar" sayılır
CONFIDENCE_THRESHOLD = 0.3

# Graph expansion zamanı əlavə gətirilən chunk sayı
GRAPH_EXPANSION_COUNT = 2

# ============================================
# LLM KONFİQURASİYASI
# ============================================

# Default LLM provider
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")

# API açarları
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Model adları (2026-cı il aprel ayına aktual)
ANTHROPIC_MODEL = "claude-sonnet-4-6"
OPENAI_MODEL = "gpt-4o"

# Maksimum cavab token sayı
MAX_RESPONSE_TOKENS = 4096

# ============================================
# SMART ROUTER KONFİQURASİYASI
# ============================================

# Kiçik layihə həddi (bu tokendən az = RAG istifadə etmə)
DIRECT_MODE_THRESHOLD = 4_000  # ~15K simvol

# Orta layihə həddi (bu tokendən az = yüngül RAG)
RAG_LIGHT_THRESHOLD = 50_000  # ~200K simvol

# ============================================
# FİLE WATCHER KONFİQURASİYASI
# ============================================

# Debounce vaxtı (saniyə) — çoxsaylı save-ləri birləşdirir
WATCHER_DEBOUNCE_SEC = 2.0

# Hash store faylı (incremental indexing üçün)
HASH_STORE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".file_hashes.json")

# Daxili (builtin) watcher: MCP server-in özündə file system izləməsi.
# Hooks-dan asılı olmur — VS Code Claude Code, Antigravity, Cursor və s.
# bütün IDE-lərdə avtomatik re-index aktiv qalır. Söndürmək üçün:
#   MLA_DISABLE_WATCHER=1
ENABLE_BUILTIN_WATCHER = os.getenv("MLA_DISABLE_WATCHER", "").lower() not in ("1", "true", "yes")

# İzlənəcək kök qovluq. None olarsa MCP serverin cwd-si götürülür
# (Claude Code adətən proyekt kökündən launch edir). Override:
#   MLA_WATCH_DIR=/path/to/project
WATCH_DIRECTORY_OVERRIDE = os.getenv("MLA_WATCH_DIR") or None

# ============================================
# PROMPT ŞABLONLARI
# ============================================

SYSTEM_PROMPT = """Sənə yalnız aşağıdakı kod bloklarını verirəm. 
Sualımı yalnız bu kodlara əsaslanaraq cavabla. 
Əgər cavab kodlarda yoxdursa, 'Məlumat tapılmadı' de.
Cavabını ətraflı və izahlı ver."""

QUERY_DECOMPOSITION_PROMPT = """Aşağıdakı sualı kod bazasında axtarış üçün 2-3 sadə 
alt-suala böl. Hər alt-sual bir funksiya və ya fayl haqqında olsun.
Yalnız JSON list formatında cavab ver, başqa heç nə yazma.

Sual: {query}

Alt-suallar:"""

CONTEXTUAL_ENRICHMENT_PROMPT = """Aşağıdakı kod bloku {file_name} faylındandır.
Bu kod blokunun nə etdiyini və hansı kontekstdə istifadə olunduğunu 1-2 cümlə ilə izah et.
Yalnız izahı yaz, başqa heç nə əlavə etmə.

Kod:
{code_chunk}

İzah:"""

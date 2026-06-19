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
# LAYİHƏ KÖKÜ (DB / index / hash faylları burada yaşayır)
# ============================================
# DİQQƏT: əvvəl CHROMA_DB_PATH/HASH/BM25 `os.path.dirname(__file__)`-ə bağlı idi.
# `python -m tokengram` cwd-dən staging (MLA_AGENT/tokengram/) və ya site-packages
# `tokengram/`-i yükləyəndə __file__ PAKET qovluğuna düşürdü → DB layihə kökü
# əvəzinə `tokengram/chroma_db`-ə (clean install-da hətta site-packages-ə, bütün
# layihələr üçün ORTAQ) yazılırdı. Hook-lar isə həmişə layihə kökünə yazır →
# split-brain + fon drain livelock (2026-06-14 "re-index failed" insidenti).
# İndi hook-lardakı (hooks/project_root.py) EYNİ məntiq: CLAUDE_PROJECT_DIR
# (Claude Code launch-da təyin edir) → marker walk-up.
def _resolve_project_root() -> str:
    # DİQQƏT: hooks/project_root.py-dakı find_project_root ilə EYNİ olmalıdır.
    # Köhnə versiya səviyyə-səviyyə gedib HƏR səviyyədə marker-lərdən HƏR HANSI
    # birini tapan KİMİ qayıdırdı (ən yaxın səviyyə qalib gəlir → depth-first).
    # Hook-lar isə HƏR marker üçün AYRI tam walk-up edir → ən GÜCLÜ marker
    # (.mla_savings_history.jsonl = real data) dərinlikdən asılı olmayaraq qalib
    # gəlir (priority-first). Fərq monorepo split-brain yaradırdı: alt-qovluqda
    # .mcp.json, valideyndə real history olanda server alt-qovluğa, hook-lar
    # valideynə işarə edirdi. İndi hook-larla eyni priority-first məntiq.
    start = os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    home = os.path.abspath(os.path.expanduser("~"))

    def walk_up(predicate):
        cur = start
        for _ in range(8):
            if cur == home:
                return None  # ~/.claude qlobal config-dir, layihə kökü deyil
            try:
                if predicate(cur):
                    return cur
            except OSError:
                pass
            parent = os.path.dirname(cur)
            if parent == cur:
                return None
            cur = parent
        return None

    def _nonempty_history(d):
        h = os.path.join(d, ".mla_savings_history.jsonl")
        return os.path.exists(h) and os.path.getsize(h) > 0

    return (
        walk_up(_nonempty_history)
        or walk_up(lambda d: os.path.exists(os.path.join(d, ".claude", "settings.json")))
        or walk_up(lambda d: os.path.exists(os.path.join(d, ".mcp.json")))
        or walk_up(lambda d: os.path.exists(os.path.join(d, ".mla_enforcement.flag")))
        or start
    )


PROJECT_ROOT = _resolve_project_root()

# ============================================
# CHROMADB KONFİQURASİYASI
# ============================================

# ChromaDB verilənlər bazasının yolu (layihə kökü-nisbi — yuxarıdakı izaha bax)
CHROMA_DB_PATH = os.path.join(PROJECT_ROOT, "chroma_db")

# ChromaDB collection adı
COLLECTION_NAME = "code_vectors"

# ============================================
# EMBEDDİNG MODELİ KONFİQURASİYASI
# ============================================

# Embedding modeli: BAAI/bge-small-en-v1.5
# 33M parametr, 384-ölçü, ~130MB. fastembed (ONNX Runtime) ilə yüklənir —
# torch YOX. Eyni model id, eyni vektorlar; sadəcə backend dəyişib:
# ~38% az RAM, ~25× sürətli soyuq-start (68s → ~3s). fastembed bge üçün
# L2-normalize olunmuş vektor qaytarır → Chroma-nın default L2 məsafəsi
# kosinusla eyni sıralayır.
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"

# bge-en-v1.5: query üçün instruction prefix tövsiyə olunur,
# sənəd üçün prefix yoxdur. (fastembed `.embed()`-ə manual veririk ki,
# köhnə sentence-transformers davranışı ilə tam eyni qalsın.)
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
DOCUMENT_PREFIX = ""

# Embedding backend imzası — HashStore-da saxlanılır. Backend dəyişəndə
# (sentence-transformers → fastembed) vektor normalizasiyası dəyişir, ona görə
# köhnə vektorlar yenidən embed olunmalıdır. Bu tag dəyişsə (və ya köhnə, tagsız
# hash store görünsə) HashStore sıfırlanır → növbəti reindex HƏR faylı yenidən
# embed edir (upsert köhnə vektoru yerində üzərinə yazır). Səssiz qarışıq-
# normalizasiya deqradasiyasının qarşısını alır.
EMBED_BACKEND_TAG = "fastembed-bge-small-en-v1.5-onnx-v1"

# ============================================
# RERANKER KONFİQURASİYASI
# ============================================

# Cross-encoder reranker modeli — fastembed (ONNX) ilə yüklənir, torch YOX.
# Xenova/ms-marco-MiniLM-L-6-v2 = cross-encoder/ms-marco-MiniLM-L-6-v2-nin ONNX
# eksportu; eyni çəkilər → eyni logit-lər (bit-bit parity test edilib). 22M
# parametr, ~90MB.
RERANKER_MODEL_NAME = "Xenova/ms-marco-MiniLM-L-6-v2"

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

# Model warm-up (A1): server start-da embedding modelini fonda RAM-a yüklə.
# Soyuq ilk semantic/auto axtarış 30-60s çəkir — warm-up bunu ~1s-ə endirir,
# beləcə "auto" mode demək olar həmişə semantic işləyə bilir (real qənaət ↑).
# Zəif/az-RAM maşında söndürmək üçün: MLA_DISABLE_WARMUP=1
ENABLE_MODEL_WARMUP = os.getenv("MLA_DISABLE_WARMUP", "").lower() not in ("1", "true", "yes")

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

# Hash store faylı (incremental indexing üçün) — layihə kökü-nisbi
HASH_STORE_PATH = os.path.join(PROJECT_ROOT, ".file_hashes.json")

# BM25 keyword indeksinin persist faylı (iki fazalı index).
# Faza 1: xam chunk-lardan BM25 dərhal qurulub buraya yazılır (ML yox, saniyələr)
# → keyword axtarış embedding bitməsini gözləmədən işləyir.
# CHROMA_DB_PATH ilə eyni qovluqda (layihə kökü) qalır ki, hər iki proses eyni yeri tapsın.
BM25_INDEX_PATH = os.path.join(PROJECT_ROOT, ".bm25_index.pkl")

# Embedding encode batch ölçüsü. SentenceTransformer default 32.
# 128 böyük PHP fayllarında (vendor) zəif maşında RAM spike + upsert crash
# verirdi (12542 fayl → hamısı xəta) → 32-yə endirildi. Stabil profil.
EMBED_BATCH_SIZE = 32

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

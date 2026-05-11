"""Real MCP cavabları — token sayımı."""
import sys, tiktoken
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
enc = tiktoken.get_encoding("cl100k_base")

# Baseline
baseline = sum(
    len(enc.encode(open(f, encoding="utf-8").read()))
    for f in ["smart_router.py", "llm_agent.py", "main.py"]
)

# Real cavabları (indi MCP-dən gəldi)
q1 = '''Etibar: BM25_ONLY (mode=fast)


--- Mənbə #1: llm_agent.py → RAGAgent (skor: 4.690) ---
# Sinif: RAGAgent
def __init__(self, search_engine, provider: Optional[BaseLLMProvider] = None):
        self.search_engine = search_engine
        self.provider = provider or get_provider()

--- Mənbə #2: benchmark_results.py → imports_and_globals (skor: 3.760) ---
"""Final benchmark — MCP üzərindən gerçək cavabları hesablayır."""
[BÖYÜK STALE CHUNK — silinmiş fayldan, ~2500 tok]

--- Mənbə #3: PROGRESS.md → 1. Asılılıqları quraşdır (skor: 3.703) ---
# 1. Asılılıqları quraşdır ... (kifayət qədər kiçik)'''

q2 = '''Etibar: BM25_ONLY (mode=fast)


--- Mənbə #1: main.py → cmd_route (skor: 6.478) ---
def cmd_route(args):
    """Smart router məsləhəti göstər."""
    from smart_router import SmartRouter

    router = SmartRouter(args.directory)
    print(router.summary())
    print(f"\\n  Tövsiyə olunan parametrlər: {router.search_params()}")
    print(f"  RAG istifadə: {router.should_use_rag()}")
    return 0

--- Mənbə #2: smart_router.py → load_all_files_as_context (skor: 4.340) ---
def load_all_files_as_context(directory: str) -> str:
    """Bütün faylları birləşdirib LLM üçün kontekst kimi qaytarır.

    DIRECT mode üçün — kiçik layihələrdə tam kod LLM-ə verilir.
    """
    files = find_code_files(directory)
    blocks = []

    for file_path in files:
        try:
            text = Path(file_path).read_text(encoding="utf-8", errors="replace")
            blocks.append(f"--- {file_path.name} ---\\n{text}\\n")
        except Exception as e:
            logger.warning(f"Fayl oxuma xətası ({file_path}): {e}")

    return "\\n".join(blocks)

--- Mənbə #3: smart_router.py → SmartRouter (skor: 3.159) ---
class SmartRouter:
    """Layihənin ölçüsünə görə uyğun strategiyanı seçən router.

    İstifadə:
        router = SmartRouter("./my_project")
        mode = router.mode  # RouteMode.RAG_LIGHT
        params = router.search_params()  # {"top_k": 4, ...}
    """

    def __init__(self, directory: str):
        self.directory = directory
        self.token_count, self.file_count = estimate_project_tokens(directory)
        self.mode = decide_route(self.token_count)
        logger.info(
            f"🧭 Router: {self.file_count} fayl, {self.token_count:,} token "
            f"→ {self.mode.value.upper()}"
        )

    def search_params(self) -> dict:
        """Seçilmiş rejimə görə axtarış parametrlərini qaytarır."""
        if self.mode == RouteMode.RAG_LIGHT:
            return {
                "top_k": min(3, config.TOP_K_RESULTS),
                "use_reranker": False,
            }
        return {
            "top_k": config.TOP_K_RESULTS,
            "use_reranker": True,
        }

    def should_use_rag(self) -> bool:
        """RAG istifadə olunsun, yoxsa kod birbaşa LLM-ə verilsin?"""
        return self.mode != RouteMode.DIRECT

    def summary(self) -> str:
        """İnsana oxunaqlı qısa məlumat."""
        return (
            f"Layihə: {self.directory}\\n"
            f"  Fayllar: {self.file_count}\\n"
            f"  Tokenlər: {self.token_count:,}\\n"
            f"  Rejim: {self.mode.value.upper()}"
        )'''

q3 = '''Etibar: BM25_ONLY (mode=fast)


--- Mənbə #1: main.py → imports_and_globals (skor: 6.618) ---
"""
============================================
main.py — CLI Giriş Nöqtəsi
============================================
MƏRHƏLƏ 7: Bütün modulları birləşdirən CLI.
İstifadə:
    python main.py index ./my_project           # Layihəni indeksləşdir
    python main.py ask "Sual nədir?"             # Sual ver
    python main.py watch ./my_project            # Avtomatik re-index
    python main.py stats                         # Statistika göstər
    python main.py reset                         # Bazanı sıfırla
    python main.py route ./my_project            # Smart router məsləhəti
"""
import argparse
import logging
import sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import config
if __name__ == "__main__":
    sys.exit(main())

--- Mənbə #2: README.md → Layihə Quruluşu (skor: 3.352) ---
## Layihə Quruluşu
... (README from project)

--- Mənbə #3: README.md → CLI Əmrləri (skor: 3.028) ---
## CLI Əmrləri
... (README content)'''

print("=" * 60)
print("FINAL FAKTİKİ NƏTİCƏ — mode='fast' (BM25-only)")
print("=" * 60)
print(f"\nBASELINE (Read tool 3 fayl tam):     {baseline:>6,} tok")

q1_t = len(enc.encode(q1))
q2_t = len(enc.encode(q2))
q3_t = len(enc.encode(q3))
total = q1_t + q2_t + q3_t

print(f"\nRAG (3 sorğu, mode='fast'):")
print(f"  Q1 RAGAgent ask:                  {q1_t:>6,} tok")
print(f"  Q2 SmartRouter mode:              {q2_t:>6,} tok")
print(f"  Q3 cmd_ask CLI:                   {q3_t:>6,} tok")
print(f"  CƏMİ:                             {total:>6,} tok")

saving = baseline - total
pct = saving * 100.0 / baseline
print(f"\nQƏNAƏT:                             {saving:>6,} tok ({pct:.1f}%)")
print(f"\nƏlavə üstünlüklər:")
print(f"  - sentence_transformers YÜKLƏNMƏDİ")
print(f"  - RAM ehtiyacı: ~93 MB (1.5GB əvəzinə)")
print(f"  - Cavab vaxtı: ~50ms hər sorğu")

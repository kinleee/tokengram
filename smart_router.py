"""
============================================
smart_router.py — Layihə Ölçüsünə Görə Routing
============================================
MƏRHƏLƏ 5: Layihə ölçüsünə görə avtomatik fərqli
strategiyalar seçir.

- DIRECT_MODE — kiçik layihə (<4K token): bütün kodu LLM-ə ver
- RAG_LIGHT — orta layihə (<50K token): yüngül RAG (top-k az)
- RAG_FULL — böyük layihə (≥50K token): tam hybrid + reranker

Qərar token sayma əsasında verilir (tiktoken).
"""

import logging
from enum import Enum
from pathlib import Path
from typing import List, Tuple

import config
from document_loader import find_code_files

logger = logging.getLogger(__name__)


class RouteMode(Enum):
    """Layihə üçün seçilən rejim."""
    DIRECT = "direct"
    RAG_LIGHT = "rag_light"
    RAG_FULL = "rag_full"


def count_tokens(text: str) -> int:
    """Mətnin təxmini token sayını hesablayır.

    tiktoken yüklənmədikdə təxmin: 1 token ≈ 4 simvol.
    """
    try:
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def estimate_project_tokens(directory: str) -> Tuple[int, int]:
    """Layihənin təxmini ümumi token sayını və fayl sayını qaytarır."""
    files = find_code_files(directory)
    total_tokens = 0

    for file_path in files:
        try:
            text = Path(file_path).read_text(encoding="utf-8", errors="replace")
            total_tokens += count_tokens(text)
        except Exception as e:
            logger.warning(f"Token sayma xətası ({file_path}): {e}")

    return total_tokens, len(files)


def decide_route(token_count: int) -> RouteMode:
    """Token sayına görə rejim seçir."""
    if token_count < config.DIRECT_MODE_THRESHOLD:
        return RouteMode.DIRECT
    if token_count < config.RAG_LIGHT_THRESHOLD:
        return RouteMode.RAG_LIGHT
    return RouteMode.RAG_FULL


def load_all_files_as_context(directory: str) -> str:
    """Bütün faylları birləşdirib LLM üçün kontekst kimi qaytarır.

    DIRECT mode üçün — kiçik layihələrdə tam kod LLM-ə verilir.
    """
    files = find_code_files(directory)
    blocks = []

    for file_path in files:
        try:
            text = Path(file_path).read_text(encoding="utf-8", errors="replace")
            blocks.append(f"--- {file_path.name} ---\n{text}\n")
        except Exception as e:
            logger.warning(f"Fayl oxuma xətası ({file_path}): {e}")

    return "\n".join(blocks)


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
            f"Layihə: {self.directory}\n"
            f"  Fayllar: {self.file_count}\n"
            f"  Tokenlər: {self.token_count:,}\n"
            f"  Rejim: {self.mode.value.upper()}"
        )

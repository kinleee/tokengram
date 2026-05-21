"""
============================================
search_engine.py — Hybrid Axtarış + Reranker
============================================
MƏRHƏLƏ 3: Dense + BM25 hybrid axtarış, RRF fusion,
Cross-Encoder reranking, confidence scoring.
"""

import os
import logging
from typing import List, Optional, Dict
from dataclasses import dataclass, field
from rank_bm25 import BM25Okapi
import config

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Axtarış nəticəsi."""
    content: str
    metadata: Dict[str, str] = field(default_factory=dict)
    score: float = 0.0
    rank: int = 0
    source: str = "unknown"

    @property
    def id(self) -> str:
        fp = self.metadata.get("file_path", "unknown")
        ci = self.metadata.get("chunk_index", "0")
        return f"{fp}::chunk_{ci}"

    @property
    def file_info(self) -> str:
        name = self.metadata.get("file_name", "?")
        symbol = self.metadata.get("symbol_name", "?")
        return f"{name} → {symbol}"


class BM25Index:
    """BM25 keyword axtarış indeksi."""
    
    def __init__(self):
        self.bm25 = None
        self.documents = []
        self.doc_ids = []
        self.doc_metadatas = []
        self._is_built = False
    
    def build(self, documents, doc_ids, metadatas):
        """BM25 indeksi qur."""
        if not documents:
            return
        self.documents = documents
        self.doc_ids = doc_ids
        self.doc_metadatas = metadatas
        tokenized = [doc.lower().split() for doc in documents]
        self.bm25 = BM25Okapi(tokenized)
        self._is_built = True
        logger.info(f"📑 BM25 indeks quruldu: {len(documents)} sənəd")
    
    def search(self, query, top_k=10):
        """BM25 ilə keyword axtarışı."""
        if not self._is_built or self.bm25 is None:
            return []
        tokenized_query = query.lower().split()
        scores = self.bm25.get_scores(tokenized_query)
        scored_indices = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
        results = []
        for rank, (idx, score) in enumerate(scored_indices):
            if score > 0:
                results.append(SearchResult(
                    content=self.documents[idx],
                    metadata=self.doc_metadatas[idx] if idx < len(self.doc_metadatas) else {},
                    score=float(score), rank=rank + 1, source="bm25"
                ))
        return results


class Reranker:
    """Cross-Encoder reranker — nəticələri dəqiq yenidən sıralayır."""
    
    def __init__(self):
        self.model = None
        self._is_loaded = False
        
    def _lazy_load(self):
        """Modeli ilk istifadədə yüklə.

        CrossEncoder lazy import — module-level olsa MCP server startup
        ~34s çəkir və Claude Code timeout-unu keçir. Bu lazy import deadlock
        yaratmır, çünki sentence_transformers onsuz da embedding üçün eyni
        prosesdə lazy load olunmuşdur — yəni gələndə artıq sys.modules-də
        cache-dədir, yeni import lock yaranmır.
        """
        if self._is_loaded:
            return
        try:
            from sentence_transformers import CrossEncoder
            logger.info(f"🔄 Reranker yüklənir: {config.RERANKER_MODEL_NAME}")
            self.model = CrossEncoder(config.RERANKER_MODEL_NAME, max_length=config.RERANKER_MAX_LENGTH)
            self._is_loaded = True
            logger.info("✅ Reranker yükləndi")
        except Exception as e:
            logger.error(f"❌ Reranker yüklənə bilmədi: {e}")
    
    def rerank(self, query, candidates, top_k=None):
        """Namizədləri yenidən sıralayır. Returns (results, confidence).

        Cross-encoder raw logit-lər qaytarır (təxminən -10..+10). Bu, mənfi
        ədədlər göstərib istifadəçini qarışdırırdı. Sigmoid ilə [0,1]-ə
        çeviririk və sonrakı threshold müqayisəsini bu məkana keçiririk —
        həm `LOW_CONFIDENCE` etiketi məntiqli olur, həm də skor müsbət
        və oxunaqlı qalır.
        """
        import math

        top_k = top_k or config.TOP_K_RESULTS
        if not candidates:
            return [], "NO_RESULTS"
        self._lazy_load()
        if not self._is_loaded or self.model is None:
            return candidates[:top_k], "NO_RERANKER"
        try:
            pairs = [[query, c.content] for c in candidates]
            raw_scores = self.model.predict(pairs)
            for candidate, raw in zip(candidates, raw_scores):
                # Sigmoid: -inf -> 0, 0 -> 0.5, +inf -> 1
                candidate.score = 1.0 / (1.0 + math.exp(-float(raw)))
            ranked = sorted(candidates, key=lambda x: x.score, reverse=True)
            best_score = ranked[0].score if ranked else 0.0
            confidence = (
                "LOW_CONFIDENCE"
                if best_score < config.CONFIDENCE_THRESHOLD
                else "HIGH_CONFIDENCE"
            )
            for i, result in enumerate(ranked[:top_k]):
                result.rank = i + 1
            return ranked[:top_k], confidence
        except Exception as e:
            logger.error(f"Rerank xətası: {e}")
            return candidates[:top_k], "RERANK_ERROR"


class HybridSearchEngine:
    """Dense + BM25 hybrid axtarış, RRF fusion, reranking.

    BM25 staleness aşkarlanması: HashStore (.file_hashes.json) faylının
    mtime-ı "imza" kimi saxlanılır. Başqa proses (məs. flush_queue.py
    hook-u) bazaya yazanda hash faylı yenilənir → bu siniff özünü
    avtomatik təzələyir.
    """

    def __init__(self, vector_store):
        self.vector_store = vector_store
        self.collection = vector_store.collection
        self.bm25_index = BM25Index()
        self.reranker = Reranker()
        self._bm25_signature: float = 0.0
        self._build_bm25_index()

    def _hash_store_signature(self) -> float:
        """HashStore faylının mtime-ı (yoxdursa 0.0)."""
        try:
            return os.path.getmtime(config.HASH_STORE_PATH)
        except OSError:
            return 0.0

    def _build_bm25_index(self):
        try:
            documents, ids, metadatas = self.vector_store.get_all_texts_with_ids()
            if documents:
                self.bm25_index.build(documents, ids, metadatas)
            # Hər uğurlu build-dən sonra imzanı yenilə
            self._bm25_signature = self._hash_store_signature()
        except Exception as e:
            logger.warning(f"BM25 indeks qurma xətası: {e}")

    def rebuild_bm25(self):
        """BM25 indeksini yenidən qur."""
        self._build_bm25_index()

    def _ensure_fresh_bm25(self):
        """Başqa proses hash-ları yenilədibsə, BM25-i yenidən qur."""
        current = self._hash_store_signature()
        if current != self._bm25_signature and current > 0:
            logger.info("🔄 BM25 stale (hash store dəyişib) — yenidən qurulur")
            self._build_bm25_index()

    def search(self, query, top_k=None, alpha=None, file_type=None, use_reranker=True):
        """Hybrid axtarış. Returns (results, confidence)."""
        top_k = top_k or config.TOP_K_RESULTS
        alpha = alpha if alpha is not None else config.HYBRID_ALPHA
        candidate_count = config.CANDIDATE_COUNT

        # Başqa proses fayl indeksləyibsə, BM25-i avtomatik yenilə
        self._ensure_fresh_bm25()

        semantic_results = self._semantic_search(query, n_results=candidate_count, file_type=file_type)
        bm25_results = self.bm25_index.search(query, top_k=candidate_count)
        combined = self._rrf(semantic_results, bm25_results, alpha=alpha)
        
        if use_reranker and combined:
            results, confidence = self.reranker.rerank(query, combined, top_k=top_k)
        else:
            results = combined[:top_k]
            confidence = "NO_RERANKER"
        
        logger.info(f"🔍 Axtarış: '{query[:50]}' → {len(results)} nəticə ({confidence})")
        return results, confidence
    
    def _semantic_search(self, query, n_results=20, file_type=None):
        """ChromaDB semantic axtarış."""
        try:
            count = self.collection.count()
            if count == 0:
                return []
            # QUERY_PREFIX əlavə etmirik — CodeEmbeddingFunction.embed_query
            # özü prefix əlavə edir. İkiqat prefix-dən qaçırıq.
            query_params = {
                "query_texts": [query],
                "n_results": min(n_results, count),
            }
            if file_type:
                query_params["where"] = {"file_extension": file_type}
            results = self.collection.query(**query_params)
            search_results = []
            if results and results.get("documents"):
                for i, (doc, meta, dist) in enumerate(zip(
                    results["documents"][0], results["metadatas"][0], results["distances"][0]
                )):
                    similarity = 1.0 / (1.0 + dist)
                    search_results.append(SearchResult(
                        content=doc, metadata=meta, score=similarity,
                        rank=i + 1, source="semantic"
                    ))
            return search_results
        except Exception as e:
            logger.error(f"Semantic axtarış xətası: {e}")
            return []
    
    def _rrf(self, semantic_results, bm25_results, alpha=0.6, k=60):
        """Reciprocal Rank Fusion."""
        all_docs = {}
        semantic_rank = {}
        for i, r in enumerate(semantic_results):
            semantic_rank[r.id] = i + 1
            all_docs[r.id] = r
        bm25_rank = {}
        for i, r in enumerate(bm25_results):
            bm25_rank[r.id] = i + 1
            if r.id not in all_docs:
                all_docs[r.id] = r
        max_rank = max(len(semantic_results), len(bm25_results), 1) + 1
        rrf_scores = {}
        for doc_id in all_docs:
            s_rank = semantic_rank.get(doc_id, max_rank)
            b_rank = bm25_rank.get(doc_id, max_rank)
            rrf_scores[doc_id] = alpha * (1.0 / (k + s_rank)) + (1 - alpha) * (1.0 / (k + b_rank))
        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
        combined = []
        for rank, doc_id in enumerate(sorted_ids):
            result = all_docs[doc_id]
            result.score = rrf_scores[doc_id]
            result.rank = rank + 1
            result.source = "hybrid"
            combined.append(result)
        return combined
    
    def search_simple(self, query, top_k=None):
        """Sadə axtarış — yalnız semantic, reranker yox.

        ChromaDB SQLite-əsaslıdır → başqa proseslərin yazıları
        avtomatik görünür, ona görə burada staleness yoxlaması lazım deyil.
        """
        top_k = top_k or config.TOP_K_RESULTS
        return self._semantic_search(query, n_results=top_k)

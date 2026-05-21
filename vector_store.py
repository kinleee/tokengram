"""
============================================
vector_store.py — ChromaDB Vektor Bazası
============================================
MƏRHƏLƏ 2: ChromaDB PersistentClient ilə lokal vektor
bazası yaradır. nomic-embed-code custom embedding ilə
kodları indeksləyir. BM25 dual index dəstəyi var.
Hash-əsaslı incremental indexing ilə yalnız dəyişən
fayllar yenidən indekslənir.
"""

import json
import hashlib
import logging
from pathlib import Path
from typing import List, Optional, Dict, Tuple

import chromadb

from document_loader import CodeChunk
import config

logger = logging.getLogger(__name__)


def _canonical_path(p) -> str:
    """Yolu kanonik formaya gətir: absolute + forward-slash.

    Windows-da `c:\\x` vs `C:\\x` vs `c:/x` üçün eyni nəticə qaytarır,
    beləliklə ChromaDB where-filter, HashStore və `get_stats` dedup düz işləyir.
    """
    try:
        return Path(p).resolve(strict=False).as_posix()
    except (OSError, ValueError):
        # Path resolve mümkün deyilsə, ən azı slash normalize et
        return str(p).replace("\\", "/")


# ============================================
# CUSTOM EMBEDDİNG FUNKSİYASI
# ============================================

class CodeEmbeddingFunction:
    """BAAI/bge-small-en-v1.5 ilə ChromaDB-yə uyğun embedding funksiyası.

    33M parametrli standard SentenceTransformer modeli (~130MB).
    Lokal işləyir, API xərci yoxdur, Windows-da stabildir.

    ⚡ Lazy-of-lazy yükləmə: `__init__`-də model RAM-a alınmır.
    Yalnız ilk `__call__`-də (real embedding zamanı) yüklənir.
    Beləcə `count()`/`get()` kimi metadata çağırışları üçün
    sentence_transformers ümumiyyətlə import olunmur.

    ChromaDB ≥ 0.6 EmbeddingFunction protokolu üçün `name()` metodu
    və `__call__` lazımdır.
    """

    def __init__(self):
        # Model yox — ilk __call__-də yüklənəcək
        self._model = None

    @staticmethod
    def name() -> str:
        """ChromaDB-nin tələb etdiyi unikal ad."""
        return "mla-bge-small-en-v1.5"

    def _ensure_loaded(self):
        """İlk dəfə real embedding lazım olduqda modeli yüklə."""
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer
        logger.info(f"🔄 Embedding modeli yüklənir: {config.EMBEDDING_MODEL_NAME}")
        self._model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
        logger.info("✅ Embedding modeli yükləndi")

    def __call__(self, input: List[str]) -> List[List[float]]:
        """Mətnləri embedding vektorlarına çevir.

        Args:
            input: Embedding ediləcək mətn siyahısı (ChromaDB v0.6+ adıdır)

        Returns:
            Embedding vektorları siyahısı
        """
        self._ensure_loaded()
        # bge sənəd embedding-i üçün prefix istəmir (config-də DOCUMENT_PREFIX="")
        if config.DOCUMENT_PREFIX:
            input = [f"{config.DOCUMENT_PREFIX}{t}" for t in input]
        embeddings = self._model.encode(input, show_progress_bar=False)
        return embeddings.tolist()

    def embed_query(self, input) -> List[List[float]]:
        """Sorğu üçün ayrı embedding metodu (ChromaDB ≥ 0.6 tələbi).

        ChromaDB v0.6+ bu metodu chromadb-internal collection.query path-ında
        çağırır və **batch** kimi davranır: input List[str] və ya tək str
        ola bilər, return həmişə List[List[float]] olmalıdır.

        bge modelləri query üçün xüsusi instruction prefix istəyir.
        """
        self._ensure_loaded()
        # Input str və ya List[str] ola bilər
        texts = [input] if isinstance(input, str) else list(input)
        if config.QUERY_PREFIX:
            texts = [f"{config.QUERY_PREFIX}{t}" for t in texts]
        embeddings = self._model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()

    def embed_documents(self, input: List[str]) -> List[List[float]]:
        """Sənəd batch-i üçün ayrı embedding metodu (ChromaDB ≥ 0.6 tələbi)."""
        return self(input)


# ============================================
# HASH STORE (İnkremental İndeksləmə üçün)
# ============================================

class HashStore:
    """Fayl hash-larını saxlayan persistent store.
    
    Hər faylın MD5 hash-ini saxlayır. İndeksləmə zamanı
    yalnız hash-i dəyişmiş fayllar yenidən işlənir.
    """
    
    def __init__(self, store_path: str = None):
        self.store_path = store_path or config.HASH_STORE_PATH
        self.hashes: Dict[str, str] = {}
        self._load()
    
    def _load(self):
        """Disk-dən hash-ları yüklə."""
        try:
            if Path(self.store_path).exists():
                with open(self.store_path, "r", encoding="utf-8") as f:
                    self.hashes = json.load(f)
                logger.debug(f"Hash store yükləndi: {len(self.hashes)} fayl")
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Hash store oxuna bilmədi, sıfırdan başlanır: {e}")
            self.hashes = {}
    
    def _save(self):
        """Hash-ları diskə yaz."""
        try:
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump(self.hashes, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Hash store yazıla bilmədi: {e}")
    
    def get(self, file_path: str) -> Optional[str]:
        """Faylın saxlanılmış hash-ini qaytarır."""
        return self.hashes.get(_canonical_path(file_path))

    def update(self, file_path: str, file_hash: str):
        """Faylın hash-ini yenilə və diskə yaz."""
        self.hashes[_canonical_path(file_path)] = file_hash
        self._save()

    def remove(self, file_path: str):
        """Faylın hash-ini sil."""
        self.hashes.pop(_canonical_path(file_path), None)
        self._save()
    
    def clear(self):
        """Bütün hash-ları sil."""
        self.hashes = {}
        self._save()
    
    @staticmethod
    def compute_hash(file_path: str) -> str:
        """Faylın MD5 hash-ini hesabla."""
        try:
            content = Path(file_path).read_bytes()
            return hashlib.md5(content).hexdigest()
        except IOError as e:
            logger.error(f"Fayl hash-i hesablana bilmədi: {e}")
            return ""


# ============================================
# CHROMA VECTOR STORE
# ============================================

class ChromaVectorStore:
    """ChromaDB ilə vektor bazası əməliyyatları.
    
    Əsas xüsusiyyətlər:
    - PersistentClient — verilənlər diskdə saxlanılır
    - nomic-embed-code — kod üçün xüsusi embedding
    - Upsert — dublikat chunk yaranmır
    - Hash-əsaslı incremental indexing — yalnız dəyişən fayllar
    - BM25 corpus — hybrid search üçün keyword index
    
    İstifadə:
        store = ChromaVectorStore()
        store.index_documents(chunks)
        results = store.get_all_documents()
    """
    
    def __init__(self, db_path: str = None, collection_name: str = None):
        """ChromaDB bağlantısını qur və collection-u yarat/aç.
        
        Args:
            db_path: ChromaDB verilənlər bazasının qovluq yolu
            collection_name: Collection adı
        """
        self.db_path = db_path or config.CHROMA_DB_PATH
        self.collection_name = collection_name or config.COLLECTION_NAME
        self.hash_store = HashStore()
        
        # ChromaDB PersistentClient yarat
        try:
            logger.info(f"🗄️  ChromaDB açılır: {self.db_path}")
            self.client = chromadb.PersistentClient(path=self.db_path)
            
            # Custom embedding funksiyası
            self.embedding_fn = CodeEmbeddingFunction()
            
            # Collection-u al və ya yarat
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_fn,
                metadata={"description": "Kod bazası vektor indeksi"}
            )
            
            logger.info(f"✅ Collection hazır: '{self.collection_name}' "
                        f"({self.collection.count()} sənəd)")
            
        except Exception as e:
            logger.error(f"❌ ChromaDB qurulma xətası: {e}")
            raise
    
    def index_documents(self, chunks: List[CodeChunk], 
                        batch_size: int = 50) -> Dict[str, int]:
        """Chunk-ları ChromaDB-yə upsert ilə əlavə edir.
        
        Eyni ID ilə mövcud chunk varsa, yenilənir (dublikat yoxdur).
        Batch processing ilə böyük dataset-ləri effektiv idarə edir.
        
        Args:
            chunks: İndekslənəcək CodeChunk siyahısı
            batch_size: Hər batch-da neçə chunk göndərilsin
            
        Returns:
            Statistika: {"indexed": N, "skipped": N, "errors": N}
        """
        if not chunks:
            logger.warning("İndekslənəcək chunk yoxdur")
            return {"indexed": 0, "skipped": 0, "errors": 0}
        
        stats = {"indexed": 0, "skipped": 0, "errors": 0}
        
        # Batch-lara böl
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            
            ids = []
            documents = []
            metadatas = []
            
            for chunk in batch:
                try:
                    # Defensive: chunk metadata-sındakı file_path-i normallaşdır
                    fp = chunk.metadata.get("file_path")
                    if fp:
                        chunk.metadata["file_path"] = _canonical_path(fp)
                    chunk_id = chunk.unique_id
                    ids.append(chunk_id)
                    documents.append(chunk.full_content)
                    metadatas.append(chunk.metadata)
                except Exception as e:
                    logger.error(f"Chunk hazırlama xətası: {e}")
                    stats["errors"] += 1
                    continue
            
            if ids:
                try:
                    # Upsert: mövcud olanları yenilə, yenilərini əlavə et
                    self.collection.upsert(
                        ids=ids,
                        documents=documents,
                        metadatas=metadatas,
                    )
                    stats["indexed"] += len(ids)
                    logger.debug(f"  Batch {i // batch_size + 1}: "
                                f"{len(ids)} chunk upsert edildi")
                except Exception as e:
                    logger.error(f"Batch upsert xətası: {e}")
                    stats["errors"] += len(ids)
        
        logger.info(f"📊 İndeksləmə nəticəsi: {stats}")
        return stats
    
    def index_file(self, file_path: str, chunks: List[CodeChunk]) -> bool:
        """Tək bir faylı indeksləyir (incremental indexing üçün).

        Hash yoxlaması ilə: fayl dəyişməyibsə, keçilir.
        Dəyişibsə: köhnə chunk-ları silir, yenilərini əlavə edir.

        Args:
            file_path: Faylın yolu
            chunks: Bu fayldan yaranan chunk-lar

        Returns:
            True — fayl indeksləndi, False — dəyişiklik yoxdur
        """
        canonical = _canonical_path(file_path)

        # Hash yoxla
        new_hash = HashStore.compute_hash(file_path)
        old_hash = self.hash_store.get(canonical)

        if new_hash and new_hash == old_hash:
            logger.debug(f"⏭️  Dəyişiklik yoxdur, keçildi: {canonical}")
            return False

        # Chunk metadata-larında file_path-i kanonik formaya gətir
        # (Windows-da casing/slash fərqi səbəbindən stale duplicate olmasın)
        for ch in chunks:
            ch.metadata["file_path"] = canonical

        # Köhnə chunk-ları sil — həm kanonik, həm də mümkün stale variantları
        try:
            stale_variants = {
                canonical,
                str(file_path),
                str(Path(file_path)),
            }
            ids_to_delete: List[str] = []
            for variant in stale_variants:
                existing = self.collection.get(where={"file_path": variant})
                if existing and existing.get("ids"):
                    ids_to_delete.extend(existing["ids"])
            if ids_to_delete:
                self.collection.delete(ids=list(set(ids_to_delete)))
                logger.debug(f"🗑️  {len(set(ids_to_delete))} köhnə chunk silindi: {canonical}")
        except Exception as e:
            logger.warning(f"Köhnə chunk-ları silmə xətası: {e}")

        # Yeni chunk-ları əlavə et
        self.index_documents(chunks)

        # Hash-i yenilə
        if new_hash:
            self.hash_store.update(canonical, new_hash)

        logger.info(f"♻️  Yenidən indeksləndi: {canonical}")
        return True

    def delete_file(self, file_path: str):
        """Bir faylın bütün chunk-larını bazadan silir.

        Args:
            file_path: Silinəcək faylın yolu
        """
        canonical = _canonical_path(file_path)
        try:
            stale_variants = {
                canonical,
                str(file_path),
                str(Path(file_path)),
            }
            ids_to_delete: List[str] = []
            for variant in stale_variants:
                existing = self.collection.get(where={"file_path": variant})
                if existing and existing.get("ids"):
                    ids_to_delete.extend(existing["ids"])
            if ids_to_delete:
                self.collection.delete(ids=list(set(ids_to_delete)))
                self.hash_store.remove(canonical)
                logger.info(f"🗑️  Silindi: {canonical} ({len(set(ids_to_delete))} chunk)")
        except Exception as e:
            logger.error(f"Fayl silmə xətası: {e}")
    
    def clear_collection(self):
        """Collection-u tamamilə sıfırlayır.
        
        DİQQƏT: Bu əməliyyat geri qaytarıla bilməz!
        """
        try:
            self.client.delete_collection(self.collection_name)
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_fn,
                metadata={"description": "Kod bazası vektor indeksi"}
            )
            self.hash_store.clear()
            logger.info("🗑️  Collection sıfırlandı")
        except Exception as e:
            logger.error(f"Collection sıfırlama xətası: {e}")
    
    def get_all_documents(self) -> Optional[dict]:
        """Bazadakı bütün sənədləri qaytarır.
        
        Returns:
            ChromaDB get() nəticəsi: {ids, documents, metadatas}
        """
        try:
            return self.collection.get()
        except Exception as e:
            logger.error(f"Sənəd oxuma xətası: {e}")
            return None
    
    def get_stats(self) -> Dict:
        """Baza statistikasını qaytarır.
        
        Returns:
            dict: chunk sayı, fayl sayı, fayl növləri və s.
        """
        try:
            total = self.collection.count()
            
            if total == 0:
                return {
                    "total_chunks": 0,
                    "total_files": 0,
                    "file_types": {},
                    "status": "boş"
                }
            
            all_docs = self.collection.get()
            
            # Unikal fayllar
            file_paths = set()
            file_types = {}
            chunk_types = {}
            
            if all_docs and all_docs.get("metadatas"):
                for meta in all_docs["metadatas"]:
                    fp = meta.get("file_path", "unknown")
                    ext = meta.get("file_extension", "unknown")
                    ct = meta.get("chunk_type", "unknown")
                    
                    file_paths.add(fp)
                    file_types[ext] = file_types.get(ext, 0) + 1
                    chunk_types[ct] = chunk_types.get(ct, 0) + 1
            
            return {
                "total_chunks": total,
                "total_files": len(file_paths),
                "file_types": file_types,
                "chunk_types": chunk_types,
                "status": "aktiv"
            }
            
        except Exception as e:
            logger.error(f"Statistika xətası: {e}")
            return {"error": str(e)}
    
    def get_all_texts_with_ids(self) -> Tuple[List[str], List[str], List[Dict]]:
        """BM25 index qurmaq üçün bütün sənədləri qaytarır.
        
        Returns:
            Tuple: (sənəd mətnləri, ID-lər, metadata-lar)
        """
        try:
            all_docs = self.collection.get()
            if all_docs and all_docs.get("documents"):
                return (
                    all_docs["documents"],
                    all_docs["ids"],
                    all_docs["metadatas"]
                )
            return ([], [], [])
        except Exception as e:
            logger.error(f"Sənəd oxuma xətası: {e}")
            return ([], [], [])

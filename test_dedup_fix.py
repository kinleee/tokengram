"""
test_dedup_fix.py — index_file path-dedup düzəlişi üçün izolə test.

Eyni faylı 3 fərqli path formatında (case/slash variantları) index edib
total_files-ın 1 qaldığını yoxlayır. Düzəlişdən əvvəl total_files şişir.
"""
import sys
import tempfile
import shutil
from pathlib import Path


def _stub_embed_class():
    class StubEmbedFn:
        @staticmethod
        def name():
            return "stub-fast-384"

        def __call__(self, input):
            return [[0.0] * 384 for _ in input]

        def embed_query(self, input):
            texts = [input] if isinstance(input, str) else list(input)
            return [[0.0] * 384 for _ in texts]

        def embed_documents(self, input):
            return self(input)

    return StubEmbedFn


def main():
    tmpdir = Path(tempfile.mkdtemp(prefix="tg_dedup_test_"))
    print(f"[setup] Temp dir: {tmpdir}")

    # Config-i temp dir-ə yönləndir (import-dan əvvəl)
    import config
    config.CHROMA_DB_PATH = str(tmpdir / "chroma")
    config.HASH_STORE_PATH = str(tmpdir / "hashes.json")
    config.COLLECTION_NAME = "test_dedup_collection"

    # vector_store-u import et və embedding-i stub ilə əvəz et
    import vector_store as vs
    from document_loader import CodeChunk
    vs.CodeEmbeddingFunction = _stub_embed_class()

    # Test faylı yarat
    test_file = tmpdir / "billing.py"
    test_file.write_text("def foo():\n    return 42\n", encoding="utf-8")
    print(f"[setup] Test file: {test_file}")

    store = vs.ChromaVectorStore()

    def make_chunks(path_str: str, n: int = 3):
        chunks = []
        for i in range(n):
            ch = CodeChunk(
                content=f"chunk content {i} for {path_str}",
                metadata={
                    "file_path": path_str,
                    "file_name": "billing.py",
                    "file_extension": ".py",
                    "chunk_index": i,
                    "chunk_type": "function",
                    "start_line": i * 10,
                    "end_line": i * 10 + 9,
                },
            )
            chunks.append(ch)
        return chunks

    # 3 fərqli path format
    abs_path = str(test_file)
    variants = [
        ("lowercase-drive + backslash", abs_path[0].lower() + abs_path[1:]),
        ("uppercase-drive + forward-slash", (abs_path[0].upper() + abs_path[1:]).replace("\\", "/")),
        ("mixed-case + backslash", abs_path),
    ]

    results = []
    for label, p in variants:
        # Hash-ı dəyişməyən faylı təkrar index etmək üçün store.hash_store-u sıfırla
        # ki index_file həqiqətən delete-qabarmaq yolunu işlətsin
        store.hash_store.clear()
        canonical_dbg = vs._canonical_path(p)
        print(f"[debug] input={p!r}")
        print(f"        canonical={canonical_dbg!r}")
        chunks_dbg = make_chunks(p)
        store.index_file(p, chunks_dbg)
        for ch in chunks_dbg:
            print(f"        chunk_id={ch.unique_id!r}  fp_meta={ch.metadata['file_path']!r}")
        all_docs = store.collection.get()
        print(f"        DB ids: {sorted(all_docs['ids'])}")
        print(f"        DB fp metas: {sorted(set(m.get('file_path') for m in all_docs['metadatas']))}")
        stats = store.get_stats()
        results.append((label, p, stats["total_files"], stats["total_chunks"]))
        print(f"[index] {label}")
        print(f"        path: {p}")
        print(f"        -> total_files={stats['total_files']}, total_chunks={stats['total_chunks']}")

    final = store.get_stats()
    print(f"\n[final] total_files={final['total_files']}, total_chunks={final['total_chunks']}")

    # Cleanup
    try:
        shutil.rmtree(tmpdir)
    except Exception as e:
        print(f"[cleanup] Warning: {e}")

    # Verification
    if final["total_files"] == 1:
        print("\n[PASS] DEDUP TEST: 1 fayl 3 ferqli path format-da hele de 1 sayilir")
        return 0
    else:
        print(f"\n[FAIL] DEDUP TEST: total_files={final['total_files']}, gozlenilen 1")
        for label, p, f, c in results:
            print(f"   {label}: files={f} chunks={c}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

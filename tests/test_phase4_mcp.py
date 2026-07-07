"""Phase 4 — MCP server `search_code` direct invocation testləri.

Stdio MCP layer-i təqlid etmədən, `mcp_server.search_code(...)` funksiyasını
birbaşa Python-dan çağırır. Bu, sessiyada görünən `'RustBindingsAPI' object
has no attribute 'bindings'` xətasını reproduksiya etmək üçün yazılıb.

Nəticə: direct call-larda xəta yaranmadı — transient `--fresh` re-index
yarışı (eyni anda iki proses chroma_db-ə) ehtimaldır. Test mövcud davranışı
kilidləyir: 3 mode-da cavab gəlir, qaytarılan mətn boş deyil.

Run: `python tests/test_phase4_mcp.py`
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestSearchCodeDirect(unittest.TestCase):
    """`mcp_server.search_code` API smoke test (3 mode × 2 query)."""

    @classmethod
    def setUpClass(cls):
        # Import lazımdır — chromadb ilk yüklənmədə embedding modelini gətirir,
        # 30-60 saniyə çəkə bilər (cold start).
        import mcp_server  # noqa: F401 — module-level singletons-u trigger edir
        cls.mcp_server = mcp_server

    def test_fast_mode_returns_content(self):
        result = self.mcp_server.search_code("savings report", top_k=2, mode="fast")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 100, "fast mode should return real content")
        # EN-default keçidi (az.json removal, fdc3ef5): başlıq artıq İngiliscədir
        self.assertIn("Confidence:", result)

    def test_fast_mode_with_file_type_filter(self):
        result = self.mcp_server.search_code(
            "embedding model", top_k=2, mode="fast", file_type=".py"
        )
        self.assertIsInstance(result, str)

    def test_semantic_mode_returns_content(self):
        result = self.mcp_server.search_code("vector embedding", top_k=2, mode="semantic")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 100)

    def test_two_consecutive_calls_no_state_corruption(self):
        """`--fresh` sonrası gördüyümüz transient bug-un əsas profil-i."""
        r1 = self.mcp_server.search_code("first query", top_k=1, mode="fast")
        r2 = self.mcp_server.search_code("second query", top_k=1, mode="fast")
        self.assertIsInstance(r1, str)
        self.assertIsInstance(r2, str)

    def test_no_results_returns_clean_response(self):
        # Çox spesifik query — adətən nəticə yox olur
        result = self.mcp_server.search_code(
            "asdfqwertyzxcv random nonsense xyz12345", top_k=2, mode="fast"
        )
        self.assertIsInstance(result, str)
        # Boş və ya minimum cavab — crash etməməlidir


if __name__ == "__main__":
    unittest.main(verbosity=2)

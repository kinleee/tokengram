# =============================================================================
#  PROPRIETARY & CONFIDENTIAL — Tokengram.  Copyright (c) Ilkin Humbatov.
#  All rights reserved.  This is NOT open-source software.
# =============================================================================

"""Ghost sweep testləri — `ChromaVectorStore.sweep_ghosts()`.

Kök səbəb (2026-07-07): chunk ID-si `file_path::chunk_N` olduğu üçün path
forması dəyişən dövrlərdən qalan chunk-lar (nisbi / backslash / kanonik)
nə upsert ilə əvəz olunur, nə də kanonik `$in` delete ilə silinir →
axtarış faylın KÖHNƏ reviziyalarını qaytarır. Silinmiş faylların
chunk-larını da heç kim təmizləmirdi.

Run: `python -m pytest tests/test_ghost_sweep.py -q`
"""
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vector_store import ChromaVectorStore, _canonical_path  # noqa: E402


class TestGhostSweep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="mla_ghost_"))
        cls.db_dir = cls.tmp / "chroma"
        # Real, diskdə mövcud "canlı" fayl
        cls.live_file = cls.tmp / "live_module.py"
        cls.live_file.write_text("def alive():\n    return 1\n", encoding="utf-8")
        cls.store = ChromaVectorStore(
            db_path=str(cls.db_dir), collection_name="ghost_test"
        )
        # HashStore-u da izolyasiya et (default global fayla yazmasın)
        cls.store.hash_store.store_path = str(cls.tmp / "hashes.json")
        cls.store.hash_store.hashes = {}

    @classmethod
    def tearDownClass(cls):
        try:
            del cls.store
        except Exception:
            pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # Hər test təmiz vəziyyətdən başlayır (sıra asılılığı olmasın)
        existing = self.store.collection.get()
        if existing["ids"]:
            self.store.collection.delete(ids=existing["ids"])
        (Path(self.store.db_path) / ".ghost_sweep_ts").unlink(missing_ok=True)
        self.store.hash_store.hashes = {}

    def _seed(self):
        """4 chunk: 1 sağlam + 3 ghost növü (a/b/c)."""
        canon_live = _canonical_path(str(self.live_file))
        canon_dead = _canonical_path(str(self.tmp / "deleted_module.py"))
        legacy_form = str(self.live_file)  # backslash forması (kanonik deyil)
        assert legacy_form != canon_live, "testin mənası itdi: formalar eynidir"

        self.store.collection.upsert(
            ids=[
                f"{canon_live}::chunk_0",        # sağlam
                f"{legacy_form}::chunk_0",       # (b) legacy path forması
                f"{canon_dead}::chunk_0",        # (c) fayl silinib
                "orphan::chunk_0",               # (a) file_path metadata yoxdur
            ],
            documents=[
                "def alive(): return 1",
                "def alive_OLD_REVISION(): return 0",
                "def deleted_code(): pass",
                "mystery chunk",
            ],
            metadatas=[
                {"file_path": canon_live, "chunk_index": "0"},
                {"file_path": legacy_form, "chunk_index": "0"},
                {"file_path": canon_dead, "chunk_index": "0"},
                {"note": "no file_path key"},
            ],
        )
        # Hash-store: hər iki kanonik açar dolu olsun — sweep (b)/(c) üçün
        # onları atmalıdır ki, növbəti reindex faylı yenidən embed etsin.
        self.store.hash_store.hashes[canon_live] = "fakehash_live"
        self.store.hash_store.hashes[canon_dead] = "fakehash_dead"
        return canon_live, canon_dead

    def test_sweep_removes_all_three_ghost_kinds(self):
        canon_live, canon_dead = self._seed()
        self.assertEqual(self.store.collection.count(), 4)

        removed = self.store.sweep_ghosts()

        self.assertEqual(removed, 3)
        remaining = self.store.collection.get()
        self.assertEqual(remaining["ids"], [f"{canon_live}::chunk_0"])
        # (b)/(c) hash girişləri atılıb → növbəti reindex yenidən embed edər
        self.assertNotIn(canon_dead, self.store.hash_store.hashes)
        self.assertNotIn(canon_live, self.store.hash_store.hashes,
                         "legacy-forma ghost-un kanonik hash-i də atılmalıdır")

    def test_sweep_idempotent(self):
        self._seed()
        first = self.store.sweep_ghosts()
        self.assertEqual(first, 3)
        # İkinci sweep artıq heç nə tapmır
        self.assertEqual(self.store.sweep_ghosts(), 0)

    def test_interval_guard_skips_recent_sweep(self):
        # Marker indicə yazılıb → guard-lı çağırış heç nə etmir
        (Path(self.store.db_path) / ".ghost_sweep_ts").touch()
        legacy = str(self.live_file)
        self.store.collection.upsert(
            ids=[f"{legacy}::chunk_9"],
            documents=["ghost under guard"],
            metadatas=[{"file_path": legacy, "chunk_index": "9"}],
        )
        self.assertEqual(self.store.sweep_ghosts(min_interval_hours=24), 0)
        self.assertEqual(self.store.collection.count(), 1, "guard silməməli idi")
        # Guard-sız çağırış təmizləyir
        self.assertEqual(self.store.sweep_ghosts(), 1)
        self.assertEqual(self.store.collection.count(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

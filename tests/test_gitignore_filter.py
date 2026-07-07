"""Gitignore-aware filtrləmə üçün unit testlər (mla_constants.filter_gitignored
+ is_gitignored + document_loader.find_code_files inteqrasiyası).

Run: `python tests/test_gitignore_filter.py`
Vanilla unittest — 3rd-party framework yoxdur. Git quraşdırılmayıbsa skip.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mla_constants as MC
from document_loader import find_code_files


def _git_ok() -> bool:
    try:
        subprocess.run(["git", "--version"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5)
        return True
    except Exception:
        return False


GIT = _git_ok()


@unittest.skipUnless(GIT, "git not available")
class TestGitignoreFilter(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="gi_test_"))
        # Hər zəng üçün repo-root cache-ni təmizlə (tmp yollar təkrar olunmasın)
        MC._REPO_ROOT_CACHE.clear()
        def g(*args):
            subprocess.run(["git", "-C", str(self.dir), *args],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=True)
        g("init")
        g("config", "user.email", "t@t.t")
        g("config", "user.name", "t")
        (self.dir / ".gitignore").write_text("*.log\nbuild/\nsecret.py\nprivate/\n")
        (self.dir / "app.py").write_text("x = 1\n")
        (self.dir / "secret.py").write_text("KEY = 1\n")        # ignored, force-tracked below
        (self.dir / "debug.log").write_text("noise\n")          # ignored + untracked
        (self.dir / "build").mkdir()
        (self.dir / "build" / "out.py").write_text("y = 2\n")   # ignored dir
        (self.dir / "private").mkdir()
        (self.dir / "private" / "notes.py").write_text("z = 3\n")  # ignored dir
        (self.dir / "sub").mkdir()
        (self.dir / "sub" / "keep.py").write_text("w = 4\n")    # normal source
        g("add", "app.py", "sub/keep.py", ".gitignore")
        g("add", "-f", "secret.py")                              # force-track an ignored file
        g("commit", "-m", "init")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _abs(self, *rel):
        return str(self.dir / Path(*rel))

    def test_drops_untracked_ignored(self):
        cands = [self._abs("app.py"), self._abs("debug.log"),
                 self._abs("build", "out.py"), self._abs("private", "notes.py"),
                 self._abs("sub", "keep.py")]
        kept = MC.filter_gitignored(self.dir, cands)
        keptrel = sorted(os.path.relpath(k, self.dir).replace("\\", "/") for k in kept)
        self.assertEqual(keptrel, ["app.py", "sub/keep.py"])

    def test_tracked_ignored_file_is_kept(self):
        # secret.py matches `secret.py` rule but is force-tracked → must be KEPT
        cands = [self._abs("app.py"), self._abs("secret.py")]
        kept = MC.filter_gitignored(self.dir, cands)
        self.assertIn(self._abs("secret.py"), kept)

    def test_is_gitignored_single(self):
        self.assertTrue(MC.is_gitignored(self._abs("debug.log")))
        self.assertFalse(MC.is_gitignored(self._abs("app.py")))
        self.assertFalse(MC.is_gitignored(self._abs("secret.py")))  # tracked

    def test_order_preserved(self):
        cands = [self._abs("sub", "keep.py"), self._abs("debug.log"),
                 self._abs("app.py")]
        kept = MC.filter_gitignored(self.dir, cands)
        self.assertEqual(kept, [self._abs("sub", "keep.py"), self._abs("app.py")])

    def test_empty_input(self):
        self.assertEqual(MC.filter_gitignored(self.dir, []), [])

    def test_find_code_files_respects_gitignore(self):
        found = {os.path.relpath(p, self.dir).replace("\\", "/")
                 for p in find_code_files(str(self.dir))}
        # debug.log isn't a supported ext anyway; the meaningful checks are the
        # ignored .py files under build/ and private/ being absent, and tracked
        # secret.py + normal source being present.
        self.assertIn("app.py", found)
        self.assertIn("sub/keep.py", found)
        self.assertIn("secret.py", found)              # tracked-ignored kept
        self.assertNotIn("build/out.py", found)        # ignored dir
        self.assertNotIn("private/notes.py", found)    # ignored dir


class TestNonGitNoOp(unittest.TestCase):
    def test_non_git_dir_is_noop(self):
        MC._REPO_ROOT_CACHE.clear()
        d = Path(tempfile.mkdtemp(prefix="gi_nogit_"))
        try:
            cands = [str(d / "a.py"), str(d / "b.log")]
            self.assertEqual(MC.filter_gitignored(d, cands), cands)
            self.assertFalse(MC.is_gitignored(str(d / "b.log")))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

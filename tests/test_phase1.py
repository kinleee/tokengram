"""Phase 1 — mla_constants + find_code_files unit testləri.

Run: `python tests/test_phase1.py`
Heç bir 3rd-party test framework istifadə etmir — vanilla unittest.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mla_constants as MC
import config
from document_loader import find_code_files


class TestConstants(unittest.TestCase):
    def test_supported_extensions_well_formed(self):
        self.assertGreaterEqual(len(MC.SUPPORTED_EXTENSIONS), 30)
        for ext in MC.SUPPORTED_EXTENSIONS:
            self.assertTrue(ext.startswith("."), f"ext missing dot: {ext!r}")
            self.assertEqual(ext, ext.lower(), f"ext not lowercase: {ext!r}")

    def test_excluded_dirs_non_empty(self):
        self.assertGreater(len(MC.EXCLUDED_DIRS), 10)
        # Sanity: well-known bloat dirs are present
        for must in ("node_modules", ".git", "dist", "build", "target"):
            self.assertIn(must, MC.EXCLUDED_DIRS)

    def test_excluded_file_patterns_present(self):
        for must in (
            "package-lock.json",
            "yarn.lock",
            "Cargo.lock",
            ".mla_session_log",
        ):
            self.assertIn(must, MC.EXCLUDED_FILE_PATTERNS)

    def test_excluded_file_suffixes_present(self):
        for must in (".min.js", ".min.css", ".bundle.js", ".map"):
            self.assertIn(must, MC.EXCLUDED_FILE_SUFFIXES)

    def test_max_file_size_sane(self):
        self.assertEqual(MC.MAX_FILE_SIZE_BYTES, 1_000_000)

    def test_config_reexports_match(self):
        self.assertIs(config.SUPPORTED_EXTENSIONS, MC.SUPPORTED_EXTENSIONS)
        self.assertIs(config.EXCLUDED_DIRS, MC.EXCLUDED_DIRS)
        self.assertIs(config.EXCLUDED_FILE_PATTERNS, MC.EXCLUDED_FILE_PATTERNS)
        self.assertIs(config.EXCLUDED_FILE_SUFFIXES, MC.EXCLUDED_FILE_SUFFIXES)
        self.assertEqual(config.MAX_FILE_SIZE_BYTES, MC.MAX_FILE_SIZE_BYTES)


class TestFindCodeFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mla_test_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_basic_discovery_by_extension(self):
        (self.tmp / "a.py").write_text("print('hi')\n")
        (self.tmp / "b.ts").write_text("const x = 1;\n")
        (self.tmp / "c.unknown").write_text("noop\n")
        found = find_code_files(str(self.tmp))
        names = sorted(p.name for p in found)
        self.assertEqual(names, ["a.py", "b.ts"])

    def test_lock_file_excluded(self):
        (self.tmp / "real.js").write_text("// ok\n")
        (self.tmp / "package-lock.json").write_text("{}\n")
        (self.tmp / "yarn.lock").write_text("# ok\n")
        found = {p.name for p in find_code_files(str(self.tmp))}
        self.assertIn("real.js", found)
        self.assertNotIn("package-lock.json", found)
        self.assertNotIn("yarn.lock", found)

    def test_minified_bundle_excluded(self):
        (self.tmp / "app.js").write_text("// ok\n")
        (self.tmp / "app.min.js").write_text("var a=1\n")
        (self.tmp / "vendor.bundle.js").write_text("var b=1\n")
        (self.tmp / "app.js.map").write_text("{}\n")
        found = {p.name for p in find_code_files(str(self.tmp))}
        self.assertIn("app.js", found)
        self.assertNotIn("app.min.js", found)
        self.assertNotIn("vendor.bundle.js", found)
        self.assertNotIn("app.js.map", found)

    def test_size_cap_excluded(self):
        (self.tmp / "small.py").write_text("print('hi')\n")
        big = self.tmp / "huge.py"
        big.write_bytes(b"x = 1\n" * 250_000)  # ~1.5 MB
        found = {p.name: p.stat().st_size for p in find_code_files(str(self.tmp))}
        self.assertIn("small.py", found)
        self.assertNotIn("huge.py", found, f"huge.py should be skipped, size={big.stat().st_size}")

    def test_excluded_dir_skipped(self):
        (self.tmp / "a.py").write_text("print(1)\n")
        nm = self.tmp / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "b.ts").write_text("export {}\n")
        found = {p.name for p in find_code_files(str(self.tmp))}
        self.assertEqual(found, {"a.py"})

    def test_empty_file_accepted(self):
        # Empty file is below size cap. Whether to keep is chunker's call;
        # find_code_files itself accepts it.
        (self.tmp / "empty.py").write_text("")
        found = {p.name for p in find_code_files(str(self.tmp))}
        self.assertIn("empty.py", found)

    def test_new_language_extensions(self):
        for ext in (".ts", ".tsx", ".go", ".rs", ".java", ".rb", ".cs", ".kt"):
            (self.tmp / f"sample{ext}").write_text("noop\n")
        found = {p.name for p in find_code_files(str(self.tmp))}
        self.assertEqual(len(found), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)

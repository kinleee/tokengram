"""
setup_cython.py — bizim biznes logic modullarını .pyd-ə kompilyasiya edir.

İstifadə:
    python setup_cython.py build_ext --inplace
    python setup_cython.py clean --all      # .c və .pyd faylları sil

Çıxış: hər .py faylı yanında .pyd (Windows) və ya .so (Linux/macOS).

Strategiya:
- Yalnız OZ kodumuz kompilyasiya olunur. Third-party deps (chromadb,
  sentence-transformers, etc.) toxunulmur — onsuz da GitHub-da açıqdır.
- hooks/* kompilyasiya OLUNMUR — Claude Code shell ilə çağırır, .py qalmalıdır.
  İSTİSNA: hooks/license_gate.py — import-only (script kimi çağırılmır) və
  enforcement gate-ini saxlayır, ona görə .pyd kimi ship olunur. Ayrıca
  `build_license_gate.py` ilə build + deploy olunur (bu skriptdə DEYİL, çünki
  o, çıxışı tokengram/hooks/ + vscode-extension/resources/hooks/-a yerləşdirir).
"""
from __future__ import annotations

import sys
from pathlib import Path

from setuptools import setup
from Cython.Build import cythonize

# Bizim biznes logic — sensitive, .pyd-ə kompilyasiya olunmalıdır
MODULES = [
    "license.py",
    "mcp_server.py",
    "search_engine.py",
    "vector_store.py",
    "document_loader.py",
    "smart_router.py",
    "conversation_indexer.py",
    # 2026-05-14 əlavə: tester paket açanda açıq görünən fayllar — kompil et
    "main.py",
    "llm_agent.py",
    "file_watcher.py",
    "config.py",
    "mla_constants.py",
    "i18n.py",
    # 2026-06-11: korrupsiya qoruması (pre-flight + karantin + yazıçı kilidi)
    "db_guard.py",
]

def _build():
    """Setup wrapping — Windows multiprocessing fork-safety üçün lazımdır."""
    project_root = Path(__file__).parent
    missing = [m for m in MODULES if not (project_root / m).exists()]
    if missing:
        print(f"XƏTA: tapılmadı: {missing}", file=sys.stderr)
        sys.exit(1)

    setup(
        name="mla-agent-compiled",
        ext_modules=cythonize(
            MODULES,
            compiler_directives={
                "language_level": "3",
                "embedsignature": True,   # FastMCP inspect.signature() istifadə edir
                "binding": True,          # function decorators / introspection üçün
                "always_allow_keywords": True,
            },
            annotate=False,
            nthreads=0,   # tək-thread — Windows multiprocessing fork problemlərindən qaçır
        ),
        zip_safe=False,
    )


if __name__ == "__main__":
    _build()

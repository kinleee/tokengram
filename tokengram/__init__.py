"""Tokengram — token-saving memory layer for AI coding assistants."""
__version__ = "0.1.7"

# The Cython-compiled `.pyd` modules inside this package import each other via
# top-level names (`import config`, `import mcp_server`, ...). Those imports
# only resolve when the directory holding the .pyd files is on `sys.path`.
# Doing the insert here — at package import time — means every entry point
# (`from tokengram import mcp_server`, `python -m tokengram`,
# `python -m tokengram.server`, the `tokengram` console script) works the
# same way, with no per-caller wrapper required.
def _ensure_pkg_dir_on_syspath() -> None:
    import os
    import sys

    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    if pkg_dir and pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)


_ensure_pkg_dir_on_syspath()
del _ensure_pkg_dir_on_syspath

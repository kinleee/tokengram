"""Tokengram — token-saving memory layer for AI coding assistants."""
__version__ = "0.1.32"


def _ensure_pkg_dir_on_syspath() -> None:
    import os
    import sys

    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    if pkg_dir and pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)


_ensure_pkg_dir_on_syspath()
del _ensure_pkg_dir_on_syspath

"""Entry point: `python -m tokengram.server` or the `tokengram` console script.

This file delegates to the compiled `mcp_server` module shipped inside the
package. We do the import lazily so that `import tokengram` stays cheap.
"""
from __future__ import annotations


def main() -> int:
    import os
    import sys

    # Compiled `.pyd` modullari `import config`, `import mcp_server` kimi top-level
    # adlarla import edir (Cython build belə qurulub). Onları sibling .pyd-lərə
    # yönəltmək üçün paket qovluğunu sys.path-ə əlavə edirik.
    pkg_dir = os.path.dirname(__file__)
    if pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)

    from tokengram import server

    return server.main()


if __name__ == "__main__":
    import sys

    sys.exit(main())

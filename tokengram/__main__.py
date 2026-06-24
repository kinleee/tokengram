"""Entry point: `python -m tokengram.server` or the `tokengram` console script.

This file delegates to the compiled `mcp_server` module shipped inside the
package. We do the import lazily so that `import tokengram` stays cheap.
"""
from __future__ import annotations


def main() -> int:
    import os
    import sys

    # The compiled `.pyd` modules import each other via top-level names like
    # `import config`, `import mcp_server` (this is how the Cython build is set
    # up). To resolve those names to the sibling .pyd files, we add the package
    # directory to sys.path.
    pkg_dir = os.path.dirname(__file__)
    if pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)

    from tokengram import server

    return server.main()


if __name__ == "__main__":
    import sys

    sys.exit(main())

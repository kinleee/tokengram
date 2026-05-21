"""MCP server wrapper - mcp_server.pyd (Cython-compiled) ucun giris noqtesi.

Cython-compiled .pyd modullari `python -m mcp_server` ile islemir
("No code object available" errorunu verir). Buna gore standalone wrapper.

CLI rejimi: `python run_mcp_server.py --reindex <path> [--fresh]` MCP-i
qaldirmadan tek-vurusluq reindex edir (VS Code extension dyumesi ucun).
"""
import os
import sys


def _ensure_pkg_dir_on_syspath() -> None:
    # The Cython-compiled .pyd modules inside the tokengram package import each
    # other via top-level names (`import config`, `import mcp_server`). For those
    # imports to resolve, the directory holding the .pyd files must be on
    # sys.path BEFORE we try to import any of them. `__main__.py` does the same
    # thing for the `python -m tokengram` entry point — this is the parallel for
    # `python -m tokengram.server` / the `tokengram` console script.
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    if pkg_dir and pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)


def _import_mcp_module():
    # Wheel install: module lives at tokengram.mcp_server. Dev source: top-level mcp_server.
    try:
        from tokengram import mcp_server as _m  # type: ignore
        return _m
    except ImportError:
        import mcp_server as _m  # type: ignore
        return _m


def main() -> int:
    _ensure_pkg_dir_on_syspath()
    mod = _import_mcp_module()
    if len(sys.argv) >= 2 and sys.argv[1] == "--reindex":
        return mod._cli_reindex(sys.argv[2:])

    mod.mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

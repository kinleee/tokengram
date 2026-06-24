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


def _wait_for_install_unlock(max_wait: float = 180.0) -> None:
    """Block (bounded) while the VS Code extension is mid-install/upgrade.

    Butun VS Code pencereleri TEK ~/.tokengram/venv-i paylasir. Bir pencere
    wheel-i yenileyende pip kompilyasiya olunmus .pyd fayllarini (py_rust_stemmers,
    mcp_server, ...) ustune yazmalidir. Windows-da ISTENILEN isleyen prosese
    yuklenmis .pyd evez edile bilmir -> pip "os error 32 (file in use)" verib
    sinir. Claude Code olu MCP serveri saniyeler icinde yeniden spawn edir, ona
    gore install penceresinde respawn fayllari yeniden kilidleyir ve yenilemeni
    sindirir (cox-pencereli install yarisi).

    Installer install muddetinde ~/.tokengram/install.lock markerini qoyur.
    Burada, .pyd yukleyen HER HANSI import-dan EVVEL, o markerin temizlenmesini
    gozleyirik ki, bu proses faylari ustune-yazma vaxti map etmesin. max_wait ve
    marker bayatligi ile mehdudlasdirilir ki, cokmuws installer serveri ebedi
    asib saxlaya bilmesin. Marker yoxdursa (normal hal) deruhal qayidir.
    """
    import time

    lock = os.path.join(os.path.expanduser("~"), ".tokengram", "install.lock")
    stale_after = 600.0  # installer legitim sekilde >10 deq isleye bilmez
    waited = 0.0
    while waited < max_wait:
        try:
            mtime = os.stat(lock).st_mtime
        except OSError:
            return  # marker yox (ve ya oxunmur) -> install getmir
        if (time.time() - mtime) > stale_after:
            return  # bayat marker -> cokmuws installer, asma
        time.sleep(1.0)
        waited += 1.0
    # Timeout -- yene de davam et; hec vaxt xidmet etmemekdense bir respawn riski
    # daha yaxsidir.


def main() -> int:
    # Cox-pencereli install yarisinin qarsisi: install gedirse .pyd-leri yukleyib
    # kilitlemeden evvel gozle (ETRAFLI: bax _wait_for_install_unlock).
    _wait_for_install_unlock()
    _ensure_pkg_dir_on_syspath()
    mod = _import_mcp_module()
    if len(sys.argv) >= 2 and sys.argv[1] == "--reindex":
        return mod._cli_reindex(sys.argv[2:])

    serve = getattr(mod, "serve", None)
    if serve is not None:
        # 0.1.24+: fon servislər (worker, warm-up, watchdog) + zəmanətli çıxış.
        # mcp.run()-ı birbaşa çağırmaq bunların heç birini başlatmırdı.
        return serve()
    mod.mcp.run()  # köhnə .pyd üçün fallback
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Assemble tokengram/ package and build a PyPI wheel.

Run this from the repo root:

    python build_pypi.py            # build wheel for current platform
    python build_pypi.py --upload   # build + twine upload to PyPI

What it does:
    1. Ensure Cython .pyd files exist (delegates to make_distribution.py if needed)
    2. Copy compiled extensions + run_mcp_server.py into tokengram/
    3. Copy hooks/*.py into tokengram/hooks/
    4. Copy messages/*.json into tokengram/messages/
    5. Build wheel with `python -m build --wheel`
    6. (Optional) twine upload

Output: dist/tokengram-X.Y.Z-cp312-cp312-<platform>.whl
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PKG = ROOT / "tokengram"

# 13 modules currently compiled by setup_cython.py / make_distribution.py
COMPILED_MODULES = [
    "license",
    "mcp_server",
    "search_engine",
    "vector_store",
    "document_loader",
    "smart_router",
    "conversation_indexer",
    "llm_agent",
    "file_watcher",
    "main",
    "config",
    "mla_constants",
    "i18n",
    # 2026-06-11: korrupsiya qoruması (pre-flight + karantin + yazıçı kilidi)
    "db_guard",
]

# Plain-source files that ship as-is (no compilation)
INCLUDED_PY = [
    ("run_mcp_server.py", "server.py"),
]

HOOK_FILES = [
    "pre_read_check.py",
    "post_grep_check.py",
    "post_bash_check.py",
    "queue_change.py",
    "savings_report.py",
    "reset_savings.py",
    "refresh_bar.py",
    "arch_doc.py",
    "show_arch.py",
    "flush_queue.py",
    "toggle_mla.py",
    # license_gate is NOT copied as plaintext: it holds the enforcement gate and
    # is import-only, so it ships COMPILED (.pyd) via build_license_gate.py below.
    "project_root.py",
    "atomic_write.py",
    # 2026-06-21: bloklamayan search_code yönləndirməsi (additionalContext nudge).
    # pre_read/post_grep/post_bash bunu import edir; əskik olsa no-op stub-a düşür.
    "nudge.py",
]


# `python -m tokengram` (həm MCP server, həm reindex CLI buradan keçir) bu iki
# faylı TƏLƏB edir. Onlar `tokengram/`-da persistent qalır, amma populate_package
# onları kopyalamır — qovluq təmizlənib build olunsa, wheel `__main__.py`-sız
# çıxırdı və install-da `No module named tokengram.__main__` verirdi (tester
# vusal.ir-dəki dəqiq xəta). Aşağıda hər build-də mövcudluqları zəmanətə alınır.
_PKG_INIT_PY = '''"""Tokengram — token-saving memory layer for AI coding assistants."""
__version__ = "{version}"


def _ensure_pkg_dir_on_syspath() -> None:
    import os
    import sys

    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    if pkg_dir and pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)


_ensure_pkg_dir_on_syspath()
del _ensure_pkg_dir_on_syspath
'''

_PKG_MAIN_PY = '''"""Entry point: `python -m tokengram` / `python -m tokengram.server` / console script."""
from __future__ import annotations


def main() -> int:
    import os
    import sys

    pkg_dir = os.path.dirname(__file__)
    if pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)

    from tokengram import server

    return server.main()


if __name__ == "__main__":
    import sys

    sys.exit(main())
'''


def read_version() -> str:
    """pyproject.toml — versiyanın TƏK mənbəyi. __init__.py hər build-də
    buradan sinxronlaşır (0.1.12-də ilişib qalmış __version__ dərsi)."""
    import re
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        fail("pyproject.toml-da version tapılmadı")
    return m.group(1)


def step(msg: str) -> None:
    print(f"\n=== {msg} ===", flush=True)


def fail(msg: str, code: int = 1) -> None:
    print(f"[error] {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def find_compiled(stem: str) -> Path | None:
    """Return path to a compiled extension for *stem*, or None if absent."""
    for d in (ROOT, ROOT / "dist_compiled"):
        for ext in ("*.pyd", "*.so"):
            matches = list(d.glob(f"{stem}.{ext.split('.')[-1]}"))
            if not matches:
                matches = list(d.glob(f"{stem}.*.{ext.split('.')[-1]}"))
            if matches:
                return matches[0]
    return None


def ensure_compiled() -> None:
    step("Verify compiled extensions exist")
    missing = [m for m in COMPILED_MODULES if not find_compiled(m)]
    if not missing:
        print(f"  ok — all {len(COMPILED_MODULES)} extensions present")
        return
    print(f"  missing: {', '.join(missing)}")
    print("  running make_distribution.py to build...")
    subprocess.check_call([sys.executable, "make_distribution.py"], cwd=ROOT)
    still_missing = [m for m in COMPILED_MODULES if not find_compiled(m)]
    if still_missing:
        fail(f"compilation failed for: {', '.join(still_missing)}")


def populate_package() -> None:
    step("Populate tokengram/ from compiled extensions + hooks + messages")
    PKG.mkdir(exist_ok=True)
    (PKG / "hooks").mkdir(exist_ok=True)
    (PKG / "messages").mkdir(exist_ok=True)

    # 0. Paket giriş faylları — `python -m tokengram` üçün MƏCBUR.
    # __init__.py HƏMİŞƏ yenidən yazılır ki, __version__ pyproject.toml ilə
    # sinxron qalsın; __main__.py yalnız əskikdirsə yazılır.
    version = read_version()
    init_dst = PKG / "__init__.py"
    init_dst.write_text(_PKG_INIT_PY.format(version=version), encoding="utf-8")
    print(f"  + tokengram/__init__.py (__version__ = {version})")
    main_dst = PKG / "__main__.py"
    if not main_dst.exists():
        main_dst.write_text(_PKG_MAIN_PY, encoding="utf-8")
        print("  + tokengram/__main__.py (canonical — əskik idi)")
    else:
        print("  · tokengram/__main__.py (mövcud)")

    # 1. Compiled .pyd / .so files
    for stem in COMPILED_MODULES:
        src = find_compiled(stem)
        if not src:
            fail(f"compiled extension for '{stem}' disappeared between steps")
        dst = PKG / src.name
        shutil.copy2(src, dst)
        print(f"  + {dst.relative_to(ROOT)}")

    # 2. Plain Python files
    for src_name, dst_name in INCLUDED_PY:
        src = ROOT / src_name
        if not src.exists():
            fail(f"required source missing: {src_name}")
        shutil.copy2(src, PKG / dst_name)
        print(f"  + tokengram/{dst_name}")

    # 3. Hooks
    hooks_src = ROOT / "hooks"
    for h in HOOK_FILES:
        src = hooks_src / h
        if not src.exists():
            print(f"  ! warn — hook missing: {h}")
            continue
        shutil.copy2(src, PKG / "hooks" / h)
        print(f"  + tokengram/hooks/{h}")

    # 3b. license_gate — the enforcement gate, shipped COMPILED (.pyd) so an AI
    # (or anyone) can't read or patch it. build_license_gate.py compiles
    # hooks/license_gate.py and drops the .pyd into tokengram/hooks/ (+ the VSIX
    # resources/hooks/), removing any plaintext license_gate.py left there.
    print("  · compiling license_gate -> .pyd (build_license_gate.py)")
    subprocess.check_call([sys.executable, "build_license_gate.py"], cwd=ROOT)
    stray = PKG / "hooks" / "license_gate.py"
    if stray.exists():
        stray.unlink()  # belt-and-suspenders: never ship the gate as plaintext

    # 4. i18n messages
    msgs = ROOT / "messages"
    if msgs.is_dir():
        for j in msgs.glob("*.json"):
            shutil.copy2(j, PKG / "messages" / j.name)
            print(f"  + tokengram/messages/{j.name}")


def build_wheel() -> Path:
    step("Build wheel (python -m build --wheel)")
    # Fail-fast: `python -m tokengram` (MCP server + reindex) bu fayllar olmadan
    # işləmir. Sınıq wheel ship etməkdənsə build-i dayandır.
    for required in ("__init__.py", "__main__.py"):
        if not (PKG / required).exists():
            fail(f"tokengram/{required} əskikdir — `python -m tokengram` sınar. Build dayandırıldı.")
    dist = ROOT / "dist"
    # Clean stale wheels so the post-build glob picks up only the new one
    if dist.exists():
        for old in dist.glob("tokengram-*.whl"):
            old.unlink()
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "build"],
        cwd=ROOT,
    )
    subprocess.check_call([sys.executable, "-m", "build", "--wheel"], cwd=ROOT)
    wheels = sorted(dist.glob("tokengram-*.whl"))
    if not wheels:
        fail("no wheel produced in dist/")
    print(f"\n  built: {wheels[-1].relative_to(ROOT)}")
    return wheels[-1]


def verify_wheel(wheel: Path) -> None:
    """Wheel-i TƏMİZ prosesdə import-test et — build 'uğurlu' sayılmazdan əvvəl.

    2026-06-11 dərsi: yarıda kəsilmiş build truncated .pyd qoyur (document_loader
    2MB-də kəsilmişdi, 'not a valid Win32 application'); stale build/temp obyektləri
    üzündən növbəti build onu yenidən linkləmir. Bu addım zədəli/əskik modulu
    wheel ship olunmazdan əvvəl tutur.
    """
    step("Verify wheel (clean-process import smoke test)")
    import tempfile
    import zipfile
    with tempfile.TemporaryDirectory(prefix="tg_wheel_verify_") as td:
        with zipfile.ZipFile(wheel) as z:
            names = z.namelist()
            z.extractall(td)
        # Source-protection guard: the license gate MUST ship compiled, never as
        # readable/patchable plaintext. Fail the build if that ever regresses.
        gate = [n for n in names if "hooks/license_gate" in n]
        if any(n.endswith("hooks/license_gate.py") for n in gate):
            fail("wheel ships PLAINTEXT tokengram/hooks/license_gate.py — gate must be .pyd")
        if not any(n.endswith(".pyd") or n.endswith(".so") for n in gate):
            fail("wheel is MISSING the compiled license_gate (.pyd/.so) — run build_license_gate.py")
        print("  gate ships compiled:", [n.split('/')[-1] for n in gate])
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]);\n"
            "import tokengram\n"
            "from tokengram import mcp_server as m\n"
            "for attr in ('_cli_reindex', 'serve', 'search_code', 'get_stats'):\n"
            "    assert hasattr(m, attr), f'mcp_server.{attr} ƏSKİKDİR'\n"
            "import db_guard, vector_store, search_engine, document_loader\n"
            "for fn in ('preflight_check_and_heal', 'acquire_writer_lock', 'quarantine_db'):\n"
            "    assert hasattr(db_guard, fn), f'db_guard.{fn} ƏSKİKDİR'\n"
            "print('wheel import smoke: OK,', tokengram.__version__)\n"
        )
        try:
            subprocess.check_call([sys.executable, "-c", code, td], cwd=td)
        except subprocess.CalledProcessError:
            fail(
                "wheel import smoke testi KEÇMƏDİ — zədəli/əskik modul var. "
                "Həll: build/, dist_compiled/, kök .pyd/.c silib tam rebuild et."
            )


def upload(wheel: Path) -> None:
    step("Upload to PyPI (twine)")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "twine"],
        cwd=ROOT,
    )
    subprocess.check_call([sys.executable, "-m", "twine", "upload", str(wheel)], cwd=ROOT)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true", help="twine upload after build")
    parser.add_argument("--skip-compile-check", action="store_true")
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="skip the clean-process import smoke test (it needs the full runtime "
        "dependency tree installed; useful when building the wheel separately "
        "from verifying it, e.g. on a RAM-constrained machine)",
    )
    args = parser.parse_args()

    if not args.skip_compile_check:
        ensure_compiled()
    populate_package()
    wheel = build_wheel()
    if not args.skip_verify:
        verify_wheel(wheel)
    if args.upload:
        upload(wheel)


if __name__ == "__main__":
    main()

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
    "license_gate.py",
]


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

    # 4. i18n messages
    msgs = ROOT / "messages"
    if msgs.is_dir():
        for j in msgs.glob("*.json"):
            shutil.copy2(j, PKG / "messages" / j.name)
            print(f"  + tokengram/messages/{j.name}")


def build_wheel() -> Path:
    step("Build wheel (python -m build --wheel)")
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
    args = parser.parse_args()

    if not args.skip_compile_check:
        ensure_compiled()
    populate_package()
    wheel = build_wheel()
    if args.upload:
        upload(wheel)


if __name__ == "__main__":
    main()

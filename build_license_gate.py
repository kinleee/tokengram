# =============================================================================
#  PROPRIETARY & CONFIDENTIAL — Tokengram.  Copyright (c) Ilkin Humbatov.
#  All rights reserved.  This is NOT open-source software.
# =============================================================================
"""build_license_gate.py — compile the license-enforcement gate to a .pyd.

    python build_license_gate.py

Why this exists
---------------
`license_gate` is the only hook shipped COMPILED. Every other hook is invoked by
Claude Code as a script and must stay .py, but `license_gate` is import-only and
holds the enforcement gate — shipping it as plaintext let an AI read and explain
how to disable it. This script compiles `hooks/license_gate.py` and deploys the
resulting `license_gate.*.pyd` into the two SHIPPED trees:

    tokengram/hooks/                      (the wheel — install_hooks_locally copies it)
    vscode-extension/resources/hooks/     (the VSIX bundle — ensureGlobalHooks copies it)

removing the plaintext `license_gate.py` from BOTH. The editable source stays at
`hooks/license_gate.py` (dev only — never shipped). Run this after editing the
gate, before building the wheel.

The compile is done in a temp dir so it never drops a .c next to the source, and
it touches no other .pyd — `license_gate` is never loaded by the MCP server, so a
running server does not block this build.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "hooks" / "license_gate.py"
SHIPPED_HOOK_DIRS = [
    ROOT / "tokengram" / "hooks",
    ROOT / "vscode-extension" / "resources" / "hooks",
]
DIRECTIVES = {
    "language_level": "3",
    "embedsignature": True,
    "binding": True,
    "always_allow_keywords": True,
}


def _build_pyd(workdir: Path) -> Path:
    from setuptools import setup
    from Cython.Build import cythonize

    shutil.copy2(SRC, workdir / "license_gate.py")
    argv_saved = sys.argv
    sys.argv = ["setup_license_gate", "build_ext", "--inplace"]
    cwd_saved = Path.cwd()
    try:
        import os
        os.chdir(workdir)
        setup(
            name="tokengram-license-gate",
            ext_modules=cythonize(
                ["license_gate.py"], compiler_directives=DIRECTIVES, annotate=False, nthreads=0
            ),
            zip_safe=False,
        )
    finally:
        sys.argv = argv_saved
        import os
        os.chdir(cwd_saved)

    pyds = list(workdir.glob("license_gate.*.pyd")) + list(workdir.glob("license_gate.*.so"))
    if not pyds:
        print("ERROR: build produced no license_gate.*.pyd/.so", file=sys.stderr)
        sys.exit(1)
    return pyds[0]


def main() -> None:
    if not SRC.exists():
        print(f"ERROR: source not found: {SRC}", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        pyd = _build_pyd(Path(tmp))
        print(f"built: {pyd.name} ({pyd.stat().st_size / 1024:.1f} KB)")

        for d in SHIPPED_HOOK_DIRS:
            if not d.exists():
                print(f"  SKIP (missing): {d}")
                continue
            shutil.copy2(pyd, d / pyd.name)
            stale_py = d / "license_gate.py"
            if stale_py.exists():
                stale_py.unlink()
            print(f"  deployed .pyd + removed plaintext .py -> {d}")

    print("\nDone. Now rebuild the wheel (python -m build) so it ships the compiled gate.")


if __name__ == "__main__":
    main()

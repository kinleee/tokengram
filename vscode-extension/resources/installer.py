#!/usr/bin/env python3
"""Tokengram installer — cross-platform setup of ~/.tokengram/venv + tokengram package.

Invoked by the VS Code extension's setup wizard. Streams progress to stdout
line-by-line so the extension can render it in the webview log.

Stdlib-only — no third-party imports at install time.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

MIN_PY = (3, 12)


def log(msg: str) -> None:
    print(msg, flush=True)


def fail(msg: str, code: int = 1) -> None:
    print(f"[error] {msg}", flush=True)
    sys.exit(code)


def check_python() -> None:
    if sys.version_info[:2] < MIN_PY:
        fail(
            f"Python {MIN_PY[0]}.{MIN_PY[1]}+ required; this is {sys.version_info.major}.{sys.version_info.minor}",
        )
    log(f"[1/5] Python {sys.version.split()[0]} on {platform.system()} {platform.machine()}")


def ensure_tokengram_home(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    log(f"[2/5] Tokengram home: {home}")


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def venv_pip(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "pip.exe"
    return venv / "bin" / "pip"


def create_venv(venv: Path) -> None:
    if venv_python(venv).exists():
        log(f"[3/5] venv already exists at {venv}, reusing")
        return
    log(f"[3/5] Creating venv at {venv}...")
    subprocess.check_call([sys.executable, "-m", "venv", str(venv)])


def upgrade_pip(venv: Path) -> None:
    # Don't pass --quiet here: the wizard listens for progress lines, and a
    # silent pip upgrade leaves the user staring at a blank notification for
    # 5–10 seconds wondering if anything is happening.
    log("[3/5] Upgrading pip inside venv (a few seconds)...")
    subprocess.check_call(
        [str(venv_python(venv)), "-m", "pip", "install", "--upgrade", "pip"],
    )


def install_tokengram(venv: Path, source: str | None) -> None:
    pip = str(venv_pip(venv))
    # Force-uninstall first so an old .pyd that pip's --upgrade silently skips
    # on Windows (file-lock + caching edge cases) cannot survive into the new
    # install. The fresh install below puts every file back from the wheel.
    log("[4/5] Removing any previous tokengram install...")
    try:
        subprocess.check_call(
            [pip, "uninstall", "tokengram", "-y"],
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError:
        pass  # not installed yet — fine, fall through to install
    if source:
        log(f"[4/5] Installing tokengram package from bundled wheel: {Path(source).name}")
        subprocess.check_call([pip, "install", "--force-reinstall", "--no-deps", source])
        # --no-deps because deps haven't changed and reinstalling them is slow.
        # Run a second pass with deps to make sure missing ones do get installed
        # (no-deps would skip first-time install of dependencies).
        log("[4/5] Resolving and downloading dependencies (~300 MB on first install)...")
        subprocess.check_call([pip, "install", source])
    else:
        log("[4/5] Installing tokengram from PyPI...")
        subprocess.check_call([pip, "install", "--force-reinstall", "--no-deps", "tokengram"])
        log("[4/5] Resolving and downloading dependencies (~300 MB on first install)...")
        subprocess.check_call([pip, "install", "tokengram"])


def install_hooks_locally(venv: Path, home: Path) -> None:
    """Copy hooks/ from the installed package into ~/.tokengram/hooks/.

    Claude Code expects to spawn hook scripts by absolute path. We expose them
    at a stable location so .claude/settings.json doesn't break when the venv
    re-creates wheel paths.
    """
    log("[5/5] Installing hook scripts to ~/.tokengram/hooks ...")
    py = str(venv_python(venv))
    locate = (
        "import importlib.util,json,pathlib;"
        "spec=importlib.util.find_spec('tokengram');"
        "p=pathlib.Path(spec.submodule_search_locations[0]) if spec else None;"
        "print(json.dumps(str(p)) if p else 'null')"
    )
    out = subprocess.check_output([py, "-c", locate], text=True).strip()
    if out == "null":
        log("[5/5] tokengram module not found after install; skipping hook copy")
        return
    pkg_root = Path(json.loads(out))
    src_hooks = pkg_root / "hooks"
    if not src_hooks.exists():
        log(f"[5/5] no hooks/ directory in package at {pkg_root}; skipping")
        return
    dst_hooks = home / "hooks"
    if dst_hooks.exists():
        shutil.rmtree(dst_hooks)
    shutil.copytree(src_hooks, dst_hooks)
    log(f"[5/5] Hooks copied to {dst_hooks}")


def write_marker(home: Path) -> None:
    marker = home / "install.json"
    marker.write_text(
        json.dumps(
            {
                "installed_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                "python": sys.executable,
                "platform": platform.platform(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tokengram-home",
        default=str(Path.home() / ".tokengram"),
        help="Where to create venv + hooks (default: ~/.tokengram)",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Install tokengram from this local path/wheel instead of PyPI (dev only)",
    )
    args = parser.parse_args()

    home = Path(args.tokengram_home).expanduser()
    venv = home / "venv"

    check_python()
    ensure_tokengram_home(home)
    create_venv(venv)
    upgrade_pip(venv)
    install_tokengram(venv, args.source)
    install_hooks_locally(venv, home)
    write_marker(home)
    log("done")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        fail(f"subprocess failed: {e}", e.returncode or 1)
    except urllib.error.URLError as e:
        fail(f"network error: {e}")

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
import threading
import urllib.error
import urllib.request
from pathlib import Path

# Wheel cp312-only kompayl olunub; cp313 .pyd hazır olana qədər EXACT 3.12.
# 3.13 install üçün ayrı cp313 .pyd build pipeline-i lazımdır.
REQUIRED_PY = (3, 12)

# Windows-da stdout/stderr pipe olunanda default cp1252 olur; Azərbaycan hərfli
# log sətirləri ('ə' və s.) UnicodeEncodeError ilə bütün install-i çökdürür.
# UTF-8-ə keçir (hooks-da olduğu kimi) — yoxsa migrate/log sətirləri fail edir.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


# Persistent transcript — tester-in maşınında xəta ötəri output channel-da
# itməsin deyə HƏR install bütün stdout + pip stderr-i bura yazır. "Setup did
# not complete" olanda tester bu faylı göndərir → real səbəb dəqiqləşir.
_LOG_FH = None
_LOG_PATH = None


def _init_log(home: Path) -> None:
    global _LOG_FH, _LOG_PATH
    import datetime as _dt

    try:
        home.mkdir(parents=True, exist_ok=True)
        _LOG_PATH = home / "install.log"
        _LOG_FH = open(_LOG_PATH, "w", encoding="utf-8")
        stamp = _dt.datetime.now(_dt.timezone.utc).isoformat()
        _LOG_FH.write(f"# Tokengram install log — {stamp}\n")
        _LOG_FH.write(f"# launcher python: {sys.executable} ({sys.version.split()[0]})\n")
        _LOG_FH.write(f"# platform: {platform.platform()}\n\n")
        _LOG_FH.flush()
    except OSError:
        _LOG_FH = None


def _log_raw(line: str) -> None:
    if _LOG_FH is not None:
        try:
            _LOG_FH.write(line + "\n")
            _LOG_FH.flush()
        except OSError:
            pass


def log(msg: str) -> None:
    print(msg, flush=True)
    _log_raw(msg)


def fail(msg: str, code: int = 1) -> None:
    line = f"[error] {msg}"
    print(line, flush=True)
    _log_raw(line)
    if _LOG_PATH is not None:
        hint = f"[error] Full log: {_LOG_PATH}"
        print(hint, flush=True)
        _log_raw(hint)
    sys.exit(code)


def _run(args: list, timeout: int | None = None) -> None:
    """Subprocess-i işə sal; birləşmiş stdout+stderr-i HƏM stdout-a (extension
    progress oxuyur) HƏM install.log-a ötür. Non-zero exit-də CalledProcessError
    atır ki, main()-in handler-i bildirsin. Pip-in əsl xətası beləcə log-da qalır.
    """
    printable = " ".join(str(a) for a in args)
    _log_raw(f"$ {printable}")
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            print(line, flush=True)
            _log_raw(line)
        ret = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    if ret != 0:
        raise subprocess.CalledProcessError(ret, args)


def check_python() -> None:
    actual = sys.version_info[:2]
    if actual != REQUIRED_PY:
        fail(
            f"Tokengram requires Python {REQUIRED_PY[0]}.{REQUIRED_PY[1]}.x — this is "
            f"{actual[0]}.{actual[1]}. Download 3.12 from "
            f"https://www.python.org/downloads/release/python-3128/ "
            f"(install, then re-run Tokengram setup). Python 3.13 support is coming in the next release.",
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


def _venv_python_version(venv: Path) -> tuple[int, int] | None:
    """Mövcud venv-in Python major.minor-unu qaytar; mövcud deyilsə None."""
    py = venv_python(venv)
    if not py.exists():
        return None
    try:
        out = subprocess.check_output(
            [str(py), "-c", "import sys;print(sys.version_info[0]);print(sys.version_info[1])"],
            text=True, timeout=10,
        ).strip().splitlines()
        return (int(out[0]), int(out[1]))
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError):
        return None


def create_venv(venv: Path, uv: str | None) -> None:
    existing = _venv_python_version(venv)
    if existing == REQUIRED_PY:
        log(f"[3/5] venv already exists at {venv} (Python {existing[0]}.{existing[1]}), reusing")
        return
    # Yenidən-qurma lazımdır əgər (a) köhnə venv başqa Python ilə yaranıb VƏ YA
    # (b) venv qovluğu mövcuddur amma python.exe YOXDUR/işləmir (existing is None).
    # (b) halı KRİTİK: antivirus venv-in python.exe-ni karantinə ala bilər → qovluq
    # qalır (tokengram.exe + site-packages), python.exe yox. Belə qalıq qovluğa qarşı
    # `uv venv` exit 2 verir ("A virtual environment already exists ... --clear")
    # → python.exe HEÇ yaranmır → install hər dəfə eyni yerdə sınır. Qalıq qovluğu
    # əvvəlcə tam silirik ki, təmiz lövhədən qurulsun (canlı doğrulandı 2026-06-19).
    if venv.exists() and existing != REQUIRED_PY:
        reason = (
            f"Python {existing[0]}.{existing[1]}" if existing is not None
            else "partial/broken (python.exe missing)"
        )
        log(f"[3/5] Existing venv is {reason}, rebuilding for {REQUIRED_PY[0]}.{REQUIRED_PY[1]}...")
        try:
            shutil.rmtree(venv)
        except OSError as e:
            fail(f"could not remove old venv at {venv}: {e}. Close VS Code and try again.")
    log(f"[3/5] Creating venv at {venv}...")
    if uv:
        # uv özü 3.12-ni provision edir (sistemdə yoxdursa standalone endirir) —
        # user-də heç bir Python olmasa belə işləyir. Bu, "Python 3.12 yoxdur"
        # problemini tamamilə aradan qaldırır. `--clear`: rmtree kilidli fayl üzündən
        # alınmasa belə uv qalıq qovluğu özü təmizləsin (idempotent sığorta).
        _run([uv, "venv", "--clear", "--python", "3.12", str(venv)])
    else:
        _run([sys.executable, "-m", "venv", "--clear", str(venv)])


def upgrade_pip(venv: Path, uv: str | None) -> None:
    # uv rejimində venv-də pip yoxdur (uv pip öz resolver-i ilə işləyir) —
    # pip upgrade lazım deyil və mənasızdır.
    if uv:
        return
    # Don't pass --quiet here: the wizard listens for progress lines, and a
    # silent pip upgrade leaves the user staring at a blank notification for
    # 5–10 seconds wondering if anything is happening.
    log("[3/5] Upgrading pip inside venv (a few seconds)...")
    _run([str(venv_python(venv)), "-m", "pip", "install", "--upgrade", "pip"])


_PIP_NET_FLAGS = ["--retries", "5", "--timeout", "60"]
_PIP_TIMEOUT_SEC = 900  # 15 dəq — uzun depend tree + slow proxy üçün


def _pip_run(args: list[str]) -> None:
    """Pip-i timeout + retry flag-ləri ilə çağır.

    --retries 5 --timeout 60 → şəbəkə qısa kəsilməsində avtomatik retry.
    process timeout=900 → tam hang olsa user-i 15 dəq sonra azad et.
    """
    _run(args + _PIP_NET_FLAGS, timeout=_PIP_TIMEOUT_SEC)


# Fresh install-da deps (chromadb + onnxruntime + fastembed + mcp + asılılıqlar)
# venv-ə təxminən bu qədər bayt yazır. torch + transformers + sentence-transformers
# (~491MB torch + asılılıqlar) SİLİNDİ → fastembed onnxruntime-i təkrar istifadə
# edir; venv böyüməsi ~1.25 GB-dan ~600 MB-a düşür. Yalnız barın dolma sürətini
# kalibrləyir — az/çox təxmin düzgünlüyü pozmur.
_DEPS_TARGET_BYTES = 600_000_000


def _dir_size(path: Path) -> int:
    """Qovluğun ümumi ölçüsü (rekursiv, symlink-siz). Xətalar səssiz keçilir —
    install gedərkən fayllar yaranıb-silindiyi üçün race normaldır."""
    total = 0
    stack = [str(path)]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def _monitor_deps_progress(venv: Path, stop: threading.Event) -> None:
    """Arxa fonda: uv deps yığarkən venv-in disk böyüməsini ölçüb hər ~0.8s-də
    `[DL] <yazılan_bayt> <hədəf_bayt>` sətri yazır. Extension bunu real faizə
    çevirir (vaxta görə təxmin deyil). Səhvlər install-i pozmamalıdır → hamısı
    səssiz tutulur, thread daemon-dur."""
    try:
        base = _dir_size(venv)
    except Exception:
        base = 0
    while not stop.is_set():
        try:
            done = _dir_size(venv) - base
            if done < 0:
                done = 0
            sys.stdout.write(f"[DL] {done} {_DEPS_TARGET_BYTES}\n")
            sys.stdout.flush()
        except Exception:
            pass
        stop.wait(0.8)


def install_tokengram(venv: Path, source: str | None, uv: str | None) -> None:
    if uv:
        vpy = str(venv_python(venv))
        target = source if source else "tokengram"
        label = Path(source).name if source else "tokengram (PyPI)"
        log(f"[4/5] Installing tokengram package: {label}")
        log("[4/5] Resolving and downloading dependencies (~300 MB on first install)...")
        # uv pip wheel + bütün asılılıqları bir əmrdə resolve+install edir;
        # pip-dən xeyli sürətli və 300MB timeout riskini azaldır. --reinstall
        # köhnə .pyd-in qalmasının qarşısını alır.
        # Yan thread venv böyüməsini ölçüb `[DL]` sətirləri yazır ki, wizard
        # real faiz göstərsin (uv pipe-da per-bayt progress vermir).
        stop = threading.Event()
        monitor = threading.Thread(
            target=_monitor_deps_progress, args=(venv, stop), daemon=True
        )
        monitor.start()
        try:
            _run(
                [uv, "pip", "install", "--python", vpy, "--reinstall", target],
                timeout=_PIP_TIMEOUT_SEC,
            )
        finally:
            stop.set()
            monitor.join(timeout=2)
        return

    pip = str(venv_pip(venv))
    # Force-uninstall first so an old .pyd that pip's --upgrade silently skips
    # on Windows (file-lock + caching edge cases) cannot survive into the new
    # install. The fresh install below puts every file back from the wheel.
    log("[4/5] Removing any previous tokengram install...")
    # Uninstall: stderr ayrıca tut ki, "not installed" ilə real "in use" lock
    # error-larını fərqləndirə bilək (köhnə kod hər iki halı silentd örtürdü).
    try:
        _run([pip, "uninstall", "tokengram", "-y"], timeout=120)
    except subprocess.CalledProcessError as e:
        log(f"[4/5] uninstall exited with {e.returncode} (ehtimal: yox idi) — install-ə davam")
    except subprocess.TimeoutExpired:
        log("[4/5] uninstall timeout — install-ə davam (file-lock ola bilər)")

    if source:
        log(f"[4/5] Installing tokengram package from bundled wheel: {Path(source).name}")
        _pip_run([pip, "install", "--force-reinstall", "--no-deps", source])
        # --no-deps because deps haven't changed and reinstalling them is slow.
        # Run a second pass with deps to make sure missing ones do get installed
        # (no-deps would skip first-time install of dependencies).
        log("[4/5] Resolving and downloading dependencies (~300 MB on first install)...")
        _pip_run([pip, "install", source])
    else:
        log("[4/5] Installing tokengram from PyPI...")
        _pip_run([pip, "install", "--force-reinstall", "--no-deps", "tokengram"])
        log("[4/5] Resolving and downloading dependencies (~300 MB on first install)...")
        _pip_run([pip, "install", "tokengram"])


def predownload_embedding_model(venv: Path) -> None:
    """Embedding modelini setup zamanı ONLINE endir (HF cache-ə yaz).

    Reindex runtime-da `HF_HUB_OFFLINE=1` ilə işləyir (worker hang qarşısı) —
    yəni model əvvəlcədən cache-də OLMALIDIR, yoxsa embedding boş keçir və
    baza boş qalır (səssiz uğursuzluq). Burada online endiririk.

    Symlink xəbərdarlığı söndürülür (Windows-da Developer Mode yoxdursa HF
    copy ilə işləyir — symlink lazım deyil). Uğursuz olsa install dayanmır:
    runtime-da `_ensure_loaded` ehtiyat online fallback edir.
    """
    log("[5/5] Pre-downloading embed + rerank models (~220 MB, one-time)...")
    py = str(venv_python(venv))
    env = dict(os.environ)
    # Online məcburi (offline bayraqlarını sil) + symlink xəbərdarlığını sus
    env.pop("HF_HUB_OFFLINE", None)
    env.pop("TRANSFORMERS_OFFLINE", None)
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    env["TRANSFORMERS_VERBOSITY"] = "error"
    # fastembed (ONNX) — hər iki modeli cache-ə endir: bge-small (embed) +
    # ms-marco (rerank). torch YOX → endirmə də, RAM da xeyli azdır.
    code = (
        "from tokengram import config;"
        "from fastembed import TextEmbedding;"
        "from fastembed.rerank.cross_encoder import TextCrossEncoder;"
        "list(TextEmbedding(model_name=config.EMBEDDING_MODEL_NAME).embed(['warmup']));"
        "list(TextCrossEncoder(model_name=config.RERANKER_MODEL_NAME).rerank('warmup', ['doc']));"
        "print('models cached')"
    )
    try:
        subprocess.run(
            [py, "-c", code], env=env, timeout=600, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        log("[5/5] Embed + rerank models cached OK")
    except Exception as e:
        # Non-fatal: runtime fallback modeli ilk reindex-də endirəcək.
        log(f"[5/5] Model pre-download keçildi (runtime fallback edəcək): {e}")


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

    # Hooks `mla_constants` / `i18n`-i top-level modul kimi ~/.tokengram/-dan
    # import edir (sys.path-ə hooks/-un parent-ını əlavə edirlər). Wheel-də
    # bunlar yalnız paket içində compiled .pyd kimi olur — ona görə onları
    # (və i18n-in runtime-da oxuduğu messages/ qovluğunu) hooks/-un yanına
    # köçürürük. Bu olmasa təmiz maşında hər hook ModuleNotFoundError ilə çökür.
    for stem in ("mla_constants", "i18n"):
        copied = False
        for match in pkg_root.glob(f"{stem}.*"):
            if match.suffix.lower() in (".py", ".pyd", ".so"):
                shutil.copy2(match, home / match.name)
                copied = True
        if not copied:
            log(f"[5/5] warning: '{stem}' module not found in package at {pkg_root}")
    src_messages = pkg_root / "messages"
    if src_messages.exists():
        dst_messages = home / "messages"
        if dst_messages.exists():
            shutil.rmtree(dst_messages)
        shutil.copytree(src_messages, dst_messages)
    log(f"[5/5] Constants + i18n + messages copied to {home}")


def migrate_legacy_mla_dir(home: Path) -> None:
    """Köhnə ~/.mla/ qovluğundan license key / pubkey / server_url-i
    yeni ~/.tokengram/-a köçür (rebrand birləşməsi).

    Yalnız hədəf fayl yoxdursa kopyalanır — user-in son yenilədiyi fayl
    silinmir. Source fayl bütöv qalır (manual cleanup user-ın seçimi).
    """
    legacy = Path.home() / ".mla"
    if not legacy.exists() or legacy.resolve() == home.resolve():
        return
    home.mkdir(parents=True, exist_ok=True)
    moved = []
    # Yalnız açarı köçür. server_url.txt + pubkey.pem köhnə ~/.mla-da çox vaxt
    # ölü serverə (park olunmuş domen / stale Cloudflare worker) işarə edir və
    # düzgün default-u əzərdi → activation "network_error/rejected" verirdi.
    # Onlar cari serverə qarşı yenidən yazılır (write_server_url + fetchPubkey).
    for name in ("license_key.txt",):
        src = legacy / name
        dst = home / name
        if src.exists() and not dst.exists():
            try:
                shutil.copy2(src, dst)
                moved.append(name)
            except OSError:
                pass
    if moved:
        log(f"[migrate] Köhnə ~/.mla/-dan köçürüldü: {', '.join(moved)}")


# Lisenziya serverinin canonical URL-i. Tək mənbə — extension/MCP heç vaxt köhnə
# ~/.mla dəyərinə və ya səhv default-a düşməsin deyə hər install bunu yazır.
LICENSE_SERVER_URL = "https://tokengram.click"


def write_server_url(home: Path) -> None:
    """~/.tokengram/server_url.txt-i canonical URL-ə sabitlə (köhnə/stale dəyəri əz)."""
    try:
        (home / "server_url.txt").write_text(LICENSE_SERVER_URL, encoding="utf-8")
        log(f"[setup] server_url.txt -> {LICENSE_SERVER_URL}")
    except OSError as e:
        log(f"[setup] server_url.txt yazıla bilmədi: {e}")


def write_marker(home: Path) -> None:
    import datetime as _dt
    marker = home / "install.json"
    # 3.12+ datetime.utcnow() deprecation warning verir; UTC explicit.
    now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")
    marker.write_text(
        json.dumps(
            {
                "installed_at": now_iso,
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
    parser.add_argument(
        "--uv",
        default=None,
        help="Path to uv.exe — when set, uv provisions Python 3.12 + venv + install "
        "(user needs no preinstalled Python). Without it, falls back to system venv+pip.",
    )
    args = parser.parse_args()

    home = Path(args.tokengram_home).expanduser()
    venv = home / "venv"
    uv = args.uv or None

    _init_log(home)
    if uv:
        log(f"[0/5] uv mode: {uv}")
    check_python()
    ensure_tokengram_home(home)
    migrate_legacy_mla_dir(home)
    write_server_url(home)
    create_venv(venv, uv)
    upgrade_pip(venv, uv)
    install_tokengram(venv, args.source, uv)
    predownload_embedding_model(venv)
    install_hooks_locally(venv, home)
    write_marker(home)
    log("done")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        fail(f"subprocess failed (see lines above for the real pip/venv error): {e}", e.returncode or 1)
    except subprocess.TimeoutExpired as e:
        fail(f"step timed out after {e.timeout:.0f}s — slow/blocked network or stuck download: {e.cmd}")
    except urllib.error.URLError as e:
        fail(f"network error: {e}")
    except Exception as e:  # son qalxan: hər hal log-a düşsün
        import traceback

        _log_raw(traceback.format_exc())
        fail(f"unexpected error: {type(e).__name__}: {e}")

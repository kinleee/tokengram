"""
make_distribution.py — Cython hybrid distribution paketi qurur.

İcra:
    python make_distribution.py

Çıxış: ./dist/mla-agent-vX.Y.Z/  (Windows-da; Linux/Mac-də ayrıca build lazımdır)

Daxili strukturu:
    mcp_server.cp312-win_amd64.pyd      ← bizim biznes logic (compiled)
    license.cp312-win_amd64.pyd         ← license check (compiled)
    search_engine.cp312-win_amd64.pyd   ← hybrid search (compiled)
    vector_store.cp312-win_amd64.pyd    ← chromadb wrapper (compiled)
    document_loader.cp312-win_amd64.pyd ← chunkers (compiled)
    smart_router.cp312-win_amd64.pyd    ← router (compiled)

    config.py                            ← sabitlər, sensitive deyil
    mla_constants.py                     ← sabitlər
    main.py                              ← CLI entry (sensitive deyil, .pyd-i çağırır)
    hooks/                               ← Claude Code shell tərəfindən çağırılır

    requirements.txt                     ← üçüncü tərəf deps (chromadb, sentence-transformers, etc.)
    .mcp.json                            ← Claude Code config
    README_SETUP.md                      ← iş yoldaşı təlimatı

Distribution-da bizim 6 modulun .py mənbəyi DAXİL EDİLMİR — yalnız .pyd.
Üçüncü tərəf paketlər colleague-ın pip install ilə qurulur (requirements.txt).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# Windows-da Azərbaycan dilli print üçün stdout-u UTF-8-ə keçir
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

VERSION = "0.1.0-alpha"
PROJECT_ROOT = Path(__file__).parent
DIST_ROOT = PROJECT_ROOT / "dist" / f"mla-agent-{VERSION}"

# 13 fayl — Cython ilə .pyd-ə kompil olunur, mənbə .py DAXİL EDİLMİR.
# 2026-05-14: əvvəl 7 idi (core), tester paket açanda 6 ek orchestration faylı
# açıq görsənirdi (IP leakage) — bunlar da əlavə olundu.
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

# 2026-05-14: əvvəlki hamı .pyd-ə keçirildi (bax: setup_cython.py MODULES).
# Yalnız run_mcp_server.py qaldı — 4 sətirlik wrapper, .pyd kimi compile etmək məntiqsiz.
INCLUDED_PY_FILES = [
    "run_mcp_server.py",
]

# Bütöv qovluqlar paketə daxil edilir
INCLUDED_DIRS = [
    "hooks",   # Claude Code shell-dən çağırır, .py qalmalıdır
]

# Konfiqurasiya faylları
INCLUDED_CONFIG = [
    "requirements.txt",
    ".mcp.json.binary",   # → distribution-da .mcp.json olaraq adlandırılacaq
    "install.ps1",
]


def step(msg: str) -> None:
    print(f"\n=== {msg} ===")


def build_cython(force: bool = False) -> None:
    """Cython rebuild — əgər .pyd-lər artıq mövcuddur və --force verilməyibsə skip et.

    Access-denied problem: bir Python prosesi (məs. yaşayan MCP server) .pyd-ni
    load edibsə overwrite edilə bilməz. Bu halda mövcud .pyd-lər istifadə olunur.
    """
    have_all = all(
        list(PROJECT_ROOT.glob(f"{stem}.*.pyd")) or
        list((PROJECT_ROOT / "dist_compiled").glob(f"{stem}.*.pyd"))
        for stem in COMPILED_MODULES
    )
    if have_all and not force:
        step("Cython build (SKIP — .pyd-lər artıq mövcuddur)")
        print("  --force ilə yenidən build edə bilərsən")
        return

    step("Cython modulları build edilir")
    result = subprocess.run(
        [sys.executable, "setup_cython.py", "build_ext", "--inplace"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("setup_cython.py STDERR:", result.stderr[-2000:])
        sys.exit(1)
    print("Cython build OK")


def find_pyd_files() -> list[Path]:
    """Build-dən sonra yaranan .pyd fayllarını root-da və dist_compiled/-də axtar."""
    pyds: list[Path] = []
    for stem in COMPILED_MODULES:
        candidates = list(PROJECT_ROOT.glob(f"{stem}.*.pyd"))
        if not candidates:
            candidates = list((PROJECT_ROOT / "dist_compiled").glob(f"{stem}.*.pyd"))
        if not candidates:
            print(f"XƏTA: {stem}.*.pyd tapılmadı", file=sys.stderr)
            sys.exit(1)
        pyds.append(candidates[0])
    return pyds


def prepare_dist_dir() -> None:
    step(f"Distribution qovluğu hazırlanır: {DIST_ROOT}")
    if DIST_ROOT.exists():
        shutil.rmtree(DIST_ROOT)
    DIST_ROOT.mkdir(parents=True)


def copy_pyd_files(pyd_files: list[Path]) -> None:
    step("Compiled .pyd faylları kopyalanır")
    for src in pyd_files:
        dst = DIST_ROOT / src.name
        shutil.copy2(src, dst)
        print(f"  {src.name}  ({src.stat().st_size / 1024:.1f} KB)")


def copy_included_py_files() -> None:
    step("Sensitive olmayan .py faylları kopyalanır")
    for name in INCLUDED_PY_FILES:
        src = PROJECT_ROOT / name
        if not src.exists():
            print(f"  ATLANIR: {name} (tapılmadı)")
            continue
        shutil.copy2(src, DIST_ROOT / name)
        print(f"  {name}")


def copy_included_dirs() -> None:
    step("Bütöv qovluqlar kopyalanır")
    for name in INCLUDED_DIRS:
        src = PROJECT_ROOT / name
        if not src.exists():
            print(f"  ATLANIR: {name}/ (tapılmadı)")
            continue
        shutil.copytree(
            src,
            DIST_ROOT / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        print(f"  {name}/")


def copy_config_files() -> None:
    step("Konfiqurasiya faylları kopyalanır")
    for name in INCLUDED_CONFIG:
        src = PROJECT_ROOT / name
        if not src.exists():
            print(f"  ATLANIR: {name} (tapılmadı)")
            continue
        # .mcp.json.binary → .mcp.json
        dst_name = ".mcp.json" if name == ".mcp.json.binary" else name
        shutil.copy2(src, DIST_ROOT / dst_name)
        print(f"  {name} → {dst_name}")


def copy_vsix() -> None:
    """vscode-extension/*.vsix-i distribution-a daxil et — installer onu install edə bilsin."""
    step("VSCode extension .vsix daxil edilir")
    vsix_dir = PROJECT_ROOT / "vscode-extension"
    vsix_files = sorted(vsix_dir.glob("*.vsix"))
    if not vsix_files:
        print("  ATLANIR: .vsix tapılmadı (vscode-extension/ qovluğunda yoxdur)")
        return
    src = vsix_files[-1]   # son versiya
    shutil.copy2(src, DIST_ROOT / src.name)
    print(f"  {src.name}  ({src.stat().st_size / 1024:.1f} KB)")


def write_setup_readme() -> None:
    step("README_SETUP.md yazılır")
    readme = DIST_ROOT / "README_SETUP.md"
    readme.write_text(
        f"""# MLA Agent {VERSION} — Internal Alpha

## Sürətli quraşdırma (1 komanda)

PowerShell aç, bu qovluğa keç, sonra:

```powershell
.\\install.ps1 -ProjectPath C:\\your\\project -LicenseKey mla_live_xxxxxxxx -PublicKeyPath .\\mla_pubkey.pem
```

Bu skript:
- Python 3.12 mövcudluğunu yoxlayır
- Virtual environment yaradır + `requirements.txt`-i quraşdırır (~2-3 dəq)
- `~/.mla/` qovluğunu hazırlayır (license_key.txt, server_url.txt, pubkey.pem)
- Layihə qovluğuna `.mcp.json` yerləşdirir
- VSCode extension-ı (`*.vsix`) install edir

Sonra **Claude Code-u yenidən başlat**.

## Manual quraşdırma (skriptə güvənmirsənsə)

1. `python -m venv venv` və `.\\venv\\Scripts\\pip install -r requirements.txt`
2. `~/.mla/license_key.txt`, `~/.mla/server_url.txt`, `~/.mla/pubkey.pem` yerləşdir
3. `.mcp.json`-u öz layihə qovluğuna kopyalat (PYTHONPATH-i düzəlt)
4. `code --install-extension mla-agent-*.vsix`

## Daxili strukturu

- `*.pyd` — kompil edilmiş biznes modulları (mənbə kodu açıq deyil)
- `config.py`, `main.py`, `hooks/` — yardımçı fayllar
- `install.ps1` — PowerShell installer
- `requirements.txt` — açıq Python paketləri (chromadb, sentence-transformers)
- `.mcp.json` — Claude Code MCP server config şablonu
- `mla-agent-*.vsix` — VSCode extension paketi

## Tələblər

- Windows 10/11
- Python 3.12 (digər versiyada .pyd işləməyəcək)
- VSCode 1.85+ (extension üçün)
- Claude Code quraşdırılmış
- İnternet (ilk activation + ilk axtarışda model download ~500 MB)

## Problem həlli

- `python --version` Python 3.12 göstərməlidir.
- `requirements.txt` install 2-3 dəq çəkir (chromadb + torch heavy).
- İlk axtarış ML modeli download edir (~500 MB), bir-iki dəq.
- Status bar boşdursa: VSCode-da `Ctrl+Shift+P` → "MLA: Open menu" → "Refresh status bar"

## Feedback

n.ilkin.humbatov@gmail.com
""",
        encoding="utf-8",
    )
    print(f"  {readme.name}")


def write_dist_zip() -> None:
    step("Zip arxivi yaradılır")
    zip_path = DIST_ROOT.parent / f"mla-agent-{VERSION}-win64-py312.zip"
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(
        str(zip_path.with_suffix("")),
        "zip",
        root_dir=DIST_ROOT.parent,
        base_dir=DIST_ROOT.name,
    )
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  {zip_path.name}  ({size_mb:.2f} MB)")


def main() -> None:
    print(f"MLA Agent distribution build — version {VERSION}")
    print(f"Platform: Windows x86_64, Python 3.12")

    force_build = "--force" in sys.argv
    build_cython(force=force_build)
    pyd_files = find_pyd_files()
    prepare_dist_dir()
    copy_pyd_files(pyd_files)
    copy_included_py_files()
    copy_included_dirs()
    copy_config_files()
    copy_vsix()
    write_setup_readme()
    write_dist_zip()

    print(f"\n✓ Distribution hazırdır: {DIST_ROOT}")
    print(f"  Ümumi ölçü: {sum(f.stat().st_size for f in DIST_ROOT.rglob('*') if f.is_file()) / (1024 * 1024):.2f} MB")


if __name__ == "__main__":
    main()

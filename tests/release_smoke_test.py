"""Release smoke test (S1 — launch plan). HƏR release-dən əvvəl hazır wheel üzərində işlədilir.

Run:
    python tests/release_smoke_test.py dist/tokengram-X.Y.Z-py3-none-any.whl
    python tests/release_smoke_test.py dist/tokengram-*.whl --venv C:/path/to/venv/Scripts/python.exe

Nəyi yoxlayır (R1 boşluğunun regressiyasını sinif olaraq bağlayır):
  1. STATİK: wheel-də yalnız icazəli .py faylları var — bütün biznes məntiqi
     (license daxil) compiled olmalıdır. license.py .py kimi ship olunsa,
     dev-mode bypass-ı geri qayıdır və məhsul "işlədiyi" üçün heç kim görməz.
  2. STATİK: tokengram/license compiled artefaktı (.pyd/.so) mövcuddur.
  3. RUNTIME (--venv verilsə): wheel quraşdırılmış interpreter-də təmiz HOME +
     TOKENGRAM_DEV_MODE=1 ilə açarsız axın dev mode QAYTARMIR — trial axınına
     gedir (əlçatmaz server → LicenseError). None qayıdırsa, bypass sızıb.

Exit code: 0 = PASS, 1 = FAIL.
"""
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# Windows konsolu default cp1252 — AZ hərfləri printdə çökdürür (installer-dəki
# eyni fix). errors="replace": ən pis halda hərf itir, test çökmür.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Wheel-də .py kimi qalmasına icazə verilən fayllar — mövcud source-protection
# auditi ilə eyni siyahı: MCP stdio shim + hooks (Claude Code .py tələb edir).
ALLOWED_PY = ("tokengram/__init__.py", "tokengram/__main__.py", "tokengram/server.py")
ALLOWED_PY_PREFIXES = ("tokengram/hooks/",)


def fail(msg: str) -> None:
    print(f"SMOKE FAIL: {msg}")
    sys.exit(1)


def static_audit(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()

    py_files = [n for n in names if n.endswith(".py")]
    bad = [
        n for n in py_files
        if n not in ALLOWED_PY and not any(n.startswith(p) for p in ALLOWED_PY_PREFIXES)
    ]
    if bad:
        fail(f"icazəsiz .py faylları wheel-dədir (biznes məntiqi açıq sızır): {bad}")

    if "tokengram/license.py" in names:
        fail("tokengram/license.py wheel-də .py kimidir — dev-mode bypass geri qayıdıb!")
    license_compiled = [
        n for n in names
        if n.startswith("tokengram/license.") and n.endswith((".pyd", ".so"))
    ]
    if not license_compiled:
        fail(f"tokengram/license compiled artefaktı tapılmadı. Fayllar: "
             f"{[n for n in names if 'license' in n]}")
    print(f"  [1/3] OK: yalnız icazəli .py-lar ({len(py_files)} fayl)")
    print(f"  [2/3] OK: license compiled-dir ({license_compiled[0]})")


_RUNTIME_PROBE = r"""
import sys
from tokengram import license as lic
try:
    guard = lic.ensure_license()
except lic.LicenseError as e:
    # Gözlənilən: açar yoxdur → trial cəhdi → əlçatmaz server → LicenseError.
    # Yəni dev mode YOX, trial axını VAR.
    print("PROBE-OK: dev refused, trial attempted:", str(e)[:80])
    sys.exit(0)
except Exception as e:
    print("PROBE-FAIL: gozlenilmez xeta:", type(e).__name__, e)
    sys.exit(1)
if guard is None:
    print("PROBE-FAIL: dev mode None qaytardi — TOKENGRAM_DEV_MODE bypass release-de ISLEYIR!")
    sys.exit(1)
print("PROBE-FAIL: acarsiz/serversiz guard qayitdi?!")
sys.exit(1)
"""


def runtime_probe(venv_python: Path) -> None:
    import os

    with tempfile.TemporaryDirectory() as tmp_home:
        env = dict(os.environ)
        env.update({
            "USERPROFILE": tmp_home,           # Path.home() (Windows)
            "HOME": tmp_home,                  # Path.home() (POSIX)
            "TOKENGRAM_DEV_MODE": "1",         # bypass cəhdi — TƏSİR ETMƏMƏLİDİR
            # Əlçatmaz server: connection refused dərhal qayıdır, test 10s gözləmir
            "MLA_LICENSE_SERVER_URL": "http://127.0.0.1:9",
        })
        env.pop("MLA_LICENSE_KEY", None)
        env.pop("MLA_LICENSE_PUBKEY", None)
        r = subprocess.run(
            [str(venv_python), "-c", _RUNTIME_PROBE],
            capture_output=True, text=True, timeout=60, env=env,
        )
        print("  " + (r.stdout.strip() or r.stderr.strip()[:200]))
        if r.returncode != 0:
            fail("runtime probe uğursuz (yuxarıdakı çıxışa bax)")
    print("  [3/3] OK: TOKENGRAM_DEV_MODE=1 release build-də dev mode AÇMIR")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(2)
    wheel = Path(args[0])
    if not wheel.exists():
        fail(f"wheel tapılmadı: {wheel}")

    print(f"Release smoke test: {wheel.name}")
    static_audit(wheel)

    if "--venv" in sys.argv:
        venv_python = Path(sys.argv[sys.argv.index("--venv") + 1])
        if not venv_python.exists():
            fail(f"venv python tapılmadı: {venv_python}")
        runtime_probe(venv_python)
    else:
        print("  [3/3] SKIP: runtime probe (--venv verilməyib) — release checklist-də MƏCBURİDİR")

    print("SMOKE PASS")


if __name__ == "__main__":
    main()

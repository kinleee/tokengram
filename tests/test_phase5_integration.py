"""Phase 5 — İnteqrasiya regression: slash command back-end skriptləri.

`/MlaOn`, `/MlaOff`, `/MlaResetBar`, `/MlaRefreshBar`, `/MlaArch` slash
command-ları sadəcə `hooks/*.py` skript-lərini çağırır. Bu mərhələ skript
davranışını birbaşa yoxlayır.

`/MlaReindex` (`main.py index . --fresh`) regression-i test deyil — full
ChromaDB rebuild 60+ saniyə çəkir; o tək-dəfə manual yoxlandı (Phase 4
qabağı session-da).

`/MlaSync` = `savings_report.py` — Phase 3-də 9 case-də artıq sınanıb.

Run: `python tests/test_phase5_integration.py`
"""
import json
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

TOGGLE = ROOT / "hooks" / "toggle_mla.py"
RESET = ROOT / "hooks" / "reset_savings.py"
REFRESH = ROOT / "hooks" / "refresh_bar.py"
SHOW_ARCH = ROOT / "hooks" / "show_arch.py"

FLAG = ROOT / ".mla_enforcement.flag"
HISTORY = ROOT / ".mla_savings_history.jsonl"
ARCH_DOC = ROOT / ".mla_arch.md"


def _snap(p: Path):
    return p.read_bytes() if p.exists() else None


def _restore(p: Path, data):
    if data is None:
        p.unlink(missing_ok=True)
    else:
        p.write_bytes(data)


def _run(script: Path, args=(), timeout=5, lang: str = "en"):
    """`lang` MLA_LANG env-ini override edir (default `en`)."""
    import os
    env = dict(os.environ)
    env["MLA_LANG"] = lang
    proc = subprocess.run(
        [PYTHON, str(script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


class TestSlashCommandBackends(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._snap = {
            "flag": _snap(FLAG),
            "history": _snap(HISTORY),
            "arch": _snap(ARCH_DOC),
        }

    @classmethod
    def tearDownClass(cls):
        _restore(FLAG, cls._snap["flag"])
        _restore(HISTORY, cls._snap["history"])
        _restore(ARCH_DOC, cls._snap["arch"])
        # Yığılan backup faylları təmizlə
        for bak in ROOT.glob(".mla_savings_history.jsonl.bak*"):
            bak.unlink(missing_ok=True)

    # ---- toggle_mla.py (/MlaOn, /MlaOff) ----

    def test_toggle_on(self):
        rc, out, _ = _run(TOGGLE, ["on"])
        self.assertEqual(rc, 0)
        self.assertEqual(FLAG.read_text(encoding="utf-8"), "on")
        self.assertIn("ON", out)

    def test_toggle_off(self):
        rc, out, _ = _run(TOGGLE, ["off"])
        self.assertEqual(rc, 0)
        self.assertEqual(FLAG.read_text(encoding="utf-8"), "off")
        self.assertIn("OFF", out)

    def test_toggle_invalid_arg(self):
        rc, _, err = _run(TOGGLE, ["maybe"])
        self.assertEqual(rc, 1)
        self.assertIn("Usage", err)

    # ---- reset_savings.py (/MlaResetBar) ----

    def test_reset_with_content_creates_timestamped_backup(self):
        """Backup HƏMİŞƏ timestamped `.bak.<ts>`-dir (folder tidy, ext 0.1.56) —
        suffix-siz `.jsonl.bak` artıq yaranmır."""
        content = '{"ts": 1, "searches": 1}\n'
        HISTORY.write_text(content, encoding="utf-8")
        rc, out, _ = _run(RESET)
        self.assertEqual(rc, 0)
        self.assertEqual(HISTORY.read_text(encoding="utf-8"), "")
        timestamped = list(ROOT.glob(".mla_savings_history.jsonl.bak.*"))
        self.assertGreaterEqual(len(timestamped), 1)
        # Backup köhnə history-nin surətidir
        newest = max(timestamped, key=lambda p: p.stat().st_mtime)
        self.assertEqual(newest.read_text(encoding="utf-8"), content)

    def test_reset_backup_retention_keeps_two(self):
        """Hər reset yeni .bak yaradır, amma yalnız son 2-si saxlanır —
        .bak yığını qovluğu zibilləmesin."""
        for i in range(3):
            HISTORY.write_text(f'{{"ts": {i}}}\n', encoding="utf-8")
            rc, _, _ = _run(RESET)
            self.assertEqual(rc, 0)
        timestamped = list(ROOT.glob(".mla_savings_history.jsonl.bak.*"))
        self.assertLessEqual(len(timestamped), 2, msg=f"got: {[p.name for p in timestamped]}")

    def test_reset_empty_history_idempotent(self):
        HISTORY.write_text("", encoding="utf-8")
        rc, out, _ = _run(RESET)
        self.assertEqual(rc, 0)
        self.assertIn("already empty", out)

    # ---- refresh_bar.py (/MlaRefreshBar) ----

    def test_refresh_bar_updates_mtime(self):
        HISTORY.write_text("{}\n", encoding="utf-8")
        old_mtime = HISTORY.stat().st_mtime
        time.sleep(0.05)
        rc, out, err = _run(REFRESH)
        self.assertEqual(rc, 0)
        self.assertGreater(HISTORY.stat().st_mtime, old_mtime)
        # Mesaj STDERR-ə yazılır — hook stdout-u Claude kontekstinə düşür,
        # ona görə insan-üçün status sətirləri stderr-dədir.
        self.assertIn("refresh triggered", err)

    def test_refresh_bar_creates_history_if_missing(self):
        HISTORY.unlink(missing_ok=True)
        rc, _, _ = _run(REFRESH)
        self.assertEqual(rc, 0)
        self.assertTrue(HISTORY.exists())

    # ---- show_arch.py (/MlaArch) ----

    def test_show_arch_prints_content(self):
        ARCH_DOC.write_text("# Test Arch\nContent\n", encoding="utf-8")
        rc, out, _ = _run(SHOW_ARCH)
        self.assertEqual(rc, 0)
        self.assertIn("# Test Arch", out)
        self.assertIn("Content", out)

    def test_show_arch_missing_file_friendly_message(self):
        ARCH_DOC.unlink(missing_ok=True)
        # Default lokal `en`
        rc, out, _ = _run(SHOW_ARCH)
        self.assertEqual(rc, 0)
        self.assertIn("hasn't been generated", out)

    def test_show_arch_missing_file_az_falls_back_to_en(self):
        # az.json qəsdən silinib (fdc3ef5) → az locale EN mesajı qaytarır
        ARCH_DOC.unlink(missing_ok=True)
        rc, out, _ = _run(SHOW_ARCH, lang="az")
        self.assertEqual(rc, 0)
        self.assertIn("hasn't been generated", out)


class TestSavingsReader24hMath(unittest.TestCase):
    """`vscode-extension/src/savingsReader.ts`-in 24h summary məntiqinin
    Python ekvivalenti. Ts kodu ilə eyni formul — sadəcə fərqli dildə yazılıb,
    formul drift olmamalıdır.
    """

    @staticmethod
    def _summary(records, now: float):
        cutoff = now - 86400
        recent = [r for r in records if r["ts"] >= cutoff]
        actualR = sum(r["actual_tokens"] for r in recent)
        baseR = sum(r["baseline_tokens"] for r in recent)
        savedR = baseR - actualR
        pctR = (savedR / baseR * 100) if baseR > 0 else 0.0
        savedFromBlocks24h = sum(r.get("block_baseline_tokens", 0) for r in recent)
        savedFromGreps24h = sum(
            r.get("grep_baseline_tokens", 0) - r.get("grep_actual_tokens", 0)
            for r in recent
        )
        savedFromSearch24h = savedR - savedFromBlocks24h - savedFromGreps24h
        return {
            "savedTokens24h": savedR,
            "savedPct24h": pctR,
            "savedFromBlocks24h": savedFromBlocks24h,
            "savedFromGreps24h": savedFromGreps24h,
            "savedFromSearch24h": savedFromSearch24h,
            "recent24hTasks": len(recent),
        }

    def test_pure_search_24h(self):
        now = time.time()
        records = [
            {"ts": now - 100, "actual_tokens": 500, "baseline_tokens": 2000,
             "block_baseline_tokens": 0, "grep_baseline_tokens": 0, "grep_actual_tokens": 0},
        ]
        s = self._summary(records, now)
        self.assertEqual(s["savedTokens24h"], 1500)
        self.assertEqual(s["savedFromBlocks24h"], 0)
        self.assertEqual(s["savedFromSearch24h"], 1500)
        self.assertEqual(s["recent24hTasks"], 1)

    def test_mixed_search_block_grep(self):
        now = time.time()
        records = [
            {"ts": now - 100, "actual_tokens": 200, "baseline_tokens": 3000,
             "block_baseline_tokens": 1000, "grep_baseline_tokens": 500,
             "grep_actual_tokens": 75},
        ]
        s = self._summary(records, now)
        self.assertEqual(s["savedTokens24h"], 2800)
        self.assertEqual(s["savedFromBlocks24h"], 1000)
        self.assertEqual(s["savedFromGreps24h"], 425)
        # search saved = 2800 − 1000 − 425 = 1375
        self.assertEqual(s["savedFromSearch24h"], 1375)

    def test_old_records_excluded(self):
        now = time.time()
        records = [
            {"ts": now - 86401, "actual_tokens": 1000, "baseline_tokens": 2000,
             "block_baseline_tokens": 0, "grep_baseline_tokens": 0, "grep_actual_tokens": 0},
            {"ts": now - 100, "actual_tokens": 100, "baseline_tokens": 500,
             "block_baseline_tokens": 0, "grep_baseline_tokens": 0, "grep_actual_tokens": 0},
        ]
        s = self._summary(records, now)
        self.assertEqual(s["recent24hTasks"], 1)
        self.assertEqual(s["savedTokens24h"], 400)


class TestEnforcementCascade(unittest.TestCase):
    """on → bütün hooks aktiv; off → hamısı self-exit."""

    @classmethod
    def setUpClass(cls):
        cls._saved = _snap(FLAG)

    @classmethod
    def tearDownClass(cls):
        _restore(FLAG, cls._saved)

    def test_flag_cycle(self):
        for state in ("on", "off", "on", "off"):
            rc, _, _ = _run(TOGGLE, [state])
            self.assertEqual(rc, 0)
            self.assertEqual(FLAG.read_text(encoding="utf-8"), state)


if __name__ == "__main__":
    unittest.main(verbosity=2)

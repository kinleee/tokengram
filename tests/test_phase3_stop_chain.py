"""Phase 3 — Stop hook chain (arch_doc.py + savings_report.py).

Bu test-lər real `.mla_*` faylları üzərində işləyir, çünki hook-larda
PROJECT_ROOT hardcode-dir. Hər test əvvəl mövcud fayl içəriyini saxlayır,
sonda bərpa edir — beləliklə production data toxunulmaz qalır.

Run: `python tests/test_phase3_stop_chain.py`
"""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

ARCH_DOC_SCRIPT = ROOT / "hooks" / "arch_doc.py"
SAVINGS_SCRIPT = ROOT / "hooks" / "savings_report.py"
TOGGLE_SCRIPT = ROOT / "hooks" / "toggle_mla.py"

FLAG = ROOT / ".mla_enforcement.flag"
SESSION_LOG = ROOT / ".mla_session_log.jsonl"
HISTORY = ROOT / ".mla_savings_history.jsonl"
ARCH_STATE = ROOT / ".mla_arch_state.json"
ARCH_DOC = ROOT / ".mla_arch.md"
SETTINGS = ROOT / ".claude" / "settings.json"


def _snapshot(path: Path):
    if path.exists():
        return path.read_bytes()
    return None


def _restore(path: Path, data):
    if data is None:
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(data)


def _run(script: Path, timeout: float = 10.0, lang: str = "en"):
    """`lang` parametri MLA_LANG env var-ını override edir (default `en`)."""
    env = dict(os.environ)
    env["MLA_LANG"] = lang
    proc = subprocess.run(
        [PYTHON, str(script)],
        input="",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _set_flag(state: str):
    FLAG.write_text(state, encoding="utf-8")


class TestStopChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._snap = {
            "flag": _snapshot(FLAG),
            "session": _snapshot(SESSION_LOG),
            "history": _snapshot(HISTORY),
            "arch_state": _snapshot(ARCH_STATE),
            "arch_doc": _snapshot(ARCH_DOC),
        }

    @classmethod
    def tearDownClass(cls):
        _restore(FLAG, cls._snap["flag"])
        _restore(SESSION_LOG, cls._snap["session"])
        _restore(HISTORY, cls._snap["history"])
        _restore(ARCH_STATE, cls._snap["arch_state"])
        _restore(ARCH_DOC, cls._snap["arch_doc"])

    def setUp(self):
        # Hər test üçün təmiz vəziyyət
        SESSION_LOG.unlink(missing_ok=True)
        HISTORY.unlink(missing_ok=True)
        ARCH_STATE.unlink(missing_ok=True)
        ARCH_DOC.unlink(missing_ok=True)
        _set_flag("on")

    # ------------- savings_report tests -------------

    def test_savings_empty_session_no_history_write(self):
        rc, _, _ = _run(SAVINGS_SCRIPT)
        self.assertEqual(rc, 0)
        self.assertFalse(HISTORY.exists(), "history should not be written for empty session")

    def test_savings_with_mixed_entries_writes_one_record(self):
        entries = [
            {"ts": time.time(), "query": "test1", "files": {"a.py": 500}, "actual_tokens": 100},
            {"ts": time.time(), "type": "read_block", "file": "b.py", "lines": 100, "estimated_baseline_tokens": 1000},
            {"ts": time.time(), "type": "grep_search", "file": "c.py", "lines": 50,
             "estimated_baseline_tokens": 500, "estimated_actual_tokens": 75},
            {"ts": time.time(), "type": "bash_inspect", "file": "d.py", "lines": 60,
             "estimated_baseline_tokens": 600, "estimated_actual_tokens": 120},
        ]
        SESSION_LOG.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n",
            encoding="utf-8",
        )
        rc, _, err = _run(SAVINGS_SCRIPT)
        self.assertEqual(rc, 0)
        # Default lokal `en` — xülasə ingiliscə gəlir.
        self.assertIn("search", err, msg=f"stderr={err!r}")
        # session_log silinməlidir
        self.assertFalse(SESSION_LOG.exists())
        # history bir record-dur
        records = [json.loads(l) for l in HISTORY.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r["searches"], 1)
        self.assertEqual(r["blocks"], 1)
        self.assertEqual(r["greps"], 1)
        self.assertEqual(r["bash_inspects"], 1)
        # Sübut-əsaslı model (method 2): search-ün nəticəsinə toxunulmayıb →
        # hunt fallback = min(top_file, cap) = 500; block = 1000 (real cəhd).
        # Sübutsuz (un-steered) grep/bash KREDİT ALMIR — xərcləri ungated-ə düşür.
        self.assertEqual(r["method"], 2)
        # Baseline = 500 (search hunt) + 1000 (block) = 1500
        self.assertEqual(r["baseline_tokens"], 1500)
        # Actual = yalnız search chunk-ları = 100 (grep/bash ungated xərcdir)
        self.assertEqual(r["actual_tokens"], 100)
        # Ungated = grep 75 + bash 120 = 195
        self.assertEqual(r["ungated_spent_tokens"], 195)

    def test_savings_off_flag_keeps_session_no_history(self):
        SESSION_LOG.write_text('{"query":"x","files":{},"actual_tokens":0}\n', encoding="utf-8")
        _set_flag("off")
        rc, _, _ = _run(SAVINGS_SCRIPT)
        self.assertEqual(rc, 0)
        # OFF-da hook heç nəyə TOXUNMUR: silmə cəhdi paralel yazı ilə yarışa
        # bilər → session olduğu kimi qalır, history yazılmır (savings_report
        # main() ilk gate-də çıxır).
        self.assertTrue(SESSION_LOG.exists())
        self.assertFalse(HISTORY.exists())

    # ------------- arch_doc tests -------------

    def test_arch_doc_empty_session_does_nothing(self):
        rc, _, _ = _run(ARCH_DOC_SCRIPT)
        self.assertEqual(rc, 0)
        self.assertFalse(ARCH_STATE.exists())
        self.assertFalse(ARCH_DOC.exists())

    def test_arch_doc_builds_state_from_searches(self):
        entries = [
            {"ts": time.time(), "query": "auth flow", "files": {"auth.py": 200, "user.py": 150}, "actual_tokens": 50},
            {"ts": time.time(), "query": "db schema", "files": {"models.py": 300}, "actual_tokens": 80},
        ]
        SESSION_LOG.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n",
            encoding="utf-8",
        )
        rc, _, err = _run(ARCH_DOC_SCRIPT)
        self.assertEqual(rc, 0, msg=err)
        self.assertTrue(ARCH_STATE.exists())
        self.assertTrue(ARCH_DOC.exists())
        state = json.loads(ARCH_STATE.read_text(encoding="utf-8"))
        self.assertEqual(state["total_searches"], 2)
        self.assertIn("auth.py", state["files"])
        self.assertIn("models.py", state["files"])
        self.assertEqual(len(state["recent_searches"]), 2)

    def test_arch_doc_preserves_session_log_for_savings(self):
        """arch_doc session_log-u TƏMİZLƏMƏMƏLİDİR (savings_report o işi görür)."""
        entries = [{"ts": time.time(), "query": "x", "files": {"a.py": 100}, "actual_tokens": 50}]
        SESSION_LOG.write_text(json.dumps(entries[0]) + "\n", encoding="utf-8")
        rc, _, _ = _run(ARCH_DOC_SCRIPT)
        self.assertEqual(rc, 0)
        self.assertTrue(SESSION_LOG.exists(), "arch_doc must not delete session_log")

    def test_arch_doc_off_flag_skip(self):
        SESSION_LOG.write_text('{"query":"x","files":{"a.py":100},"actual_tokens":50}\n', encoding="utf-8")
        _set_flag("off")
        rc, _, _ = _run(ARCH_DOC_SCRIPT)
        self.assertEqual(rc, 0)
        # OFF-da arch_doc heç nə etmir
        self.assertFalse(ARCH_STATE.exists())
        self.assertFalse(ARCH_DOC.exists())
        # Amma session_log toxunulmaz qalır (savings_report onu OFF-da silir)
        self.assertTrue(SESSION_LOG.exists())

    # ------------- End-to-end chain test -------------

    def test_full_chain_arch_then_savings(self):
        """settings.json sırası (arch_doc → savings_report) işləyir."""
        entries = [
            {"ts": time.time(), "query": "hooks", "files": {"foo.py": 400}, "actual_tokens": 90},
            {"ts": time.time(), "type": "read_block", "file": "bar.py", "lines": 80, "estimated_baseline_tokens": 800},
        ]
        SESSION_LOG.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n",
            encoding="utf-8",
        )
        # 1-ci: arch_doc
        rc1, _, _ = _run(ARCH_DOC_SCRIPT)
        self.assertEqual(rc1, 0)
        self.assertTrue(SESSION_LOG.exists(), "after arch_doc, session_log still there")
        self.assertTrue(ARCH_STATE.exists())
        # 2-ci: savings_report
        rc2, _, err = _run(SAVINGS_SCRIPT)
        self.assertEqual(rc2, 0, msg=err)
        self.assertFalse(SESSION_LOG.exists(), "after savings_report, session_log gone")
        self.assertTrue(HISTORY.exists())

    def test_savings_summary_az_falls_back_to_english(self):
        """MLA_LANG=az → EN fallback (az.json qəsdən silindi, commit fdc3ef5).

        AZ dəstəyi launch üçün çıxarılıb; i18n.tr() itkin locale faylında
        İngiliscəyə düşməlidir — crash yox, boş sətir yox.
        """
        SESSION_LOG.write_text(
            json.dumps({"ts": time.time(), "query": "x", "files": {"a.py": 100}, "actual_tokens": 50}) + "\n",
            encoding="utf-8",
        )
        rc, _, err = _run(SAVINGS_SCRIPT, lang="az")
        self.assertEqual(rc, 0)
        self.assertIn("search", err)
        self.assertIn("saved", err)

    def test_settings_json_hook_order(self):
        """Canonical Stop zənciri: savings_report.py → flush_queue.py.

        arch_doc artıq Stop chain-də DEYİL (canonical dəst =
        setupWizard.ts REQUIRED_HOOK_SCRIPTS, 6 skript). savings_report
        flush_queue-dan əvvəl gəlməlidir: əvvəl session hesablanır,
        sonra reindex queue drain olunur.
        """
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        stop = data["hooks"]["Stop"][0]["hooks"]
        names = [h["command"] for h in stop]
        self.assertFalse(
            any("arch_doc" in n for n in names),
            msg=f"arch_doc Stop chain-ə qayıdıb? got: {names}",
        )
        sav_idx = next(i for i, n in enumerate(names) if "savings_report" in n)
        flush_idx = next(i for i, n in enumerate(names) if "flush_queue" in n)
        self.assertLess(sav_idx, flush_idx, msg=f"got: {names}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

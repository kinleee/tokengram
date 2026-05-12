"""Phase 2 — Enforcement hooks (pre_read_check, post_grep_check, post_bash_check).

Hər hook subprocess kimi çağırılır, stdin JSON-payload göndərilir, exit
code və session_log entry-si yoxlanır. Bu real Claude Code data flow-unu
təqlid edir.

Run: `python tests/test_phase2_hooks.py`
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
PYTHON = sys.executable

PRE_READ = HOOKS / "pre_read_check.py"
POST_GREP = HOOKS / "post_grep_check.py"
POST_BASH = HOOKS / "post_bash_check.py"

FLAG = ROOT / ".mla_enforcement.flag"
SESSION_LOG = ROOT / ".mla_session_log.jsonl"


def _set_flag(state: str):
    FLAG.write_text(state, encoding="utf-8")


def _clear_session_log():
    SESSION_LOG.unlink(missing_ok=True)


def _read_session_log():
    if not SESSION_LOG.exists():
        return []
    return [json.loads(line) for line in SESSION_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]


def _run_hook(script: Path, payload: dict, timeout: float = 5.0):
    # Explicit UTF-8 — Windows-un cp1252 default-u Azərbaycan hərflərini
    # mojibake-yə çevirir.
    proc = subprocess.run(
        [PYTHON, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


class _HookTestBase(unittest.TestCase):
    """Base — hər test üçün tmp fayl yaradır, session_log təmizləyir."""

    @classmethod
    def setUpClass(cls):
        cls._saved_flag = FLAG.read_text(encoding="utf-8") if FLAG.exists() else "off"

    @classmethod
    def tearDownClass(cls):
        FLAG.write_text(cls._saved_flag, encoding="utf-8")
        _clear_session_log()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mla_p2_", dir=ROOT))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        _clear_session_log()

    def make_file(self, name: str, lines: int) -> Path:
        p = self.tmp / name
        p.write_text("\n".join(f"line {i}" for i in range(lines)) + "\n", encoding="utf-8")
        return p


class TestPreRead(_HookTestBase):
    def test_block_typescript_100_lines(self):
        _set_flag("on")
        f = self.make_file("foo.ts", 100)
        rc, _, err = _run_hook(PRE_READ, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
        self.assertEqual(rc, 2, msg=err)
        self.assertIn("MlaReindex", err)  # New extension hint must appear

    def test_block_go_60_lines(self):
        _set_flag("on")
        f = self.make_file("foo.go", 60)
        rc, _, _ = _run_hook(PRE_READ, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
        self.assertEqual(rc, 2)

    def test_warn_python_40_lines(self):
        _set_flag("on")
        f = self.make_file("foo.py", 40)
        rc, _, err = _run_hook(PRE_READ, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
        self.assertEqual(rc, 0)
        self.assertIn("TIP", err)

    def test_silent_python_20_lines(self):
        _set_flag("on")
        f = self.make_file("foo.py", 20)
        rc, _, err = _run_hook(PRE_READ, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
        self.assertEqual(rc, 0)
        self.assertEqual(err.strip(), "")

    def test_block_json_100_lines(self):
        _set_flag("on")
        f = self.make_file("foo.json", 100)
        rc, _, _ = _run_hook(PRE_READ, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
        self.assertEqual(rc, 2)

    def test_flag_off_passthrough(self):
        _set_flag("off")
        f = self.make_file("foo.ts", 100)
        rc, _, err = _run_hook(PRE_READ, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
        self.assertEqual(rc, 0)
        self.assertEqual(err.strip(), "")

    def test_non_indexed_extension(self):
        _set_flag("on")
        f = self.make_file("foo.txt", 200)
        rc, _, _ = _run_hook(PRE_READ, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
        self.assertEqual(rc, 0)

    def test_project_external_file(self):
        _set_flag("on")
        outside = Path(tempfile.gettempdir()) / "mla_outside.py"
        outside.write_text("x = 1\n" * 200, encoding="utf-8")
        self.addCleanup(outside.unlink, missing_ok=True)
        rc, _, _ = _run_hook(PRE_READ, {"tool_name": "Read", "tool_input": {"file_path": str(outside)}})
        self.assertEqual(rc, 0)


class TestPostGrep(_HookTestBase):
    def test_logs_ts_50_lines(self):
        _set_flag("on")
        f = self.make_file("foo.ts", 50)
        rc, _, _ = _run_hook(POST_GREP, {"tool_name": "Grep", "tool_input": {"path": str(f), "pattern": "x"}})
        self.assertEqual(rc, 0)
        log = _read_session_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["type"], "grep_search")
        self.assertEqual(log[0]["lines"], 50)

    def test_skips_below_threshold(self):
        _set_flag("on")
        f = self.make_file("foo.py", 20)
        rc, _, _ = _run_hook(POST_GREP, {"tool_name": "Grep", "tool_input": {"path": str(f), "pattern": "x"}})
        self.assertEqual(rc, 0)
        self.assertEqual(_read_session_log(), [])

    def test_skips_non_indexed(self):
        _set_flag("on")
        f = self.make_file("foo.txt", 100)
        rc, _, _ = _run_hook(POST_GREP, {"tool_name": "Grep", "tool_input": {"path": str(f), "pattern": "x"}})
        self.assertEqual(rc, 0)
        self.assertEqual(_read_session_log(), [])

    def test_skips_when_flag_off(self):
        _set_flag("off")
        f = self.make_file("foo.py", 50)
        rc, _, _ = _run_hook(POST_GREP, {"tool_name": "Grep", "tool_input": {"path": str(f), "pattern": "x"}})
        self.assertEqual(rc, 0)
        self.assertEqual(_read_session_log(), [])


class TestPostBash(_HookTestBase):
    """Komanda matrisi — hamısı 50 sətirli `.py` fayl üzərində."""

    def _run_with_cmd(self, cmd_template: str):
        f = self.make_file("foo.py", 50)
        cmd = cmd_template.format(path=str(f))
        rc, _, _ = _run_hook(POST_BASH, {"tool_name": "Bash", "tool_input": {"command": cmd}})
        return rc, _read_session_log()

    def test_cat(self):
        _set_flag("on")
        rc, log = self._run_with_cmd("cat {path}")
        self.assertEqual(rc, 0)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["type"], "bash_inspect")

    def test_head_with_flags(self):
        _set_flag("on")
        rc, log = self._run_with_cmd("head -n 5 {path}")
        self.assertEqual(len(log), 1)

    def test_select_string(self):
        _set_flag("on")
        rc, log = self._run_with_cmd('Select-String "pattern" {path}')
        self.assertEqual(len(log), 1)

    def test_findstr(self):
        _set_flag("on")
        rc, log = self._run_with_cmd('findstr "pattern" {path}')
        self.assertEqual(len(log), 1)

    def test_gc_alias(self):
        _set_flag("on")
        rc, log = self._run_with_cmd("gc {path}")
        self.assertEqual(len(log), 1)

    def test_get_content(self):
        _set_flag("on")
        rc, log = self._run_with_cmd("Get-Content {path}")
        self.assertEqual(len(log), 1)

    def test_type_cmd(self):
        _set_flag("on")
        rc, log = self._run_with_cmd("type {path}")
        self.assertEqual(len(log), 1)

    def test_awk(self):
        _set_flag("on")
        rc, log = self._run_with_cmd("awk '/x/{{print}}' {path}")
        self.assertEqual(len(log), 1)

    def test_sed(self):
        _set_flag("on")
        rc, log = self._run_with_cmd("sed -n '1,10p' {path}")
        self.assertEqual(len(log), 1)

    def test_git_show(self):
        _set_flag("on")
        rc, log = self._run_with_cmd("git show HEAD:{path}")
        self.assertEqual(len(log), 1)

    def test_pipeline_head_to_grep(self):
        _set_flag("on")
        rc, log = self._run_with_cmd("head -n 5 {path} | grep def")
        self.assertEqual(len(log), 1, "head segment must be detected")

    def test_non_inspect_command_skipped(self):
        _set_flag("on")
        f = self.make_file("foo.py", 50)
        rc, _, _ = _run_hook(POST_BASH, {"tool_name": "Bash", "tool_input": {"command": f"git status; ls {self.tmp}"}})
        self.assertEqual(_read_session_log(), [])

    def test_flag_off_skip(self):
        _set_flag("off")
        rc, log = self._run_with_cmd("cat {path}")
        self.assertEqual(log, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

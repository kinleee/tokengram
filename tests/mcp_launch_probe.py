#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MCP launch probe — qəbul oraklı (acceptance oracle).

Claude Code-un EYNİ şərtlərində serveri real MCP SDK ilə yoxlayır:
  - eyni venv python, `-m tokengram`, cwd = repo root, .mcp.json env
  - real JSON-RPC `initialize` handshake (stdio üzərindən)
  - handshake < 25s (Claude Code limiti 30s, marja saxlayırıq)
  - tools/list → search_code + get_stats qeydiyyatdan keçib
  - config.py-ni `.mla_pending.txt`-ə yazıb növbənin drenləndiyini sübut edir
    (model soyuq-yükü handshake yolundan KƏNARDA, drain pəncərəsində baş verir)
  - təmiz bağlanma + təmizlik (chroma_db-yə TOXUNMUR)

İşə salma:
    <venv python> tests/mcp_launch_probe.py [python_exe] [repo_root]

Exit 0 yalnız AC1-AC3 keçəndə; əks halda exit 1 (səbəb çap olunur).
"""

import asyncio
import os
import sys
import time
import traceback
from pathlib import Path

# Windows: stdio subprocess transport üçün Proactor loop lazımdır.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Bu probe Azərbaycan mətni (məs. "növbə") və emoji çap edir; cp1252 konsolda
# (default Windows Bash/cmd) `print` UnicodeEncodeError verir və oracle SERVER
# səbəbi OLMADAN çökür. Öz stdout/stderr-imizi utf-8-ə keçiririk ki, nəticə
# çağıran shell-in encoding-indən asılı olmasın.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _resolve():
    repo_root = Path(__file__).resolve().parents[1]
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        venv_python = sys.argv[1]
    else:
        venv_python = r"C:\Users\ilkin.ha\.tokengram\venv\Scripts\python.exe"
    if len(sys.argv) >= 3 and sys.argv[2].strip():
        repo_root = Path(sys.argv[2]).resolve()
    return venv_python, repo_root


def _cleanup(repo_root: Path, pending: Path, processing: Path):
    """Sonda təmizlik — chroma_db-yə TOXUNMA."""
    for p in (pending, processing, repo_root / ".mla_probe_stderr.log"):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
    # Qalıq lock fayllarını sil (.tokengram*.lock).
    try:
        for lock in repo_root.glob(".tokengram*.lock"):
            try:
                lock.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass


async def main() -> int:
    venv_python, repo_root = _resolve()
    pending = repo_root / ".mla_pending.txt"
    processing = repo_root / ".mla_pending.processing"

    failures = []

    # 1) Ön-təmizlik — drain assertion mənalı olsun.
    pending.unlink(missing_ok=True)
    processing.unlink(missing_ok=True)

    # 2) ENV — DƏQİQ .mcp.json env + CLAUDE_PROJECT_DIR.
    env = dict(os.environ)
    env.update({
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "ANONYMIZED_TELEMETRY": "False",
        "CLAUDE_PROJECT_DIR": str(repo_root),
    })
    # QEYD: MLA_DISABLE_WARMUP TƏYIN ETMİRİK — real warm-path drain istəyirik.

    params = StdioServerParameters(
        command=venv_python,
        args=["-m", "tokengram"],
        env=env,
        cwd=str(repo_root),
    )

    handshake_seconds = None
    drain_seconds = None
    drained = False
    tool_names = []

    print(f"[probe] python   = {venv_python}", flush=True)
    print(f"[probe] repo_root= {repo_root}", flush=True)

    # Child stderr-i fayla yönləndir — konsol truncation gizlətməsin.
    errlog_path = repo_root / ".mla_probe_stderr.log"
    errlog = open(errlog_path, "w", encoding="utf-8")

    try:
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                # 3) HANDSHAKE — real MCP initialize.
                t0 = time.perf_counter()
                try:
                    await asyncio.wait_for(session.initialize(), timeout=28)
                    handshake_seconds = time.perf_counter() - t0
                except asyncio.TimeoutError:
                    handshake_seconds = time.perf_counter() - t0
                    failures.append(
                        f"initialize 28s ərzində tamamlanmadı "
                        f"(server Claude Code 30s limitində öldürülərdi); "
                        f"keçən={handshake_seconds:.2f}s"
                    )
                    raise
                print(f"[probe] handshake_seconds = {handshake_seconds:.2f}", flush=True)
                if handshake_seconds >= 25.0:
                    failures.append(
                        f"AC1: handshake_seconds {handshake_seconds:.2f} >= 25.0"
                    )

                # 4) TOOLS/LIST.
                tools = await session.list_tools()
                tool_names = [t.name for t in tools.tools]
                print(f"[probe] tools = {tool_names}", flush=True)
                if "search_code" not in tool_names:
                    failures.append("AC2: 'search_code' tool qeydiyyatda yoxdur")
                if "get_stats" not in tool_names:
                    failures.append("AC2: 'get_stats' tool qeydiyyatda yoxdur")

                # 5) ENQUEUE + DRAIN.
                pending.write_text(
                    str(repo_root / "config.py") + "\n", encoding="utf-8"
                )
                print("[probe] config.py növbəyə yazıldı; drain gözlənilir...", flush=True)
                t_drain = time.perf_counter()
                deadline = t_drain + 150
                while time.perf_counter() < deadline:
                    await asyncio.sleep(1.0)
                    if not pending.exists() and not processing.exists():
                        drained = True
                        drain_seconds = time.perf_counter() - t_drain
                        break
                if drained:
                    print(f"[probe] drain_seconds = {drain_seconds:.2f}", flush=True)
                else:
                    failures.append(
                        "AC3: növbə 150s ərzində drenlənmədi → "
                        "worker modeli yükləmədi / yol bug-ı"
                    )
            # ClientSession çıxışı → stdin bağlanır → server orphan-watchdog çıxır.
        # stdio_client çıxışı → child prosesi sonlandı.
    except Exception:
        if not failures:
            failures.append("Gözlənilməz istisna:\n" + traceback.format_exc())
        else:
            print(traceback.format_exc(), flush=True)
    finally:
        try:
            errlog.close()
        except Exception:
            pass
        # Diaqnostika üçün server stderr-inin son sətirlərini çap et.
        try:
            tail = errlog_path.read_text(encoding="utf-8", errors="replace").splitlines()
            print("[probe] --- server stderr (son 40 sətir) ---", flush=True)
            for ln in tail[-40:]:
                print("  | " + ln, flush=True)
        except Exception:
            pass
        _cleanup(repo_root, pending, processing)

    # 6) NƏTİCƏ.
    if failures:
        print("FAIL:", flush=True)
        for f in failures:
            print(f"  - {f}", flush=True)
        print(
            f"  (handshake_seconds={handshake_seconds}, "
            f"drain_seconds={drain_seconds}, drained={drained})",
            flush=True,
        )
        return 1

    print(
        f"PASS handshake_seconds={handshake_seconds:.2f} "
        f"drain_seconds={drain_seconds:.2f}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception:
        traceback.print_exc()
        sys.exit(1)

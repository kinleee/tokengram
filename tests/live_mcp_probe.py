"""Canlı MCP stdio probe — serveri əsl protokolla işlədib yoxlayır.

Nə test edir (hamısı REAL proses üzərində, mock yox):
  1. Server stdio-da qalxır, initialize handshake keçir
  2. get_stats çağırışı cavab verir (db_health + writer_lock sahələri daxil)
  3. search_code real nəticə qaytarır
  4. stdin bağlananda proses ÖZÜ çıxır (orphan-exit watchdog) — N saniyə içində

İstifadə:
    python tests/live_mcp_probe.py <python_exe> <cwd> [sorğu]
Exit 0 = bütün yoxlamalar keçdi.
"""
import json
import os
import subprocess
import sys
import threading
import time
from queue import Queue, Empty

EXIT_GRACE_SEC = 15.0


def main() -> int:
    py = sys.argv[1]
    cwd = sys.argv[2]
    query = sys.argv[3] if len(sys.argv) > 3 else "writer lock acquire"

    env = dict(os.environ)
    env.update({
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "ANONYMIZED_TELEMETRY": "False",
        "CLAUDE_PROJECT_DIR": cwd,
    })
    proc = subprocess.Popen(
        [py, "-m", "tokengram"],
        cwd=cwd, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )

    out_q: Queue = Queue()
    def _pump(stream, tag):
        for line in stream:
            out_q.put((tag, line.rstrip("\n")))
    threading.Thread(target=_pump, args=(proc.stdout, "out"), daemon=True).start()
    threading.Thread(target=_pump, args=(proc.stderr, "err"), daemon=True).start()

    def send(obj):
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def recv_response(req_id, timeout=90.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                tag, line = out_q.get(timeout=1.0)
            except Empty:
                continue
            if tag == "err":
                continue  # server logları stderr-dədir
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == req_id:
                return msg
        return None

    failures = []
    try:
        # 1) initialize
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "live-probe", "version": "0.0.1"},
        }})
        r = recv_response(1, timeout=60)
        if not r or "result" not in r:
            failures.append(f"initialize cavabsız/xətalı: {r}")
        else:
            print("[OK] initialize — server qalxdı")
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        # 2) get_stats
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": "get_stats", "arguments": {}}})
        r = recv_response(2, timeout=120)
        text = ""
        if r and "result" in r:
            parts = r["result"].get("content", [])
            text = "\n".join(p.get("text", "") for p in parts)
        if "writer_lock" in text and "total_chunks" in text:
            print("[OK] get_stats — sağlamlıq sahələri görünür:")
            for ln in text.splitlines():
                print("      " + ln)
        else:
            failures.append(f"get_stats gözlənilən sahələri qaytarmadı: {text[:400]!r}")

        # 3) search_code
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "search_code",
                          "arguments": {"query": query, "top_k": 3}}})
        r = recv_response(3, timeout=120)
        text = ""
        if r and "result" in r:
            parts = r["result"].get("content", [])
            text = "\n".join(p.get("text", "") for p in parts)
        if "Mənbə #1" in text:
            first = next(l for l in text.splitlines() if "Mənbə #1" in l)
            print(f"[OK] search_code — nəticə var: {first.strip()[:120]}")
        else:
            failures.append(f"search_code nəticə qaytarmadı: {text[:300]!r}")
    finally:
        # 4) Orphan-exit: stdin-i bağla → proses özü çıxmalıdır
        try:
            proc.stdin.close()
        except OSError:
            pass
        t0 = time.monotonic()
        rc = None
        while time.monotonic() - t0 < EXIT_GRACE_SEC:
            rc = proc.poll()
            if rc is not None:
                break
            time.sleep(0.3)
        if rc is None:
            failures.append(
                f"ORPHAN: stdin bağlandı, proses {EXIT_GRACE_SEC}s içində ÇIXMADI (PID {proc.pid})"
            )
            proc.kill()
        else:
            print(f"[OK] orphan-exit — stdin bağlanandan {time.monotonic()-t0:.1f}s sonra proses özü çıxdı (code={rc})")

    if failures:
        print("\n--- UĞURSUZ ---")
        for f in failures:
            print("  ✗ " + f)
        return 1
    print("\nBÜTÜN CANLI YOXLAMALAR KEÇDİ ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())

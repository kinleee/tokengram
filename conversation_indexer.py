"""
conversation_indexer.py — Claude Code söhbət tarixçəsini indekslədir.

Mənbə: ~/.claude/projects/<project-id>/*.jsonl
Hədəf: ChromaDB "conversations" collection (mövcud `chroma_db/` qovluğunda)

İcra:
    python conversation_indexer.py           # build/yenilə index
    python conversation_indexer.py --search "license JWT issue"

API:
    index_conversations() → {'turns': int, 'chunks': int, 'files': int}
    search_conversations(query, top_k=5) → list of {chunk_id, session_id, timestamp, snippet}
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Iterator, Optional

# Reuse existing infrastructure
sys.path.insert(0, str(Path(__file__).parent))
from vector_store import ChromaVectorStore

CONVO_COLLECTION = "conversations"
MAX_CHARS_PER_CHUNK = 1500  # ~300-400 tokens, embedding model üçün ideal


def get_claude_project_dir(cwd: Optional[Path] = None) -> Optional[Path]:
    """`~/.claude/projects/<encoded-id>/` qovluğunu tap.

    Claude Code path-i encode edir: `:` silinir, `\\` `/` `_` `.` → `-`.
    Lakin encoding versiya-versiya dəyişə bilər, ona görə glob ilə də axtarırıq.
    """
    cwd = cwd or Path.cwd()
    base = Path.home() / ".claude" / "projects"
    if not base.exists():
        return None

    # Variant 1: dəqiq encoding ilə cəhd
    cwd_str = str(cwd.resolve())
    encoded = (
        cwd_str
        .replace(":", "")
        .replace("\\", "-")
        .replace("/", "-")
        .replace("_", "-")
        .replace(".", "-")
    )
    if not encoded.startswith("c"):
        encoded = encoded.lstrip("-")
    # `c\Users` → `c-Users` → claude actually uses `c--Users` (double dash for c: separator)
    candidate = base / encoded
    if candidate.exists():
        return candidate

    # Variant 2: `c:` → `c--` (double dash for colon+separator)
    double = "c--" + cwd_str[3:].replace("\\", "-").replace("/", "-").replace("_", "-").replace(".", "-")
    candidate = base / double
    if candidate.exists():
        return candidate

    # Variant 3: glob — layihə adına görə tapmaq
    project_name = cwd.name.lower().replace("_", "-")
    for sub in base.iterdir():
        if sub.is_dir() and project_name in sub.name.lower():
            return sub

    return None


def _extract_text(content, include_tool_use: bool = False) -> str:
    """Mesaj content-indən düz mətn çıxar."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        itype = item.get("type", "")
        if itype == "text":
            t = item.get("text", "")
            if t:
                parts.append(t)
        elif itype == "tool_use" and include_tool_use:
            name = item.get("name", "?")
            parts.append(f"[tool: {name}]")
        # tool_result-ları skip edirik — çox böyükdür və search üçün dəyəri azdır
    return "\n".join(parts)


def _is_real_user_prompt(content) -> bool:
    """Tool_result mesajları role=user olur. Yalnız real text prompt-larını qəbul et."""
    if isinstance(content, str):
        return bool(content.strip())
    if not isinstance(content, list):
        return False
    has_text = False
    has_tool_result = False
    for item in content:
        if not isinstance(item, dict):
            continue
        t = item.get("type")
        if t == "text" and item.get("text", "").strip():
            has_text = True
        elif t == "tool_result":
            has_tool_result = True
    return has_text and not has_tool_result


def extract_turns(jsonl_path: Path) -> Iterator[dict]:
    """Bir .jsonl faylından turn-ləri extract et.

    Turn = bir user prompt + ondan sonrakı bütün assistant text cavabları
    (növbəti real user prompt gələnə qədər).
    """
    current_user: Optional[dict] = None
    asst_parts: list[str] = []
    last_asst_uuid: str = ""

    def _flush():
        if current_user and asst_parts:
            return {
                "user_text": current_user["text"],
                "assistant_text": "\n\n".join(asst_parts),
                "user_uuid": current_user["uuid"],
                "assistant_uuid": last_asst_uuid or current_user["uuid"],
                "timestamp": current_user.get("ts", ""),
                "session_id": current_user.get("session_id", ""),
            }
        return None

    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = entry.get("type")
                if etype == "user":
                    msg = entry.get("message", {})
                    content = msg.get("content", [])
                    if not _is_real_user_prompt(content):
                        continue  # tool_result — skip
                    # Previous turn-i flush et
                    prev = _flush()
                    if prev:
                        yield prev
                    # Yeni turn başlat
                    current_user = {
                        "text": _extract_text(content),
                        "uuid": entry.get("uuid", ""),
                        "ts": entry.get("timestamp", ""),
                        "session_id": entry.get("sessionId", ""),
                    }
                    asst_parts = []
                    last_asst_uuid = ""
                elif etype == "assistant" and current_user is not None:
                    msg = entry.get("message", {})
                    content = msg.get("content", [])
                    asst_text = _extract_text(content, include_tool_use=False)
                    if asst_text.strip():
                        asst_parts.append(asst_text)
                        last_asst_uuid = entry.get("uuid", "") or last_asst_uuid
    except OSError:
        return

    # Faylın sonunda son turn-i də flush et
    prev = _flush()
    if prev:
        yield prev


def chunk_turn(turn: dict, max_chars: int = MAX_CHARS_PER_CHUNK) -> Iterator[tuple[str, int]]:
    """Uzun turn-ləri max_chars-lı parçalara böl."""
    user = (turn.get("user_text") or "").strip()
    asst = (turn.get("assistant_text") or "").strip()
    combined = f"USER: {user}\n\nASSISTANT: {asst}"
    if len(combined) <= max_chars:
        yield combined, 0
        return
    idx = 0
    pos = 0
    while pos < len(combined):
        yield combined[pos:pos + max_chars], idx
        pos += max_chars
        idx += 1


def index_conversations(verbose: bool = True) -> dict:
    """Bütün söhbət .jsonl fayllarını indekslə."""
    claude_dir = get_claude_project_dir()
    if not claude_dir:
        if verbose:
            print("XƏTA: Claude Code project qovluğu tapılmadı", file=sys.stderr)
        return {"turns": 0, "chunks": 0, "files": 0, "error": "no_claude_dir"}

    if verbose:
        print(f"Claude qovluq: {claude_dir}")

    store = ChromaVectorStore(collection_name=CONVO_COLLECTION)

    jsonl_files = sorted(claude_dir.glob("*.jsonl"))
    if verbose:
        print(f"Söhbət faylları: {len(jsonl_files)}")

    total_turns = 0
    total_chunks = 0
    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []
    batch_size = 64

    for jsonl in jsonl_files:
        file_turns = 0
        for turn in extract_turns(jsonl):
            file_turns += 1
            total_turns += 1
            for chunk_text, chunk_idx in chunk_turn(turn):
                cid = f"{turn['assistant_uuid']}_{chunk_idx}"
                ids.append(cid)
                docs.append(chunk_text)
                metas.append({
                    "session_id": turn.get("session_id", ""),
                    "timestamp": turn.get("timestamp", ""),
                    "chunk_idx": chunk_idx,
                    "source_file": jsonl.name,
                    "user_uuid": turn.get("user_uuid", ""),
                })
                total_chunks += 1
                if len(ids) >= batch_size:
                    store.collection.upsert(ids=ids, documents=docs, metadatas=metas)
                    ids, docs, metas = [], [], []
        if verbose and file_turns > 0:
            print(f"  {jsonl.name}: {file_turns} turn")

    if ids:
        store.collection.upsert(ids=ids, documents=docs, metadatas=metas)

    if verbose:
        print(f"\nİndekslənmə tamamlandı: {total_turns} turn, {total_chunks} chunk, {len(jsonl_files)} fayl")

    return {"turns": total_turns, "chunks": total_chunks, "files": len(jsonl_files)}


def search_conversations(query: str, top_k: int = 5) -> list[dict]:
    """Keçmiş söhbətlərdə semantic axtarış."""
    store = ChromaVectorStore(collection_name=CONVO_COLLECTION)
    try:
        res = store.collection.query(query_texts=[query], n_results=top_k)
    except Exception as e:
        return [{"error": f"query failed: {e}"}]

    results = []
    if res.get("ids") and res["ids"][0]:
        for i, cid in enumerate(res["ids"][0]):
            doc = res["documents"][0][i] if res.get("documents") else ""
            meta = res["metadatas"][0][i] if res.get("metadatas") else {}
            distance = res["distances"][0][i] if res.get("distances") else None
            results.append({
                "chunk_id": cid,
                "session_id": meta.get("session_id", ""),
                "timestamp": meta.get("timestamp", ""),
                "source_file": meta.get("source_file", ""),
                "distance": distance,
                "snippet": doc[:800] + ("..." if len(doc) > 800 else ""),
            })
    return results


def main():
    if "--search" in sys.argv:
        idx = sys.argv.index("--search")
        query = " ".join(sys.argv[idx + 1:])
        if not query:
            print("Usage: conversation_indexer.py --search <query>")
            sys.exit(1)
        results = search_conversations(query, top_k=5)
        print(f"\n=== Top {len(results)} results for: {query!r} ===\n")
        for r in results:
            print(f"--- {r.get('timestamp', '?')} (distance={r.get('distance')}) ---")
            print(f"Session: {r.get('session_id', '')[:8]}...")
            print(r.get("snippet", "")[:600])
            print()
        return

    # Default: full re-index
    t0 = time.time()
    stats = index_conversations()
    elapsed = time.time() - t0
    print(f"\nVaxt: {elapsed:.1f}s")
    if "error" in stats:
        sys.exit(1)


if __name__ == "__main__":
    main()

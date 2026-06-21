#!/usr/bin/env python3
"""Tokengram hooks üçün BLOKLAMAYAN yönləndirmə (nudge) köməkçisi.

Məqsəd: agent tam fayl oxuduqda / geniş Grep etdikdə ona "növbəti dəfə
search_code işlət" deyə MODELƏ görünən qısa mesaj çatdırmaq — amma HEÇ VAXT
tool-u bloklamadan və xəta vermədən.

Mexanizm (Claude Code rəsmi kontraktı):
  stdout-a exit 0 ilə {"hookSpecificOutput": {"hookEventName": ..,
  "additionalContext": ..}} yazmaq → tool normal işləyir + mətn modelə düşür.
  `permissionDecision: "deny"` / exit 2 ASLA istifadə olunmur (bunlar bloklayır).

Rate-limit: modelin kontekstini doldurmamaq üçün
  * pəncərə başına ən çox GLOBAL_CAP nudge (bütün hook-lar paylaşır),
  * eyni açar FILE_COOLDOWN müddətində təkrar nudge olunmur.
State per-machine `chroma_db/.nudge_state.json`-da saxlanır (chroma_db onsuz da
hər layihədə gitignore-dadır → yeni gitignore sətri lazım deyil). chroma_db
yoxdursa project root-a düşür.

Hər funksiya tam müdafiəlidir: istənilən xəta → nudge YOX, amma hook sınmır.
"""
import json
import sys
import time
from pathlib import Path

GLOBAL_WINDOW = 3600   # saniyə — rate-limit pəncərəsi
GLOBAL_CAP = 6         # pəncərə ərzində maksimum nudge sayı (hamısı birlikdə)
FILE_COOLDOWN = 1800   # eyni açar bu müddətdə təkrar nudge olunmur


def _state_path(project_root: Path) -> Path:
    chroma = project_root / "chroma_db"
    if chroma.is_dir():
        return chroma / ".nudge_state.json"
    return project_root / ".mla_nudge_state.json"


def _load(p: Path) -> dict:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"events": [], "keys": {}}


def should_nudge(project_root, key) -> bool:
    """`key` üçün indi nudge etmək olarmı? İcazə varsa qeyd edib True qaytarır.

    Rate-limit: GLOBAL_WINDOW ərzində <= GLOBAL_CAP nudge VƏ eyni açar
    FILE_COOLDOWN-dan tez təkrar olunmur. Best-effort — yarış halında ən pisi
    bir əlavə nudge (zərərsiz). İstənilən xəta → False (nudge yox), hook sınmaz.
    """
    try:
        now = time.time()
        p = _state_path(Path(project_root))
        st = _load(p)
        events = [t for t in st.get("events", []) if isinstance(t, (int, float)) and now - t < GLOBAL_WINDOW]
        keys = {
            k: t for k, t in st.get("keys", {}).items()
            if isinstance(t, (int, float)) and now - t < GLOBAL_WINDOW
        }
        if len(events) >= GLOBAL_CAP:
            _save(p, {"events": events, "keys": keys})
            return False
        last = keys.get(key)
        if last is not None and now - last < FILE_COOLDOWN:
            return False
        events.append(now)
        keys[key] = now
        _save(p, {"events": events, "keys": keys})
        return True
    except Exception:
        return False


def _save(p: Path, state: dict) -> None:
    try:
        p.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


def emit(additional_context, event="PreToolUse") -> None:
    """Bloklamayan additionalContext JSON-u stdout-a yaz (sonra exit 0 olmalıdır).

    `permissionDecision` QOYULMUR → tool normal axarla işləyir. Yalnız mətn
    modelə əlavə olunur. İstənilən xəta udulur — hook sınmaz.
    """
    try:
        sys.stdout.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": additional_context,
            }
        }))
        sys.stdout.flush()
    except Exception:
        pass

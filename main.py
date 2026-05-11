"""
============================================
main.py — CLI Giriş Nöqtəsi
============================================
MƏRHƏLƏ 7: Bütün modulları birləşdirən CLI.

İstifadə:
    python main.py index ./my_project           # Layihəni indeksləşdir
    python main.py ask "Sual nədir?"             # Sual ver
    python main.py watch ./my_project            # Avtomatik re-index
    python main.py stats                         # Statistika göstər
    python main.py reset                         # Bazanı sıfırla
    python main.py route ./my_project            # Smart router məsləhəti
"""

import argparse
import logging
import sys
from pathlib import Path

# Windows konsolu cp1252 default-dur, emoji yaza bilmir.
# UTF-8-ə məcbur et ki, print/log uçmasın.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import config


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Bəzi şumulu kitabxanaların loglarını sus
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


# ============================================
# ƏMR — INDEX
# ============================================

def cmd_index(args):
    """Verilmiş qovluğu indeksləşdir."""
    from document_loader import load_directory
    from vector_store import ChromaVectorStore

    directory = Path(args.directory).resolve()
    if not directory.exists():
        print(f"❌ Qovluq tapılmadı: {directory}")
        return 1

    print(f"📂 İndeksləşdirilir: {directory}")
    chunks = load_directory(str(directory))
    if not chunks:
        print("⚠️  Heç bir chunk yaradılmadı")
        return 1

    store = ChromaVectorStore()
    if args.fresh:
        print("🗑️  Mövcud baza sıfırlanır...")
        store.clear_collection()

    stats = store.index_documents(chunks)
    print(f"✅ Bitti: {stats}")
    return 0


# ============================================
# ƏMR — ASK
# ============================================

def cmd_ask(args):
    """Sual ver."""
    from vector_store import ChromaVectorStore
    from search_engine import HybridSearchEngine
    from llm_agent import RAGAgent, get_provider

    store = ChromaVectorStore()
    if store.collection.count() == 0:
        print("⚠️  Baza boşdur. Əvvəlcə indeks yaradın: python main.py index <qovluq>")
        return 1

    engine = HybridSearchEngine(store)
    provider = get_provider(args.provider) if args.provider else None
    agent = RAGAgent(engine, provider=provider)

    query = args.query
    print(f"\n❓ Sual: {query}\n")

    if args.decompose:
        response = agent.ask_with_decomposition(query, top_k=args.top_k)
    else:
        response = agent.ask(query, top_k=args.top_k, stream=args.stream)

    if not args.stream:
        print(f"💬 Cavab:\n{response.answer}\n")

    print(f"📊 Etibar: {response.confidence}  |  "
          f"Provider: {response.provider} ({response.model})  |  "
          f"Tokenlər: {response.tokens_used}")

    if args.show_sources:
        print("\n📚 Mənbələr:")
        for i, src in enumerate(response.sources, 1):
            print(f"  {i}. {src.file_info}  (skor: {src.score:.3f})")

    return 0


# ============================================
# ƏMR — WATCH
# ============================================

def cmd_watch(args):
    """Qovluğu izlə, dəyişiklikləri avtomatik indeksləşdir."""
    from vector_store import ChromaVectorStore
    from file_watcher import FileWatcher

    directory = Path(args.directory).resolve()
    if not directory.exists():
        print(f"❌ Qovluq tapılmadı: {directory}")
        return 1

    store = ChromaVectorStore()
    watcher = FileWatcher(str(directory), store)
    print(f"👁️  İzlənilir: {directory}  (Ctrl+C ilə dayandır)")
    watcher.run_forever()
    return 0


# ============================================
# ƏMR — STATS
# ============================================

def cmd_stats(args):
    """Bazanın statistikasını göstər."""
    from vector_store import ChromaVectorStore

    store = ChromaVectorStore()
    stats = store.get_stats()
    print("\n📊 Baza Statistikası:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    return 0


# ============================================
# ƏMR — RESET
# ============================================

def cmd_reset(args):
    """Bazanı tamamilə sıfırla."""
    from vector_store import ChromaVectorStore

    if not args.yes:
        ans = input("⚠️  Bütün indeks silinəcək. Davam? (yes/no): ")
        if ans.lower() != "yes":
            print("Ləğv edildi")
            return 0

    store = ChromaVectorStore()
    store.clear_collection()
    print("✅ Baza sıfırlandı")
    return 0


# ============================================
# ƏMR — RESET-QUEUE (emergency)
# ============================================

def cmd_reset_queue(args):
    """Stuck `.mla_pending*` fayllarını sil. MCP server donduqda işlədilir."""
    project_root = Path(__file__).resolve().parent
    removed = []
    for name in (".mla_pending.txt", ".mla_pending.processing"):
        p = project_root / name
        if p.exists():
            try:
                size = p.stat().st_size
                p.unlink()
                removed.append(f"{name} ({size}B)")
            except OSError as e:
                print(f"❌ {name} silinə bilmədi: {e}")
                return 1

    if not removed:
        print("✅ Növbə artıq təmizdir")
    else:
        print(f"✅ Silindi: {', '.join(removed)}")
        print("ℹ️  İndi VS Code-u tam bağlayıb yenidən aç ki, MCP server təzələnsin")
    return 0


# ============================================
# ƏMR — ROUTE
# ============================================

def cmd_route(args):
    """Smart router məsləhəti göstər."""
    from smart_router import SmartRouter

    router = SmartRouter(args.directory)
    print(router.summary())
    print(f"\n  Tövsiyə olunan parametrlər: {router.search_params()}")
    print(f"  RAG istifadə: {router.should_use_rag()}")
    return 0


# ============================================
# ARGPARSE
# ============================================

def build_parser():
    parser = argparse.ArgumentParser(
        prog="mla-agent",
        description="MLA Agent — Hybrid RAG kod axtarış sistemi",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG log")

    sub = parser.add_subparsers(dest="cmd", required=True)

    # index
    p_index = sub.add_parser("index", help="Qovluğu indeksləşdir")
    p_index.add_argument("directory", help="İndekslənəcək qovluq")
    p_index.add_argument("--fresh", action="store_true",
                         help="Əvvəl bazanı sıfırla")
    p_index.set_defaults(func=cmd_index)

    # ask
    p_ask = sub.add_parser("ask", help="Sual ver")
    p_ask.add_argument("query", help="Sualın mətni")
    p_ask.add_argument("--top-k", type=int, default=None,
                       help="Neçə nəticə göstərilsin")
    p_ask.add_argument("--provider", choices=["anthropic", "openai"],
                       help="LLM provider (default: config-dən)")
    p_ask.add_argument("--stream", action="store_true",
                       help="Cavabı streaming verme")
    p_ask.add_argument("--decompose", action="store_true",
                       help="Sualı alt-suallara böl")
    p_ask.add_argument("--show-sources", action="store_true",
                       help="İstifadə olunan mənbələri göstər")
    p_ask.set_defaults(func=cmd_ask)

    # watch
    p_watch = sub.add_parser("watch", help="Qovluğu izlə")
    p_watch.add_argument("directory", help="İzlənəcək qovluq")
    p_watch.set_defaults(func=cmd_watch)

    # stats
    p_stats = sub.add_parser("stats", help="Baza statistikası")
    p_stats.set_defaults(func=cmd_stats)

    # reset
    p_reset = sub.add_parser("reset", help="Bazanı sıfırla")
    p_reset.add_argument("--yes", action="store_true",
                         help="Təsdiq sorma")
    p_reset.set_defaults(func=cmd_reset)

    # reset-queue (emergency)
    p_rq = sub.add_parser(
        "reset-queue",
        help="Stuck pending növbə fayllarını sil (MCP donduqda)",
    )
    p_rq.set_defaults(func=cmd_reset_queue)

    # route
    p_route = sub.add_parser("route", help="Smart router məsləhəti")
    p_route.add_argument("directory", help="Qiymətləndiriləcək qovluq")
    p_route.set_defaults(func=cmd_route)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

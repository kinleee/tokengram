#!/usr/bin/env bash
# ============================================
# MLA Agent — macOS / Linux Setup
# ============================================
# İstifadə: ./setup.sh
#         ./setup.sh /path/to/project   (başqa layihəni indeksləşdir)
#         ./setup.sh --skip-index       (yalnız asılılıqları qur)

set -euo pipefail

AGENT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="."
SKIP_INDEX=0

for arg in "$@"; do
    case "$arg" in
        --skip-index) SKIP_INDEX=1 ;;
        --*) echo "Bilinməyən flaq: $arg"; exit 1 ;;
        *) PROJECT_DIR="$arg" ;;
    esac
done

step() { printf "\n\033[1;36m==> %s\033[0m\n" "$1"; }
ok()   { printf "  \033[1;32m[OK]\033[0m %s\n" "$1"; }
warn() { printf "  \033[1;33m[!]\033[0m %s\n" "$1"; }
fail() { printf "  \033[1;31m[XƏTA]\033[0m %s\n" "$1"; exit 1; }

# ============================================
# 1. Python
# ============================================
step "Python yoxlanılır"
if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 tapılmadı. https://python.org-dan yüklə (3.10+)"
fi
PY_VER=$(python3 --version)
ok "$PY_VER"
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info[0])")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info[1])")
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    warn "Python 3.10+ tövsiyə olunur (sənində $PY_MAJOR.$PY_MINOR)"
fi

# ============================================
# 2. .env
# ============================================
step "Mühit dəyişənləri (.env)"
if [ ! -f "$AGENT_ROOT/.env" ]; then
    if [ -f "$AGENT_ROOT/.env.example" ]; then
        cp "$AGENT_ROOT/.env.example" "$AGENT_ROOT/.env"
        ok ".env yaradıldı (.env.example-dən)"
        warn "API açarı lazımdırsa, .env-i redaktə et"
    else
        warn ".env.example tapılmadı, keçildi"
    fi
else
    ok ".env artıq mövcuddur"
fi

# ============================================
# 3. Asılılıqlar
# ============================================
step "Asılılıqlar quraşdırılır"
python3 -m pip install --quiet --upgrade pip
python3 -m pip install -r "$AGENT_ROOT/requirements.txt"
ok "Bütün paketlər quraşdırıldı"

# ============================================
# 4. İndeksləmə
# ============================================
if [ "$SKIP_INDEX" -eq 0 ]; then
    step "İlk indeksləmə"
    RESOLVED_PROJECT=$(cd "$PROJECT_DIR" && pwd)
    echo "  Hədəf: $RESOLVED_PROJECT"
    warn "İlk dəfədir → embedding modeli endirilir (~130MB), 1-3 dəq çəkə bilər"
    cd "$AGENT_ROOT"
    PYTHONIOENCODING=utf-8 python3 main.py index "$RESOLVED_PROJECT" --fresh
    ok "İndeksləmə tamamlandı"
else
    step "İndeksləmə keçildi (--skip-index)"
    warn "Sonra əl ilə: python3 main.py index <qovluq> --fresh"
fi

# ============================================
# 5. Yekun
# ============================================
echo ""
echo "============================================"
echo "  Quraşdırma TAMAM!"
echo "============================================"
echo ""
echo "Növbəti addımlar:"
echo "  1. VS Code-u tam bağla və yenidən aç (MCP server pickup üçün)"
echo "  2. Claude Code-da '/mcp' yaz, 'mla-agent' connected görünməlidir"
echo "  3. Sual ver: 'mla-agent ilə yoxla — bu funksiya nə edir?'"
echo ""
echo "Problem olarsa: PROBLEMS.md və README.md-ə bax"
echo ""
